"""开发用：在判定层把场上第二个我方单位改成敌方。

前提：游戏在跑、WarpHook 的 DLL 已注入，并且正处在战斗里（两人上场）。

    python tools/dev/try_faction.py          # 第二人 → 敌方
    python tools/dev/try_faction.py --clear  # 撤销

只改 ``get__faction`` 的返回值：IsOpponent / 可攻击目标列表会把它当敌人，
单位自己的行动逻辑不变（仍由你操作）。一次只认一个单位。
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
    parser.add_argument('--clear', action='store_true', help='撤掉已经装上的阵营钩子')
    parser.add_argument('--index', type=int, default=1, help='改成第几个单位（0 起，默认第二人）')
    parser.add_argument('--wait', type=float, default=8.0, help='最多等多久把它读出来')
    args = parser.parse_args()

    game = live.live('faction_tool')
    # 装回合钩子：它把 BattleObjectManager 落进对象槽，units() 才读得到。
    game.on_round_start(lambda battle: None)
    deadline = time.time() + max(0.0, args.wait)
    units = []
    while time.time() < deadline:
        try:
            units = game.units()
        except Exception as error:  # noqa: BLE001
            print(f'读单位失败：{error}')
            units = []
        if len(units) > args.index:
            break
        time.sleep(0.5)

    print('场上单位：', [(u.index, u.id) for u in units])
    if args.clear:
        print(game.clear_unit_faction())
        return 0
    if len(units) <= args.index:
        print(f'没等到第 {args.index + 1} 个单位（在战斗里吗？宿主连上了吗？）')
        return 2
    result = game.set_unit_faction(units[args.index], 'enemy')
    print('结果：', result)
    return 0 if result.get('ok') else 2


if __name__ == '__main__':
    raise SystemExit(main())
