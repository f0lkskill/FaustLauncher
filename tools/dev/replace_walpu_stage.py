"""只替换 Walpu3 原关卡数据，不改 UI/节点/subchapter。

日志已经证明：节点 910803 只认自己的原关卡 10557。换成 10550 会被
`StageNodeBannerUIData.OnClickBanner` 直接拒绝（日志 `stage id [10550]`）。

这个工具用于验证“原入口 + 原关卡 id + 自定义战斗数据”是否能让服务器
完整处理进入和退出。

    python tools/dev/replace_walpu_stage.py
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
    host = Host(addon_name='replace_walpu', hooks=[], texts=[])
    host._block = block
    lv = live.Live(owner='replace_walpu', host=host, auto=False)
    result = lv.stage_add(
        10557, 10557, enemy_ids=[1100], level=45, sync_level=1, count=1,
        stage_level=45, recommended_level=45, strip_story=True,
        clear_scripts=True, replace=True, timeout=5.0)
    print('replace Walpu3:', result)
    return 0 if result.get('ok') else 2


if __name__ == '__main__':
    raise SystemExit(main())
