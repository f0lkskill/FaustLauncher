"""开发用：用游戏原生 ``CreateEnemyInStage`` 立即生成一个敌人。

前提：游戏在跑、WarpHook 的 DLL 已注入，并且正处在战斗里（至少一个回合
已经开始过，BattleObjectManager 才会落进对象槽）。

    python tools/dev/try_create_enemy.py --id 109
    python tools/dev/try_create_enemy.py --id 109 --position sub --level 35

生成后可以接着跑 ``scan_units.py``，用 ``id`` / ``identity`` 对照新单位。
"""

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'addons/WarpHook'))

from warphook import live, objects  # noqa: E402


def _attach_host():
    """连启动器已经建好的宿主，不自己注入、不重写钩子表。"""
    from warphook.base import shm_open
    from warphook.host import (Host, HostHeader, HOST_MAP_BYTES,
                               HOST_MAP_DEFAULT, HOST_MAGIC)
    block = shm_open(HOST_MAP_DEFAULT, HOST_MAP_BYTES, HostHeader,
                     magic_field='magic', magic_value=HOST_MAGIC)
    if block is None:
        return None
    host = Host(addon_name='create_enemy_tool', hooks=[], texts=[])
    host._block = block
    if not host.object_ptr(objects.SLOT_MANAGER):
        host.call('BattleObjectManager::get_Instance', slot=None, ret='ref',
                  out_slot=objects.SLOT_MANAGER, via='invoke', timeout=5.0)
    return host


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--id', type=int, required=True, help='EnemyStaticData 编号')
    parser.add_argument('--level', type=int, default=-1, help='等级（-1 = 游戏默认）')
    parser.add_argument('--sync-level', type=int, default=-1, help='同步等级')
    parser.add_argument('--wave', type=int, default=0, help='waveIndex')
    parser.add_argument('--speed', type=int, default=0, help='firstTurnSpeed')
    parser.add_argument('--position', default='main', choices=('main', 'sub', 'assistance'))
    parser.add_argument('--immediate', action='store_true',
                        help='直接 CreateEnemyInStage（worker 线程会崩 Unity，仅诊断）')
    parser.add_argument('--attach', action='store_true',
                        help='连启动器已挂钩的宿主，不自己注入')
    parser.add_argument('--wait', type=float, default=8.0, help='最多等多久进战斗')
    args = parser.parse_args()

    if args.attach:
        host = _attach_host()
        if host is None:
            print('打不开宿主共享内存（启动器挂钩了吗？）')
            return 2
        read_units = lambda: objects.units(host, slot=objects.SLOT_MANAGER)
        create = lambda: live._create_enemy_on(
            host, args.id, level=args.level, sync_level=args.sync_level,
            wave_index=args.wave, first_turn_speed=args.speed,
            position=args.position, immediate=args.immediate)
    else:
        game = live.live('create_enemy_tool')
        # 回合钩子把 BattleObjectManager 落进对象槽，create_enemy 才拿得到。
        game.on_round_start(lambda battle: None)
        read_units = game.units
        create = lambda: game.create_enemy(
            args.id, level=args.level, sync_level=args.sync_level,
            wave_index=args.wave, first_turn_speed=args.speed,
            position=args.position, immediate=args.immediate)

    deadline = time.time() + max(0.0, args.wait)
    units = []
    while time.time() < deadline:
        try:
            units = read_units()
        except Exception as error:  # noqa: BLE001
            print(f'读单位失败：{error}')
            units = []
        if units:
            break
        time.sleep(0.5)

    print('生成前：', [(u.index, u.id, u.identity) for u in units])
    result = create()
    print('结果：', result)
    if not result.get('ok'):
        return 2

    time.sleep(1.0)
    after = read_units()
    print('生成后：', [(u.index, u.id, u.identity) for u in after])
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
