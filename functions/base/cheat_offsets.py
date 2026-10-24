# -*- coding: utf-8 -*-
"""cheat_offsets.py —— 启动器侧的「作弊偏移量」供应模块

启动器自己维护着一套**随游戏版本动态更新的偏移索引**（``functions/hook``：
从 ``global-metadata.dat`` + ``GameAssembly.dll`` 解析符号，产出
``cache/hook/hook_index.json``，每次游戏更新后由 hook 流程刷新）。本模块把
这套索引整理成稳定的 Python API，供 ``addons`` 里的插件直接使用：

    from functions.base.cheat_offsets import get_offsets, verify_local_gameassembly
    offs = get_offsets()
    if offs and verify_local_gameassembly(offs)["ok"]:
        ...  # 注入用 offs["rva_get_take_attack_dmg_multiplier"] 等

获取顺序（越靠前越可信）：
1. **本地 HookIndex**：``hooks["take_attack_dmg_multiplier"]`` / ``hooks["opponent_faction"]``
   给出的 rva + prologue，游戏指纹来自 ``index.game``。这是启动器动态更新的那一份。
2. **远端接口**：``https://web.lcta.top/cheat_damage.json``，字段更全但滞后。
3. **磁盘缓存**：``<app_root>/config/cheat_offsets.json``，离线兜底。

返回结构与远端接口一致::

    {"game_version", "gameassembly_sha256", "gameassembly_size",
     "rva_get_take_attack_dmg_multiplier", "rva_get_opponent_faction",
     "prologue", "source"}

``source`` 标记来源：``hook_index`` / ``api`` / ``cache``。
"""

import json
import os
import time
import urllib.request
from typing import Optional, Dict, Any

DEFAULT_API_URL = "https://web.lcta.top/cheat_damage.json"
CACHE_NAME = "cheat_offsets.json"

# 缓存默认有效期：HookIndex 走不到时才用得上，12 小时足够
DEFAULT_MAX_AGE = 12 * 3600
FETCH_TIMEOUT = 20

GAME_DLL_NAME = "GameAssembly.dll"

# HookIndex 里与本模块相关的两个钩子键
HOOK_TAKE_ATTACK = "take_attack_dmg_multiplier"
HOOK_OPPONENT_FACTION = "opponent_faction"

OFFSET_KEYS = (
    "rva_get_take_attack_dmg_multiplier",
    "rva_get_opponent_faction",
)


class OffsetsError(RuntimeError):
    """偏移获取或校验失败。"""


# ---------------------------------------------------------------------------
# 路径
# ---------------------------------------------------------------------------


def cache_path() -> str:
    """偏移缓存的落盘路径（放在 cache/ 下：那是运行期目录，不入库）。"""
    from functions.base.common.path_utils import get_app_root

    return os.path.join(get_app_root(create=False), "cache", CACHE_NAME)


# ---------------------------------------------------------------------------
# payload 解析
# ---------------------------------------------------------------------------


def _parse_prologue(value: Any) -> bytes:
    """把 ``"48 89 5C 24 ..."`` 之类的字符串解析成 16 字节。"""
    raw = bytes.fromhex("".join(str(value or "").split()))
    if len(raw) != 16:
        raise OffsetsError("prologue 必须为 16 字节")
    return raw


def normalize_payload(data: Any) -> Dict[str, Any]:
    """校验 payload 并规范化；非法时抛 OffsetsError。"""
    if isinstance(data, dict) and isinstance(data.get("cheat_damage"), dict):
        data = data["cheat_damage"]
    if not isinstance(data, dict):
        raise OffsetsError("payload 不是 JSON 对象")

    sha = str(data.get("gameassembly_sha256", "")).strip().upper()
    if len(sha) != 64 or any(c not in "0123456789ABCDEF" for c in sha):
        raise OffsetsError("gameassembly_sha256 缺失或非法")

    try:
        rva_take = int(data["rva_get_take_attack_dmg_multiplier"])
        rva_faction = int(data["rva_get_opponent_faction"])
    except (KeyError, TypeError, ValueError):
        raise OffsetsError("RVA 字段缺失或不是整数")

    if rva_take <= 0 or rva_faction <= 0:
        raise OffsetsError("RVA 非法（必须为正数）")

    prologue = _parse_prologue(data.get("prologue"))
    return {
        "game_version": str(data.get("game_version") or "unknown"),
        "gameassembly_sha256": sha,
        "gameassembly_size": int(data.get("gameassembly_size") or 0),
        "rva_get_take_attack_dmg_multiplier": rva_take,
        "rva_get_opponent_faction": rva_faction,
        "prologue": " ".join(f"{b:02X}" for b in prologue),
        "source": str(data.get("source") or ""),
    }


# ---------------------------------------------------------------------------
# 来源 1：启动器的 HookIndex（动态更新）
# ---------------------------------------------------------------------------


def _load_hook_index() -> Any:
    """取启动器当前的 HookIndex；任何异常都返回 None（不影响插件）。"""
    try:
        from functions.hook.index import get_index

        index, _source = get_index(allow_cloud=False)
        return index
    except Exception:  # noqa: BLE001
        return None


def offsets_from_hook_index(index: Any) -> Optional[Dict[str, Any]]:
    """从 HookIndex 组装偏移表；字段不全返回 None。"""
    if index is None:
        return None
    hooks = dict(getattr(index, "hooks", None) or {})
    cheat = dict(getattr(index, "cheat_damage", None) or {})
    game = dict(getattr(index, "game", None) or {})

    take = hooks.get(HOOK_TAKE_ATTACK) or {}
    faction = hooks.get(HOOK_OPPONENT_FACTION) or {}

    rva_take = int(take.get("rva") or cheat.get("rva_get_take_attack_dmg_multiplier") or 0)
    rva_faction = int(faction.get("rva") or cheat.get("rva_get_opponent_faction") or 0)
    prologue = str(take.get("prologue") or cheat.get("prologue") or "")
    sha = str(game.get("gameassembly_sha256") or cheat.get("gameassembly_sha256") or "")
    size = int(game.get("gameassembly_size") or cheat.get("gameassembly_size") or 0)
    version = str(game.get("game_version") or cheat.get("game_version") or "unknown")

    if rva_take <= 0 or rva_faction <= 0 or not prologue or not sha:
        return None

    try:
        return normalize_payload({
            "game_version": version,
            "gameassembly_sha256": sha,
            "gameassembly_size": size,
            "rva_get_take_attack_dmg_multiplier": rva_take,
            "rva_get_opponent_faction": rva_faction,
            "prologue": prologue,
            "source": "hook_index",
        })
    except OffsetsError:
        return None


# ---------------------------------------------------------------------------
# 来源 2：远端 API
# ---------------------------------------------------------------------------


def fetch_offsets(api_url: str = DEFAULT_API_URL, timeout: int = FETCH_TIMEOUT) -> Dict[str, Any]:
    """从远端 API 拉取并校验偏移表。"""
    req = urllib.request.Request(api_url, headers={"User-Agent": "FaustLauncher/main"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001 - 网络异常种类太多，统一收敛
        raise OffsetsError(f"请求偏移接口失败: {e}")

    try:
        data = json.loads(raw)
    except ValueError as e:
        raise OffsetsError(f"偏移接口返回的不是合法 JSON: {e}")

    payload = normalize_payload(data)
    payload["source"] = "api"
    return payload


# ---------------------------------------------------------------------------
# 来源 3：磁盘缓存
# ---------------------------------------------------------------------------


def load_cached() -> Optional[Dict[str, Any]]:
    """读取磁盘缓存；不存在或损坏返回 None。"""
    path = cache_path()
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(data, dict):
        return None
    payload = data.get("offsets")
    if not isinstance(payload, dict):
        return None
    try:
        result = normalize_payload(payload)
    except OffsetsError:
        return None
    result["source"] = "cache"
    return result


def save_cached(offsets: Dict[str, Any]) -> bool:
    """把偏移表写入磁盘缓存；失败静默返回 False（不影响主流程）。"""
    path = cache_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"fetched_at": time.time(), "offsets": offsets}, f,
                      ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        return True
    except Exception:  # noqa: BLE001
        return False


def _cache_age() -> Optional[float]:
    try:
        return max(0.0, time.time() - os.path.getmtime(cache_path()))
    except OSError:
        return None


# ---------------------------------------------------------------------------
# 统一入口
# ---------------------------------------------------------------------------


def get_offsets(force: bool = False, max_age: float = DEFAULT_MAX_AGE,
                api_url: str = DEFAULT_API_URL) -> Optional[Dict[str, Any]]:
    """拿一份可用偏移表，失败返回 None（不抛异常，方便插件直接 if）。

    默认顺序：HookIndex → 新鲜缓存 → 远端 API → 过期缓存。
    ``force=True`` 时跳过缓存、强制走 HookIndex 或远端。
    """
    if not force:
        fresh_cache = load_cached()
        age = _cache_age()
        if fresh_cache is not None and age is not None and age <= max_age:
            # 缓存虽然新鲜，但 HookIndex 可能已经跟着游戏更新了，仍优先试它
            index_offsets = offsets_from_hook_index(_load_hook_index())
            return index_offsets or fresh_cache

    index_offsets = offsets_from_hook_index(_load_hook_index())
    if index_offsets is not None:
        save_cached(index_offsets)
        return index_offsets

    try:
        payload = fetch_offsets(api_url=api_url)
    except OffsetsError:
        return load_cached()

    save_cached(payload)
    return payload


# ---------------------------------------------------------------------------
# 本地文件校验
# ---------------------------------------------------------------------------


def game_dir() -> str:
    """当前设置里的游戏根目录（没有则空串）。"""
    try:
        from functions.base.settings_manager import get_settings_manager

        return str(get_settings_manager().get_setting("game_path") or "")
    except Exception:  # noqa: BLE001
        return ""


def find_gameassembly(root: str = "") -> Optional[str]:
    """在给定目录（或当前游戏目录）里定位 GameAssembly.dll。"""
    roots = [root] if root else [game_dir()]
    for base in roots:
        if not base:
            continue
        for candidate in (
            os.path.join(base, GAME_DLL_NAME),
            os.path.join(base, "LimbusCompany_Data", GAME_DLL_NAME),
        ):
            if os.path.isfile(candidate):
                return candidate
    return None


def sha256_of_file(path: str, chunk: int = 1 << 20) -> str:
    """流式计算文件 sha256（大写十六进制）。"""
    import hashlib

    digest = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            block = f.read(chunk)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest().upper()


def verify_local_gameassembly(offsets: Dict[str, Any], root: str = "") -> Dict[str, Any]:
    """把本机 GameAssembly.dll 的 sha256 与偏移表比对。

    返回 ``{"ok", "path", "sha256", "error"}``；找不到文件或哈希不一致都算不匹配
    （不允许注入：序言校验也必然失败）。
    """
    path = find_gameassembly(root)
    if not path:
        return {"ok": False, "path": "", "sha256": "",
                "error": "未找到 GameAssembly.dll，请先在设置里配置游戏路径"}
    try:
        actual = sha256_of_file(path)
    except OSError as e:
        return {"ok": False, "path": path, "sha256": "", "error": f"读取 GameAssembly.dll 失败: {e}"}

    expected = str(offsets.get("gameassembly_sha256") or "").upper()
    if actual != expected:
        return {
            "ok": False,
            "path": path,
            "sha256": actual,
            "error": f"游戏版本与偏移表不匹配（本地 {actual[:12]}… / 期望 {expected[:12]}…）",
        }
    return {"ok": True, "path": path, "sha256": actual, "error": ""}


if __name__ == "__main__":
    import sys

    try:
        sys.stdout.reconfigure(encoding="utf-8") # type: ignore
    except Exception:  # noqa: BLE001
        pass

    print(f"缓存路径: {cache_path()}")
    offs = get_offsets()
    if not offs:
        print("获取偏移失败（HookIndex、接口与缓存都不可用）")
        raise SystemExit(1)
    print(f"来源    : {offs.get('source')}")
    print(f"游戏版本: {offs['game_version']}")
    print(f"SHA256  : {offs['gameassembly_sha256']}")
    print(f"大小    : {offs['gameassembly_size']}")
    for key in OFFSET_KEYS:
        print(f"{key} = 0x{offs[key]:X} ({offs[key]})")
    print(f"prologue: {offs['prologue']}")

    check = verify_local_gameassembly(offs)
    print(f"本地校验: {'通过' if check['ok'] else '失败'}  {check['error']}")
    print(f"GameAssembly: {check['path']}")
    raise SystemExit(0 if check["ok"] else 2)
