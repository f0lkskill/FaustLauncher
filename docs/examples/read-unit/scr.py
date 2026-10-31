# -*- coding: utf-8 -*-
"""04 篇示例：读场上一个单位。"""

from typing import cast

ADDON_ARG = globals().get('ADDON_ARG') or {}
ADDON_NAME = ADDON_ARG.get('AddonName') or '看看我方'

_NS = ADDON_ARG.get('Namespaces')
_W = cast("WarpNamespace", _NS.space('warp') if _NS is not None else None)
game = _W.game


def _log(message):
    print(f'[{ADDON_NAME}] {message}', flush=True)


def _show():
    """看一眼我方第一个单位。"""
    u = game.player()          # 我方第一个（没有就返回 None）
    if u is None:
        _log('现在不在战斗里，或者我方没人')
        return

    _log(f'编号 {u.id}   人格 {u.identity}')
    _log(f'血量 {u.hp} / {u.max_hp}   （{u.hp_ratio:.0%}）')
    _log(f'理智 {u.sp}')
    _log(f'速度 {u.speed}')
    _log(f'活着 {u.alive}   混乱 {u.is_break}   恐慌 {u.is_panic}')


def _all():
    """把全体扫一遍。"""
    battle = game.battle()
    if battle is None:
        _log('现在不在战斗里')
        return
    _log(f'{battle.scene_name}：{battle.count} 个单位')
    for u in battle.units:
        _log(f'  #{u.id} 人格 {u.identity}  HP {u.hp}/{u.max_hp}  SP {u.sp}')


game.start(menu=(
    ('看看我方第一个', _show),
    ('扫一遍全场', _all),
))
