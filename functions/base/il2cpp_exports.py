"""il2cpp C API 导出名映射，供 frida-il2cpp-bridge 这类插件使用。

游戏把 ``GameAssembly.dll`` 里 234 个 ``il2cpp_*`` 导出改成了混淆名，但
``UnityPlayer.dll`` 的 ``.text`` 段里仍然按固定顺序 ``lea`` 引用这些名字。
本模块复刻这条定位链路，并把它接入启动器的缓存/版本体系：

* 缓存同时校验两个 DLL、基准表有序内容和解析器版本。
* 标准导出直接按名字映射；混淆导出依赖游戏注册顺序与基准表一致的约定。
  数量及唯一性检查只能拒绝部分异常，不能证明同数量重排没有发生。
* 失败报告导出、字符串和引用三个阶段的计数，不把解析失败归因于基准表缺失。
* 版本信息取自启动器的 HookIndex（``functions.hook.index``），与
  ``cheat_offsets`` 共用同一套「游戏版本从哪来」的约定。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import struct
import tempfile
from typing import Any, Dict, List, Optional

from functions.base.common.path_utils import get_app_root

GAMEASSEMBLY = "GameAssembly.dll"
UNITYPLAYER = "UnityPlayer.dll"
CANONICAL_FILE = "il2cpp-api-names.txt"
CACHE_DIR_NAME = "il2cpp_exports"

CACHE_SCHEMA = 2
# REX.W，REX.R 可选：覆盖 rax-r15 的 RIP-relative LEA。
_LEA_RE = re.compile(rb"[\x48\x4c]\x8d[\x05\x0d\x15\x1d\x25\x2d\x35\x3d]")
# 只将完整 C 字符串与真实 PE 导出表比对，不假定混淆名长度。
_SYMBOL_RE = re.compile(rb"(?:\A|(?<=\x00))[A-Za-z_][A-Za-z0-9_]*\x00")
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
    """返回 il2cpp C API 基准名字表（234 项，顺序即接口布局）。

    默认直接用内嵌常量 :data:`functions.base.il2cpp_api_names.CANONICAL_NAMES`
    —— 启动器自带这张表，不依赖 ``addons/`` 下任何插件目录，也不依赖外部
    文件，打包后同样可用。

    只有显式传入 ``path`` 时才改读文件，留给「游戏更新、需要临时换表」的
    场景；文件里只保留 ``il2cpp_`` 开头的合法标识符。
    """
    if path:
        if not os.path.isfile(path):
            raise Il2cppExportsError(f"找不到 il2cpp 基准名字表: {path}")
        with open(path, "r", encoding="utf-8-sig") as handle:
            names = [line.strip() for line in handle]
        names = [name for name in names if _CANONICAL_RE.fullmatch(name)]
        if not names:
            raise Il2cppExportsError(f"il2cpp 基准名字表为空或格式不对: {path}")
        return names

    from functions.base.il2cpp_api_names import CANONICAL_NAMES

    names = list(CANONICAL_NAMES)
    if not names:
        raise Il2cppExportsError("内嵌的 il2cpp 基准名字表为空")
    return names


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
    try:
        pe.parse_data_directories(directories=[0])
        directory = getattr(pe, "DIRECTORY_ENTRY_EXPORT", None)
        if directory is None:
            return {}
        return {entry.name.decode("ascii"): entry.address
                for entry in directory.symbols if entry.name and entry.address
                and not getattr(entry, "forwarder", None)}
    finally:
        close = getattr(pe, "close", None)
        if close:
            close()


def _locate_strings(unityplayer_path: str, export_names: Dict[str, int]) -> Dict[int, str]:
    """把 UnityPlayer.dll 里出现的导出名字符串映射到它所在的 RVA。"""
    import pefile

    unityplayer = pefile.PE(unityplayer_path, fast_load=True)
    with open(unityplayer_path, "rb") as handle:
        data = handle.read()
    found: Dict[int, str] = {}
    try:
        for match in _SYMBOL_RE.finditer(data):
            name = match.group()[:-1].decode("ascii")
            if name in export_names:
                found[unityplayer.get_rva_from_offset(match.start())] = name
        return found
    finally:
        close = getattr(unityplayer, "close", None)
        if close:
            close()


def _ordered_exports(unityplayer_path: str, strings: Dict[int, str]) -> List[str]:
    """按 lea 指令在 .text 段里出现的先后顺序，排出导出名序列。"""
    import pefile

    unityplayer = pefile.PE(unityplayer_path, fast_load=True)
    try:
        section = next((item for item in unityplayer.sections
                        if item.Name.rstrip(b"\x00") == b".text"), None)
        if section is None:
            raise Il2cppExportsError("UnityPlayer.dll 缺少 .text 段")
        code = section.get_data()
        ordered: List[str] = []
        for match in _LEA_RE.finditer(code):
            if match.start() + 7 > len(code):
                continue
            target = (section.VirtualAddress + match.start() + 7
                      + struct.unpack_from("<i", code, match.start() + 3)[0])
            if target in strings:
                ordered.append(strings[target])
        return ordered
    finally:
        close = getattr(unityplayer, "close", None)
        if close:
            close()


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

    if len(set(canonical)) != len(canonical):
        raise Il2cppExportsError("il2cpp 基准名字表包含重复项")
    standard = all(name in exports for name in canonical)
    strings = {} if standard else _locate_strings(unityplayer, exports)
    ordered = list(canonical) if standard else _ordered_exports(unityplayer, strings)
    # 游戏的注册顺序仍以基准表为前提；不排序、不截断、不去重凑数量。
    ok = len(ordered) == len(canonical) and len(set(ordered)) == len(ordered)
    mapping = dict(zip(canonical, ordered)) if ok else {}
    identity = _cache_identity(game_dir, canonical)
    reason = ""
    if not ok:
        reason = (
            f"导出映射解析未完成：PE 导出 {len(exports)} 个，"
            f"匹配名字字符串 {len(strings)} 处，引用 {len(ordered)} 个"
            f"（唯一 {len(set(ordered))}），已读取基准表 {len(canonical)} 项；"
            "请检查两 DLL 是否来自同一游戏安装及解析器兼容性；"
            "仅凭引用数量不能判定基准表缺失或接口布局变化。"
            f"目录={game_dir}；GameAssembly SHA256={identity['sha256']}；"
            f"UnityPlayer SHA256={identity['unityplayer_sha256']}；解析器={CACHE_SCHEMA}"
        )
    return {
        **identity,
        "ok": ok,
        "mapping": mapping,
        "strategy": "standard" if standard else "ordered-lea",
        "ordered": len(ordered),
        "unique_references": len(set(ordered)),
        "string_count": len(strings),
        "canonical": len(canonical),
        "export_count": len(exports),
        "game_dir": game_dir,
        "reason": reason,
    }


def _file_sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _cache_identity(game_dir: str, canonical: List[str]) -> Dict[str, Any]:
    return {
        "schema": CACHE_SCHEMA,
        "sha256": gameassembly_sha256(game_dir),
        "unityplayer_sha256": _file_sha256(os.path.join(game_dir, UNITYPLAYER)),
        "canonical_sha256": hashlib.sha256("\n".join(canonical).encode("utf-8")).hexdigest(),
    }


def load_cache(game_dir: str, *, names_path: str = "") -> Optional[Dict[str, Any]]:
    """按当前 GameAssembly.dll 的 sha256 读取缓存，版本不符返回 None。"""
    try:
        canonical = canonical_names(names_path)
        identity = _cache_identity(game_dir, canonical)
        with open(cache_path(identity["sha256"]), "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if not isinstance(payload, dict) or payload.get("ok") is not True:
            return None
        if any(payload.get(key) != value for key, value in identity.items()):
            return None
        mapping = payload.get("mapping")
        if not isinstance(mapping, dict) or set(mapping) != set(canonical):
            return None
        values = list(mapping.values())
        if not all(isinstance(value, str) and value for value in values):
            return None
        if len(set(values)) != len(canonical) or len(set(canonical)) != len(canonical):
            return None
        exports = _pe_exports(os.path.join(game_dir, GAMEASSEMBLY))
        if not all(value in exports for value in values):
            return None
    except (OSError, ValueError, Il2cppExportsError):
        return None
    payload["game_dir"] = os.path.abspath(game_dir)
    payload["cached"] = True
    return payload


def save_cache(result: Dict[str, Any]) -> str:
    """把对齐成功的扫描结果写入缓存，返回缓存路径。"""
    if result.get("ok") is not True or not result.get("mapping"):
        raise Il2cppExportsError("不缓存失败的导出映射")
    path = cache_path(result["sha256"])
    payload = dict(result)
    payload.pop("cached", None)
    temporary = ""
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=os.path.dirname(path),
                                         prefix="exports-", suffix=".tmp", delete=False) as handle:
            temporary = handle.name
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)
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
