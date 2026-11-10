"""开发用：扫描当前在场单位的身份信息，方便对照敌人 id / 人格 id。

前提：游戏在跑、WarpHook 的 DLL 已注入，并且正处在战斗里。

    python tools/dev/scan_units.py            # 关键字段
    python tools/dev/scan_units.py --all      # 把字段表里能读的全读一遍（慢）
    python tools/dev/scan_units.py --json     # 机器可读

``id`` 是战斗内实例编号，``identity`` 是 ``_originID``（人格 / 敌人静态数据
的映射编号），``position`` 是 ``UNIT_POSITION``（1=MAIN、2=SUB、3=ASSISTANCE）。
"""

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'addons/WarpHook'))

from warphook import live  # noqa: E402

KEYS = ('index', 'id', 'identity', 'position', 'hp', 'max_hp', 'sp',
        'speed', 'alive', 'panic', 'break', 'buffs')


def _row(unit):
    return {
        'index': unit.index,
        'id': unit.id,
        'identity': unit.identity,
        'position': unit.get_pro('_position'),
        'hp': unit.hp,
        'max_hp': unit.max_hp,
        'sp': unit.sp,
        'speed': unit.speed,
        'alive': unit.alive,
        'panic': unit.is_panic,
        'break': unit.is_break,
        'buffs': unit.buff_count(),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--all', action='store_true', help='打印字段表里的全部字段')
    parser.add_argument('--json', action='store_true', help='输出 JSON')
    parser.add_argument('--wait', type=float, default=8.0, help='最多等多久把单位读出来')
    args = parser.parse_args()

    game = live.live('scan_units')
    # 回合钩子把 BattleObjectManager 落进对象槽，units() 才读得到。
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

    if not units:
        print('没读到单位（在战斗里吗？宿主连上了吗？）')
        return 2

    rows = []
    for unit in units:
        row = _row(unit)
        if args.all:
            row['fields'] = unit.scan()
        rows.append(row)

    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0

    print(f'场上单位：{len(rows)}')
    if args.all:
        for row in rows:
            print(f"--- index={row['index']} id={row['id']} "
                  f"identity={row['identity']} ---")
            for name, value in (row.get('fields') or {}).items():
                print(f'  {name} = {value}')
        return 0

    header = '  '.join(f'{k:>10}' for k in KEYS)
    print(header)
    for row in rows:
        print('  '.join(f'{str(row.get(k)):>10}' for k in KEYS))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
