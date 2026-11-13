"""把当前战场上唯一的敌人 HP 改成 0（ObscuredInt 按 key/hidden 编码）。

前提：游戏在战斗中、WarpHook 已注入。只用于调试，不改变玩家单位。

    python tools/dev/zero_enemy_hp.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'addons/WarpHook'))

from warphook import live, objects  # noqa: E402
from warphook.base import shm_open  # noqa: E402
from warphook.host import (Host, HostHeader, HOST_MAP_BYTES,  # noqa: E402
                           HOST_MAP_DEFAULT, HOST_MAGIC)


def _i32(host, slot, off):
    return host.read(slot, [{'off': off, 'deref': False}],
                     kind='int', default=0, timeout=3) or 0


def _ptr(host, slot, off):
    return ((_i32(host, slot, off + 4) & 0xFFFFFFFF) << 32) | (
        _i32(host, slot, off) & 0xFFFFFFFF)


def _set_hp_zero(host, unit):
    model = unit.read({'off': objects._UNIT_MODEL, 'deref': False},
                      kind='int', default=0, timeout=3)
    model |= unit.read({'off': objects._UNIT_MODEL + 4, 'deref': False},
                       kind='int', default=0, timeout=3) << 32
    if not model:
        return False, 'model 指针为空'
    host.put_slot(24, model)
    state = _ptr(host, 24, 0x148)
    if not state:
        return False, 'CharacterState 指针为空'
    host.put_slot(23, state)
    hp_off = 0x148
    # ObscuredInt = {key, hidden}; value = hidden ^ key。写 0/0 得到 0。
    host.write_int(23, hp_off, 0, timeout=3)
    host.write_int(23, hp_off + 4, 0, timeout=3)
    return True, state


def main():
    block = shm_open(HOST_MAP_DEFAULT, HOST_MAP_BYTES, HostHeader,
                     magic_field='magic', magic_value=HOST_MAGIC)
    if block is None:
        print('打不开宿主共享内存（启动器挂钩了吗？）')
        return 2
    host = Host(addon_name='zero_enemy_hp', hooks=[], texts=[])
    host._block = block
    enemy_ids = live._model_list_ids(host, faction=1, timeout=3)
    print('enemy instance ids:', enemy_ids)
    if not enemy_ids:
        print('当前没有敌人')
        return 2
    if len(enemy_ids) != 1:
        print('敌人不止一个，请先确认唯一目标')
        return 2
    acc = objects.access(host)
    unit = acc.get_obj(id=enemy_ids[0])
    if unit is None:
        print('找不到 instance id', enemy_ids[0])
        return 2
    print('target', unit.index, unit.id, unit.identity, 'hp',
          unit.hp, '/', unit.max_hp)
    ok, detail = _set_hp_zero(host, unit)
    print('set hp=0:', ok, detail)
    return 0 if ok else 2


if __name__ == '__main__':
    raise SystemExit(main())
