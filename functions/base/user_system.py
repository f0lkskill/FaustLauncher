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
    """用户信息骨架 (结构对齐 config/settings.json)。

    `server_profile` 是服务端返回的**完整用户对象**的本地快照。
    用户数据不会只有皮肤 (服务端还有 role / is_admin / profile_token, 以后还会有别的),
    所以这里不逐个字段建模, 而是把服务端那一份原样镜像 —— 服务端加字段, 本地自动就有,
    不需要在客户端逐字段改代码。
    """
    uid = user_id or _make_user_id()
    return {
        "user_id": _setting("用户ID", "string", uid, "", "用于跨设备同步用户解锁信息。"),
        "unlocked_skins": _setting("已解锁皮肤", "list", [], [], "已解锁的皮肤 ID 列表。"),
        # 成就的完成信息与皮肤**同处这一份用户文件**: 只记 id 列表, 完成与否以它为准
        # (成就监测是独立子进程, 它解锁一条就往这里补一条; 启动器主进程只读)
        "completed_achievements": _setting("已完成成就", "list", [], [],
                                           "已完成的成就 ID 列表 (成就页据此判定完成)。"),
        # 注意 _setting 的签名是 (name, type_name, value, default, description) ——
        # value 与 default 都要给, 少一个后面的参数就会错位 (曾经因此启动即崩)
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
    raw_done = _value(data, "completed_achievements", [])
    if not isinstance(raw_done, list):
        raw_done = []
    done = []
    for aid in raw_done:
        aid = str(aid).strip()
        if aid and aid not in done:
            done.append(aid)
    # 注意: 这里不再产出 auto_created 之类的账号来源标记 ——
    # 本地无法可靠区分"自动生成的号"和"用户自己的号", 误判会造成困扰。
    # 因此归一化结果里多余的旧字段会在下次保存时被自然剔除。
    profile = _value(data, "server_profile", {})
    if not isinstance(profile, dict):
        profile = {}
    normalized = _new_user(uid)
    normalized["unlocked_skins"]["value"] = skins
    normalized["completed_achievements"]["value"] = done
    # 服务端资料整份带着走 (原样镜像, 不挑字段)
    normalized["server_profile"]["value"] = profile
    return normalized


def _store_server_profile(data: dict, payload: dict) -> dict:
    """把服务端返回的用户对象整份存进本地快照。

    只剔除 `ok` 这个传输用的状态位, 其余字段**一个不留地**存下来 ——
    用户数据以后不只是皮肤, 逐个字段挑选必然漏; 原样镜像才跟得上服务端。
    """
    if isinstance(payload, dict) and payload:
        snapshot = {k: v for k, v in payload.items() if k != "ok"}
        data["server_profile"]["value"] = snapshot
    return data


def server_profile() -> dict:
    """本地保存的服务端资料快照 (可能为空: 还没成功同步过)"""
    profile = _value(load_user(), "server_profile", {})
    return profile if isinstance(profile, dict) else {}


def _profile_keys(payload: dict) -> str:
    """日志用: 服务端这次返回了哪些字段 (只列字段名, 不打印任何值)"""
    if not isinstance(payload, dict):
        return "(无)"
    keys = sorted(k for k in payload.keys() if k != "ok")
    return ", ".join(keys) if keys else "(空)"


def _refresh_profile_from(payload: dict) -> dict:
    """把服务端返回的用户对象存进本地快照并落盘, 返回更新后的本地数据。

    每个写接口 (/api/me/skins、/api/me/name …) 的回包都是一份完整的用户对象,
    顺手拿它刷新快照, 本地就始终跟服务端保持一致。
    """
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
            print(f"[用户] 服务端昵称已写回设置项: {name}")
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
        print(f"[用户] 本地登录态属于另一个账号, 重新登记 (账号 {mask_uid(uid)})")

    reg = user_api.register(uid, **dict(defaults or {}))
    if reg.get("ok"):
        created = (reg.get("data") or {}).get("created")
        print(f"[用户] 注册接口确认账号 (账号 {mask_uid(uid)}, "
              f"{'新建' if created else '已存在, 未改动任何数据'})")
        return reg["data"], None
    if reg.get("offline"):
        return None, reg

    # 注册被拒 (格式不合规 / 需要令牌): 已存在的账号仍可登录
    print(f"[用户] 注册被拒 (HTTP {reg.get('status')}: {reg.get('error')}), 退回登录接口")
    login_result = user_api.login(uid)
    if login_result.get("ok"):
        print(f"[用户] 登录接口成功 (账号 {mask_uid(uid)})")
        return login_result["data"], None
    return None, (login_result if login_result.get("error") else reg)


# --------------------------------------------------------------------------- 成就云端同步
# 与服务端约定（见 FaustLauncherWeb/API.md §4.2 / §4.10）：
#   · 云端只存**内置成就**的 id 列表（用户记录的 achievements 字段）；**插件成就永远不上云**，
#     它们只存在本地那份 plugin_achievements.json 里；
#   · 上传是**整体替换**语义：客户端报全量列表，服务端在锁内只改自己那一行（不会牵连别人）；
#   · 同步口径与皮肤一致：**只增不减**（先取并集写回本地，再把并集推回云端），
#     这样离线解锁、上次上传失败的条目不会被云端旧列表抹掉。想强制对齐可传 mode="overwrite"。


def pull_achievements_from_cloud(mode: str = "union") -> dict:
    """读云端成就列表并与本地合并（默认**只增不减**）。

    ``mode="union"``（默认）：与皮肤同步同一个口径 —— 本地独有的条目
    （离线解锁、上次上传失败的那批）不会被云端旧列表抹掉；合并结果随后由
    :func:`push_achievements_to_cloud` 回传，两边最终收敛到并集。
    ``mode="overwrite"``：云端为准直接覆盖本地（想强制对齐时用）。

    插件成就不参与（它们只存在本地那份独立文件里）。
    """
    result = user_api.me()
    if not result.get("ok"):
        return {"ok": False, "error": result.get("error") or "云端读取失败"}
    # ⚠ user_api._request() 返回的是**信封** ``{"ok","data","status",...}``，服务端响应体
    #   整个塞在 ``data`` 键里（user_api.py:247）。这里以前直接读信封的 ``achievements``，
    #   永远是 None → remote 恒为 []。后果不只是"同步不上"：紧接着的全量上报走
    #   ``POST /api/me/achievements``（服务端**整体替换**），于是"云端→本地"从未发生、
    #   "本地→云端"却是覆盖写，别的设备解锁的成就会被静默抹掉。
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
        else:                                   # union：本地在前，云端补齐
            merged = list(mine)
            for aid in remote:
                if aid not in merged:
                    merged.append(aid)
        local["completed_achievements"]["value"] = merged
        local = _normalize(local)
        save_user(local)
    added = len(merged) - len(mine)
    action = "覆盖本地" if mode == "overwrite" else f"与本地取并集（新增 {added} 条）"
    print(f"[用户] 云端成就 {len(remote)} 条 → {action}，合计 {len(merged)} 条")
    return {"ok": True, "mode": mode, "count": len(remote), "achievements": merged,
            "local_before": len(mine), "local_after": len(merged), "added": added}


def push_achievement(achievement_id: str, uid: str = "") -> dict:
    """立刻把**一条**成就推到云端（服务端 ``POST /api/achievements/add``，幂等）。

    与 ``push_achievements_to_cloud()``（整份覆盖）的分工：
      · 解锁的**当下**用这个 —— 只加一条、只改服务端那一行，多机轮流上线也不会互相覆盖；
      · 启动同步（``sync_user``）仍用整份覆盖做**对账**（并集，只增不减）。

    服务端对不认识的成就 ID **不做强制校验**（返回 ``known: false``），
    所以客户端可以先上新成就、服务端稍后再补 ``achievements.json``。
    """
    aid = str(achievement_id or "").strip()
    if not aid:
        return {"ok": False, "error": "成就 ID 为空"}
    target = str(uid or "").strip() or str(_value(load_user(), "user_id", "") or "").strip()
    if not target:
        print("[用户] 未登录，跳过单条成就上报")
        return {"ok": False, "error": "未登录"}
    result = user_api.add_achievement(aid, target)
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    if result.get("ok"):
        assert data is not None
        added = bool(data.get("added"))
        known = data.get("known")
        note = "" if known is None else ("（服务端已收录）" if known else "（服务端暂未收录该 ID）")
        print(f"[用户] 成就单条上报: {aid} → {'新加' if added else '云端已有(幂等跳过)'}{note}")
        assert data is not None
        return {"ok": True, "added": added, "known": known,
                "count": int(data.get("count") or 0)}
    print(f"[用户] 成就单条上报失败: {aid} → {result.get('error')}")
    return {"ok": False, "error": str(result.get("error") or "")}


def push_achievements_to_cloud() -> dict:
    """把本地**内置**成就全量上报（云端整体替换）。插件成就排除在外。

    先用方式① ``/api/me/achievements``（uid 取自登录会话，普通用户即可）；
    失败再退回方式② ``/api/achievements/overwrite``（uid 写在请求体）。
    """
    ids = completed_achievements()
    result = user_api.push_achievements(ids)
    if result.get("ok"):
        return {**result, "method": "me", "count": len(ids)}
    uid = str(_value(load_user(), "user_id", "")).strip()
    fallback = user_api.overwrite_achievements(ids, uid)
    print(f"[用户] 方式①上报失败({result.get('error')})，改用方式②覆盖上传")
    return {**fallback, "method": "overwrite", "count": len(ids),
            "first_error": result.get("error")}


def sync_achievements(pull: bool = True, mode: str = "union") -> dict:
    """成就云端同步的统一入口（**启动初始化**与成就页「云端同步」按钮都走它）。

    默认口径 **(B) 只增不减**：先把云端与本地**取并集**写回本地，再把并集全量推回云端
    —— 离线解锁的、上次上传失败的都不会被云端旧列表抹掉（与皮肤同步一致）。
    ``mode="overwrite"`` 时改为云端覆盖本地（(A) 口径）。
    """
    pulled: dict = {"ok": False, "skipped": True}
    if pull:
        pulled = pull_achievements_from_cloud(mode=mode)
    pushed = push_achievements_to_cloud()
    return {"ok": bool(pushed.get("ok")), "pull": pulled, "push": pushed,
            "local_count": len(completed_achievements())}


def sync_playtime(overwrite: bool = True) -> dict:
    """读本机 Steam 记录的游玩时长并上报（排行榜用）。

    数据源是 ``<Steam>/userdata/<id>/config/localconfig.vdf`` 里的 ``Playtime``（分钟）——
    **那个文件只存在于已登录 Steam 客户端的本机**，远程拿不到，所以必须在用户自己的
    电脑上读。启动器初始化 / 云端同步时各跑一次即可。

    Steam 的 ``Playtime`` 本身就是**累计总量**，所以用**覆盖**语义上报
    （``{"playtime": 秒}``），不需要自己维护增量、也不会因重复上报而翻倍。
    """
    try:
        from functions.base import steam_playtime
        info = steam_playtime.read_playtime()
    except Exception as exc:  # noqa: BLE001
        print(f"[用户] 读取 Steam 游玩时长失败: {type(exc).__name__}: {exc}")
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    if not info.get("ok"):
        print(f"[用户] 游玩时长未上报: {info.get('error')}")
        return {"ok": False, "skipped": True, "error": str(info.get("error") or "")}
    result = user_api.report_playtime(int(info["seconds"]), overwrite=overwrite)
    ok = bool(result.get("ok"))
    print(f"[用户] 游玩时长上报: 本机 {info['hours']} 小时（{info['minutes']} 分钟）→ "
          f"{'成功' if ok else '失败(' + str(result.get('error')) + ')'}")
    return {"ok": ok, "seconds": int(info["seconds"]), "hours": info["hours"],
            "minutes": int(info["minutes"]), "error": str(result.get("error") or "")}


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
        local_skins = list(_value(local, "unlocked_skins", []))
        print(f"[用户] 开始同步: 账号 {mask_uid(uid)}, 本地皮肤 {len(local_skins)} 项")

        # 建档初值用本地现状: 新环境第一次运行就能把自己的昵称/皮肤一次带上去
        # (ID 已存在时 register 是幂等的, 这些初值不会覆盖服务端数据)
        data, err = _server_identity(uid, {
            "user_name": local_name,
            "skins": local_skins,
        })
        if data is None:
            err = err or {}
            message = err.get("error") or "云端读取失败"
            print(f"[用户] 同步失败: {message}")
            return {"ok": False, "offline": bool(err.get("offline")), "user": local,
                    "error": message}

        remote_skins = [str(s).strip() for s in (data.get("skins") or []) if str(s).strip()]
        merged = _merge_skins(local_skins, remote_skins)
        print(f"[用户] 服务端资料字段: {_profile_keys(data)}")
        print(f"[用户] 皮肤对比: 本地 {len(local_skins)} 项 / 服务端 {len(remote_skins)} 项 "
              f"-> 并集 {len(merged)} 项")
        # 服务端返回的整份用户对象都存进本地快照 (皮肤只是其中一个字段)
        local = _store_server_profile(local, data)

        # 服务端缺的补上去 (并集策略: 只增不减)
        pushed, push_error = True, ""
        if sorted(merged) != sorted(remote_skins):
            push = user_api.push_skins(merged)
            pushed = bool(push.get("ok"))
            if not pushed:
                push_error = push.get("error") or "云端写入失败"
                print(f"[用户] 补写服务端皮肤失败: {push_error}")
            else:
                print(f"[用户] 已把本地多出的皮肤补写到服务端 (共 {len(merged)} 项)")
        else:
            print("[用户] 皮肤两边一致, 无需写回")

        local["unlocked_skins"]["value"] = merged
        local = _normalize(local)
        save_user(local)

        # 成就也跟着同步一次：**先与云端取并集写回本地（只增不减），再把并集全量推回去**。
        # 插件成就不参与（它们只存本地独立文件，永远不上云）。
        try:
            print("[用户] 成就云端同步: 开始")
            ach = sync_achievements(pull=True)
            pull = ach.get("pull") or {}
            print(f"[用户] 成就同步: 云端 {pull.get('count', '?')} 条 / 本地原有 "
                  f"{pull.get('local_before', '?')} 条 → 合并 {ach.get('local_count', '?')} 条 / "
                  f"上传方式={ach['push'].get('method', '-')} "
                  f"{'成功' if ach.get('ok') else '失败(' + str(ach['push'].get('error')) + ')'}")
        except Exception as exc:  # noqa: BLE001
            print(f"[用户] 成就同步异常（不影响皮肤同步）: {type(exc).__name__}: {exc}")

        # 游玩时长也顺手报一次（排行榜）：读本机 Steam 的 localconfig.vdf。
        # Steam 的 Playtime 是累计总量 → 覆盖语义，重复上报不会翻倍。
        try:
            sync_playtime(overwrite=True)
        except Exception as exc:  # noqa: BLE001
            print(f"[用户] 游玩时长同步异常（不影响其它同步）: {type(exc).__name__}: {exc}")

        remote_name = str(data.get("user_name") or "").strip()
        if remote_name:
            _apply_user_name(settings_manager, remote_name)

        print(f"[用户] 同步完成: 账号 {mask_uid(uid)}, 本地皮肤 {len(merged)} 项"
              + (f"（服务端写入未完成: {push_error}）" if push_error else ""))
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

        local_skins = list(_value(local, "unlocked_skins", []))
        data, err = _server_identity(uid, {"skins": local_skins})
        if data is None:
            err = err or {}
            message = err.get("error") or "云端读取失败"
            print(f"[用户] 上报皮肤前读取服务端失败: {message}")
            return {"ok": False, "offline": bool(err.get("offline")), "user": local,
                    "error": message}

        remote = [str(s).strip() for s in (data.get("skins") or []) if str(s).strip()]
        merged = _merge_skins(local_skins, remote)
        local["unlocked_skins"]["value"] = merged
        save_user(local)

        # 两边已经一致就不必再写一次 (少一次请求, 也少一次并发写入的机会)
        if sorted(merged) == sorted(remote):
            print(f"[用户] 上报皮肤: 服务端已是最新 ({len(merged)} 项), 跳过写入")
            return {"ok": True, "user": load_user(), "cloud": data, "skipped": True}

        print(f"[用户] 上报皮肤: 本地 {len(local_skins)} 项 / 服务端 {len(remote)} 项 "
              f"-> 写入并集 {len(merged)} 项")
        result = user_api.push_skins(merged)
        if not result.get("ok"):
            print(f"[用户] 上报皮肤失败: {result.get('error')}")
            return {"ok": False, "offline": bool(result.get("offline")),
                    "user": load_user(), "error": result.get("error") or "云端写入失败"}
        print(f"[用户] 上报皮肤成功 ({len(merged)} 项)")
        _refresh_profile_from(result.get("data") or {})
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
            message = err.get("error") or "云端读取失败"
            print(f"[用户] 上报昵称前读取服务端失败: {message}")
            return {"ok": False, "offline": bool(err.get("offline")), "error": message}

        print(f"[用户] 上报昵称: {clean}")
        result = user_api.push_name(clean)
        if not result.get("ok"):
            print(f"[用户] 上报昵称失败: {result.get('error')}")
            return {"ok": False, "offline": bool(result.get("offline")),
                    "error": result.get("error") or "云端写入失败"}
        print("[用户] 上报昵称成功")
        _refresh_profile_from(result.get("data") or {})
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
        print(f"[用户] 登录被冷却限制拒绝: {blocked}")
        return {"ok": False, "limited": True, "error": blocked}
    with _USER_LOCK:
        old_id = str(_value(load_user(), "user_id", "")).strip()
        if old_id and old_id == uid:
            return {"ok": False, "error": "当前已经是该账号"}

        print(f"[用户] 开始登录 (目标账号 {mask_uid(uid)})")
        result = user_api.login(uid)
        if not result.get("ok"):
            message = result.get("error") or "登录失败"
            print(f"[用户] 登录失败: {message}")
            return {"ok": False, "offline": bool(result.get("offline")), "error": message}

        data = result.get("data") or {}
        print(f"[用户] 服务端资料字段: {_profile_keys(data)}")
        local = _new_user(uid)
        _store_server_profile(local, data)
        local["unlocked_skins"]["value"] = [str(s) for s in (data.get("skins") or []) if str(s).strip()]
        local = _normalize(local)
        if not save_user(local):
            return {"ok": False, "error": "本地用户信息保存失败"}

        remote_name = str(data.get("user_name") or "").strip()
        if remote_name:
            _apply_user_name(settings_manager, remote_name)

        print(f"[用户] 已登录账号 {mask_uid(uid)}"
              + ("（管理员）" if data.get("is_admin") else "")
              + f", 服务端皮肤 {len(_value(local, 'unlocked_skins', []))} 项")
        mark_logged_in()          # 登录成功才计入 12 小时冷却
        return {"ok": True, "user": local, "cloud": data}


def playtime_text(seconds: int) -> str:
    """把秒数说成人话（与官网排行榜的文案口径一致：X 天 X 小时 / X 小时 X 分）。"""
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

    # 官网链接：主页要**用服务端给的 profile_token** 拼（不能拿用户 ID 拼，那样 404）；
    # 排行榜是公开页，直接给站点根 + /leaderboard。
    base = ""
    try:
        base = str(user_api.api_base() or "").rstrip("/")
    except Exception:  # noqa: BLE001
        base = ""
    token = str(profile.get("profile_token") or "").strip()

    # 当前游玩时长：直接读**本机 Steam 记录**（实时，而且就是上报给排行榜的那个值）。
    # 读不到（没装/没登录 Steam）时给 ok=False，前端照实说明，不编数字。
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
            # 服务端资料的完整副本: 前端据此做"本地 <-> 服务端"的字段级对照
            # (服务端以后新增字段, 这里不用改代码就会带出来)
            "profile": profile,
            # 官网入口（空串 = 拿不到，前端应禁用按钮而不是打开坏链接）
            "profile_url": f"{base}/user/{token}" if base and token else "",
            "leaderboard_url": f"{base}/leaderboard" if base else "",
            # 当前游玩时长（本机 Steam 记录）。
            # 面板统一按**小时**显示（产品要求），详细写法（X 天 X 小时）放 detail 供 hover。
            "playtime": {"ok": bool(play.get("ok")), "seconds": seconds,
                         "hours": float(play.get("hours") or 0),
                         "text": f"{float(play.get('hours') or 0):.1f} 小时"
                                 if play.get("ok") else "",
                         "detail": playtime_text(seconds) if play.get("ok") else "",
                         "error": str(play.get("error") or "")}}


def completed_achievements() -> list[str]:
    """本地记录的已完成成就 ID 列表（**内置成就**；与皮肤同处一份用户文件）。"""
    done = _value(load_user(), "completed_achievements", [])
    return [str(x) for x in done] if isinstance(done, list) else []


# --------------------------------------------------------------------------- 插件成就
# 插件自定义成就的完成记录**单独一个文件**存放，理由：
#   1. 与内置内容彻底分开（内置那份可能参与云端同步，插件这份永远不参与）；
#   2. 插件被删掉时，内置记录不受影响，插件那份也能一眼看出是谁留下的。
_PLUGIN_ACH_FILE_NAME = "plugin_achievements.json"


def plugin_achievements_file() -> str:
    """插件成就的独立存档路径（用户目录下，与内置的 settings.json 分开）。"""
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
    """插件自定义成就的完成 ID 列表（**只从插件那份独立文件读**）。"""
    done = _load_plugin_achievements().get("completed", [])
    return [str(x).strip() for x in done if str(x).strip()] if isinstance(done, list) else []


def record_plugin_achievements(achievement_ids, addon: str = "") -> list[str]:
    """记录插件成就的完成（幂等），返回合并后的列表。

    ``addon`` 是插件目录名，用来在插件那份文件里按插件归类（便于插件被删后清理）。
    """
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
            print(f"[用户] 插件成就记录写入失败: {type(exc).__name__}: {exc}")
            return merged
        print(f"[用户] 记录插件成就 {len(added)} 条（插件档共 {len(merged)} 条）")
        return merged


def record_achievements(achievement_ids) -> list[str]:
    """把成就 ID 追加进本地记录（幂等），返回合并后的完整列表。

    成就监测跑在**独立子进程**里：它解锁一条就往用户文件补一条，启动器主进程只读。
    每次都是「重新读盘 → 合并 → 写回」，所以主进程刚写过的皮肤/昵称不会被这里覆盖。
    """
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
        print(f"[用户] 记录已完成成就 {len(added)} 条（本地共 {len(merged)} 条）")
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
        print(f"[用户] 皮肤 {sid} 已写入本地 (共 {len(skins)} 项), 准备上报服务端")
        # 本地刚解锁: 与云端取并集后上报。反过来用云端覆盖本地会把这个皮肤抹掉。
        pushed = push_skins(settings_manager)
        if not pushed.get("ok"):
            print(f"[用户] 皮肤上报未完成(本地已保留): {pushed.get('error')}")
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
    assert unlock is not None
    kind = str(unlock.get("type") or "free").lower()
    if kind == "free":
        return {"ok": True, "unlocked": True, "condition": unlock}
    if kind == "edge_window_title":
        assert unlock is not None
        passed, title = _edge_title_contains(unlock.get("title_keyword") or "DeepSeek")
        return {"ok": True, "unlocked": passed, "title": title, "condition": unlock}
    return {"ok": False, "unlocked": False, "condition": unlock, "error": "未知解锁条件"}
