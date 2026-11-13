"""把友方单位身上的烧伤/燃烧 buff 层数和回合改成 1。"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'addons/WarpHook'))

from warphook.base import shm_open  # noqa: E402
from warphook.host import (Host, HostHeader, HOST_MAP_BYTES,  # noqa: E402
                           HOST_MAP_DEFAULT, HOST_MAGIC)


def _string(host, slot):
    n = host.call('System.String::get_Length', slot=slot, ret='int32',
                  via='invoke', timeout=3)
    if isinstance(n, str):
        return None
    out = []
    for i in range(min(int(n), 80)):
        c = host.call('System.String::get_Chars', slot=slot, args=(i,),
                      ret='int32', via='invoke', timeout=3)
        if isinstance(c, str):
            return None
        out.append(chr(int(c) & 0xFFFF))
    return ''.join(out)


def _buff_info(host, unit_slot, index, out_slot):
    result = host.call('BattleUnitModel::GetBuffAll', slot=unit_slot,
                       args=(38,), ret='ref', out_slot=out_slot,
                       via='invoke', timeout=3)
    if isinstance(result, str) or not host.object_ptr(out_slot):
        return None
    host.put_slot(out_slot - 1, 0)
    host.list_item(out_slot, index, out_slot - 1, timeout=3)
    return host.object_ptr(out_slot - 1)


def main():
    block = shm_open(HOST_MAP_DEFAULT, HOST_MAP_BYTES, HostHeader,
                     magic_field='magic', magic_value=HOST_MAGIC)
    if block is None:
        print('打不开宿主共享内存（启动器挂钩了吗？）')
        return 2
    host = Host(addon_name='clear_burn_buff', hooks=[], texts=[])
    host._block = block
    host.call('BattleObjectManager::get_Instance', slot=None, ret='ref',
              out_slot=28, via='invoke', timeout=3)
    if not host.object_ptr(28):
        print('BattleObjectManager 未就绪')
        return 2

    changed = 0
    result = host.call('BattleObjectManager::GetModelList', slot=28,
                       args=(0, False), ret='ref', out_slot=24,
                       via='invoke', timeout=3)
    if isinstance(result, str) or not host.object_ptr(24):
        print('友方列表读取失败：', result)
        return 2
    models = host.read(24, [], kind='count', default=0, timeout=3) or 0
    for mi in range(models):
        host.put_slot(23, 0)
        host.list_item(24, mi, 23, timeout=3)
        iid = host.call('BattleUnitModel::get_InstanceID', slot=23,
                        ret='int32', via='invoke', timeout=3)
        r = host.call('BattleUnitModel::GetBuffAll', slot=23, args=(38,),
                      ret='ref', out_slot=22, via='invoke', timeout=3)
        if isinstance(r, str) or not host.object_ptr(22):
            continue
        bufs = host.read(22, [], kind='count', default=0, timeout=3) or 0
        for bi in range(bufs):
            host.put_slot(21, 0)
            host.list_item(22, bi, 21, timeout=3)
            r = host.call('BuffInfo::GetName', slot=21, ret='ref',
                          out_slot=20, via='invoke', timeout=3)
            name = _string(host, 20) if not isinstance(r, str) else None
            if not name:
                continue
            low = name.lower()
            if not any(x in low for x in
                       ('burn', 'combust', '烧伤', '燃烧')):
                continue
            stack = host.call('BuffInfo::GetStack', slot=21, ret='int32',
                              via='invoke', timeout=3)
            turn = host.call('BuffInfo::GetTurn', slot=21, ret='int32',
                             via='invoke', timeout=3)
            keyword = host.call('BuffInfo::GetKeyword', slot=21,
                                ret='int32', via='invoke', timeout=3)
            if (isinstance(stack, str) or isinstance(turn, str) or
                    isinstance(keyword, str)):
                continue
            # BuffInfo 只是 UI 快照；真正改 BuffModel 要调用模型方法。
            host.call('BattleUnitModel::LoseBuffAllStack', slot=23,
                      args=(int(keyword), 1), ret='void',
                      via='invoke', timeout=3)
            host.call('BattleUnitModel::ForceToDestroyBuff', slot=23,
                      args=(int(keyword), 0, 1), ret='void',
                      via='invoke', timeout=3)
            changed += 1
            print('clear ally', iid, name, f'{stack}/{turn} -> removed')
    print('changed', changed)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
