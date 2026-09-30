"""FaustLauncher 用户身份、皮肤解锁与云端同步。

云端数据**一律通过服务端 API 读写** (`functions/base/user_api.py`):

  · 不再读 `/note/FaustLauncher.users`, 也不再 `POST /update/` 整表覆盖
    —— 那种写法是最后写入者胜, 客户端本地表旧一点就会成批丢用户;
  · 服务端的 `/api/me/*` 从登录会话里取 uid, 锁内只改自己那一行,
    结构上不可能牵连别人;
  · 本模块**不缓存任何用户数据**, 每次同步都发真实请求。

本地用户文件 (`%APPDATA%\\FaustLauncher\\user\\settings.json`) 只保存两件事:
本机当前使用的用户 ID、以及本地已解锁的皮肤。
"""

from __future__ import annotations

import ctypes
import os
import secrets
import string
import sys
import threading
import time
from ctypes import wintypes

from functions.base import user_api
from functions.base.common.json_io import read_json, write_json
from functions.base.user_api import user_data_dir

_USER_LOCK = threading.RLock()
_USER_FILE_NAME = "settings.json"
_legacy_cache_checked = False


def user_dir() -> str:
    """用户数据目录 (唯一定义在 user_api, 与登录态文件放在同一处)"""
    return user_data_dir()


def user_file() -> str:
    return os.path.join(user_dir(), _USER_FILE_NAME)


def _project_root() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.abspath(os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", ".."))


def drop_legacy_user_cache() -> None:
    """清理旧实现留下的用户表缓存 (启动时执行一次)。

    老版本用 Webnote 读整张用户表, 会在 `cache/webnote/` 下留一份
    `FaustLauncher.users.txt`。现在不再整表读写, 这份缓存既没有用处,
    又可能被误当成"云端数据", 所以直接删掉。
    """
    global _legacy_cache_checked
    if _legacy_cache_checked:
        return
    _legacy_cache_checked = True
    try:
        cache_dir = os.path.join(_project_root(), "cache", "webnote")
        for name in ("FaustLauncher.users.txt", "FaustLauncher_users.txt"):
            path = os.path.join(cache_dir, name)
            if os.path.isfile(path):
                os.remove(path)
                print(f"[用户] 已清理旧版用户表缓存: {path}")
    except Exception as exc:
        print(f"[用户] 清理旧缓存失败(忽略): {exc}")


# ============================================================
# 操作冷却限制
# ------------------------------------------------------------
# 用户触发的更新 (改昵称 / 切换账号) 都会写服务端, 需要限流:
#   · 改名: 1 小时内只能改一次
#   · 登录: 12 小时内只能登录一次
# 两项**独立计时** (改完名不影响登录冷却, 反之亦然)。
#
# 时间戳存在独立文件里 (与账号无关) —— 存在用户文件里的话,
# 登录会把整个用户文件换成新账号的内容, 冷却时间会跟着被重置, 限制就失效了。
# ============================================================
RENAME_COOLDOWN_SEC = 3600            # 改名冷却: 1 小时
LOGIN_COOLDOWN_SEC = 12 * 3600        # 登录冷却: 12 小时
_RESTRICTIONS_FILE = "restrictions.json"


def restrictions_file() -> str:
    return os.path.join(user_dir(), _RESTRICTIONS_FILE)


def _load_restrictions() -> dict:
    try:
        data = read_json(restrictions_file())
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _save_restrictions(data: dict) -> None:
    path = restrictions_file()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        write_json(path, data if isinstance(data, dict) else {}, indent=4, fsync=True)
    except Exception as exc:
        print(f"[用户] 保存操作限制失败: {exc}")


def _left_seconds(stamp, cooldown: int) -> int:
    """剩余冷却秒数; 无记录或已过期返回 0"""
    try:
        last = float(stamp or 0)
    except (TypeError, ValueError):
        last = 0.0
    if last <= 0:
        return 0
    left = cooldown - (time.time() - last)
    if left <= 0:
        return 0
    # 向上取整: 还剩 0.4 秒也显示"1 分钟", 不能显示成 0 让用户以为已经可以操作
    return int(left) + 1


def format_left(seconds) -> str:
    """剩余时间的中文描述"""
    total = int(seconds or 0)
    if total <= 0:
        return ""
    if total >= 86400:
        days, rest = divmod(total, 86400)
        hours = rest // 3600
        return f"{days} 天 {hours} 小时" if hours else f"{days} 天"
    if total >= 3600:
        hours, rest = divmod(total, 3600)
        minutes = rest // 60
        return f"{hours} 小时 {minutes} 分钟" if minutes else f"{hours} 小时"
    return f"{max(1, total // 60)} 分钟"


def get_restrictions() -> dict:
    """当前两项冷却的剩余秒数 (0 = 可以操作)"""
    data = _load_restrictions()
    return {
        "rename_left": _left_seconds(data.get("last_rename_at"), RENAME_COOLDOWN_SEC),
        "login_left": _left_seconds(data.get("last_login_at"), LOGIN_COOLDOWN_SEC),
        "rename_cooldown": RENAME_COOLDOWN_SEC,
        "login_cooldown": LOGIN_COOLDOWN_SEC,
    }


def check_rename_allowed() -> str:
    """改名是否被冷却挡住; 挡住时返回提示文案, 允许则返回空串"""
    left = _left_seconds(_load_restrictions().get("last_rename_at"), RENAME_COOLDOWN_SEC)
    if left <= 0:
        return ""
    return f"用户名 1 小时内只能修改一次，请 {format_left(left)}后再试"


def check_login_allowed() -> str:
    """登录是否被冷却挡住; 挡住时返回提示文案, 允许则返回空串"""
    left = _left_seconds(_load_restrictions().get("last_login_at"), LOGIN_COOLDOWN_SEC)
    if left <= 0:
        return ""
    return f"登录 12 小时内只能进行一次，请 {format_left(left)}后再试"


def _mark_time(kind: str) -> None:
    data = _load_restrictions()
    data[f"last_{kind}_at"] = time.time()
    _save_restrictions(data)


def mark_renamed() -> None:
    """记录本次改名时间 (只在昵称真的变化且保存成功后调用)"""
    _mark_time("rename")


def mark_logged_in() -> None:
    """记录本次登录时间 (只在登录成功后调用)"""
    _mark_time("login")


# ============================================================
# 本地用户文件
# ============================================================
def _setting(name, type_name, value, default, description):
    return {
        "name": name,
        "type": type_name,
        "default": default,
        "value": value,
        "description": description,
    }


def _new_user(user_id: str | None = None) -> dict:
    """用户信息骨架 (结构对齐 config/settings.json)。"""
    uid = user_id or _make_user_id()
    return {
        "user_id": _setting("用户ID", "string", uid, "", "用于跨设备同步用户解锁信息。"),
        "unlocked_skins": _setting("已解锁皮肤", "list", [], [], "已解锁的皮肤 ID 列表。"),
    }


def _make_user_id() -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "FL-" + "".join(secrets.choice(alphabet) for _ in range(16))


def _value(data: dict, key: str, fallback):
    item = data.get(key)
    if isinstance(item, dict):
        return item.get("value", item.get("default", fallback))
    return fallback


def _skin_root() -> str:
    from functions.base.common.path_utils import get_web_root
    return get_web_root("app_skins")


def skin_metadata() -> dict[str, dict]:
    """返回 skin id -> config.json 元数据。默认内置皮肤不参与解锁。"""
    root = _skin_root()
    out: dict[str, dict] = {}
    try:
        names = sorted(os.listdir(root))
    except Exception:
        return out
    for name in names:
        path = os.path.join(root, name)
        if not os.path.isdir(path) or os.path.basename(name) != name:
            continue
        config = os.path.join(path, "config.json")
        try:
            data = read_json(config)
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        sid = str(data.get("id") or name).strip()
        if sid:
            out[sid] = data
    return out


def _free_skin_ids() -> list[str]:
    result = []
    for sid, meta in skin_metadata().items():
        unlock = meta.get("unlock")
        if isinstance(unlock, dict) and str(unlock.get("type") or "").lower() == "free":
            result.append(sid)
    return result


def _normalize(data: dict) -> dict:
    if not isinstance(data, dict):
        data = {}
    uid = str(_value(data, "user_id", "")).strip() or _make_user_id()
    raw_skins = _value(data, "unlocked_skins", [])
    if not isinstance(raw_skins, list):
        raw_skins = []
    skins = []
    for sid in raw_skins:
        sid = str(sid).strip()
        if sid and sid not in skins:
            skins.append(sid)
    for sid in _free_skin_ids():
        if sid not in skins:
            skins.append(sid)
    # 注意: 这里不再产出 auto_created 之类的账号来源标记 ——
    # 本地无法可靠区分"自动生成的号"和"用户自己的号", 误判会造成困扰。
    # 因此归一化结果里多余的旧字段会在下次保存时被自然剔除。
    normalized = _new_user(uid)
    normalized["unlocked_skins"]["value"] = skins
    return normalized


def load_user() -> dict:
    with _USER_LOCK:
        path = user_file()
        try:
            data = read_json(path)
        except Exception:
            data = _new_user()
        normalized = _normalize(data)
        if data != normalized:
            save_user(normalized)
        return normalized


def save_user(data: dict) -> bool:
    normalized = _normalize(data)
    path = user_file()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        write_json(path, normalized, indent=4, fsync=True)
        return True
    except Exception as exc:
        print(f"[用户] 保存本地用户信息失败: {exc}")
        return False


def _apply_user_name(settings_manager, name: str) -> str:
    """把服务端的昵称同步回设置项 (settings.json → user_name)。

    老配置里可能没有 user_name 这一项, 这时现场补一个 schema 项 ——
    SettingsManager.set_setting 对未知键直接返回 False, 不会创建。
    """
    name = str(name or "").strip()
    if not name or settings_manager is None:
        return ""
    try:
        if "user_name" not in settings_manager.settings:
            settings_manager.settings["user_name"] = {
                "name": "用户名",
                "type": "string",
                "default": "Player",
                "value": "Player",
                "description": "你的用户名，将显示在边狱巴士的个人车票上。",
                "page": "美化",
            }
        if str(settings_manager.get_setting("user_name") or "") != name:
            settings_manager.set_setting("user_name", name)
            settings_manager.save_settings()
    except Exception as exc:
        print(f"[用户] 同步昵称到设置项失败: {exc}")
    return name


# ============================================================
# 服务端同步
# ============================================================
def _merge_skins(*lists) -> list[str]:
    """皮肤并集 (保持先后顺序, 去空去重)"""
    out: list[str] = []
    for seq in lists:
        for sid in (seq or []):
            sid = str(sid or "").strip()
            if sid and sid not in out:
                out.append(sid)
    return out


def _server_identity(uid: str, defaults: dict | None = None) -> tuple[dict | None, dict | None]:
    """取服务端上 `uid` 这个账号的记录, 并确保拿到可用的登录态。

    走 `/api/register` 而不是 `/api/login` —— 服务端要求的顺序就是"先 register":
      · ID 已存在: 幂等返回, **一个字段都不改** (不会冲掉昵称/皮肤/角色);
      · ID 不存在: 直接建档 (新环境第一次运行走的就是这条路);
      · 两种情况都下发登录 Cookie, 紧接着就能调 /api/me/*。
    只有注册被拒时才退回 login (已存在的账号仍然登录得上):
      · 服务端配了 REGISTER_TOKEN 而客户端没有令牌;
      · 本地 ID 不是 `FL-` + 16 位的新格式 (更老版本留下的)。

    Args:
        defaults: 建档时用的初值 {"user_name": ..., "skins": [...]};
                  对**已存在**的账号完全无影响。

    Returns: (记录, 错误) —— 记录为 None 时看错误里的 error/offline/status。
    """
    result = user_api.me()
    if result.get("ok"):
        remote_id = str((result.get("data") or {}).get("id") or "")
        if remote_id == uid:
            return result["data"], None
        # 会话里是另一个账号 (例如本地身份被改过): 下面重新登记成本地这个 ID

    reg = user_api.register(uid, **dict(defaults or {}))
    if reg.get("ok"):
        return reg["data"], None
    if reg.get("offline"):
        return None, reg

    # 注册被拒 (格式不合规 / 需要令牌): 已存在的账号仍可登录
    login_result = user_api.login(uid)
    if login_result.get("ok"):
        return login_result["data"], None
    return None, (login_result if login_result.get("error") else reg)


def sync_user(settings_manager=None) -> dict:
    """启动 / 窗口聚焦时同步: 皮肤取**并集**, 昵称以服务端为准。

    为什么是并集而不是"云端覆盖本地": 玩家自己解锁的皮肤, 或服务端某次写失败的
    记录, 都会在下次同步时被云端旧列表抹掉。并集保证两边只增不减。
    """
    drop_legacy_user_cache()
    with _USER_LOCK:
        local = load_user()
        uid = str(_value(local, "user_id", "")).strip()
        if not uid:
            return {"ok": False, "user": local, "error": "本地没有用户 ID"}

        local_name = ""
        if settings_manager is not None:
            local_name = str(settings_manager.get_setting("user_name") or "").strip()
        # 建档初值用本地现状: 新环境第一次运行就能把自己的昵称/皮肤一次带上去
        # (ID 已存在时 register 是幂等的, 这些初值不会覆盖服务端数据)
        data, err = _server_identity(uid, {
            "user_name": local_name,
            "skins": list(_value(local, "unlocked_skins", [])),
        })
        if data is None:
            err = err or {}
            return {"ok": False, "offline": bool(err.get("offline")), "user": local,
                    "error": err.get("error") or "云端读取失败"}

        remote_skins = [str(s).strip() for s in (data.get("skins") or []) if str(s).strip()]
        merged = _merge_skins(_value(local, "unlocked_skins", []), remote_skins)

        # 服务端缺的补上去 (并集策略: 只增不减)
        pushed, push_error = True, ""
        if sorted(merged) != sorted(remote_skins):
            push = user_api.push_skins(merged)
            pushed = bool(push.get("ok"))
            if not pushed:
                push_error = push.get("error") or "云端写入失败"

        local["unlocked_skins"]["value"] = merged
        local = _normalize(local)
        save_user(local)

        remote_name = str(data.get("user_name") or "").strip()
        if remote_name:
            _apply_user_name(settings_manager, remote_name)

        return {"ok": True, "user": local, "cloud": data,
                "pushed": pushed, "push_error": push_error}


def push_skins(settings_manager=None) -> dict:
    """把本地皮肤列表同步到服务端。

    先与云端取并集再整体写回 —— 服务端的 `/api/me/skins` 是"整体替换自己那一行",
    不比一次云端就会覆盖掉别的设备刚解锁的皮肤。
    """
    with _USER_LOCK:
        local = load_user()
        uid = str(_value(local, "user_id", "")).strip()
        if not uid:
            return {"ok": False, "user": local, "error": "本地没有用户 ID"}

        data, err = _server_identity(uid, {"skins": list(_value(local, "unlocked_skins", []))})
        if data is None:
            err = err or {}
            return {"ok": False, "offline": bool(err.get("offline")), "user": local,
                    "error": err.get("error") or "云端读取失败"}

        remote = [str(s).strip() for s in (data.get("skins") or []) if str(s).strip()]
        merged = _merge_skins(_value(local, "unlocked_skins", []), remote)
        local["unlocked_skins"]["value"] = merged
        save_user(local)

        # 两边已经一致就不必再写一次 (少一次请求, 也少一次并发写入的机会)
        if sorted(merged) == sorted(remote):
            return {"ok": True, "user": load_user(), "cloud": data, "skipped": True}

        result = user_api.push_skins(merged)
        if not result.get("ok"):
            return {"ok": False, "offline": bool(result.get("offline")),
                    "user": load_user(), "error": result.get("error") or "云端写入失败"}
        return {"ok": True, "user": load_user(), "cloud": result.get("data") or {}}


def push_name(name: str, settings_manager=None) -> dict:
    """把昵称写到服务端**自己**的记录 (`POST /api/me/name`)"""
    clean = str(name or "").strip()
    if not clean:
        return {"ok": False, "error": "昵称不能为空"}
    with _USER_LOCK:
        uid = str(_value(load_user(), "user_id", "")).strip()
        if not uid:
            return {"ok": False, "error": "本地没有用户 ID"}

        data, err = _server_identity(uid, {"user_name": clean})
        if data is None:
            err = err or {}
            return {"ok": False, "offline": bool(err.get("offline")),
                    "error": err.get("error") or "云端读取失败"}

        result = user_api.push_name(clean)
        if not result.get("ok"):
            return {"ok": False, "offline": bool(result.get("offline")),
                    "error": result.get("error") or "云端写入失败"}
        return {"ok": True, "cloud": result.get("data") or {}}


def login_user(user_id: str, settings_manager=None) -> dict:
    """按用户 ID 登录: 本地身份切换为该账号, 昵称/皮肤取服务端记录。

    服务端会和它自己的用户表核对 (不存在直接回"用户 ID「x」不存在"), 并下发登录 Cookie。
    切换账号时**以服务端记录为准** —— 不能把上一个账号的皮肤并过来;
    旧账号的记录原样保留, 随时可以用它的 ID 登录回来。
    """
    uid = str(user_id or "").strip()
    if not uid:
        return {"ok": False, "error": "用户 ID 不能为空"}
    blocked = check_login_allowed()
    if blocked:
        return {"ok": False, "limited": True, "error": blocked}
    with _USER_LOCK:
        old_id = str(_value(load_user(), "user_id", "")).strip()
        if old_id and old_id == uid:
            return {"ok": False, "error": "当前已经是该账号"}

        result = user_api.login(uid)
        if not result.get("ok"):
            return {"ok": False, "offline": bool(result.get("offline")),
                    "error": result.get("error") or "登录失败"}

        data = result.get("data") or {}
        local = _new_user(uid)
        local["unlocked_skins"]["value"] = [str(s) for s in (data.get("skins") or []) if str(s).strip()]
        local = _normalize(local)
        if not save_user(local):
            return {"ok": False, "error": "本地用户信息保存失败"}

        remote_name = str(data.get("user_name") or "").strip()
        if remote_name:
            _apply_user_name(settings_manager, remote_name)

        print(f"[用户] 已登录账号 {uid}" + ("（管理员）" if data.get("is_admin") else ""))
        mark_logged_in()          # 登录成功才计入 12 小时冷却
        return {"ok": True, "user": local, "cloud": data}


def get_user_info(settings_manager=None) -> dict:
    data = load_user()
    user_name = "Player"
    if settings_manager is not None:
        user_name = str(settings_manager.get_setting("user_name") or "Player")
    return {"user": data, "user_name": user_name, "user_path": user_file(),
            "restrictions": get_restrictions(),
            "logged_in": user_api.has_session()}


def unlock_skin(skin_id: str, settings_manager=None) -> dict:
    sid = str(skin_id or "").strip()
    if not sid:
        return {"ok": False, "error": "默认皮肤无需解锁"}
    if not skin_metadata().get(sid):
        return {"ok": False, "error": "皮肤不存在"}
    with _USER_LOCK:
        data = load_user()
        skins = list(_value(data, "unlocked_skins", []))
        if sid not in skins:
            skins.append(sid)
        data["unlocked_skins"]["value"] = skins
        save_user(data)
        # 本地刚解锁: 与云端取并集后上报。反过来用云端覆盖本地会把这个皮肤抹掉。
        pushed = push_skins(settings_manager)
    return {"ok": True, "user": load_user(), "sync": pushed}


# ============================================================
# 皮肤解锁条件验证
# ============================================================
def _edge_title_contains(keyword: str) -> tuple[bool, str]:
    keyword = str(keyword or "DeepSeek").lower()
    found = []
    if os.name != "nt":
        return False, ""
    try:
        user32 = ctypes.windll.user32
    except Exception:
        return False, ""
    try:
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def callback(hwnd, _lparam):
            if not user32.IsWindowVisible(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                return True
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            title = buf.value
            if keyword in title.lower() and ("edge" in title.lower() or "deepseek" in title.lower()):
                found.append(title)
                return False
            return True
        user32.EnumWindows(callback_type(callback), 0)
    except Exception:
        return False, ""
    return bool(found), (found[0] if found else "")


def verify_skin(skin_id: str) -> dict:
    sid = str(skin_id or "").strip()
    meta = skin_metadata().get(sid)
    if not meta:
        return {"ok": False, "unlocked": False, "error": "皮肤不存在"}
    unlock = meta.get("unlock") if isinstance(meta.get("unlock"), dict) else {"type": "free"}
    kind = str(unlock.get("type") or "free").lower()
    if kind == "free":
        return {"ok": True, "unlocked": True, "condition": unlock}
    if kind == "edge_window_title":
        passed, title = _edge_title_contains(unlock.get("title_keyword") or "DeepSeek")
        return {"ok": True, "unlocked": passed, "title": title, "condition": unlock}
    return {"ok": False, "unlocked": False, "condition": unlock, "error": "未知解锁条件"}
