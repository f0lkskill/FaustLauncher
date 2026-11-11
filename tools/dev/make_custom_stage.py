"""克隆一个关卡并用新 id 追加到关卡表，同时在章节表顶部加一个入口。

前置：游戏运行、WarpHook 已注入、静态数据已加载（打开过章节选择/关卡列表）。

    python tools/dev/make_custom_stage.py
    python tools/dev/make_custom_stage.py --source 10557 --new-id 990001 \
        --enemy 1100 --level 45 --sync 1 --count 1

默认从 Walpu3 的 STAGE_NODE 入口克隆：
    source node 910803 -> 新节点 910804
    source stage 10557 -> 新 stage 990001
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
    host = Host(addon_name='make_custom_stage', hooks=[], texts=[])
    host._block = block
    return host


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=int, default=10557,
                        help='素材关卡 id（默认 Walpu3）')
    parser.add_argument('--new-id', type=int, default=990001,
                        help='新关卡 id')
    parser.add_argument('--replace', action='store_true',
                        help='用 new-id 替换已存在的关卡，而不是追加新 id')
    parser.add_argument('--no-guard', action='store_true',
                        help='不安装服务器 stageid 改写 hook')
    parser.add_argument('--enemy', type=int, action='append', default=None,
                        help='敌人/异想体 id，可重复传入')
    parser.add_argument('--level', type=int, default=45)
    parser.add_argument('--sync', type=int, default=1,
                        help='unitSyncLevel，1 表示人格同步等级/技能强度')
    parser.add_argument('--count', type=int, default=1)
    parser.add_argument('--ui-source-node', type=int, default=910803,
                        help='素材章节 UI 节点 id（Walpu3）')
    parser.add_argument('--new-node', type=int, default=910804,
                        help='新章节 UI 节点 id')
    parser.add_argument('--source-subchapter', type=int, default=9108,
                        help='素材章节 subchapter id')
    parser.add_argument('--new-subchapter', type=int, default=9910,
                        help='新 subchapter id')
    parser.add_argument('--no-ui', action='store_true',
                        help='只追加关卡表，不添加章节 UI 入口')
    parser.add_argument('--no-scripts', action='store_true',
                        help='保留原关卡脚本/异想体事件')
    args = parser.parse_args()

    host = _attach_host()
    if host is None:
        print('打不开宿主共享内存（启动器挂钩了吗？）')
        return 2
    lv = live.Live(owner='make_custom_stage', host=host, auto=False)
    add = lv.stage_add(
        args.source, args.new_id,
        enemy_ids=args.enemy or [1100],
        level=args.level, sync_level=args.sync, count=args.count,
        stage_level=args.level, recommended_level=args.level,
        strip_story=False, clear_scripts=not args.no_scripts,
        replace=args.replace, timeout=5.0)
    print('stage_add:', add)
    if not add.get('ok'):
        return 2
    ui = None
    if not args.no_ui:
        ui = lv.chapter_add_top(args.ui_source_node, args.new_node,
                                args.new_id, new_subchapter_id=args.new_subchapter, timeout=5.0)
        print('chapter_add_top:', ui)
        if not ui.get('ok'):
            return 2
    if args.no_guard:
        guard = {'ok': True, 'skipped': True}
    else:
        guard_source_stage = args.new_id if args.replace else args.source
        guard = lv.custom_stage_server_guard(
            args.new_id, guard_source_stage,
            custom_node_id=(ui or {}).get('node_id'),
            source_node_id=args.ui_source_node,
            custom_subchapter_id=(ui or {}).get('target_subchapter_id'),
            source_subchapter_id=args.source_subchapter)
    print('custom_stage_server_guard:', guard)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())



