"""FaustLauncherWeb 服务端 API 客户端

用户身份与皮肤数据**全部通过服务端接口读写**, 不再直接读写用户笔记:

  · 旧做法是"读整张用户表 → 改 → 写回"(`/note/FaustLauncher.users` + `/update/`),
    那是**最后写入者胜**: 客户端本地表旧一点、或两台设备同时解锁, 就会成批丢用户;
  · 现在统一走 `/api/me/*` —— uid 由服务端从**登录会话**里取(绝不从请求体读),
    服务端在锁内"读整表 → 只改自己这一行 → 原子写回", 结构上不可能牵连别人;
  · 本模块**不做任何缓存**: 每次调用都发真实请求 (服务端响应本身带 no-store)。

接口 (详见服务端 API.md 4.1 / 4.2):

  POST /api/login        {"id": uid}             -> 统一用户对象; 失败: HTTP 200 + ok:false
  GET  /api/me                                    -> 统一用户对象 (401 未登录 / 404 无此人)
  POST /api/me/skins     {"skins": [...]}         -> 整体替换**自己**的皮肤列表
  POST /api/me/name      {"user_name": "..."}     -> 设置**自己**的昵称
  GET  /api/user/<uid>                            -> 公开只读 (404 无此人)
  GET  /api/logout                                -> 清登录态

登录态: 服务端下发 `login_user` / `login_sig` 两个签名 Cookie (30 天), 这里持久化到
`%APPDATA%\\FaustLauncher\\user\\session.json`。登录只要用户 ID、**没有密码**, 所以
Cookie 失效时随时可以用本地保存的 ID 重建会话。
"""

from __future__ import annotations

import os
import threading
import time
from urllib.parse import quote, urlsplit

from functions.base.common.json_io import read_json, write_json

# 站点根地址 (config/web_config.json → api_base 可覆盖)
DEFAULT_API_BASE = "https://folkskill.pythonanywhere.com"

CONNECT_TIMEOUT = 10        # 建连超时 (秒)
READ_TIMEOUT = 20           # 读取超时 (秒)
_SESSION_FILE = "session.json"
_LOGIN_COOKIES = ("login_user", "login_sig")

_lock = threading.RLock()
_session = None
_session_base = ""


def user_data_dir() -> str:
    """用户数据目录 (`%APPDATA%\\FaustLauncher\\user`) —— 全项目唯一定义处"""
    roaming = os.getenv("APPDATA")
    if not roaming:
        roaming = os.path.join(os.path.expanduser("~"), "AppData", "Roaming")
    return os.path.join(roaming, "FaustLauncher", "user")


def session_file() -> str:
    return os.path.join(user_data_dir(), _SESSION_FILE)


def api_base() -> str:
    """服务端站点根地址"""
    base = ""
    try:
        from functions.base.web_config import get_api_base
        base = get_api_base()
    except Exception:
        base = ""
    return (base or DEFAULT_API_BASE).rstrip("/")


# ============================================================
# 会话 (requests.Session + 登录 Cookie 持久化)
# ============================================================
def _restore_cookies(session, base: str) -> None:
    try:
        data = read_json(session_file())
    except Exception:
        return
    cookies = (data or {}).get("cookies")
    if not isinstance(cookies, dict):
        return
    host = urlsplit(base).hostname or ""
    for name in _LOGIN_COOKIES:
        value = cookies.get(name)
        if isinstance(value, str) and value:
            try:
                session.cookies.set(name, value, domain=host, path="/")
            except Exception:
                pass


def _save_cookies(session) -> None:
    """只持久化登录用的那两个 Cookie (其余会话 Cookie 没有保留价值)"""
    cookies = {}
    try:
        for c in session.cookies:
            if c.name in _LOGIN_COOKIES and c.value:
                cookies[c.name] = c.value
    except Exception:
        return
    if len(cookies) < len(_LOGIN_COOKIES):
        return
    path = session_file()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        write_json(path, {"cookies": cookies, "saved_at": time.time()}, indent=4, fsync=True)
    except Exception as exc:
        print(f"[用户] 保存登录态失败: {exc}")


def clear_session() -> None:
    """清掉本地登录态 (Cookie 文件 + 内存会话)"""
    global _session, _session_base
    with _lock:
        try:
            if os.path.isfile(session_file()):
                os.remove(session_file())
        except Exception as exc:
            print(f"[用户] 清除登录态失败: {exc}")
        _session = None
        _session_base = ""


def has_session() -> bool:
    """本地是否存有登录态 (不代表它还有效)"""
    return os.path.isfile(session_file())


def _get_session():
    global _session, _session_base
    import requests
    base = api_base()
    with _lock:
        if _session is None or _session_base != base:
            session = requests.Session()
            session.headers.update({
                # 服务端日志里能认出是启动器, 与网页端区分开
                "User-Agent": "FaustLauncher-Client/1.0",
                "Accept": "application/json",
            })
            _restore_cookies(session, base)
            _session = session
            _session_base = base
        return _session


# ============================================================
# 统一请求
# ============================================================
def _request(method: str, path: str, payload: dict | None = None,
             keep_cookies: bool = False) -> dict:
    """发一次请求, 统一返回:

        {"ok": bool, "data": dict, "error": str, "status": int, "offline": bool}

    · offline=True 表示压根没连上服务端 (断网/超时), 与"服务端明确拒绝"区分开;
    · 失败原因优先用服务端给的 `msg` (它的文案已经足够给用户看)。
    """
    url = api_base() + path
    try:
        session = _get_session()
        resp = session.request(method, url, json=payload,
                               timeout=(CONNECT_TIMEOUT, READ_TIMEOUT))
    except Exception as exc:
        return {"ok": False, "data": {}, "status": 0, "offline": True,
                "error": f"无法连接服务端（{type(exc).__name__}），请检查网络后重试"}

    status = int(getattr(resp, "status_code", 0) or 0)
    data = {}
    try:
        parsed = resp.json()
        if isinstance(parsed, dict):
            data = parsed
    except Exception:
        data = {}

    if status == 200 and data.get("ok"):
        if keep_cookies:
            _save_cookies(session)
        return {"ok": True, "data": data, "error": "", "status": status, "offline": False}

    msg = str(data.get("msg") or data.get("error") or "").strip()
    if not msg:
        if status == 403:
            text = ""
            try:
                text = str(resp.text or "")[:200].lower()
            except Exception:
                text = ""
            msg = ("请求被服务端拦截（可能触发了限流），请稍后再试"
                   if "<html" in text else "服务端拒绝了这次请求")
        else:
            msg = {400: "请求参数有误", 401: "登录已失效，请重新登录",
                   404: "该用户不存在", 405: "服务端不支持这个请求",
                   413: "请求内容过大", 500: "服务端内部错误"}.get(
                       status, f"服务端返回 {status or '未知状态'}")
    return {"ok": False, "data": data, "error": msg, "status": status, "offline": False}


# ============================================================
# 对外接口
# ============================================================
def register(uid: str, user_name: str | None = None, skins=None) -> dict:
    """注册 / 登记自己的账号 (**幂等**, 客户端应当优先用它而不是 login)。

    服务端策略:
      · ID 已存在 → 原样返回并登录, **一个字段都不改** (不会冲掉昵称/皮肤/角色);
      · ID 不存在 → 建档 (未传 user_name 用 `Player`, 未传 skins 用 `["faust"]`)。

    所以它同时覆盖"老用户重建会话"和"新环境首次登记"两种情况, 成功后直接下发
    登录 Cookie, 紧接着就能用 `/api/me/*`。

    注意: ID 格式必须是 `FL-` + 16 位数字/大写字母 (与 `_make_user_id()` 一致),
    否则服务端返回 400。
    """
    payload: dict = {"id": str(uid or "").strip()}
    if user_name:
        payload["user_name"] = str(user_name).strip()
    if skins is not None:
        payload["skins"] = [str(s) for s in (skins or [])]
    return _request("POST", "/api/register", payload, keep_cookies=True)


def login(uid: str) -> dict:
    """用用户 ID 登录 (要求该 ID **已存在**; 新环境请先用 register)"""
    return _request("POST", "/api/login", {"id": str(uid or "").strip()}, keep_cookies=True)


def logout() -> dict:
    """退出登录 (清服务端 Cookie + 本地登录态)"""
    result = _request("GET", "/api/logout")
    clear_session()
    return result


def me() -> dict:
    """读自己在服务端的记录 (未登录 401 / 不存在 404)"""
    return _request("GET", "/api/me")


def push_skins(skins) -> dict:
    """整体替换**自己**的皮肤列表 (调用方负责先与云端取并集)"""
    return _request("POST", "/api/me/skins", {"skins": [str(s) for s in (skins or [])]})


def push_name(name: str) -> dict:
    """设置**自己**的昵称"""
    return _request("POST", "/api/me/name", {"user_name": str(name or "").strip()})


def public_user(uid: str) -> dict:
    """按用户 ID 读公开资料 (无需登录)"""
    return _request("GET", "/api/user/" + quote(str(uid or "").strip(), safe=""))
