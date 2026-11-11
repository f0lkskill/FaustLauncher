"""扫描章节 UI 数据，定位直接进单场景的章节大关卡。

    python tools/dev/scan_chapters.py

当前版本里 ``SUBCHAPTER_TYPE.STAGE_NODE=3`` 是直接进单场景的章节大关卡。
UI 的 ``SubchapterUIDataInPart.nodeId`` 是 UI 节点 id，需要再用
``PartStaticDataList.GetStageInfoForUI(nodeId)`` 换成 ``StageNodeInfo``，
其中的 ``stageId`` 才是 ``StageStaticDataList`` 的关卡 id。
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'addons/WarpHook'))

from warphook.base import shm_open  # noqa: E402
from warphook.host import (Host, HostHeader, HOST_MAP_BYTES,  # noqa: E402
                           HOST_MAP_DEFAULT, HOST_MAGIC)

SUBTYPE_NAMES = {0: 'MAIN', 1: 'SUB', 2: 'MINI_STORY',
                 3: 'STAGE_NODE', 4: 'STORY_THEATER', 5: 'EVENT'}


def _attach_host():
    block = shm_open(HOST_MAP_DEFAULT, HOST_MAP_BYTES, HostHeader,
                     magic_field='magic', magic_value=HOST_MAGIC)
    if block is None:
        return None
    host = Host(addon_name='scan_chapters', hooks=[], texts=[])
    host._block = block
    return host


def _int(host, slot, chain, default=None):
    return host.read(slot, chain, kind='int', default=default, timeout=3.0)


def scan(host):
    result = host.call('StaticDataManager::get_Instance', slot=None,
                       ret='ref', out_slot=30, via='invoke', timeout=3.0)
    if isinstance(result, str):
        print('取 StaticDataManager 失败：', result)
        return 2
    result = host.call('StaticDataManager::get_partList', slot=30,
                       ret='ref', out_slot=31, via='invoke', timeout=3.0)
    if isinstance(result, str):
        print('取 partList 失败：', result)
        return 2
    parts = host.read(31, [{'off': 0x10, 'deref': True}],
                      kind='count', default=0, timeout=3.0) or 0
    print(f'partList: {parts} 个 part')
    counts = {}
    for i in range(parts):
        part = [{'off': 0x10, 'deref': True}, {'list': i}]
        pid = _int(host, 31, part + [{'off': 0x10, 'deref': False}])
        ui_count = host.read(31, part + [{'off': 0x28, 'deref': True}],
                             kind='count', default=0, timeout=3.0) or 0
        for j in range(ui_count):
            base = part + [{'off': 0x28, 'deref': True}, {'list': j}]
            typ = _int(host, 31, base + [{'off': 0x48, 'deref': False}])
            sub = _int(host, 31, base + [{'off': 0x14, 'deref': False}])
            node = _int(host, 31, base + [{'off': 0x18, 'deref': False}])
            counts[typ] = counts.get(typ, 0) + 1
            if typ != 3:
                continue
            result = host.call('PartStaticDataList::GetStageInfoForUI',
                               slot=31, args=(node,), ret='ref',
                               out_slot=27, via='invoke', timeout=3.0)
            if isinstance(result, str) or not host.object_ptr(27):
                print(f'  part={pid} type=STAGE_NODE sub={sub} '
                      f'node={node} -> 解析失败 {result}')
                continue
            stage_id = _int(host, 27, [{'off': 0x1C, 'deref': False}])
            node_id = _int(host, 27, [{'off': 0x10, 'deref': False}])
            node_type = _int(host, 27, [{'off': 0x78, 'deref': False}])
            print(f'  part={pid} type=STAGE_NODE sub={sub} ui_node={node} '
                  f'-> nodeId={node_id} stageId={stage_id} '
                  f'stageNodeType={node_type}')
    print('类型计数：', {SUBTYPE_NAMES.get(k, k): v for k, v in counts.items()})
    return 0


def main():
    host = _attach_host()
    if host is None:
        print('打不开宿主共享内存（启动器挂钩了吗？）')
        return 2
    return scan(host)


if __name__ == '__main__':
    raise SystemExit(main())


