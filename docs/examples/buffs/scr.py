# -*- coding: utf-8 -*-
"""06 篇示例：读 buff。"""

from typing import cast

ADDON_ARG = globals().get('ADDON_ARG') or {}
ADDON_NAME = ADDON_ARG.get('AddonName') or 'buff 观察'

_NS = ADDON_ARG.get('Namespaces')
_W = cast("WarpNamespace", _NS.space('warp') if _NS is not None else None)
game = _W.game


def _log(message):
    print(f'[{ADDON_NAME}] {message}', flush=True)


def _list_buffs():
    u = game.player()
    if u is None:
        _log('现在不在战斗里')
        return
    _log(f'编号 {u.id}（人格 {u.identity}）身上 {u.buff_count()} 个 buff：')
    for b in u.buffs:
        _log(f'  {b.name or b.key}  {b.stack}/{b.max_stack} 层  '
             f'{b.turn}/{b.max_turn} 次   [{b.key}]')


def _check():
    """判断身上有没有某个 buff —— 插件最常用的写法。"""
    u = game.player()
    if u is None:
        return
    if u.has_buff('Breath'):
        b = u.buff('Breath')
        _log(f'身上有呼吸法：{b.stack} 层，还剩 {b.turn} 次')
    else:
        _log('没有呼吸法')

    if u.is_break:
        _log('注意：已混乱')
    if u.hp_ratio is not None and u.hp_ratio < 0.3:
        _log('注意：血量低于 30%')


def _on_round(battle):
    """回合边界把全场的 buff 数报一遍。"""
    for u in battle.units:
        names = [b.key for b in u.buffs]
        if names:
            _log(f'#{u.id}（{u.identity}）{len(names)} 个：{", ".join(names)}')


game.start(menu=(
    ('列出我方 buff', _list_buffs),
    ('检查几个 buff', _check),
))
game.on_round_start(_on_round)
