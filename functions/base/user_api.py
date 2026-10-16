
from __future__ import annotations

import os
import threading
import time
from urllib.parse import quote, urlsplit

from functions.base.common.json_io import read_json, write_json

DEFAULT_API_BASE = "https://folkskill.pythonanywhere.com"

CONNECT_TIMEOUT = 10
READ_TIMEOUT = 20
_SESSION_FILE = "session.json"
_LOGIN_COOKIES = ("login_user", "login_sig")

_lock = threading.RLock()
_session = None
_session_base = ""

def user_data_dir() -> str:
    roaming = os.getenv("APPDATA")
    if not roaming:
        roaming = os.path.join(os.path.expanduser("~"), "AppData", "Roaming")
    return os.path.join(roaming, "FaustLauncher", "user")

def session_file() -> str:
    return os.path.join(user_data_dir(), _SESSION_FILE)

def api_base() -> str:
    base = ""
    try:
        from functions.base.web_config import get_api_base
        base = get_api_base()
    except Exception:
        base = ""
    return (base or DEFAULT_API_BASE).rstrip("/")

def mask_uid(uid) -> str:
    text = str(uid or "").strip()
    if not text:
        return "(空)"
    head = (text.split("-", 1)[0] + "-") if "-" in text else ""
    rest = len(text) - len(head)
    if rest <= 4:
        return head + "•" * rest
    return head + "•" * (rest - 2) + text[-2:]

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
    clean = str(path or "").split("?", 1)[0]
    if clean in _PATH_ACTIONS:
        return _PATH_ACTIONS[clean]
    for prefix, label in _PATH_ACTION_PREFIXES:
        if clean.startswith(prefix):
            return label
    return "[Hidden]"

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
        print(f"[UserAPI] 已载入本地登录态。")

def _save_cookies(session) -> None:
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
        print("[UserAPI] 已保存登录态 (login_user / login_sig, 内容不打印)")
    except Exception as exc:
        print(f"[UserAPI] 保存登录态失败: {exc}")

def clear_session() -> None:
    global _session, _session_base
    with _lock:
        removed = False
        try:
            if os.path.isfile(session_file()):
                os.remove(session_file())
                removed = True
        except Exception as exc:
            print(f"[UserAPI] 清除登录态失败: {exc}")
        _session = None
        _session_base = ""
        if removed:
            print("[UserAPI] 已清除本地登录态")

def has_session() -> bool:
    return os.path.isfile(session_file())

def _get_session():
    global _session, _session_base
    import requests
    base = api_base()
    with _lock:
        if _session is None or _session_base != base:
            session = requests.Session()
            session.headers.update({
                "User-Agent": "FaustLauncher-Client/1.0",
                "Accept": "application/json",
            })
            _restore_cookies(session, base)
            _session = session
            _session_base = base
        return _session

def _request(method: str, path: str, payload: dict | None = None,
             keep_cookies: bool = False, note: str = "") -> dict:
    url = api_base() + path
    label = f"{method} {_safe_path(path)}" + (f" [{note}]" if note else "")
    started = time.time()
    try:
        session = _get_session()
        resp = session.request(method, url, json=payload,
                               timeout=(CONNECT_TIMEOUT, READ_TIMEOUT))
    except Exception as exc:
        cost = time.time() - started
        print(f"[UserAPI] {label} 连接失败: {type(exc).__name__} ({cost:.2f}s)")
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
        print(f"[UserAPI] {label} -> {status} 成功 ({cost:.2f}s)")
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
    print(f"[UserAPI] {label} -> {status} 失败: {msg} ({cost:.2f}s)")
    return {"ok": False, "data": data, "error": msg, "status": status, "offline": False}

def register(uid: str, user_name: str | None = None, skins=None) -> dict:
    payload: dict = {"id": str(uid or "").strip()}
    if user_name:
        payload["user_name"] = str(user_name).strip()
    if skins is not None:
        payload["skins"] = [str(s) for s in (skins or [])]
    return _request("POST", "/api/register", payload, keep_cookies=True,
                    note=f"id={mask_uid(uid)}")

def login(uid: str) -> dict:
    return _request("POST", "/api/login", {"id": str(uid or "").strip()}, keep_cookies=True,
                    note=f"id={mask_uid(uid)}")

def logout() -> dict:
    result = _request("GET", "/api/logout")
    clear_session()
    return result

def me() -> dict:
    return _request("GET", "/api/me")

def push_skins(skins) -> dict:
    items = [str(s) for s in (skins or [])]
    return _request("POST", "/api/me/skins", {"skins": items}, note=f"{len(items)} 项")

def push_name(name: str) -> dict:
    clean = str(name or "").strip()
    return _request("POST", "/api/me/name", {"user_name": clean}, note=f"昵称={clean}")

def public_user(uid: str) -> dict:
    return _request("GET", "/api/user/" + quote(str(uid or "").strip(), safe=""),
                    note=f"id={mask_uid(uid)}")

def push_achievements(achievements) -> dict:
    items = [str(a).strip() for a in (achievements or []) if str(a).strip()]
    return _request("POST", "/api/me/achievements", {"achievements": items},
                    note=f"{len(items)} 条")

def overwrite_achievements(achievements, uid: str = "") -> dict:
    items = [str(a).strip() for a in (achievements or []) if str(a).strip()]
    payload: dict = {"achievements": items}
    if str(uid or "").strip():
        payload["id"] = str(uid).strip()
    return _request("POST", "/api/achievements/overwrite", payload,
                    note=f"{len(items)} 条" + (f" -> {mask_uid(uid)}" if uid else ""))

def add_achievement(achievement_id: str, uid: str = "") -> dict:
    aid = str(achievement_id or "").strip()
    if not aid:
        return {"ok": False, "error": "成就 ID 为空", "status": 0, "data": {}, "offline": False}
    payload = {"achievement": aid}
    if uid:
        payload["id"] = str(uid)
    return _request("POST", "/api/achievements/add", payload, note=f"单条 {aid}")

def report_download(name: str, kind: str) -> dict:
    return _request("POST", "/api/download",
                    {"name": str(name or "").strip(), "type": str(kind or "").strip()},
                    note=f"{kind}:{name}")

def report_playtime(seconds: int, overwrite: bool = True) -> dict:
    try:
        value = max(0, int(seconds))
    except (TypeError, ValueError):
        value = 0
    payload = {"playtime": value} if overwrite else {"add": value}
    return _request("POST", "/api/me/playtime", payload,
                    note=f"{'覆盖' if overwrite else '累加'} {value} 秒")

def leaderboard(kind: str = "playtime", limit: int = 20) -> dict:
    try:
        size = max(1, min(200, int(limit)))
    except (TypeError, ValueError):
        size = 20
    kind = str(kind or "playtime").strip() or "playtime"
    path = f"/api/leaderboard?type={quote(kind, safe='')}&limit={size}"
    return _request("GET", path, note=f"{kind} 前 {size} 名")
