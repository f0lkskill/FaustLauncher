"""FaustLauncher 用户身份、皮肤解锁与云端同步。"""

from __future__ import annotations

import ctypes
import json
import os
import secrets
import string
import threading
import time
from ctypes import wintypes

from functions.base.common.json_io import read_json, write_json
from functions.base.web_config import get_webnote

_USER_LOCK = threading.RLock()
_USER_DIR_NAME = "FaustLauncher"
_USER_FILE_NAME = "settings.json"
_CLOUD_NOTE_ID = "users"


def user_dir() -> str:
    roaming = os.getenv("APPDATA")
    if not roaming:
        roaming = os.path.join(os.path.expanduser("~"), "AppData", "Roaming")
    return os.path.join(roaming, _USER_DIR_NAME, "user")


def user_file() -> str:
    return os.path.join(user_dir(), _USER_FILE_NAME)


# ============================================================
# 操作冷却限制
# ------------------------------------------------------------
# 用户触发的更新 (改昵称 / 切换账号) 都会写云端, 需要限流:
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


def user_snapshot(data: dict | None = None, user_name: str = "") -> dict:
    data = data or load_user()
    return {
        "user_name": str(user_name or "Player"),
        "skins": list(_value(data, "unlocked_skins", [])),
    }


def _apply_user_name(settings_manager, name: str) -> str:
    """把云端记录的昵称同步回设置项 (settings.json → user_name)。

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


def _cloud_note():
    from functions.webFunc.Webnote import Note
    address, pwd = get_webnote(_CLOUD_NOTE_ID)
    if not address:
        return None
    return Note(_CLOUD_NOTE_ID, address, pwd)


def _read_cloud(note) -> tuple[dict, bool, str]:
    """读取用户云笔记。

    Returns:
        (数据, 是否读取成功, 失败原因)
        —— 失败原因必须与"该 ID 不存在"区分开: 断网/线路故障时若统一报
           "不存在该用户 ID", 用户会误以为自己的账号丢了。
    """
    result = note.fetch_note_info(allow_refresh=True)
    text = str((result or {}).get("note_content") or "").strip()
    if not text:
        if getattr(note, "last_fetch_error", "") and not getattr(note, "empty_note", False):
            return {}, False, "云端暂时无法访问，请检查网络后重试"
        return {"users": {}}, True, ""
    try:
        data = json.loads(text)
    except Exception:
        return {}, False, "云端用户数据格式异常，已停止本次操作"
    if not isinstance(data, dict):
        return {}, False, "云端用户数据格式异常，已停止本次操作"
    return data, True, ""


def _write_cloud(note, cloud: dict) -> bool:
    result = note.update_note_content(json.dumps(cloud, ensure_ascii=False, indent=2))
    return bool(result and result.get("status") == 1)


def sync_user(settings_manager=None) -> dict:
    """启动时同步：云端同 ID 覆盖本地；没有该 ID 则上传初始化记录。"""
    with _USER_LOCK:
        local = load_user()
        uid = str(_value(local, "user_id", ""))
        user_name = "Player"
        if settings_manager is not None:
            user_name = str(settings_manager.get_setting("user_name") or "Player")
        note = _cloud_note()
        if note is None:
            return {"ok": False, "offline": True, "user": local, "error": "未配置用户云笔记"}
        cloud, readable, reason = _read_cloud(note)
        if not readable:
            return {"ok": False, "offline": True, "user": local, "error": reason}
        users = cloud.setdefault("users", {})
        record = users.get(uid)
        if isinstance(record, dict):
            # 昵称: 云端有记录就同步回设置项 (与皮肤列表同样是"云端覆盖本地")
            remote_name = str(record.get("user_name") or "").strip()
            if remote_name:
                user_name = _apply_user_name(settings_manager, remote_name) or user_name
            remote_skins = record.get("skins")
            if isinstance(remote_skins, list):
                local["unlocked_skins"]["value"] = list(dict.fromkeys(str(x).strip() for x in remote_skins if str(x).strip()))
                local = _normalize(local)
                save_user(local)
            record["user_name"] = user_name
            record["skins"] = list(_value(local, "unlocked_skins", []))
        else:
            users[uid] = user_snapshot(local, user_name)
        if not _write_cloud(note, cloud):
            return {"ok": False, "offline": True, "user": local, "error": "用户信息上传失败"}
        return {"ok": True, "user": local, "cloud": users.get(uid)}


def push_user(settings_manager=None) -> dict:
    """把**当前本地**用户信息 (昵称 + 已解锁皮肤) 覆盖上传到云端。

    与 sync_user 的方向相反, 专供"本地刚刚发生了变化"的场景 (解锁皮肤 / 改名):
    这时绝不能走 sync_user —— 它会用云端旧列表覆盖本地, 刚解锁的皮肤会被抹掉。
    """
    with _USER_LOCK:
        local = load_user()
        uid = str(_value(local, "user_id", ""))
        user_name = "Player"
        if settings_manager is not None:
            user_name = str(settings_manager.get_setting("user_name") or "Player")
        note = _cloud_note()
        if note is None:
            return {"ok": False, "offline": True, "user": local, "error": "未配置用户云笔记"}
        cloud, readable, reason = _read_cloud(note)
        if not readable:
            return {"ok": False, "offline": True, "user": local, "error": reason}
        users = cloud.setdefault("users", {})
        users[uid] = user_snapshot(local, user_name)
        if not _write_cloud(note, cloud):
            return {"ok": False, "offline": True, "user": local, "error": "用户信息上传失败"}
        return {"ok": True, "user": local, "cloud": users.get(uid)}


def login_user(user_id: str, settings_manager=None) -> dict:
    """按用户 ID 登录: 本地身份切换为该账号, 昵称/已解锁皮肤取云端记录。

    刻意**不**处理被替换掉的旧账号: 旧账号的云端记录原样保留,
    用户随时可以用它自己的 ID 登录回来 (本地也无法判断哪个号"值得留",
    任何自动清理都可能删掉用户真实的账号)。
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
        note = _cloud_note()
        if note is None:
            return {"ok": False, "error": "未配置用户云笔记"}
        cloud, readable, reason = _read_cloud(note)
        if not readable:
            # 读取失败绝不能报成"账号不存在", 否则用户会以为号丢了
            return {"ok": False, "offline": True, "error": reason}
        record = cloud.get("users", {}).get(uid)
        if not isinstance(record, dict):
            return {"ok": False, "error": "云端不存在该用户 ID"}

        local = _new_user(uid)
        local["unlocked_skins"]["value"] = record.get("skins") if isinstance(record.get("skins"), list) else []
        local = _normalize(local)
        if not save_user(local):
            return {"ok": False, "error": "本地用户信息保存失败"}
        # 昵称跟随该账号的云端记录写回设置项
        remote_name = str(record.get("user_name") or "").strip()
        if remote_name:
            _apply_user_name(settings_manager, remote_name)
        print(f"[用户] 已登录账号 {uid}")
        mark_logged_in()          # 登录成功才计入 12 小时冷却
        return {"ok": True, "user": local, "cloud": record}


def get_user_info(settings_manager=None) -> dict:
    data = load_user()
    user_name = "Player"
    if settings_manager is not None:
        user_name = str(settings_manager.get_setting("user_name") or "Player")
    return {"user": data, "user_name": user_name, "user_path": user_file(),
            "restrictions": get_restrictions()}


def unlock_skin(skin_id: str, settings_manager=None) -> dict:
    sid = str(skin_id or "").strip()
    if not sid:
        return {"ok": False, "error": "默认皮肤无需解锁"}
    meta = skin_metadata().get(sid)
    if not meta:
        return {"ok": False, "error": "皮肤不存在"}
    data = load_user()
    skins = list(_value(data, "unlocked_skins", []))
    if sid not in skins:
        skins.append(sid)
        data["unlocked_skins"]["value"] = skins
        save_user(data)
    # 本地刚解锁: 用 push 上传, 不能用 sync (否则会被云端旧列表覆盖回未解锁)
    pushed = push_user(settings_manager)
    return {"ok": True, "user": load_user(), "sync": pushed}


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
