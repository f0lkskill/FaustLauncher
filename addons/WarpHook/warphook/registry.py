"""warp 命名空间注册：把能力按名字挂到启动器的命名空间容器上。

插件通过 ``env.ADDON_ARG['Namespaces'].space('warp')`` 取到这里导出的全部东西。
"""

from . import env, fields, objects
from . import audio
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
from . import live
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
    HOST_EVENT_SLOTS,
    HOST_DLL_NAME,
    HOST_ERROR_TEXT,
    HOST_EVENTS_OFFSET,
    HOST_EV_CTRL_OFFSET,
    HOST_EXPORTS_OFFSET,
    HOST_HEADER_SIZE,
    HOST_HOOK_OFFSET,
    HOST_HOOK_SIZE,
    HOST_HOOKS_PRIMARY,
    HOST_READS_PRIMARY,
    HOST_TEXTS_PRIMARY,
    HOST_MAP_BYTES,
    HOST_CMD_BUF_COUNT,
    HOST_CMD_BUF_OFFSET,
    HOST_CMD_BUF_SIZE,
    HOST_REWRITE_COUNT,
    HOST_REWRITE_OFFSET,
    HOST_REWRITE_SIZE,
    HOST_OBJECT_COUNT,
    HOST_OBJECT_SIZE,
    HOST_OBJECTS_OFFSET,
    HOST_OBJ_ARG_BASE,
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
        # ---- 门面：插件只用这几行，不用认识类名/偏移/对象槽 ----
        'Live': live.Live,
        'Battle': live.Battle,
        'live': live.live,
        'start': live.start,
        'status': live.status,
        'describe': live.describe,
        'popup': live.popup,
        'scene': live.scene,
        'battle': live.battle,
        'units': live.units,
        'count': live.count,
        'unit': live.unit,
        'player': live.player,
        'on_round_start': live.on_round_start,
        'on_scene_changed': live.on_scene_changed,
        'on_battle_start': live.on_battle_start,
        'on_battle_end': live.on_battle_end,
        'close': live.close,
        'SCENES': live.SCENES,
        # ---- 声音（0.9.10）：game.bgm('Battle_Cp9_Boss_10') ----
        'bgm': live.bgm,
        'bgm_stop': live.bgm_stop,
        'bgm_playing': live.bgm_playing,
        'bgm_index': live.bgm_index,
        'bgm_hook': live.bgm_hook,
        'bgm_unhook': live.bgm_unhook,
    },
    # 声音的底层原语：想自己拼序列时用（play/stop/is_playing/current_index）
    'audio': {
        'play': audio.play,
        'stop': audio.stop,
        'pause': audio.pause,
        'is_playing': audio.is_playing,
        'current_index': audio.current_index,
        'full_path': audio.full_path,
        'short_name': audio.short_name,
        'BGM_PREFIX': audio.BGM_PREFIX,
        'STOP_MODE_IMMEDIATE': audio.STOP_MODE_IMMEDIATE,
        'STOP_MODE_FADE': audio.STOP_MODE_FADE,
        'SLOT_SCRATCH': audio.SLOT_SCRATCH,
        'SLOT_BATTLE_BGM': audio.SLOT_BATTLE_BGM,
        'hook_battle_bgm': audio.hook_battle_bgm,
        'unhook_battle_bgm': audio.unhook_battle_bgm,
    },
    # 对象/字段的门面（Unit / Buff / Access）单独一个子分区，和 game 分开取
    'object': {
        'Unit': objects.Unit,
        'Buff': objects.Buff,
        'Access': objects.Access,
        'access': objects.access,
        'units': objects.units,
        'unit': objects.unit,
        'count': objects.count,
        'snapshot': objects.snapshot,
        'scene': objects.scene,
        'scene_full': objects.scene_full,
        'scene_name': objects.scene_name,
        'scan_class': objects.scan_class,
        'scan_object': objects.scan_object,
        'bind_manager': objects.bind_manager,
        'bind_scene': objects.bind_scene,
        'SCENES': objects.SCENES,
        'SLOT_MANAGER': objects.SLOT_MANAGER,
        'SLOT_SCENE': objects.SLOT_SCENE,
        'SLOT_SCRATCH': objects.SLOT_SCRATCH,
    },
    # 字段表：查偏移、看某条链是怎么拼的
    'field': {
        'field': fields.field,
        'has': fields.has,
        'kind_of': fields.kind_of,
        'read_chain': fields.read_chain,
        'unit_path': fields.unit_path,
        'units_chain': fields.units_chain,
        'units_iter': fields.units_iter,
        'verified_names': fields.verified_names,
        'unverified_names': fields.unverified_names,
        'FIELD_TABLE': fields.FIELD_TABLE,
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
        'HOST_CMD_BUF_OFFSET': HOST_CMD_BUF_OFFSET,
        'HOST_CMD_BUF_SIZE': HOST_CMD_BUF_SIZE,
        'HOST_CMD_BUF_COUNT': HOST_CMD_BUF_COUNT,
        'HOST_REWRITE_OFFSET': HOST_REWRITE_OFFSET,
        'HOST_REWRITE_SIZE': HOST_REWRITE_SIZE,
        'HOST_REWRITE_COUNT': HOST_REWRITE_COUNT,
        'HOST_OBJECT_COUNT': HOST_OBJECT_COUNT,
        'HOST_OBJECT_SIZE': HOST_OBJECT_SIZE,
        'HOST_OBJECTS_OFFSET': HOST_OBJECTS_OFFSET,
        'HOST_OBJ_ARG_BASE': HOST_OBJ_ARG_BASE,
        'HOST_HEADER_SIZE': HOST_HEADER_SIZE,
        'HOST_HOOK_SIZE': HOST_HOOK_SIZE,
        'HOST_TEXT_SIZE': HOST_TEXT_SIZE,
        'HOST_HOOK_OFFSET': HOST_HOOK_OFFSET,
        'HOST_TEXTS_OFFSET': HOST_TEXTS_OFFSET,
        'HOST_HOOKS_PRIMARY': HOST_HOOKS_PRIMARY,
        'HOST_READS_PRIMARY': HOST_READS_PRIMARY,
        'HOST_TEXTS_PRIMARY': HOST_TEXTS_PRIMARY,
        'HOST_EXPORTS_OFFSET': HOST_EXPORTS_OFFSET,
        'HOST_VAR_COUNT': HOST_VAR_COUNT,
        'HOST_CMD_TEXT_LEN': HOST_CMD_TEXT_LEN,
        'HOST_ACT_EVENT': HOST_ACT_EVENT,
        'HOST_EVENT_COUNT': HOST_EVENT_COUNT,
        'HOST_EVENT_SIZE': HOST_EVENT_SIZE,
        'HOST_EVENT_SLOTS': HOST_EVENT_SLOTS,
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
        warp.game       门面：popup / bgm / units / scene / on_round_start（新手用这个）
        warp.object     对象门面：Unit / Buff / Access（要更细的时候用）
        warp.field      字段表：查偏移、看读链怎么拼
        warp.audio      声音原语：play / stop / is_playing（自己拼序列时用）
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
    """插件卸载：停掉所有插件的后台流程、门面实例与抽卡循环，关掉共享内存映射。"""
    try:
        live.close_all()
    except Exception:  # noqa: BLE001
        pass
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
