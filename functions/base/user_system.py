
from __future__ import annotations

import ctypes
import json
import os
import secrets
import string
import sys
import threading
import time
from ctypes import wintypes

from functions.base import user_api
from functions.base.common.json_io import read_json, write_json
from functions.base.user_api import mask_uid, user_data_dir

_USER_LOCK = threading.RLock()
_USER_FILE_NAME = "settings.json"
_legacy_cache_checked = False

def user_dir() -> str:
    return user_data_dir()

def user_file() -> str:
    return os.path.join(user_dir(), _USER_FILE_NAME)

def _project_root() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.abspath(os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", ".."))

def drop_legacy_user_cache() -> None:
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
                print(f"[User] 已清理旧版用户表缓存: {path}")
    except Exception as exc:
        print(f"[User] 清理旧缓存失败(忽略): {exc}")

RENAME_COOLDOWN_SEC = 3600
LOGIN_COOLDOWN_SEC = 12 * 3600
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
        print(f"[User] 保存操作限制失败: {exc}")

def _left_seconds(stamp, cooldown: int) -> int:
    try:
        last = float(stamp or 0)
    except (TypeError, ValueError):
        last = 0.0
    if last <= 0:
        return 0
    left = cooldown - (time.time() - last)
    if left <= 0:
        return 0
    return int(left) + 1

def format_left(seconds) -> str:
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
    data = _load_restrictions()
    return {
        "rename_left": _left_seconds(data.get("last_rename_at"), RENAME_COOLDOWN_SEC),
        "login_left": _left_seconds(data.get("last_login_at"), LOGIN_COOLDOWN_SEC),
        "rename_cooldown": RENAME_COOLDOWN_SEC,
        "login_cooldown": LOGIN_COOLDOWN_SEC,
    }

def check_rename_allowed() -> str:
    left = _left_seconds(_load_restrictions().get("last_rename_at"), RENAME_COOLDOWN_SEC)
    if left <= 0:
        return ""
    return f"用户名 1 小时内只能修改一次，请 {format_left(left)}后再试"

def check_login_allowed() -> str:
    left = _left_seconds(_load_restrictions().get("last_login_at"), LOGIN_COOLDOWN_SEC)
    if left <= 0:
        return ""
    return f"登录 12 小时内只能进行一次，请 {format_left(left)}后再试"

def _mark_time(kind: str) -> None:
    data = _load_restrictions()
    data[f"last_{kind}_at"] = time.time()
    _save_restrictions(data)

def mark_renamed() -> None:
    _mark_time("rename")

def mark_logged_in() -> None:
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
    uid = user_id or _make_user_id()
    return {
        "user_id": _setting("用户ID", "string", uid, "", "用于跨设备同步用户解锁信息。"),
        "unlocked_skins": _setting("已解锁皮肤", "list", [], [], "已解锁的皮肤 ID 列表。"),
        "completed_achievements": _setting("已完成成就", "list", [], [],
                                           "已完成的成就 ID 列表 (成就页据此判定完成)。"),
        "server_profile": _setting("服务端资料", "dict", {}, {},
                                   "服务端返回的完整用户资料快照 (原样镜像, 不挑选字段)。"),
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
    raw_done = _value(data, "completed_achievements", [])
    if not isinstance(raw_done, list):
        raw_done = []
    done = []
    for aid in raw_done:
        aid = str(aid).strip()
        if aid and aid not in done:
            done.append(aid)
    profile = _value(data, "server_profile", {})
    if not isinstance(profile, dict):
        profile = {}
    normalized = _new_user(uid)
    normalized["unlocked_skins"]["value"] = skins
    normalized["completed_achievements"]["value"] = done
    normalized["server_profile"]["value"] = profile
    return normalized

def _store_server_profile(data: dict, payload: dict) -> dict:
    if isinstance(payload, dict) and payload:
        snapshot = {k: v for k, v in payload.items() if k != "ok"}
        data["server_profile"]["value"] = snapshot
    return data

def server_profile() -> dict:
    profile = _value(load_user(), "server_profile", {})
    return profile if isinstance(profile, dict) else {}

def _profile_keys(payload: dict) -> str:
    if not isinstance(payload, dict):
        return "(无)"
    keys = sorted(k for k in payload.keys() if k != "ok")
    return ", ".join(keys) if keys else "(空)"

def _refresh_profile_from(payload: dict) -> dict:
    if not isinstance(payload, dict) or not payload:
        return load_user()
    save_user(_store_server_profile(load_user(), payload))
    return load_user()

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
        print(f"[User] 保存本地用户信息失败: {exc}")
        return False

def _apply_user_name(settings_manager, name: str) -> str:
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
            print(f"[User] 服务端昵称已写回设置项: {name}")
    except Exception as exc:
        print(f"[User] 同步昵称到设置项失败: {exc}")
    return name

def _merge_skins(*lists) -> list[str]:
    out: list[str] = []
    for seq in lists:
        for sid in (seq or []):
            sid = str(sid or "").strip()
            if sid and sid not in out:
                out.append(sid)
    return out

def _server_identity(uid: str, defaults: dict | None = None) -> tuple[dict | None, dict | None]:
    result = user_api.me()
    if result.get("ok"):
        remote_id = str((result.get("data") or {}).get("id") or "")
        if remote_id == uid:
            return result["data"], None
        print(f"[User] 本地登录态属于另一个账号, 重新登记 (账号 {mask_uid(uid)})")

    reg = user_api.register(uid, **dict(defaults or {}))
    if reg.get("ok"):
        created = (reg.get("data") or {}).get("created")
        print(f"[User] 注册接口确认账号 (账号 {mask_uid(uid)}, "
              f"{'新建' if created else '已存在, 未改动任何数据'})")
        return reg["data"], None
    if reg.get("offline"):
        return None, reg

    print(f"[User] 注册被拒 (HTTP {reg.get('status')}: {reg.get('error')}), 退回登录接口")
    login_result = user_api.login(uid)
    if login_result.get("ok"):
        print(f"[User] 登录接口成功 (账号 {mask_uid(uid)})")
        return login_result["data"], None
    return None, (login_result if login_result.get("error") else reg)

def pull_achievements_from_cloud(mode: str = "union") -> dict:
    result = user_api.me()
    if not result.get("ok"):
        return {"ok": False, "error": result.get("error") or "云端读取失败"}
    payload = result.get("data")
    payload = payload if isinstance(payload, dict) else {}
    remote = [str(x).strip() for x in (payload.get("achievements") or []) if str(x).strip()]
    with _USER_LOCK:
        local = load_user()
        current = _value(local, "completed_achievements", [])
        mine = [str(x).strip() for x in current] if isinstance(current, list) else []
        mine = [x for x in mine if x]
        if mode == "overwrite":
            merged = list(remote)
        else:
            merged = list(mine)
            for aid in remote:
                if aid not in merged:
                    merged.append(aid)
        local["completed_achievements"]["value"] = merged
        local = _normalize(local)
        save_user(local)
    added = len(merged) - len(mine)
    action = "覆盖本地" if mode == "overwrite" else f"与本地取并集（新增 {added} 条）"
    print(f"[User] 云端成就 {len(remote)} 条 → {action}，合计 {len(merged)} 条")
    return {"ok": True, "mode": mode, "count": len(remote), "achievements": merged,
            "local_before": len(mine), "local_after": len(merged), "added": added}

def push_achievement(achievement_id: str, uid: str = "") -> dict:
    aid = str(achievement_id or "").strip()
    if not aid:
        return {"ok": False, "error": "成就 ID 为空"}
    target = str(uid or "").strip() or str(_value(load_user(), "user_id", "") or "").strip()
    if not target:
        print("[User] 未登录，跳过单条成就上报")
        return {"ok": False, "error": "未登录"}
    result = user_api.add_achievement(aid, target)
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    if result.get("ok"):
        assert data is not None
        added = bool(data.get("added"))
        known = data.get("known")
        note = "" if known is None else ("（服务端已收录）" if known else "（服务端暂未收录该 ID）")
        print(f"[User] 成就单条上报: {aid} → {'新加' if added else '云端已有(幂等跳过)'}{note}")
        assert data is not None
        return {"ok": True, "added": added, "known": known,
                "count": int(data.get("count") or 0)}
    print(f"[User] 成就单条上报失败: {aid} → {result.get('error')}")
    return {"ok": False, "error": str(result.get("error") or "")}

def push_achievements_to_cloud() -> dict:
    ids = completed_achievements()
    result = user_api.push_achievements(ids)
    if result.get("ok"):
        return {**result, "method": "me", "count": len(ids)}
    uid = str(_value(load_user(), "user_id", "")).strip()
    fallback = user_api.overwrite_achievements(ids, uid)
    print(f"[User] 方式①上报失败({result.get('error')})，改用方式②覆盖上传")
    return {**fallback, "method": "overwrite", "count": len(ids),
            "first_error": result.get("error")}

def sync_achievements(pull: bool = True, mode: str = "union") -> dict:
    pulled: dict = {"ok": False, "skipped": True}
    if pull:
        pulled = pull_achievements_from_cloud(mode=mode)
    pushed = push_achievements_to_cloud()
    return {"ok": bool(pushed.get("ok")), "pull": pulled, "push": pushed,
            "local_count": len(completed_achievements())}

def sync_playtime(overwrite: bool = True) -> dict:
    try:
        from functions.base import steam_playtime
        info = steam_playtime.read_playtime()
    except Exception as exc:  # noqa: BLE001
        print(f"[User] 读取 Steam 游玩时长失败: {type(exc).__name__}: {exc}")
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    if not info.get("ok"):
        print(f"[User] 游玩时长未上报: {info.get('error')}")
        return {"ok": False, "skipped": True, "error": str(info.get("error") or "")}
    result = user_api.report_playtime(int(info["seconds"]), overwrite=overwrite)
    ok = bool(result.get("ok"))
    print(f"[User] 游玩时长上报: 本机 {info['hours']} 小时（{info['minutes']} 分钟）→ "
          f"{'成功' if ok else '失败(' + str(result.get('error')) + ')'}")
    return {"ok": ok, "seconds": int(info["seconds"]), "hours": info["hours"],
            "minutes": int(info["minutes"]), "error": str(result.get("error") or "")}

def sync_user(settings_manager=None) -> dict:
    drop_legacy_user_cache()
    with _USER_LOCK:
        local = load_user()
        uid = str(_value(local, "user_id", "")).strip()
        if not uid:
            return {"ok": False, "user": local, "error": "本地没有用户 ID"}

        local_name = ""
        if settings_manager is not None:
            local_name = str(settings_manager.get_setting("user_name") or "").strip()
        local_skins = list(_value(local, "unlocked_skins", []))
        print(f"[User] 开始同步: 账号 {mask_uid(uid)}, 本地皮肤 {len(local_skins)} 项")

        data, err = _server_identity(uid, {
            "user_name": local_name,
            "skins": local_skins,
        })
        if data is None:
            err = err or {}
            message = err.get("error") or "云端读取失败"
            print(f"[User] 同步失败: {message}")
            return {"ok": False, "offline": bool(err.get("offline")), "user": local,
                    "error": message}

        remote_skins = [str(s).strip() for s in (data.get("skins") or []) if str(s).strip()]
        merged = _merge_skins(local_skins, remote_skins)
        print(f"[User] 服务端资料字段: {_profile_keys(data)}")
        print(f"[User] 皮肤对比: 本地 {len(local_skins)} 项 / 服务端 {len(remote_skins)} 项 "
              f"-> 并集 {len(merged)} 项")
        local = _store_server_profile(local, data)

        pushed, push_error = True, ""
        if sorted(merged) != sorted(remote_skins):
            push = user_api.push_skins(merged)
            pushed = bool(push.get("ok"))
            if not pushed:
                push_error = push.get("error") or "云端写入失败"
                print(f"[User] 补写服务端皮肤失败: {push_error}")
            else:
                print(f"[User] 已把本地多出的皮肤补写到服务端 (共 {len(merged)} 项)")
        else:
            print("[User] 皮肤两边一致, 无需写回")

        local["unlocked_skins"]["value"] = merged
        local = _normalize(local)
        save_user(local)

        try:
            print("[User] 成就云端同步: 开始")
            ach = sync_achievements(pull=True)
            pull = ach.get("pull") or {}
            print(f"[User] 成就同步: 云端 {pull.get('count', '?')} 条 / 本地原有 "
                  f"{pull.get('local_before', '?')} 条 → 合并 {ach.get('local_count', '?')} 条 / "
                  f"上传方式={ach['push'].get('method', '-')} "
                  f"{'成功' if ach.get('ok') else '失败(' + str(ach['push'].get('error')) + ')'}")
        except Exception as exc:  # noqa: BLE001
            print(f"[User] 成就同步异常（不影响皮肤同步）: {type(exc).__name__}: {exc}")

        try:
            sync_playtime(overwrite=True)
        except Exception as exc:  # noqa: BLE001
            print(f"[User] 游玩时长同步异常（不影响其它同步）: {type(exc).__name__}: {exc}")

        remote_name = str(data.get("user_name") or "").strip()
        if remote_name:
            _apply_user_name(settings_manager, remote_name)

        print(f"[User] 同步完成: 账号 {mask_uid(uid)}, 本地皮肤 {len(merged)} 项"
              + (f"（服务端写入未完成: {push_error}）" if push_error else ""))
        return {"ok": True, "user": local, "cloud": data,
                "pushed": pushed, "push_error": push_error}

def push_skins(settings_manager=None) -> dict:
    with _USER_LOCK:
        local = load_user()
        uid = str(_value(local, "user_id", "")).strip()
        if not uid:
            return {"ok": False, "user": local, "error": "本地没有用户 ID"}

        local_skins = list(_value(local, "unlocked_skins", []))
        data, err = _server_identity(uid, {"skins": local_skins})
        if data is None:
            err = err or {}
            message = err.get("error") or "云端读取失败"
            print(f"[User] 上报皮肤前读取服务端失败: {message}")
            return {"ok": False, "offline": bool(err.get("offline")), "user": local,
                    "error": message}

        remote = [str(s).strip() for s in (data.get("skins") or []) if str(s).strip()]
        merged = _merge_skins(local_skins, remote)
        local["unlocked_skins"]["value"] = merged
        save_user(local)

        if sorted(merged) == sorted(remote):
            print(f"[User] 上报皮肤: 服务端已是最新 ({len(merged)} 项), 跳过写入")
            return {"ok": True, "user": load_user(), "cloud": data, "skipped": True}

        print(f"[User] 上报皮肤: 本地 {len(local_skins)} 项 / 服务端 {len(remote)} 项 "
              f"-> 写入并集 {len(merged)} 项")
        result = user_api.push_skins(merged)
        if not result.get("ok"):
            print(f"[User] 上报皮肤失败: {result.get('error')}")
            return {"ok": False, "offline": bool(result.get("offline")),
                    "user": load_user(), "error": result.get("error") or "云端写入失败"}
        print(f"[User] 上报皮肤成功 ({len(merged)} 项)")
        _refresh_profile_from(result.get("data") or {})
        return {"ok": True, "user": load_user(), "cloud": result.get("data") or {}}

def push_name(name: str, settings_manager=None) -> dict:
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
            message = err.get("error") or "云端读取失败"
            print(f"[User] 上报昵称前读取服务端失败: {message}")
            return {"ok": False, "offline": bool(err.get("offline")), "error": message}

        print(f"[User] 上报昵称: {clean}")
        result = user_api.push_name(clean)
        if not result.get("ok"):
            print(f"[User] 上报昵称失败: {result.get('error')}")
            return {"ok": False, "offline": bool(result.get("offline")),
                    "error": result.get("error") or "云端写入失败"}
        print("[User] 上报昵称成功")
        _refresh_profile_from(result.get("data") or {})
        return {"ok": True, "cloud": result.get("data") or {}}

def login_user(user_id: str, settings_manager=None) -> dict:
    uid = str(user_id or "").strip()
    if not uid:
        return {"ok": False, "error": "用户 ID 不能为空"}
    blocked = check_login_allowed()
    if blocked:
        print(f"[User] 登录被冷却限制拒绝: {blocked}")
        return {"ok": False, "limited": True, "error": blocked}
    with _USER_LOCK:
        old_id = str(_value(load_user(), "user_id", "")).strip()
        if old_id and old_id == uid:
            return {"ok": False, "error": "当前已经是该账号"}

        print(f"[User] 开始登录 (目标账号 {mask_uid(uid)})")
        result = user_api.login(uid)
        if not result.get("ok"):
            message = result.get("error") or "登录失败"
            print(f"[User] 登录失败: {message}")
            return {"ok": False, "offline": bool(result.get("offline")), "error": message}

        data = result.get("data") or {}
        print(f"[User] 服务端资料字段: {_profile_keys(data)}")
        local = _new_user(uid)
        _store_server_profile(local, data)
        local["unlocked_skins"]["value"] = [str(s) for s in (data.get("skins") or []) if str(s).strip()]
        local = _normalize(local)
        if not save_user(local):
            return {"ok": False, "error": "本地用户信息保存失败"}

        remote_name = str(data.get("user_name") or "").strip()
        if remote_name:
            _apply_user_name(settings_manager, remote_name)

        print(f"[User] 已登录账号 {mask_uid(uid)}"
              + ("（管理员）" if data.get("is_admin") else "")
              + f", 服务端皮肤 {len(_value(local, 'unlocked_skins', []))} 项")
        mark_logged_in()
        return {"ok": True, "user": local, "cloud": data}

def playtime_text(seconds: int) -> str:
    total = max(0, int(seconds or 0))
    days, rest = divmod(total, 86400)
    hours, rest = divmod(rest, 3600)
    minutes = rest // 60
    if days:
        return f"{days} 天 {hours} 小时"
    if hours:
        return f"{hours} 小时 {minutes} 分"
    if minutes:
        return f"{minutes} 分 {rest % 60} 秒"
    return f"{total} 秒"

def get_user_info(settings_manager=None) -> dict:
    data = load_user()
    user_name = "Player"
    if settings_manager is not None:
        user_name = str(settings_manager.get_setting("user_name") or "Player")
    profile = _value(data, "server_profile", {})
    profile = profile if isinstance(profile, dict) else {}

    base = ""
    try:
        base = str(user_api.api_base() or "").rstrip("/")
    except Exception:  # noqa: BLE001
        base = ""
    token = str(profile.get("profile_token") or "").strip()

    play: dict = {}
    try:
        from functions.base import steam_playtime
        play = steam_playtime.read_playtime()
    except Exception as exc:  # noqa: BLE001
        play = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    seconds = int(play.get("seconds") or 0)

    return {"user": data, "user_name": user_name, "user_path": user_file(),
            "restrictions": get_restrictions(),
            "logged_in": user_api.has_session(),
            "profile": profile,
            "profile_url": f"{base}/user/{token}" if base and token else "",
            "leaderboard_url": f"{base}/leaderboard" if base else "",
            "playtime": {"ok": bool(play.get("ok")), "seconds": seconds,
                         "hours": float(play.get("hours") or 0),
                         "text": f"{float(play.get('hours') or 0):.1f} 小时"
                                 if play.get("ok") else "",
                         "detail": playtime_text(seconds) if play.get("ok") else "",
                         "error": str(play.get("error") or "")}}

def completed_achievements() -> list[str]:
    done = _value(load_user(), "completed_achievements", [])
    return [str(x) for x in done] if isinstance(done, list) else []

_PLUGIN_ACH_FILE_NAME = "plugin_achievements.json"

def plugin_achievements_file() -> str:
    return os.path.join(user_dir(), _PLUGIN_ACH_FILE_NAME)

def _load_plugin_achievements() -> dict:
    path = plugin_achievements_file()
    if not os.path.isfile(path):
        return {"version": 1, "completed": [], "by_addon": {}}
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception:  # noqa: BLE001
        return {"version": 1, "completed": [], "by_addon": {}}
    if not isinstance(data, dict):
        return {"version": 1, "completed": [], "by_addon": {}}
    data.setdefault("version", 1)
    data.setdefault("completed", [])
    data.setdefault("by_addon", {})
    return data

def completed_plugin_achievements() -> list[str]:
    done = _load_plugin_achievements().get("completed", [])
    return [str(x).strip() for x in done if str(x).strip()] if isinstance(done, list) else []

def record_plugin_achievements(achievement_ids, addon: str = "") -> list[str]:
    wanted: list[str] = []
    for aid in achievement_ids or ():
        aid = str(aid or "").strip()
        if aid and aid not in wanted:
            wanted.append(aid)
    if not wanted:
        return []
    with _USER_LOCK:
        data = _load_plugin_achievements()
        current = data.get("completed", [])
        merged = [str(x).strip() for x in current if str(x).strip()] \
            if isinstance(current, list) else []
        added = [aid for aid in wanted if aid not in merged]
        if not added:
            return merged
        merged.extend(added)
        data["completed"] = merged
        by_addon = data.get("by_addon")
        if not isinstance(by_addon, dict):
            by_addon = {}
        if addon:
            bucket = by_addon.get(addon)
            bucket = [str(x) for x in bucket] if isinstance(bucket, list) else []
            for aid in added:
                if aid not in bucket:
                    bucket.append(aid)
            by_addon[addon] = bucket
        data["by_addon"] = by_addon
        try:
            os.makedirs(user_dir(), exist_ok=True)
            tmp = plugin_achievements_file() + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=2)
            os.replace(tmp, plugin_achievements_file())
        except Exception as exc:  # noqa: BLE001
            print(f"[User] 插件成就记录写入失败: {type(exc).__name__}: {exc}")
            return merged
        print(f"[User] 记录插件成就 {len(added)} 条（插件档共 {len(merged)} 条）")
        return merged

def record_achievements(achievement_ids) -> list[str]:
    wanted: list[str] = []
    for aid in achievement_ids or ():
        aid = str(aid or "").strip()
        if aid and aid not in wanted:
            wanted.append(aid)
    if not wanted:
        return []
    with _USER_LOCK:
        data = load_user()
        current = _value(data, "completed_achievements", [])
        merged = [str(x).strip() for x in current] if isinstance(current, list) else []
        merged = [x for x in merged if x]
        added = [aid for aid in wanted if aid not in merged]
        if not added:
            return merged
        merged.extend(added)
        data["completed_achievements"]["value"] = merged
        save_user(data)
        print(f"[User] 记录已完成成就 {len(added)} 条（本地共 {len(merged)} 条）")
        return merged

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
        print(f"[User] 皮肤 {sid} 已写入本地 (共 {len(skins)} 项), 准备上报服务端")
        pushed = push_skins(settings_manager)
        if not pushed.get("ok"):
            print(f"[User] 皮肤上报未完成(本地已保留): {pushed.get('error')}")
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
    assert unlock is not None
    kind = str(unlock.get("type") or "free").lower()
    if kind == "free":
        return {"ok": True, "unlocked": True, "condition": unlock}
    if kind == "edge_window_title":
        assert unlock is not None
        passed, title = _edge_title_contains(unlock.get("title_keyword") or "DeepSeek")
        return {"ok": True, "unlocked": passed, "title": title, "condition": unlock}
    return {"ok": False, "unlocked": False, "condition": unlock, "error": "未知解锁条件"}
