# -*- coding: utf-8 -*-
"""战况播报：每回合开始时把场上所有单位的血量打到日志里。

这一篇的重点不是「怎么钩方法」，而是：**你只写一个函数，什么时候调它由框架负责。**

    game.on_round_start(_on_round)

``_on_round`` 收到的是一个 ``Battle`` —— 那一刻场上所有单位的快照。
"""

from typing import cast

if False:  # 仅供类型检查器阅读
    from warphook.base import WarpNamespace

ADDON_ARG = globals().get('ADDON_ARG') or {}
ADDON_NAME = ADDON_ARG.get('AddonName')
ADDON_MANAGER = ADDON_ARG.get('AddonManager')
_NS = ADDON_ARG.get('Namespaces')
_W = cast("WarpNamespace", _NS.space('warp') if _NS is not None else None)
game = _W.game


def _log(message):
    print(f'[{ADDON_NAME}] {message}', flush=True)


def _settings():
    try:
        info = (ADDON_MANAGER.get_addon_info(ADDON_NAME)
                if ADDON_MANAGER is not None else None) or {}
    except Exception:  # noqa: BLE001
        info = {}
    return info.get('settings') or {}


def _on_round(battle):
    """每回合开始被调一次。``battle`` 是那一刻的全场快照。"""
    _log(f'—— {battle.scene_name}：场上 {battle.count} 个单位 ——')
    if not _settings().get('播报血量', True):
        return
    for u in battle.units:
        tags = []
        if u.is_panic:
            tags.append('混乱')
        if u.is_break:
            tags.append('崩溃')
        if not u.alive:
            tags.append('已阵亡')
        tail = ('  ' + '/'.join(tags)) if tags else ''
        _log(f'  #{u.id:<2} 人格 {u.identity:<6} '
             f'HP {u.hp}/{u.max_hp}  SP {u.sp}{tail}')


def _now():
    """菜单用：不等回合，现在就看一眼。"""
    units = game.units()
    _log(f'现在场上有 {len(units)} 个单位')
    for u in units:
        _log(f'  #{u.id:<2} 人格 {u.identity:<6} HP {u.hp}/{u.max_hp}')


game.on_round_start(_on_round)
game.on_scene_changed(
    lambda scene: _log(f'场景切换 → {scene["name"]}'))
game.start(menu=(
    ('立刻看一次', _now),
    ('看连接状态', lambda: _log(game.describe())),
))


def on_unload():
    game.close()
