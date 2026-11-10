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

from warphook import live  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--id', type=int, required=True, help='EnemyStaticData 编号')
    parser.add_argument('--level', type=int, default=-1, help='等级（-1 = 游戏默认）')
    parser.add_argument('--sync-level', type=int, default=-1, help='同步等级')
    parser.add_argument('--wave', type=int, default=0, help='waveIndex')
    parser.add_argument('--speed', type=int, default=0, help='firstTurnSpeed')
    parser.add_argument('--position', default='main', choices=('main', 'sub', 'assistance'))
    parser.add_argument('--wait', type=float, default=8.0, help='最多等多久进战斗')
    args = parser.parse_args()

    game = live.live('create_enemy_tool')
    # 回合钩子把 BattleObjectManager 落进对象槽，create_enemy 才拿得到。
    game.on_round_start(lambda battle: None)
    deadline = time.time() + max(0.0, args.wait)
    units = []
    while time.time() < deadline:
        try:
            units = game.units()
        except Exception as error:  # noqa: BLE001
            print(f'读单位失败：{error}')
            units = []
        if units:
            break
        time.sleep(0.5)

    print('生成前：', [(u.index, u.id, u.identity) for u in units])
    result = game.create_enemy(args.id, level=args.level,
                               sync_level=args.sync_level,
                               wave_index=args.wave,
                               first_turn_speed=args.speed,
                               position=args.position)
    print('结果：', result)
    if not result.get('ok'):
        return 2

    time.sleep(1.0)
    after = game.units()
    print('生成后：', [(u.index, u.id, u.identity) for u in after])
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
