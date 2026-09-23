"""hook 子系统 — 路径 / 指纹 / 时间工具。

游戏相关路径的解析顺序（越靠前优先级越高）：

1. 调用方显式传入的 ``game_path``
2. launcher 设置 ``config/settings.json → game_path``（用户在界面上配置过的）
3. Steam VDF 自动定位（``functions.base.steam_locator``）

缓存布局（都在 ``<项目根>/cache/hook`` 下，可随时删除）：

- ``hook_index.json``          最近一次生成的偏移索引（本地缓存，成就模块读它）
- ``tools/il2cppdumper/``      Il2CppDumper 工具目录（含 config.json）
- ``decrypt/run_<时间戳>/``    静态解密的运行产物（standard-rebuilt.dat / run-report.md）
- ``dump/<指纹8位>/``          dump 产物（dump.cs / dump.stdout.log）

指纹 = GameAssembly.dll 的 (size, sha256)。游戏每次更新这两个值都会变，
所以它是"要不要重新 dump"的天然判断依据（比版本号更可靠）。
"""

from __future__ import annotations

import hashlib
import os
import sys
import time
from dataclasses import dataclass

# 游戏目录内的相对路径（Steam 版标准布局）
METADATA_REL = os.path.join(
    "LimbusCompany_Data", "il2cpp_data", "Metadata", "global-metadata.dat")
GAMEASSEMBLY_NAME = "GameAssembly.dll"
GAME_EXE = "LimbusCompany.exe"

_HASH_CHUNK = 4 << 20


def project_root() -> str:
    """项目根目录（打包后为 exe 所在目录）。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))


def cache_root() -> str:
    """hook 子系统缓存根目录（不存在时创建）。"""
    path = os.path.join(project_root(), "cache", "hook")
    os.makedirs(path, exist_ok=True)
    return path


def cache_path(*parts: str) -> str:
    """缓存目录下的路径（父目录已创建）。"""
    path = os.path.join(cache_root(), *parts)
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    return path


def local_index_path() -> str:
    """本地完整版索引路径（updater 写；符号表最全）。"""
    return cache_path("hook_index.json")


def cloud_index_path() -> str:
    """从云端拉下来的索引路径（可能被发布体积预算裁剪过，符号表只有几百条）。

    单独放一个文件：否则成就进程启动时的云端刷新会把本地完整版索引覆盖掉，
    反查“RVA → 符号名”、线下排查都会变残缺（实测踩到过）。
    """
    return cache_path("hook_index_cloud.json")


# --------------------------------------------------------------------------- 游戏路径


def get_game_path(explicit: str = "") -> str:
    """解析游戏安装目录；找不到时返回空串。"""
    if explicit:
        return _normalize(explicit)
    # 1) launcher 设置
    try:
        from functions.base.settings_manager import get_settings_manager
        configured = str(get_settings_manager().get_setting("game_path") or "").strip()
        if configured and os.path.isfile(os.path.join(configured, GAME_EXE)):
            return _normalize(configured)
    except Exception:
        pass
    # 2) Steam 自动定位
    try:
        from functions.base.steam_locator import find_steam_game_path
        found = find_steam_game_path()
        if found:
            return _normalize(found)
    except Exception:
        pass
    return ""


def _normalize(path: str) -> str:
    try:
        from functions.base.steam_locator import normalize_game_path
        return normalize_game_path(path)
    except Exception:
        return os.path.normpath(str(path))


@dataclass(frozen=True)
class GamePaths:
    """一组游戏文件路径（不保证存在，用 ``missing()`` 检查）。"""

    root: str
    gameassembly: str
    metadata: str
    exe: str

    def missing(self) -> list[str]:
        items = [("GameAssembly.dll", self.gameassembly), ("global-metadata.dat", self.metadata)]
        return [f"{name}（{path}）" for name, path in items if not os.path.isfile(path)]

    @property
    def ok(self) -> bool:
        return not self.missing()


def game_paths(game_path: str = "") -> GamePaths:
    """由游戏根目录派生各文件路径（路径即使不存在也返回，便于报错提示）。"""
    root = get_game_path(game_path)
    return GamePaths(
        root=root,
        gameassembly=os.path.join(root, GAMEASSEMBLY_NAME) if root else "",
        metadata=os.path.join(root, METADATA_REL) if root else "",
        exe=os.path.join(root, GAME_EXE) if root else "",
    )


# --------------------------------------------------------------------------- 指纹


def file_sha256(path: str, on_progress=None) -> str:
    """分块计算文件 SHA-256（大写十六进制）；失败返回空串。"""
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
    """GameAssembly.dll 指纹：游戏更新的可靠判据。"""

    size: int
    sha256: str

    @property
    def short(self) -> str:
        """前 8 位（用作 dump 目录名）。"""
        return (self.sha256 or "unknown")[:8]

    @property
    def valid(self) -> bool:
        return bool(self.sha256) and self.size > 0

    def as_dict(self) -> dict:
        return {"gameassembly_size": self.size, "gameassembly_sha256": self.sha256}


def game_fingerprint(paths: GamePaths | None = None, game_path: str = "",
                     on_log=None) -> GameFingerprint:
    """计算当前 GameAssembly.dll 指纹。"""
    paths = paths or game_paths(game_path)
    if not os.path.isfile(paths.gameassembly):
        return GameFingerprint(0, "")
    size = os.path.getsize(paths.gameassembly)
    if on_log:
        on_log(f"正在计算 GameAssembly.dll 指纹（{size / 1048576:.1f} MB）...")
    sha = file_sha256(paths.gameassembly)
    return GameFingerprint(size, sha)


def now_iso() -> str:
    """本地时间 ISO 字符串（秒级）。"""
    return time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime())


def hex_off(value: int) -> str:
    """``0x`` 前缀大写十六进制（偏移量展示统一用它）。"""
    try:
        return f"0x{int(value):X}"
    except (TypeError, ValueError):
        return ""
