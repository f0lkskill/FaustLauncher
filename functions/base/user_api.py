
from __future__ import annotations

import hashlib
import os
import threading
import time
from urllib.parse import quote, urlsplit

from functions.base.common.json_io import read_json, try_read_json, write_json

DEFAULT_API_BASE = "https://folkskill.pythonanywhere.com"

CONNECT_TIMEOUT = 10
READ_TIMEOUT = 20
_SESSION_FILE = "session.json"
_LOGIN_COOKIES = ("login_user", "login_sig")
_AVATAR_CACHE_DIR_NAME = "avatar_cache"
_AVATAR_MANIFEST_NAME = "manifest.json"
_AVATAR_MAX_BYTES = 2 * 1024 * 1024

_lock = threading.RLock()
_avatar_lock = threading.RLock()
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

def avatar_cache_dir() -> str:
    """头像缓存目录，与用户设置、登录态统一放在 ``%APPDATA%/FaustLauncher/user``。"""
    return os.path.join(user_data_dir(), _AVATAR_CACHE_DIR_NAME)


def avatar_manifest_file() -> str:
    return os.path.join(avatar_cache_dir(), _AVATAR_MANIFEST_NAME)


def _avatar_cache_key(url: str) -> str:
    """按稳定的头像路径取缓存键；``?v=`` 变化时复用同一份本地图像。"""
    try:
        parts = urlsplit(str(url or "").strip())
    except Exception:
        parts = None
    stable = (f"{parts.scheme.lower()}://{parts.netloc.lower()}{parts.path}"
              if parts is not None else str(url or ""))
    return hashlib.sha1(stable.encode("utf-8")).hexdigest()


def _resolve_avatar_url(url: str):
    """校验头像 URL，只允许当前 API 主机的 ``/static/avatars/``。"""
    target = str(url or "").strip()
    if not target:
        return None
    base = api_base()
    if target.startswith("//"):
        target = "https:" + target
    elif target.startswith("/"):
        target = base + target
    try:
        parts = urlsplit(target)
        base_parts = urlsplit(base)
    except Exception:
        return None
    if (parts.scheme not in ("http", "https")
            or parts.netloc.lower() != base_parts.netloc.lower()
            or not parts.path.startswith("/static/avatars/")):
        return None
    return target


def _avatar_manifest() -> dict:
    data = try_read_json(avatar_manifest_file(), {})
    return data if isinstance(data, dict) else {}


def _avatar_entry(url: str):
    target = _resolve_avatar_url(url)
    if target is None:
        return None, None
    return target, _avatar_manifest().get(_avatar_cache_key(target))


def _image_mime(data: bytes, content_type: str = "") -> str:
    mime = str(content_type or "").split(";", 1)[0].strip().lower()
    if mime.startswith("image/"):
        return mime
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    return ""


def load_avatar_local(url: str):
    """读取本地头像，返回 ``(bytes, content_type)``；无有效缓存时返回 ``None``。"""
    target, entry = _avatar_entry(url)
    if target is None or not isinstance(entry, dict):
        return None
    stored_url = str(entry.get("url") or "").strip()
    if stored_url and _avatar_cache_key(stored_url) != _avatar_cache_key(target):
        return None
    path = os.path.join(avatar_cache_dir(), _avatar_cache_key(target) + ".bin")
    try:
        with open(path, "rb") as fh:
            data = fh.read(_AVATAR_MAX_BYTES + 1)
    except OSError:
        return None
    if not data or len(data) > _AVATAR_MAX_BYTES:
        return None
    try:
        size = int(entry.get("size") or 0)
    except (TypeError, ValueError):
        size = 0
    if size and size != len(data):
        return None
    digest = str(entry.get("sha256") or "").strip().lower()
    if digest and digest != hashlib.sha256(data).hexdigest():
        return None
    mime = _image_mime(data, str(entry.get("mime") or ""))
    return (data, mime) if mime else None


def save_avatar_local(url: str, data: bytes, content_type: str,
                      etag: str = "", last_modified: str = "") -> bool:
    """原子写入头像图像和更新元数据，下一次启动可直接离线读取。"""
    target = _resolve_avatar_url(url)
    if target is None or not data or len(data) > _AVATAR_MAX_BYTES:
        return False
    mime = _image_mime(data, content_type)
    if not mime:
        return False
    path = os.path.join(avatar_cache_dir(), _avatar_cache_key(target) + ".bin")
    entry = {
        "url": target,
        "mime": mime,
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "saved_at": time.time(),
    }
    if etag:
        entry["etag"] = str(etag)
    if last_modified:
        entry["last_modified"] = str(last_modified)
    try:
        with _avatar_lock:
            os.makedirs(avatar_cache_dir(), exist_ok=True)
            tmp = path + ".tmp"
            with open(tmp, "wb") as fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, path)
            manifest = _avatar_manifest()
            manifest[_avatar_cache_key(target)] = entry
            write_json(avatar_manifest_file(), manifest, indent=2, fsync=True)
        return True
    except OSError as exc:
        print(f"[UserAPI] 头像缓存写入失败: {type(exc).__name__}: {exc}")
        return False


def _avatar_response(url: str, etag: str = "", last_modified: str = ""):
    target = _resolve_avatar_url(url)
    if target is None:
        return None
    headers = {"Accept": "image/*,*/*;q=0.8"}
    if etag:
        headers["If-None-Match"] = str(etag)
    if last_modified:
        headers["If-Modified-Since"] = str(last_modified)
    try:
        resp = _get_session().get(
            target, headers=headers, timeout=(CONNECT_TIMEOUT, READ_TIMEOUT))
    except Exception as exc:
        print(f"[UserAPI] 头像下载失败: {type(exc).__name__}")
        return None
    status = int(getattr(resp, "status_code", 0) or 0)
    if status == 304:
        return {"not_modified": True}
    if status != 200:
        return None
    data = resp.content or b""
    if not data or len(data) > _AVATAR_MAX_BYTES:
        return None
    ctype = _image_mime(data, str(resp.headers.get("Content-Type") or ""))
    if not ctype:
        return None
    return {
        "data": data,
        "mime": ctype,
        "etag": str(resp.headers.get("ETag") or "").strip(),
        "last_modified": str(resp.headers.get("Last-Modified") or "").strip(),
    }


def fetch_avatar(url: str):
    """本地缓存优先；没有缓存才下载并落盘，失败返回 ``None``。"""
    target = _resolve_avatar_url(url)
    if target is None:
        return None
    local = load_avatar_local(target)
    if local is not None:
        return local
    got = _avatar_response(target)
    if not got or got.get("not_modified"):
        return None
    save_avatar_local(target, got["data"], got["mime"],
                      got.get("etag", ""), got.get("last_modified", ""))
    return got["data"], got["mime"]


def check_avatar_update(url: str):
    """检查远端头像更新，并始终返回当前可用的本地图像。

    有本地缓存时携带 ETag/Last-Modified 做条件请求；304、断网或服务端异常
    都保留本地图。发现新图时先原子落盘，再返回新图。
    """
    target, entry = _avatar_entry(url)
    if target is None:
        return None
    etag = str((entry or {}).get("etag") or "").strip() \
        if isinstance(entry, dict) else ""
    modified = str((entry or {}).get("last_modified") or "").strip() \
        if isinstance(entry, dict) else ""
    got = _avatar_response(target, etag, modified)
    if got and not got.get("not_modified"):
        if save_avatar_local(target, got["data"], got["mime"],
                             got.get("etag", ""), got.get("last_modified", "")):
            print("[UserAPI] 头像已更新并写入本地缓存")
            return got["data"], got["mime"]
    return load_avatar_local(target)

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
