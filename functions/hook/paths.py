"""钩子相关文件/缓存路径的统一解析。"""


from __future__ import annotations

import hashlib
import os
import sys
import time
from dataclasses import dataclass

METADATA_REL = os.path.join(
    "LimbusCompany_Data", "il2cpp_data", "Metadata", "global-metadata.dat")
GAMEASSEMBLY_NAME = "GameAssembly.dll"
GAME_EXE = "LimbusCompany.exe"

_HASH_CHUNK = 4 << 20

def project_root() -> str:
    """project根相关处理。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

def cache_root() -> str:
    """缓存根。"""
    path = os.path.join(project_root(), "cache", "hook")
    os.makedirs(path, exist_ok=True)
    return path

def cache_path(*parts: str) -> str:
    """缓存路径。"""
    path = os.path.join(cache_root(), *parts)
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    return path

def local_index_path() -> str:
    """local索引路径相关处理。"""
    return cache_path("hook_index.json")

def cloud_index_path() -> str:
    """cloud索引路径相关处理。"""
    return cache_path("hook_index_cloud.json")

def get_game_path(explicit: str = "") -> str:
    """获取游戏路径。"""
    if explicit:
        return _normalize(explicit)
    try:
        from functions.base.settings_manager import get_settings_manager
        configured = str(get_settings_manager().get_setting("game_path") or "").strip()
        if configured and os.path.isfile(os.path.join(configured, GAME_EXE)):
            return _normalize(configured)
    except Exception:
        pass
    try:
        from functions.base.steam_locator import find_steam_game_path
        found = find_steam_game_path()
        if found:
            return _normalize(found)
    except Exception:
        pass
    return ""

def _normalize(path: str) -> str:
    """内部规范化相关操作。"""
    try:
        from functions.base.steam_locator import normalize_game_path
        return normalize_game_path(path)
    except Exception:
        return os.path.normpath(str(path))

@dataclass(frozen=True)
class GamePaths:

    """游戏Paths类。"""
    root: str
    gameassembly: str
    metadata: str
    exe: str

    def missing(self) -> list[str]:
        """missing相关处理。"""
        items = [("GameAssembly.dll", self.gameassembly), ("global-metadata.dat", self.metadata)]
        return [f"{name}（{path}）" for name, path in items if not os.path.isfile(path)]

    @property
    def ok(self) -> bool:
        """ok相关处理。"""
        return not self.missing()

def game_paths(game_path: str = "") -> GamePaths:
    """游戏paths相关处理。"""
    root = get_game_path(game_path)
    return GamePaths(
        root=root,
        gameassembly=os.path.join(root, GAMEASSEMBLY_NAME) if root else "",
        metadata=os.path.join(root, METADATA_REL) if root else "",
        exe=os.path.join(root, GAME_EXE) if root else "",
    )

def file_sha256(path: str, on_progress=None) -> str:
    """文件sha256相关处理。"""
    digest = hashlib.sha256()
    try:
        total = os.path.getsize(path) or 1
        done = 0
        with open(path, "rb") as fh:
            while True:
                chunk = fh.read(_HASH_CHUNK)
                if not chunk:
                    break
                digest.update(chunk)
                done += len(chunk)
                if on_progress:
                    on_progress(done / total)
    except OSError:
        return ""
    return digest.hexdigest().upper()

def file_sha1(path: str) -> str:
    """文件sha1相关处理。"""
    digest = hashlib.sha1()
    try:
        with open(path, "rb") as fh:
            while True:
                chunk = fh.read(_HASH_CHUNK)
                if not chunk:
                    break
                digest.update(chunk)
    except OSError:
        return ""
    return digest.hexdigest().upper()

@dataclass(frozen=True)
class GameFingerprint:

    """游戏Fingerprint类。"""
    size: int
    sha256: str

    @property
    def short(self) -> str:
        """short相关处理。"""
        return (self.sha256 or "unknown")[:8]

    @property
    def valid(self) -> bool:
        """valid相关处理。"""
        return bool(self.sha256) and self.size > 0

    def as_dict(self) -> dict:
        """asdict相关处理。"""
        return {"gameassembly_size": self.size, "gameassembly_sha256": self.sha256}

def game_fingerprint(paths: GamePaths | None = None, game_path: str = "",
                     on_log=None) -> GameFingerprint:
    """游戏fingerprint相关处理。"""
    paths = paths or game_paths(game_path)
    if not os.path.isfile(paths.gameassembly):
        return GameFingerprint(0, "")
    size = os.path.getsize(paths.gameassembly)
    if on_log:
        on_log(f"正在计算 GameAssembly.dll 指纹（{size / 1048576:.1f} MB）...")
    sha = file_sha256(paths.gameassembly)
    return GameFingerprint(size, sha)

def now_iso() -> str:
    """nowiso相关处理。"""
    return time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime())

def hex_off(value: int) -> str:
    """hexoff相关处理。"""
    try:
        return f"0x{int(value):X}"
    except (TypeError, ValueError):
        return ""
