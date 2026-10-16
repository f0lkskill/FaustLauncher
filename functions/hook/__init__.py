
from __future__ import annotations

__version__ = "1.0"

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
    from .updater import update_hook_index as _impl
    return _impl(*args, **kwargs)

def status(*args, **kwargs):
    from .updater import status as _impl
    return _impl(*args, **kwargs)

def auto_update_async(*args, **kwargs):
    from .updater import auto_update_async as _impl
    return _impl(*args, **kwargs)
