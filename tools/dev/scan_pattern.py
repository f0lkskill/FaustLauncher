"""开发用：读敌人静态数据里的行动槽 / pattern 配置。

对照 ``EnemyStaticData.startActionSlotNumList / patternList / patternID``
和 ``PatternScript_Base._patternList / allPattenCount / currPatternIdx``，
判断“新创建的敌人不出招”是缺槽，还是 pattern 没载入。

    python tools/dev/scan_pattern.py --attach
"""

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'addons/WarpHook'))

from warphook import objects  # noqa: E402

MODEL = {"off": 0x10, "deref": True}
UNIT_DATA = {"off": 0x10, "deref": True}
CLASS_INFO = {"off": 0x10, "deref": True}
PATTERN_PTR = {"off": 0x190, "deref": False}


def _attach_host():
    from warphook.base import shm_open
    from warphook.host import (Host, HostHeader, HOST_MAP_BYTES,
                               HOST_MAP_DEFAULT, HOST_MAGIC)
    block = shm_open(HOST_MAP_DEFAULT, HOST_MAP_BYTES, HostHeader,
                     magic_field='magic', magic_value=HOST_MAGIC)
    if block is None:
        return None
    host = Host(addon_name='scan_pattern', hooks=[], texts=[])
    host._block = block
    if not host.object_ptr(objects.SLOT_MANAGER):
        host.call('BattleObjectManager::get_Instance', slot=None, ret='ref',
                  out_slot=objects.SLOT_MANAGER, via='invoke', timeout=5.0)
    return host


def _read(unit, *chain, kind='int', default=None):
    return unit.read(*chain, kind=kind, default=default)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--attach', action='store_true')
    parser.add_argument('--ids', default='', help='只看这些 instance id')
    parser.add_argument('--wait', type=float, default=6.0)
    args = parser.parse_args()

    only = {int(x) for x in args.ids.split(',') if x.strip()}
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

    for unit in units:
        if only and unit.id not in only:
            continue
        print(f"index={unit.index} id={unit.id} identity={unit.identity}")
        print(f"  maxActionSlot={_read(unit, MODEL, UNIT_DATA, CLASS_INFO, {'off': 0x184}, kind='int')}")
        print(f"  startSlots={_read(unit, MODEL, UNIT_DATA, CLASS_INFO, {'off': 0x188, 'deref': True}, kind='count')}")
        print(f"  patternID={_read(unit, MODEL, UNIT_DATA, CLASS_INFO, {'off': 0x198}, kind='text')}")
        print(f"  patternList={_read(unit, MODEL, UNIT_DATA, CLASS_INFO, {'off': 0x1A0, 'deref': True}, kind='count')}")
        script = _read(unit, MODEL, PATTERN_PTR)
        print(f"  patternScript=0x{(script or 0):x}")
        if script:
            print(f"    name={_read(unit, MODEL, {'off': 0x190, 'deref': True}, {'off': 0x18}, kind='text')}")
            print(f"    allPattenCount={_read(unit, MODEL, {'off': 0x190, 'deref': True}, {'off': 0x24})}")
            print(f"    currPatternIdx={_read(unit, MODEL, {'off': 0x190, 'deref': True}, {'off': 0x28})}")
            print(f"    currPhase={_read(unit, MODEL, {'off': 0x190, 'deref': True}, {'off': 0x20})}")
            print(f"    patternList={_read(unit, MODEL, {'off': 0x190, 'deref': True}, {'off': 0x30, 'deref': True}, kind='count')}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
