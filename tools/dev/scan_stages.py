"""开发用：扫描主线关卡表，找“直接进战斗、无剧情”的关卡，并可选克隆。

前提：游戏在跑、WarpHook 已注入。静态数据在进过主界面/关卡后才会加载。

    python tools/dev/scan_stages.py --scan
    python tools/dev/scan_stages.py --clone 911410
    python tools/dev/scan_stages.py --clone 911410 --keep-story
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'addons/WarpHook'))

from warphook import live, objects  # noqa: E402


def _attach_host():
    from warphook.base import shm_open
    from warphook.host import (Host, HostHeader, HOST_MAP_BYTES,
                               HOST_MAP_DEFAULT, HOST_MAGIC)
    block = shm_open(HOST_MAP_DEFAULT, HOST_MAP_BYTES, HostHeader,
                     magic_field='magic', magic_value=HOST_MAGIC)
    if block is None:
        return None
    host = Host(addon_name='scan_stages', hooks=[], texts=[])
    host._block = block
    return host


def _read_stage_row(host, list_slot, index):
    base = (list_slot, [{'list': index}])
    off = base[1]

    def read(field_off, kind='int', deref=False):
        return host.read(list_slot, off + [{'off': field_off, 'deref': deref}],
                         kind=kind, default=None)

    return {
        'id': read(0x10),
        'stage_type': read(0x20),
        'story': read(0x60, kind='ptr'),
        'stage_scripts': read(0x98, kind='count', deref=True),
        'event_script': read(0xA0, kind='ptr'),
        'abnormality_events': read(0x90, kind='count', deref=True),
        'waves': read(0xB0, kind='count', deref=True),
    }


def _scan(host, limit=500):
    result = host.call('StaticDataManager::get_Instance', slot=None,
                       ret='ref', out_slot=30, via='invoke', timeout=3.0)
    if isinstance(result, str):
        print('取 StaticDataManager 失败：', result)
        return 2
    result = host.call('StaticDataManager::get_storyBattleStageList',
                       slot=30, ret='ref', out_slot=31, via='invoke',
                       timeout=3.0)
    if isinstance(result, str):
        print('取 storyBattleStageList 失败：', result)
        return 2
    result = host.call('StageStaticDataList::GetList', slot=31,
                       ret='ref', out_slot=29, via='invoke', timeout=3.0)
    if isinstance(result, str) or not host.object_ptr(29):
        print('取 StageStaticDataList.GetList 失败：', result)
        return 2

    count = host.read(29, [], kind='count', default=0, timeout=3.0) or 0
    print(f'storyBattleStageList: {count} 个关卡（最多扫描 {limit}）')
    candidates = []
    for i in range(min(count, int(limit))):
        row = _read_stage_row(host, 29, i)
        if (row['stage_type'] == 0 and not row['story']
                and not row['stage_scripts'] and not row['event_script']
                and not row['abnormality_events'] and row['waves']):
            candidates.append(row)
            print(f"  candidate id={row['id']} waves={row['waves']}")
    print(f'纯战斗候选：{len(candidates)} 个')
    if candidates:
        print('建议克隆：', candidates[0]['id'])
    return 0


def _clone(host, source_id, keep_story=False):
    result = live._stage_clone_on(host, source_id, strip_story=not keep_story,
                                  timeout=5.0)
    print('克隆结果：', result)
    slot = result.get('slot')
    if not result.get('ok') or slot is None:
        return 2
    # 直接读克隆对象字段
    info = {
        'id': host.read(slot, [{'off': 0x10, 'deref': False}],
                        kind='int', default=None, timeout=3.0),
        'stage_type': host.read(slot, [{'off': 0x20, 'deref': False}],
                                kind='int', default=None, timeout=3.0),
        'story': host.read(slot, [{'off': 0x60, 'deref': False}],
                           kind='ptr', default=None, timeout=3.0),
        'stage_scripts': host.read(slot, [{'off': 0x98, 'deref': True}],
                                   kind='count', default=None, timeout=3.0),
        'event_script': host.read(slot, [{'off': 0xA0, 'deref': False}],
                                  kind='ptr', default=None, timeout=3.0),
        'waves': host.read(slot, [{'off': 0xB0, 'deref': True}],
                           kind='count', default=None, timeout=3.0),
    }
    print('克隆对象：', info)
    return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--scan', action='store_true', help='扫描纯战斗关卡')
    parser.add_argument('--clone', type=int, default=None, help='克隆指定关卡 id')
    parser.add_argument('--keep-story', action='store_true',
                        help='克隆时保留剧情/事件脚本')
    parser.add_argument('--limit', type=int, default=500, help='扫描上限')
    args = parser.parse_args()

    host = _attach_host()
    if host is None:
        print('打不开宿主共享内存（启动器挂钩了吗？）')
        return 2
    if args.clone is not None:
        return _clone(host, args.clone, keep_story=args.keep_story)
    return _scan(host, limit=args.limit)


if __name__ == '__main__':
    raise SystemExit(main())
