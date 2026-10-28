"""warp 命名空间注册：把能力按名字挂到启动器的命名空间容器上。

插件通过 ``env.ADDON_ARG['Namespaces'].space('warp')`` 取到这里导出的全部东西。
"""

from . import env
from .base import (
    ensure_exports,
    export_mapped,
    find_game_pid,
    has_gameassembly,
    inject_dll,
    log,
    names_table,
    resolve_exports,
    shm_open,
    SharedMap,
    wait_for_game,
    wait_for_gameassembly,
    GAME_DLL_NAME,
    GAME_PROCESS,
)
from .game import GACHA_TYPE_NAMES, Gacha, GachaBill, GachaWatcher, gacha
from .host import (
    ACT_KILL,
    ACT_PANEL,
    ACT_POPUP,
    CMD_KILL,
    CMD_NONE,
    CMD_POPUP,
    HF_BLOCK,
    HF_DEDUPE,
    HF_ONCE,
    HOST_ACT_EVENT,
    HOST_CMD_TEXT_LEN,
    HOST_EVENT_COUNT,
    HOST_EVENT_SIZE,
    HOST_DLL_NAME,
    HOST_ERROR_TEXT,
    HOST_EVENTS_OFFSET,
    HOST_EV_CTRL_OFFSET,
    HOST_EXPORTS_OFFSET,
    HOST_HEADER_SIZE,
    HOST_HOOK_OFFSET,
    HOST_HOOK_SIZE,
    HOST_MAP_BYTES,
    HOST_MAX_HOOKS,
    HOST_MAX_TEXTS,
    HOST_STATUS_TEXT,
    HOST_TEXTS_OFFSET,
    HOST_TEXT_SIZE,
    HOST_VAR_COUNT,
    Host,
    HostHeader,
    HostEvent,
    HostRead,
    HOST_STEP_ARRAY,
    HOST_STEP_LIST,
    HOST_STEP_NAMES,
    HOST_READ_MAX,
    HOST_READ_OFFSET,
    HOST_READ_SIZE,
    HOST_READ_BOOL,
    HOST_READ_FLOAT,
    HOST_READ_INT,
    HOST_READ_OBSCURED,
    HOST_READ_NAMES,
    HOST_READ_PTR,
    HOST_READ_STEPS,
    HostHook,
    host_alive,
)
from .service import COMMON_FIELDS, Runtime, Service

_NAMESPACES = {
    'il2cpp': {
        'resolve': resolve_exports,
        'names_table': names_table,
        'export_mapped': export_mapped,
        'version': env.WARP_HOOK_VERSION,
    },
    'inject': {
        'find_pid': find_game_pid,
        'has_gameassembly': has_gameassembly,
        'wait_for_game': wait_for_game,
        'wait_for_gameassembly': wait_for_gameassembly,
        'inject': inject_dll,
        'game_process': GAME_PROCESS,
        'game_module': GAME_DLL_NAME,
    },
    'shm': {
        'open': shm_open,
        'SharedMap': SharedMap,
        'ensure_exports': ensure_exports,
    },
    'game': {
        'gacha': gacha,
        'Gacha': Gacha,
        'GachaBill': GachaBill,
        'GachaWatcher': GachaWatcher,
        'GACHA_TYPE_NAMES': GACHA_TYPE_NAMES,
    },
    'plugin': {
        'Runtime': Runtime,
        'Service': Service,
        'host_alive': host_alive,
        'Host': Host,
        'HostHeader': HostHeader,
        'HostHook': HostHook,
        'HOST_MAX_HOOKS': HOST_MAX_HOOKS,
        'HOST_MAX_TEXTS': HOST_MAX_TEXTS,
        'HOST_DLL_NAME': HOST_DLL_NAME,
        'COMMON_FIELDS': COMMON_FIELDS,
        'ensure_exports': ensure_exports,
        'ACT_POPUP': ACT_POPUP,
        'ACT_PANEL': ACT_PANEL,
        'ACT_KILL': ACT_KILL,
        'HF_BLOCK': HF_BLOCK,
        'HF_ONCE': HF_ONCE,
        'HF_DEDUPE': HF_DEDUPE,
        'HOST_STATUS_TEXT': HOST_STATUS_TEXT,
        'HOST_MAP_BYTES': HOST_MAP_BYTES,
        'HOST_HEADER_SIZE': HOST_HEADER_SIZE,
        'HOST_HOOK_SIZE': HOST_HOOK_SIZE,
        'HOST_TEXT_SIZE': HOST_TEXT_SIZE,
        'HOST_HOOK_OFFSET': HOST_HOOK_OFFSET,
        'HOST_TEXTS_OFFSET': HOST_TEXTS_OFFSET,
        'HOST_EXPORTS_OFFSET': HOST_EXPORTS_OFFSET,
        'HOST_VAR_COUNT': HOST_VAR_COUNT,
        'HOST_CMD_TEXT_LEN': HOST_CMD_TEXT_LEN,
        'HOST_ACT_EVENT': HOST_ACT_EVENT,
        'HOST_EVENT_COUNT': HOST_EVENT_COUNT,
        'HOST_EVENT_SIZE': HOST_EVENT_SIZE,
        'HostEvent': HostEvent,
        'HostRead': HostRead,
        'HOST_STEP_PLAIN': 0,
        'HOST_STEP_DEREF': 1,
        'HOST_STEP_LIST': HOST_STEP_LIST,
        'HOST_STEP_ARRAY': HOST_STEP_ARRAY,
        'HOST_STEP_NAMES': HOST_STEP_NAMES,
        'HOST_READ_MAX': HOST_READ_MAX,
        'HOST_READ_SIZE': HOST_READ_SIZE,
        'HOST_READ_OFFSET': HOST_READ_OFFSET,
        'HOST_EV_CTRL_OFFSET': HOST_EV_CTRL_OFFSET,
        'HOST_EVENTS_OFFSET': HOST_EVENTS_OFFSET,
        'HOST_READ_INT': HOST_READ_INT,
        'HOST_READ_FLOAT': HOST_READ_FLOAT,
        'HOST_READ_BOOL': HOST_READ_BOOL,
        'HOST_READ_PTR': HOST_READ_PTR,
        'HOST_READ_OBSCURED': HOST_READ_OBSCURED,
        'HOST_READ_NAMES': HOST_READ_NAMES,
        'HOST_READ_STEPS': HOST_READ_STEPS,
        'CMD_NONE': CMD_NONE,
        'CMD_POPUP': CMD_POPUP,
        'CMD_KILL': CMD_KILL,
    },
    'log': {
        'write': log,
    },
}


def register():
    """把上面的子分区挂到一个顶级 space ``warp`` 下，返回是否成功。

    注册结果（``env.ADDON_ARG['Namespaces'].spaces()``）：::

        warp            顶级 space，提供方是本插件
        warp.il2cpp     导出名解析
        warp.inject     找进程 / 等引擎 / 远程线程注入
        warp.shm        共享内存
        warp.plugin     共享宿主（Runtime / Host）
        warp.log        日志

    子分区既可以从根上扁平取（``NS['warp.il2cpp']``），也可以从 warp 里
    嵌套取（``NS['warp'].il2cpp``）。根上只出现 ``warp`` 一个名字，
    别的插件可以放心注册自己的 ``il2cpp`` 之类而不会互相覆盖。
    """
    registry = env.ADDON_ARG.get('Namespaces')     # type: ignore[name-defined]
    if registry is None:
        log("当前启动器没有插件命名空间容器（env.ADDON_ARG 里没有 'Namespaces'）。"
            "本插件不生效；请更新启动器，或让依赖它的插件给出明确提示。")
        return False

    warp = registry.provide(
        'warp',
        name=env.ADDON_NAME,
        version=env.WARP_HOOK_VERSION,
        description='插件底层能力：il2cpp 导出 / 注入 / 共享内存 / 共享宿主 / 日志',
    )
    for space, items in _NAMESPACES.items():
        sub = registry.provide(f'warp.{space}', **items)
        warp.expose(space, sub)

    names = ', '.join(registry.spaces())



def on_unload():
    """插件卸载：停掉所有插件的后台流程与抽卡循环，关掉共享内存映射。"""
    try:
        gacha.stop_all()
    except Exception:  # noqa: BLE001
        pass
    try:
        Service.stop_all()
    except Exception:  # noqa: BLE001
        pass
    from .base import _maps
    for block in list(_maps.values()):
        try:
            block.close()
        except Exception:
            pass
    _maps.clear()
