# -*- coding: utf-8 -*-
"""单位观察：钩住「单位被创建」这一瞬间。

钩子是 WarpHook 的第一类原语：**游戏调到某个方法时，让你插一脚**。
这一篇只做最轻的一种——不拦、不改，只在旁边看着并记录。

选的靶子是 ``BattleUnitModel.OnCreateUnitModel``：每进一次战斗，
游戏会给场上每个单位各调一次。频率低、不会被内联、而且 ``self`` 就是这个单位本身，
非常适合第一次练习。
"""

import time
from typing import cast

if False:  # 仅供类型检查器阅读
    from warphook.base import WarpNamespace

ADDON_ARG = globals().get('ADDON_ARG') or {}
ADDON_NAME = ADDON_ARG.get('AddonName')
ADDON_MANAGER = ADDON_ARG.get('AddonManager')
_NS = ADDON_ARG.get('Namespaces')
_W = cast("WarpNamespace", _NS.space('warp') if _NS is not None else None)

# 我们自己要用的对象槽。0..23 是成就插件的主段，24..31 是辅助段，
# 插件应该从 27 起往高用，避免跟别人撞车。
SLOT_UNIT = 27

# BattleUnitModel 里两个字段的偏移（第 05 篇会讲这些数从哪来）
OFF_INSTANCE_ID = 0x60

_count = 0


def _log(message):
    print(f'[{ADDON_NAME}] {message}', flush=True)


def _settings():
    try:
        info = (ADDON_MANAGER.get_addon_info(ADDON_NAME)
                if ADDON_MANAGER is not None else None) or {}
    except Exception:  # noqa: BLE001
        info = {}
    st = info.get('settings') or {}
    return bool(st.get('报编号', True))


def _hook_spec():
    """钩子的声明。一个钩子就是一条 dict，字段跟 Host.hook() 的参数一一对应。"""
    return [
        {
            'klass': 'BattleUnitModel',
            'method': 'OnCreateUnitModel',
            'argc': 0,          # 这个方法除了 self 没有参数
            'actions': 0,       # 0 = 什么都不做，只是让我们知道它被调了
            'cache': (0, SLOT_UNIT),   # 命中时把 self 的指针存进对象槽 27
        },
    ]


def _push():
    host = service.host()
    host.configure(hooks=_hook_spec(), texts=[])
    return host.push(True) not in ('共享内存不可用',)


def _on_create_unit(host):
    """每次有单位被创建时被调一次（跑在 Service 的派发循环里）。"""
    global _count
    _count += 1

    ptr = host.object_ptr(SLOT_UNIT)
    if not ptr:
        _log(f'第 {_count} 个单位：槽 {SLOT_UNIT} 是空的（指针没存进来）')
        return

    if not _settings():
        return

    # 从对象槽出发读一个 int 字段：偏移 0x60，读到就停（deref=False 表示
    # 「这个字段本身就是值」，而不是指向别的对象）。
    instance_id = host.read(SLOT_UNIT, [{'off': OFF_INSTANCE_ID, 'deref': False}],
                            kind='int', default=None)
    _log(f'第 {_count} 个单位：指针 0x{ptr:X}，编号 {instance_id}')


service = _W.plugin.Service(
    addon_name=ADDON_NAME,
    name=ADDON_NAME,
    sync=_push,
    auto=lambda: True,
    menu=(
        ('立刻重新挂一次', lambda: service.sync()),
        ('看看宿主状态', lambda: _log(service.describe(service.status()))),
    ),
)
# 钩子命中时调 _on_create_unit —— method 要和上面 _hook_spec() 里的名字一致。
service.on_hit(_on_create_unit, method='OnCreateUnitModel')
service.start()


def on_unload():
    return service.stop()
