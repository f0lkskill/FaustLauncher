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
# 日志脱敏
# ------------------------------------------------------------
# 日志会进启动器的终端面板, 可能被截图或贴出来, 所以完整用户 ID 一律打码;
# Cookie / 签名 / 令牌这类凭据只报"存没存", 绝不打印内容。
# ============================================================
def mask_uid(uid) -> str:
    """日志用的打码用户 ID: 保留 `FL-` 前缀与末 2 位, 中间全部遮掉"""
    text = str(uid or "").strip()
    if not text:
        return "(空)"
    head = (text.split("-", 1)[0] + "-") if "-" in text else ""
    rest = len(text) - len(head)
    if rest <= 4:
        return head + "•" * rest
    return head + "•" * (rest - 2) + text[-2:]


# 日志里**不打印真实 API 路由**：服务端路由结构算内部信息，而且路径里可能带
# 用户 ID / 主页令牌。日志只留一个人看得懂的动作名，认不出来的一律折叠。
_PATH_ACTIONS = {
    "/api/register": "注册",
    "/api/login": "登录",
    "/api/logout": "退出",
    "/api/me": "读取用户信息",
    "/api/me/skins": "上报皮肤信息",
    "/api/me/name": "上报昵称",
    "/api/me/achievements": "上报成就 (用户信息路径)",
    "/api/achievements/overwrite": "上报成就 (覆写)",
    "/api/me/playtime": "上报游玩时长",
    "/api/achievements/add": "上报成就 (单条添加)",
    "/api/leaderboard": "读取排行榜信息",
    "/api/download": "上报资源下载数据",
}
_PATH_ACTION_PREFIXES = (
    ("/api/user/", "读取用户信息"),
    ("/api/profile/", "读取用户主页信息"),
)


def _safe_path(path: str) -> str:
    """给日志用的**动作名** —— 绝不原样输出路由（含路径里的用户 ID / 令牌）。"""
    clean = str(path or "").split("?", 1)[0]
    if clean in _PATH_ACTIONS:
        return _PATH_ACTIONS[clean]
    for prefix, label in _PATH_ACTION_PREFIXES:
        if clean.startswith(prefix):
            return label
    return "[已隐藏]"


# 会话 (requests.Session + 登录 Cookie 持久化)
def _restore_cookies(session, base: str) -> None:
    try:
        data = read_json(session_file())
    except Exception:
        return
    cookies = (data or {}).get("cookies")
    if not isinstance(cookies, dict):
        return
    host = urlsplit(base).hostname or ""
    restored = 0
    for name in _LOGIN_COOKIES:
        value = cookies.get(name)
        if isinstance(value, str) and value:
            try:
                session.cookies.set(name, value, domain=host, path="/")
                restored += 1
            except Exception:
                pass
    if restored:
        print(f"[用户API] 已载入本地登录态 ({host})")


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
        print("[用户API] 已保存登录态 (login_user / login_sig, 内容不打印)")
    except Exception as exc:
        print(f"[用户API] 保存登录态失败: {exc}")


def clear_session() -> None:
    """清掉本地登录态 (Cookie 文件 + 内存会话)"""
    global _session, _session_base
    with _lock:
        removed = False
        try:
            if os.path.isfile(session_file()):
                os.remove(session_file())
                removed = True
        except Exception as exc:
            print(f"[用户API] 清除登录态失败: {exc}")
        _session = None
        _session_base = ""
        if removed:
            print("[用户API] 已清除本地登录态")


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


# 统一请求
def _request(method: str, path: str, payload: dict | None = None,
             keep_cookies: bool = False, note: str = "") -> dict:
    """发一次请求, 统一返回:

        {"ok": bool, "data": dict, "error": str, "status": int, "offline": bool}

    · offline=True 表示压根没连上服务端 (断网/超时), 与"服务端明确拒绝"区分开;
    · 失败原因优先用服务端给的 `msg` (它的文案已经足够给用户看);
    · 每次调用都会打印一行 `[用户API] ...` 日志 (方法/路径/状态码/耗时),
      `note` 用来补充业务上下文 (例如打码后的用户 ID), 路径上的 ID 也会自动打码。
    """
    url = api_base() + path
    label = f"{method} {_safe_path(path)}" + (f" [{note}]" if note else "")
    started = time.time()
    try:
        session = _get_session()
        resp = session.request(method, url, json=payload,
                               timeout=(CONNECT_TIMEOUT, READ_TIMEOUT))
    except Exception as exc:
        cost = time.time() - started
        print(f"[用户API] {label} 连接失败: {type(exc).__name__} ({cost:.2f}s)")
        return {"ok": False, "data": {}, "status": 0, "offline": True,
                "error": f"无法连接服务端（{type(exc).__name__}），请检查网络后重试"}
    cost = time.time() - started

    status = int(getattr(resp, "status_code", 0) or 0)
    data = {}
    try:
        parsed = resp.json()
        if isinstance(parsed, dict):
            data = parsed
    except Exception:
        data = {}

    if status == 200 and data.get("ok"):
        print(f"[用户API] {label} -> {status} 成功 ({cost:.2f}s)")
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
    print(f"[用户API] {label} -> {status} 失败: {msg} ({cost:.2f}s)")
    return {"ok": False, "data": data, "error": msg, "status": status, "offline": False}


# 对外接口
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
    return _request("POST", "/api/register", payload, keep_cookies=True,
                    note=f"id={mask_uid(uid)}")


def login(uid: str) -> dict:
    """用用户 ID 登录 (要求该 ID **已存在**; 新环境请先用 register)"""
    return _request("POST", "/api/login", {"id": str(uid or "").strip()}, keep_cookies=True,
                    note=f"id={mask_uid(uid)}")


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
    items = [str(s) for s in (skins or [])]
    return _request("POST", "/api/me/skins", {"skins": items}, note=f"{len(items)} 项")


def push_name(name: str) -> dict:
    """设置**自己**的昵称"""
    clean = str(name or "").strip()
    return _request("POST", "/api/me/name", {"user_name": clean}, note=f"昵称={clean}")


def public_user(uid: str) -> dict:
    """按用户 ID 读公开资料 (无需登录)"""
    return _request("GET", "/api/user/" + quote(str(uid or "").strip(), safe=""),
                    note=f"id={mask_uid(uid)}")


# 服务端提供**两种**上传方式（见 FaustLauncherWeb/API.md §4.2 / §4.10）：
#   ① POST /api/me/achievements          —— uid 取自登录会话，普通用户即可，**推荐**
#   ② POST /api/achievements/overwrite   —— uid 写在请求体，普通用户只能覆盖自己、管理员可覆盖他人
# 两者都是**整体替换**语义（客户端把本地全量列表报上去，不用自己算增量）。

def push_achievements(achievements) -> dict:
    """方式①：整体替换**自己**的成就列表（uid 由服务端从登录会话取，改不到别人）。"""
    items = [str(a).strip() for a in (achievements or []) if str(a).strip()]
    return _request("POST", "/api/me/achievements", {"achievements": items},
                    note=f"{len(items)} 条")


def overwrite_achievements(achievements, uid: str = "") -> dict:
    """方式②：`POST /api/achievements/overwrite`，用户 ID 写在请求体里，整体覆盖。

    ``uid`` 留空则由服务端按登录身份处理（等价于覆盖自己）；
    传了别人的 ID 且不是管理员会被服务端 403 拒绝。
    """
    items = [str(a).strip() for a in (achievements or []) if str(a).strip()]
    payload: dict = {"achievements": items}
    if str(uid or "").strip():
        payload["id"] = str(uid).strip()
    return _request("POST", "/api/achievements/overwrite", payload,
                    note=f"{len(items)} 条" + (f" -> {mask_uid(uid)}" if uid else ""))


def add_achievement(achievement_id: str, uid: str = "") -> dict:
    """给**自己**加一条成就（服务端 ``POST /api/achievements/add``）。

    为什么不整份覆盖：这个接口只改服务端那一条记录，语义是"加一条"且**幂等**
    （已经有了就返回 ``added: false``，不报错）。整表覆盖在多机轮流上线的场景下
    会互相覆盖，而这里天然是并集。

    返回体里 ``known`` 表示服务端 ``achievements.json`` 是否认识这个 ID（它**不做强制
    校验**，所以客户端可以先上新成就，服务端稍后再补定义）。
    """
    aid = str(achievement_id or "").strip()
    if not aid:
        return {"ok": False, "error": "成就 ID 为空", "status": 0, "data": {}, "offline": False}
    payload = {"achievement": aid}
    if uid:
        payload["id"] = str(uid)
    return _request("POST", "/api/achievements/add", payload, note=f"单条 {aid}")


def report_download(name: str, kind: str) -> dict:
    """上报一次下载（下载次数 **+1 由服务端在锁内完成**）。

    客户端不要再"整份下载数据库 → 本地 +1 → 整份写回" —— 并发必然互相覆盖。
    ``kind`` 取 ``"mod"`` / ``"addon"``。
    """
    return _request("POST", "/api/download",
                    {"name": str(name or "").strip(), "type": str(kind or "").strip()},
                    note=f"{kind}:{name}")


# 服务端把时长单独存一篇统计笔记（心跳式高频上报，不塞进用户表）。两种写法：
#   {"add": N}        —— 累加 N 秒（客户端只知道"这一段玩了多久"时用）
#   {"playtime": N}   —— 覆盖为 N 秒（**本地就是权威总量**时用，我们读 Steam 记录属于这种）

def report_playtime(seconds: int, overwrite: bool = True) -> dict:
    """上报自己的累计游玩时长（单位秒）。

    ``overwrite=True`` 走覆盖语义（``{"playtime": N}``）—— Steam 的 ``Playtime`` 本身就是
    累计总量，覆盖最准确；``overwrite=False`` 时走累加语义（``{"add": N}``）。
    """
    try:
        value = max(0, int(seconds))
    except (TypeError, ValueError):
        value = 0
    payload = {"playtime": value} if overwrite else {"add": value}
    return _request("POST", "/api/me/playtime", payload,
                    note=f"{'覆盖' if overwrite else '累加'} {value} 秒")


def leaderboard(kind: str = "playtime", limit: int = 20) -> dict:
    """读排行榜（公开只读，不需要登录也能拿；登录了会额外带自己的名次）。

    ``kind`` 取 ``"playtime"``（游玩时长）或 ``"achievements"``（已解锁成就数）。
    榜单是 **GET + 查询串**（``?type=&limit=``），所以这里把参数拼进路径。
    """
    try:
        size = max(1, min(200, int(limit)))
    except (TypeError, ValueError):
        size = 20
    kind = str(kind or "playtime").strip() or "playtime"
    path = f"/api/leaderboard?type={quote(kind, safe='')}&limit={size}"
    return _request("GET", path, note=f"{kind} 前 {size} 名")
