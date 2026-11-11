"""把 Walpu3 的现成 UI 节点提升到章节顶部，并把它指向一个合法关卡 id。

这是最保守的测试路线：
- 不新增 SubChapter/StageNode，不碰其他节点列表；
- 只替换一个真实关卡 id 数据；
- 把原本的 Walpu3 UI 条目移到 UI 列表最前；
- 不改 stageid 服务器请求，让服务器按原关卡处理。

    python tools/dev/promote_walpu_stage.py --stage-id 10550
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'addons/WarpHook'))

from warphook import live  # noqa: E402
from warphook.base import shm_open  # noqa: E402
from warphook.host import (Host, HostHeader, HOST_MAP_BYTES,  # noqa: E402
                           HOST_MAP_DEFAULT, HOST_MAGIC)


def _attach_host():
    block = shm_open(HOST_MAP_DEFAULT, HOST_MAP_BYTES, HostHeader,
                     magic_field='magic', magic_value=HOST_MAGIC)
    if block is None:
        return None
    host = Host(addon_name='promote_walpu', hooks=[], texts=[])
    host._block = block
    return host


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=int, default=910803,
                        help='Walpu3 UI 节点 id')
    parser.add_argument('--stage-id', type=int, default=10550,
                        help='要替换的真实关卡 id（需未被节点引用）')
    args = parser.parse_args()

    host = _attach_host()
    if host is None:
        print('打不开宿主共享内存（启动器挂钩了吗？）')
        return 2
    lv = live.Live(owner='promote_walpu', host=host, auto=False)
    add = lv.stage_add(10557, args.stage_id, enemy_ids=[1100], level=45,
                       sync_level=1, count=1, stage_level=45,
                       recommended_level=45, strip_story=True,
                       clear_scripts=True, replace=True, timeout=5.0)
    print('stage_add:', add)
    if not add.get('ok'):
        return 2

    host.call('StaticDataManager::get_Instance', slot=None, ret='ref',
              out_slot=30, via='invoke', timeout=3)
    host.call('StaticDataManager::get_partList', slot=30, ret='ref',
              out_slot=31, via='invoke', timeout=3)
    plist = live._ptr_at(host, 31, 0x10)
    owner = live._find_stage_node_list_on(host, args.source, plist)
    if owner is None:
        print('找不到 Walpu3 StageNodeInfo')
        return 2
    node_list_ptr, node_index = owner
    host.put_slot(24, node_list_ptr)
    host.put_slot(23, 0)
    host.list_item(24, node_index, 23, timeout=3)
    host.write_int(23, 0x1C, args.stage_id, timeout=3)
    print('node', args.source, '-> stage', args.stage_id)

    # UI: move the existing Walpu3 banner to index 0.
    host.put_slot(22, plist)
    host.list_item(22, 0, 21, timeout=3)
    ui_ptr = live._ptr_at(host, 21, 0x28)
    if not ui_ptr:
        print('找不到 SubchapterUIList')
        return 2
    host.put_slot(20, ui_ptr)
    count = host.read(20, [], kind='count', default=0, timeout=3) or 0
    found = None
    for i in range(count):
        host.put_slot(19, 0)
        host.list_item(20, i, 19, timeout=3)
        if host.read(19, [{'off': 0x18, 'deref': False}],
                     kind='int', default=0) == args.source:
            found = i
            break
    if found is None:
        print('UI 列表里找不到 Walpu3 条目')
        return 2
    host.put_slot(18, 0)
    host.list_item(20, found, 18, timeout=3)
    host.set_list_item(20, 0, 18, timeout=3)
    if found != count - 1:
        host.put_slot(17, 0)
        host.list_item(20, count - 1, 17, timeout=3)
        host.set_list_item(20, found, 17, timeout=3)
    host.write_int(20, 0x18, count - 1, timeout=3)
    print('UI count', count, '->', count - 1, 'top node', args.source)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
