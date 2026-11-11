"""回到之前成功过的路线：新 stage id + 原 Walpu3 UI/节点。

- 克隆 Walpu3 10557 为新 stage 990001（追加，不替换 10557）；
- 把原 Walpu3 节点 910803 的 stageId 改成 990001；
- 不改 UI、subchapter、stageNodeList，不新增 unknown 条目；
- 服务器请求只把 stageid 990001 改写回 10557。

点击原版 Walpu3 入口即可进入新关卡，进入/退出都由合法 10557 的服务器包完成。

    python tools/dev/link_new_stage.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'addons/WarpHook'))

from warphook import live  # noqa: E402
from warphook.base import shm_open  # noqa: E402
from warphook.host import (Host, HostHeader, HOST_MAP_BYTES,  # noqa: E402
                           HOST_MAP_DEFAULT, HOST_MAGIC)


def main():
    block = shm_open(HOST_MAP_DEFAULT, HOST_MAP_BYTES, HostHeader,
                     magic_field='magic', magic_value=HOST_MAGIC)
    if block is None:
        print('打不开宿主共享内存（启动器挂钩了吗？）')
        return 2
    host = Host(addon_name='link_new_stage', hooks=[], texts=[])
    host._block = block
    lv = live.Live(owner='link_new_stage', host=host, auto=False)
    add = lv.stage_add(
        10557, 990001, enemy_ids=[1100], level=45, sync_level=1, count=1,
        stage_level=45, recommended_level=45, strip_story=True,
        clear_scripts=True, replace=False, timeout=5.0)
    print('stage_add:', add)
    if not add.get('ok'):
        return 2

    host.call('StaticDataManager::get_Instance', slot=None, ret='ref',
              out_slot=30, via='invoke', timeout=3)
    host.call('StaticDataManager::get_partList', slot=30, ret='ref',
              out_slot=31, via='invoke', timeout=3)
    plist = live._ptr_at(host, 31, 0x10)
    owner = live._find_stage_node_list_on(host, 910803, plist)
    if owner is None:
        print('找不到 Walpu3 节点 910803')
        return 2
    node_list_ptr, node_index = owner
    host.put_slot(24, node_list_ptr)
    host.put_slot(23, 0)
    host.list_item(24, node_index, 23, timeout=3)
    host.write_int(23, 0x1C, 990001, timeout=3)
    print('node 910803 stageId -> 990001')

    guard = lv.custom_stage_server_guard(990001, 10557)
    print('guard:', guard)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
