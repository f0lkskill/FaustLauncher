"""il2cpp C API 导出名映射，供 frida-il2cpp-bridge 这类插件使用。

游戏把 ``GameAssembly.dll`` 里 234 个 ``il2cpp_*`` 导出改成了混淆名，但
``UnityPlayer.dll`` 的 ``.text`` 段里仍然按固定顺序 ``lea`` 引用这些名字。
本模块复刻这条定位链路，并把它接入启动器的缓存/版本体系：

* 映射结果按 ``GameAssembly.dll`` 的 sha256 缓存到 ``cache/il2cpp_exports/``，
  同一版本只扫描一次（扫描要读 164MB + 36MB 两个 DLL，约数秒）。
* 扫描出 234 个名字但顺序和插件的基准表对不上时，直接判定「游戏接口布局
  已变化」，让插件报出可读原因，而不是在 frida 里静默崩溃。
* 版本信息取自启动器的 HookIndex（``functions.hook.index``），与
  ``cheat_offsets`` 共用同一套「游戏版本从哪来」的约定。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import struct
from typing import Any, Dict, List, Optional

from functions.base.common.path_utils import get_app_root

GAMEASSEMBLY = "GameAssembly.dll"
UNITYPLAYER = "UnityPlayer.dll"
CANONICAL_FILE = "il2cpp-api-names.txt"
CACHE_DIR_NAME = "il2cpp_exports"

# lea rax/rcx/rdx/rbx/rsp/rbp/rsi/rdi, [rip+disp32]
_LEA_RE = re.compile(rb"\x48\x8d[\x05\x0d\x15\x1d\x25\x2d\x35\x3d]")
# NUL 前的 C 标识符，长度 > 10 才能命中混淆导出名
_SYMBOL_RE = re.compile(rb"(?<=\x00)[A-Za-z_][A-Za-z0-9_]{10}\x00")
_CANONICAL_RE = re.compile(r"il2cpp_\w+")


class Il2cppExportsError(Exception):
    """扫描或校验 il2cpp 导出映射时的错误。"""


def cache_dir() -> str:
    """返回缓存目录，不存在则创建。"""
    path = os.path.join(get_app_root(create=True), "cache", CACHE_DIR_NAME)
    os.makedirs(path, exist_ok=True)
    return path


def cache_path(sha256: str) -> str:
    """按 GameAssembly.dll 的 sha256 前 16 位定位缓存文件。"""
    return os.path.join(cache_dir(), f"{str(sha256)[:16].lower()}.json")


def canonical_names(path: str = "") -> List[str]:
    """读取插件的 il2cpp C API 基准名字表（234 项，顺序即接口布局）。"""
    candidates = [path] if path else []
    if not candidates:
        candidates.append(
            os.path.join(get_app_root(create=False), "addons", "SinnersRandom",
                         "Assets", "runtime", CANONICAL_FILE)
        )
    for candidate in candidates:
        if candidate and os.path.isfile(candidate):
            with open(candidate, "r", encoding="utf-8") as handle:
                names = [line.strip() for line in handle]
            names = [name for name in names if _CANONICAL_RE.fullmatch(name)]
            if names:
                return names
    raise Il2cppExportsError(f"找不到 il2cpp 基准名字表: {path or candidates[0]}")


def gameassembly_sha256(game_dir: str) -> str:
    """计算 GameAssembly.dll 的 sha256（流式计算，避免一次读入 164MB）。"""
    path = os.path.join(game_dir, GAMEASSEMBLY)
    if not os.path.isfile(path):
        raise Il2cppExportsError(f"找不到 {GAMEASSEMBLY}: {path}")
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _pe_exports(path: str) -> Dict[str, int]:
    """列出 DLL 的导出名表。"""
    import pefile

    pe = pefile.PE(path, fast_load=True)
    pe.parse_data_directories(directories=[0])
    directory = getattr(pe, "DIRECTORY_ENTRY_EXPORT", None)
    if directory is None:
        return {}
    return {entry.name.decode(): entry.address
            for entry in directory.symbols if entry.name}


def _locate_strings(unityplayer_path: str, export_names: Dict[str, int]) -> Dict[int, str]:
    """把 UnityPlayer.dll 里出现的导出名字符串映射到它所在的 RVA。"""
    import pefile

    unityplayer = pefile.PE(unityplayer_path, fast_load=True)
    with open(unityplayer_path, "rb") as handle:
        data = handle.read()
    found: Dict[int, str] = {}
    for match in _SYMBOL_RE.finditer(data):
        name = match.group().rstrip(b"\x00").decode()
        if name in export_names:
            found[unityplayer.get_rva_from_offset(match.start())] = name
    return found


def _ordered_exports(unityplayer_path: str, strings: Dict[int, str]) -> List[str]:
    """按 lea 指令在 .text 段里出现的先后顺序，排出导出名序列。"""
    import pefile

    unityplayer = pefile.PE(unityplayer_path, fast_load=True)
    section = next((item for item in unityplayer.sections
                    if item.Name.rstrip(b"\x00") == b".text"), None)
    if section is None:
        raise Il2cppExportsError("UnityPlayer.dll 缺少 .text 段")
    code = section.get_data()
    ordered: List[str] = []
    for match in _LEA_RE.finditer(code):
        target = (section.VirtualAddress + match.start() + 7
                  + struct.unpack_from("<i", code, match.start() + 3)[0])
        if target in strings:
            ordered.append(strings[target])
    return ordered


def scan(game_dir: str, *, names_path: str = "") -> Dict[str, Any]:
    """扫描两个 DLL 得到 ``{il2cpp 名: 混淆导出名}``，并报告是否对齐。"""
    game_dir = os.path.abspath(game_dir)
    assembly = os.path.join(game_dir, GAMEASSEMBLY)
    unityplayer = os.path.join(game_dir, UNITYPLAYER)
    for path in (assembly, unityplayer):
        if not os.path.isfile(path):
            raise Il2cppExportsError(f"找不到 {os.path.basename(path)}: {path}")

    canonical = canonical_names(names_path)
    exports = _pe_exports(assembly)
    if not exports:
        raise Il2cppExportsError(f"{GAMEASSEMBLY} 没有导出表，可能已被加壳")

    strings = _locate_strings(unityplayer, exports)
    ordered = _ordered_exports(unityplayer, strings)
    sha256 = gameassembly_sha256(game_dir)

    ok = len(ordered) == len(canonical)
    mapping: Dict[str, str] = {}
    if ok:
        mapping = dict(zip(canonical, ordered))

    return {
        "ok": ok,
        "mapping": mapping,
        "ordered": len(ordered),
        "canonical": len(canonical),
        "export_count": len(exports),
        "sha256": sha256,
        "game_dir": game_dir,
        "reason": "" if ok else (
            f"接口布局已变化：解析到 {len(ordered)} 个导出引用，"
            f"基准表有 {len(canonical)} 个（游戏更新后需要新的 {CANONICAL_FILE}）"
        ),
    }


def load_cache(game_dir: str, *, names_path: str = "") -> Optional[Dict[str, Any]]:
    """按当前 GameAssembly.dll 的 sha256 读取缓存，版本不符返回 None。"""
    try:
        sha256 = gameassembly_sha256(game_dir)
    except Il2cppExportsError:
        return None
    path = cache_path(sha256)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError):
        return None
    if payload.get("sha256") != sha256 or not payload.get("mapping"):
        return None
    try:
        if len(payload["mapping"]) != len(canonical_names(names_path)):
            return None
    except Il2cppExportsError:
        return None
    payload["cached"] = True
    return payload


def save_cache(result: Dict[str, Any]) -> str:
    """把对齐成功的扫描结果写入缓存，返回缓存路径。"""
    path = cache_path(result["sha256"])
    payload = dict(result)
    payload.pop("cached", None)
    temporary = path + ".tmp"
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    os.replace(temporary, path)
    return path


def _game_info() -> Dict[str, Any]:
    """从 HookIndex 取游戏版本信息，失败时返回空字典。"""
    try:
        from functions.hook.index import get_index

        # get_index 返回 (HookIndex | None, 说明文字)
        index, _ = get_index(allow_cloud=False)
        if index is None:
            return {}
        return dict(getattr(index, "game", None) or {})
    except Exception:  # noqa: BLE001 - HookIndex 不可用时不影响映射本身
        return {}


def resolve(game_dir: str = "", *, refresh: bool = False,
            names_path: str = "") -> Dict[str, Any]:
    """取得映射：优先缓存，未命中则扫描并写缓存。

    返回同 :func:`scan`，额外带 ``cached`` 与 ``game``（HookIndex 版本信息）。
    """
    if not game_dir:
        from functions.base.settings_manager import get_settings_manager

        game_dir = str(get_settings_manager().get_setting("game_path") or "")
    if not game_dir:
        raise Il2cppExportsError("设置里没有游戏路径")

    if not refresh:
        cached = load_cache(game_dir, names_path=names_path)
        if cached is not None:
            cached["game"] = _game_info()
            return cached

    result = scan(game_dir, names_path=names_path)
    result["cached"] = False
    if result["ok"]:
        result["cache_file"] = save_cache(result)
    result["game"] = _game_info()
    return result


def verify(game_dir: str = "", *, names_path: str = "") -> Dict[str, Any]:
    """轻量校验：只判断基准表能否与当前游戏对齐，供插件启动前调用。

    返回 ``{ok, detail, sha256, game_version, ordered, canonical}``，不抛异常。
    """
    try:
        result = resolve(game_dir, names_path=names_path)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "detail": str(exc), "sha256": "", "game_version": "",
                "ordered": 0, "canonical": 0}
    game = result.get("game") or {}
    if not result["ok"]:
        detail = result["reason"]
    elif result.get("cached"):
        detail = f"接口映射缓存命中（{result['ordered']} 个导出）"
    else:
        detail = f"接口映射已重建（{result['ordered']} 个导出）"
    return {
        "ok": bool(result["ok"]),
        "detail": detail,
        "sha256": result.get("sha256", ""),
        "game_version": str(game.get("game_version") or ""),
        "ordered": result.get("ordered", 0),
        "canonical": result.get("canonical", 0),
    }


def __main__() -> int:  # pragma: no cover - 手工自检入口
    import sys

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    result = resolve()
    game = result.get("game") or {}
    print(f"游戏目录: {result['game_dir']}")
    print(f"游戏版本: {game.get('game_version', '?')}  build {game.get('game_build_id', '?')}")
    print(f"GameAssembly 大小: {game.get('gameassembly_size', '?')}")
    print(f"SHA256: {result['sha256']}")
    print(f"导出总数: {result['export_count']}  解析到引用: {result['ordered']}  基准表: {result['canonical']}")
    print(f"对齐: {'通过' if result['ok'] else '失败'}  ({'缓存' if result.get('cached') else '新扫描'})")
    if result["ok"]:
        sample = list(result["mapping"].items())[:3]
        for name, export in sample:
            print(f"  {name} -> {export}")
        print(f"缓存文件: {result.get('cache_file', cache_path(result['sha256']))}")
        return 0
    print(f"原因: {result['reason']}")
    return 2


if __name__ == "__main__":
    raise SystemExit(__main__())
