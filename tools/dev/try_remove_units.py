"""开发用：清空敌方阵营，保留指定的 InstanceID。

走 ``game.clear_enemies``（内部是 ``GetModelList`` + ``EnqueueRemoveUnitInstanceID``），
只改队列、不碰 Unity View，真正的移除由游戏主线程在生成/回合时机处理。

    python tools/dev/try_remove_units.py --attach --keep 17,18
"""

import argparse
import sys
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
    host = Host(addon_name='remove_units_tool', hooks=[], texts=[])
    host._block = block
    if not host.object_ptr(objects.SLOT_MANAGER):
        host.call('BattleObjectManager::get_Instance', slot=None, ret='ref',
                  out_slot=objects.SLOT_MANAGER, via='invoke', timeout=5.0)
    return host


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--keep', default='', help='保留的 instance id，逗号分隔')
    parser.add_argument('--wave', type=int, default=0, help='生成/移除所属的 wave')
    parser.add_argument('--include-assistance', action='store_true',
                        help='连协助敌人一起清')
    parser.add_argument('--attach', action='store_true',
                        help='连启动器已挂钩的宿主，不自己注入')
    args = parser.parse_args()

    keep = {int(x) for x in args.keep.split(',') if x.strip()}
    if args.attach:
        host = _attach_host()
        if host is None:
            print('打不开宿主共享内存（启动器挂钩了吗？）')
            return 2
        result = live._clear_enemies_on(
            host, keep=keep, faction=1, wave_index=args.wave,
            include_assistance=args.include_assistance)
    else:
        result = live.clear_enemies(
            keep=keep, faction='enemy', wave_index=args.wave,
            include_assistance=args.include_assistance)

    print('结果：', result)
    if result.get('ok'):
        print(f"已入队 {result.get('queued')} 个；保留 {result.get('kept')}")
        return 0
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
