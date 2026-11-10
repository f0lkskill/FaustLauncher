"""开发用：扫描单位的行动槽 / 技能队列 / AI pattern 指针。

只看结构，不做修改。重点对照“正常敌人”和“刚创建出来的敌人”：
``_actionList``、``_actionSlotDetail._sinActionList``、``_patternScript``、
``UnitDataModel._skillList/_attackSkillList``。

    python tools/dev/scan_actions.py --attach
"""

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'addons/WarpHook'))

from warphook import objects  # noqa: E402

MODEL = {"off": 0x10, "deref": True}
ACTION_LIST = {"off": 0xA0, "deref": True}
SLOT_DETAIL = {"off": 0x88, "deref": True}
SIN_LIST = {"off": 0x18, "deref": True}
PATTERN = {"off": 0x190, "deref": False}
UNIT_DATA = {"off": 0x10, "deref": True}
SKILL_LIST = {"off": 0x50, "deref": True}
ATTACK_SKILL_LIST = {"off": 0x40, "deref": True}


def _attach_host():
    from warphook.base import shm_open
    from warphook.host import (Host, HostHeader, HOST_MAP_BYTES,
                               HOST_MAP_DEFAULT, HOST_MAGIC)
    block = shm_open(HOST_MAP_DEFAULT, HOST_MAP_BYTES, HostHeader,
                     magic_field='magic', magic_value=HOST_MAGIC)
    if block is None:
        return None
    host = Host(addon_name='scan_actions', hooks=[], texts=[])
    host._block = block
    if not host.object_ptr(objects.SLOT_MANAGER):
        host.call('BattleObjectManager::get_Instance', slot=None, ret='ref',
                  out_slot=objects.SLOT_MANAGER, via='invoke', timeout=5.0)
    return host


def _read(unit, *chain, kind='int', default=None):
    return unit.read(*chain, kind=kind, default=default)


def _sin_rows(unit, count):
    rows = []
    for i in range(count or 0):
        base = (MODEL, SLOT_DETAIL, SIN_LIST, {"list": i})
        rows.append({
            'ready': _read(unit, *base, {"off": 0x30, "deref": True}, kind='count'),
            'current': _read(unit, *base, {"off": 0x40, "deref": True}, kind='count'),
            'select': _read(unit, *base, {"off": 0x48, "deref": False}),
            'slot': _read(unit, *base, {"off": 0x68, "deref": False}),
            'action': _read(unit, *base, {"off": 0x70, "deref": False}),
        })
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--attach', action='store_true',
                        help='连启动器已挂钩的宿主，不自己注入')
    parser.add_argument('--wait', type=float, default=6.0)
    args = parser.parse_args()

    host = _attach_host()
    if host is None:
        print('打不开宿主共享内存（启动器挂钩了吗？）')
        return 2

    deadline = time.time() + max(0.0, args.wait)
    units = []
    while time.time() < deadline:
        try:
            units = objects.units(host, slot=objects.SLOT_MANAGER)
        except Exception as error:  # noqa: BLE001
            print(f'读单位失败：{error}')
            units = []
        if units:
            break
        time.sleep(0.5)

    if not units:
        print('没读到单位（在战斗里吗？宿主连上了吗？）')
        return 2

    for unit in units:
        actions = _read(unit, MODEL, ACTION_LIST, kind='count')
        sins = _read(unit, MODEL, SLOT_DETAIL, SIN_LIST, kind='count')
        pattern = _read(unit, MODEL, PATTERN)
        skills = _read(unit, MODEL, UNIT_DATA, SKILL_LIST, kind='count')
        attacks = _read(unit, MODEL, UNIT_DATA, ATTACK_SKILL_LIST, kind='count')
        print(f"index={unit.index} id={unit.id} identity={unit.identity} "
              f"actions={actions} sins={sins} pattern=0x{(pattern or 0):x} "
              f"skills={skills} attacks={attacks}")
        for i, row in enumerate(_sin_rows(unit, sins)):
            print(f"  sin[{i}] ready={row['ready']} current={row['current']} "
                  f"select=0x{(row['select'] or 0):x} "
                  f"slot=0x{(row['slot'] or 0):x} "
                  f"action=0x{(row['action'] or 0):x}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
