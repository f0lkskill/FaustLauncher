# -*- coding: utf-8 -*-
"""05 篇示例：把能读的字段全读一遍。"""

from typing import cast

ADDON_ARG = globals().get('ADDON_ARG') or {}
ADDON_NAME = ADDON_ARG.get('AddonName') or '全属性'

_NS = ADDON_ARG.get('Namespaces')
_W = cast("WarpNamespace", _NS.space('warp') if _NS is not None else None)
game = _W.game
fields = _W.field


def _log(message):
    print(f'[{ADDON_NAME}] {message}', flush=True)


def _dump(personality):
    """按人格 ID 找一个单位，把所有字段打出来。"""
    u = game.unit(identity=personality)
    if u is None:
        _log(f'场上没有人格 {personality} 的单位')
        return

    _log(f'=== 人格 {personality}（编号 {u.id}）===')
    props = u.props()                       # 一次读 60 多个字段，会慢（约 2 秒）
    for name, value in props.items():
        if value is None:
            continue                        # 读不到的不显示
        _log(f'  {name:<36} {value}')


def _single():
    """只读几个字段，快得多。"""
    u = game.player()
    if u is None:
        return
    hp = u.get_pro('hp')
    mx = u.get_pro('CharacterState._maxHp')
    dmg = u.get_pro('_totalTakeDamageInThisBattle')
    _log(f'编号 {u.id}：HP {hp}/{mx}，本场累计承伤 {dmg}')


game.start(menu=(
    ('打印 10115 全部字段', lambda: _dump(10115)),
    ('只读三个字段', _single),
    ('告诉我字段表里有多少字段',
     lambda: _log(f'共 {len(fields.FIELD_TABLE)} 类，'
                  f'BattleUnitModel {len(fields.FIELD_TABLE["BattleUnitModel"])} 个字段')),
))
