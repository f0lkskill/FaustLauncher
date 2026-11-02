# 换首歌：在战斗里切 BGM
from typing import cast

if False:  # 仅供类型检查器阅读，运行时不会执行
    from warphook.base import WarpNamespace

ADDON_ARG = globals().get('ADDON_ARG') or {}
ADDON_NAME = ADDON_ARG.get('AddonName', '换首歌')

_NS = ADDON_ARG.get('Namespaces')
_W = cast("WarpNamespace", _NS.space('warp') if _NS is not None else None)

game = _W.game

DEFAULT_SONG = 'Battle_Cp9_Boss_10'


def _song() -> str:
    """从插件设置里取曲目名，读不到就用默认值。"""
    manager = ADDON_ARG.get('AddonManager')
    try:
        info = manager.get_addon_info(ADDON_NAME) or {}
        value = (info.get('settings') or {}).get('曲目')
        if isinstance(value, str) and value.strip():
            return value.strip()
    except Exception:
        pass
    return DEFAULT_SONG


def _play(result) -> None:
    if result.get('ok'):
        print(f'[{ADDON_NAME}] 正在播放 {result.get("name")}', flush=True)
    else:
        print(f'[{ADDON_NAME}] 换曲失败：{result.get("reason")}', flush=True)


def _swap() -> None:
    """换到设置里的那首。"""
    _play(game.bgm(_song()))


def _back() -> None:
    """停掉附加曲，让游戏自己的战斗 BGM 回来。"""
    if game.bgm_stop().get('ok'):
        print(f'[{ADDON_NAME}] 已恢复游戏原曲', flush=True)


def _status() -> None:
    print(f'[{ADDON_NAME}] 当前曲目编号 {game.bgm_index()}，'
          f'{"在播" if game.bgm_playing() else "没播"}', flush=True)


game.start(menu=(
    ('换成设置里的曲子', _swap),
    ('恢复游戏原曲', _back),
    ('看播放状态', _status),
))


def on_unload():
    game.close()
