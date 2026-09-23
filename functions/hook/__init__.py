"""``functions.hook`` —— 边狱巴士（Limbus Company）偏移索引子系统。

**它解决什么问题**

游戏每次更新，IL2CPP 的符号 RVA 与模块内静态槽位偏移都会变。改动过
``test/damage_log.c``（MinHook detour）或桌面 ``ok.py``（CE 指针链）的人，
每次更新都要重新逆向一遍。这个子系统把这件事自动化：

::

    GameAssembly.dll + 加密 global-metadata.dat
            │  （Limbus 的 metadata 是保护过的：文件头没有标准魔数）
            ▼
    1. 静态解密 / 运行时内存 dump ──▶ 标准明文 metadata
            ▼
    2. Il2CppDumper ─────────────▶ dump.cs（含每个方法的 RVA 与字段偏移）
            ▼
    3. 解析 + 运行时校验 ────────▶ 偏移索引（钩子 RVA + prologue、数据链、符号表）
            ▼
    4. 写云端笔记 ───────────────▶ FaustLauncher.hook_index
            ▼
    5. 消费方（都是"只读"）
       - 注入 DLL：读 rva + prologue，prologue 不符就不装钩（防旧偏移打新版本）
       - 成就模块：读 targets.enkephalin 的指针链
       - test/damage_log.py：--api-url 直接指向笔记地址即可（cheat_damage 兼容块）

**常用入口**

- ``updater.update_hook_index()``   完整更新（带日志回调，适合挂在界面上）
- ``updater.auto_update_async()``   后台线程跑一次（成就监测进程里用它）
- ``index.get_target_chain("enkephalin")``  读一条数据链（进程内记忆 → 本地缓存 → 内置默认）
- CLI：``python -m functions.hook.main status|update|show|gen-header|locate``

**注意**

- 静态解密需要 ``capstone``（``pip install capstone``；仓库 requirements 里已加）
- 运行时 dump / 重定位需要游戏进程在跑，纯 ctypes 实现，不用 Frida、不用管理员
  （读同用户进程即可）
- ``metadata_recovery/`` 是从 LCTA 项目移植过来的 metadata 解密流水线
  （定位 → 提取 → 验证 → 求解 → 重建，IL2CPP v39）
"""

from __future__ import annotations

__version__ = "1.0"

# 注意：这里不要在模块级 import capstone / metadata_recovery / dumper 等重模块，
# 成就监测子进程会 import 本包（只要 get_target_chain），必须保持轻量。
from .index import (  # noqa: E402
    HookIndex,
    get_index,
    get_target_chain,
    note_key,
    pull_cloud,
    push_cloud,
)
from .paths import (  # noqa: E402
    GameFingerprint,
    GamePaths,
    cache_root,
    game_fingerprint,
    game_paths,
    get_game_path,
    local_index_path,
)

__all__ = [
    "__version__",
    "HookIndex",
    "GameFingerprint",
    "GamePaths",
    "cache_root",
    "game_fingerprint",
    "game_paths",
    "get_game_path",
    "get_index",
    "get_target_chain",
    "local_index_path",
    "note_key",
    "pull_cloud",
    "push_cloud",
    "update_hook_index",
    "status",
    "auto_update_async",
]


def update_hook_index(*args, **kwargs):
    """完整更新偏移索引（懒加载 updater，避免 import 时拉起 subprocess/网络依赖）。"""
    from .updater import update_hook_index as _impl
    return _impl(*args, **kwargs)


def status(*args, **kwargs):
    """当前索引 / 游戏文件状态（懒加载）。"""
    from .updater import status as _impl
    return _impl(*args, **kwargs)


def auto_update_async(*args, **kwargs):
    """后台线程更新一次（懒加载）。"""
    from .updater import auto_update_async as _impl
    return _impl(*args, **kwargs)
