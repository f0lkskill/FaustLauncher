"""WarpHook 的运行时实现（拆分包）。

``scr.py`` 只是薄入口：拿到 ``ADDON_ARG`` 之后调 :func:`bind`，
再把 :func:`register` 的结果挂到启动器的命名空间容器上。
"""

from .env import WARP_HOOK_VERSION, bind  # noqa: F401

__version__ = WARP_HOOK_VERSION
from .base import (  # noqa: F401
    SharedMap,
    export_mapped,
    find_game_pid,
    has_gameassembly,
    inject_dll,
    log,
    names_table,
    resolve_exports,
    shm_open,
    wait_for_game,
    wait_for_gameassembly,
)
from .game import Gacha, GachaBill, GachaWatcher, gacha  # noqa: F401
from .host import Host, host_alive  # noqa: F401
from . import diag  # noqa: F401
from . import fields  # noqa: F401
from . import objects  # noqa: F401
from .registry import on_unload, register  # noqa: F401
from .service import Runtime, Service  # noqa: F401
