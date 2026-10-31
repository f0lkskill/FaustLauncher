"""warp.plugin.Host：一块共享映射的配置端。

插件用它登记「哪个类的哪个方法要被钩住」以及「钩住之后可能说什么」，
全部写进 warp_host.dll 认得的那块内存；DLL 侧只负责按表装配。
"""

import ctypes
import struct
import threading
import os, sys, time

from . import env
from .base import (
    SharedMap,
    read_chain,
    _valid_snapshot,
    ensure_exports,
    export_mapped,
    find_game_pid,
    has_gameassembly,
    inject_dll,
    log,
    names_table,
    resolve_exports,
    shm_open,
    wait_for_game,
    wait_for_gameassembly,
    _tick32,
    GAME_PROCESS,
    GAME_DLL_NAME,
    WAIT_GAME_TIMEOUT,
    WAIT_DLL_TIMEOUT,
    FILE_MAP_ALL_ACCESS,
)

HOST_MAGIC = 0x54534857           # "WHST"
HOST_VERSION = 10                 # v9：命令的 out 参数缓冲（CALL 能拿回值类型）
                                  # （v8：钩子参数改写；v7：代读读链；v6：字典容器步）
# v5：尾部追加 buff 关注哈希表段（BUF 行）。
# v4：钩子表 16→32（成就 25 条 + NoGacha 2 条装不下 16 槽）
HOST_MAP_DEFAULT = "Local\\WarpHost_Default"
HOST_MAP_ENV = "WARP_HOST_MAP"
HOST_DLL_NAME = "warp_host.dll"

HOST_MAX_HOOKS = 32
HOST_MAX_TEXTS = 256
HOST_TEXT_LEN = 128
HOST_KLASS_LEN = 48
HOST_METHOD_LEN = 48
HOST_LOG_LEN = 48
HOST_EXPORT_COUNT = 22
HOST_NAME_MAX = 64
HOST_VAR_COUNT = 8
HOST_CMD_TEXT_LEN = 256

# 命令类型：py 一行调用 → 游戏主线程执行
CMD_NONE = 0
CMD_POPUP = 1     # 弹原版系统弹窗
CMD_KILL = 2      # 结束游戏进程
CMD_MAKE = 3      # 构造对象（object_new + .ctor）→ 对象槽
CMD_CALL = 4      # 调方法（runtime_invoke），槽内对象当 this（无槽 = 静态）
CMD_STR = 5       # 造 il2cpp 字符串 → 对象槽
CMD_RELEASE = 6   # 解掉槽上 GC 句柄并清槽
CMD_READ = 7      # 代读：按 HOST_CMD_READ_OFFSET 处那条链读对象槽，结果 vars[6]/[7]

# CALL 的返回值形状（retkind 打进 cmd_type 12-15 位）
CMD_RET_INT32 = 0   # box 返回，真值在 +0x10，位模式写回 vars[6]
CMD_RET_FLOAT = 1   # box 返回 float，位模式写回 vars[6]
CMD_RET_REF = 2     # 引用返回，落 vars[7] 指定的槽（挂 GC 句柄）
CMD_RET_NAMES = {"int32": CMD_RET_INT32, "int": CMD_RET_INT32,
                 "float": CMD_RET_FLOAT, "ref": CMD_RET_REF,
                 "ptr": CMD_RET_REF}

# 命令执行结果码（DLL 写 cmd_result）
CMD_RES_BUSY = -2  # 与 C 侧 WARP_CMD_RES_BUSY 一致：已取走、还在执行

CMD_RES_NAMES = {
    0: "已执行",
    1: "失败",
    2: "未知命令",
    3: "方法抛了异常",
    4: "类没找到",
    5: "方法没找到",
    6: "对象槽越界",
    7: "参数太多（vars 最多 6 个）",
}

HOST_HEADER_SIZE = 432   # 160 状态头 + 命令槽（4 个 int + 256 字节文本）
HOST_HOOK_OFFSET = HOST_HEADER_SIZE
#: 一条读取链最多走几跳（v7：4 → 8，容器遍历 + 深字段不再顶格）。
HOST_READ_STEPS = 8
# 读取链每一步的动作。deref 位存的既是「要不要解引用」也是「做什么」：
# 0 加偏移 / 1 解引用 / 2 List 取下标 / 3 Array 取下标 /
# 4 List 取下标（值类型，元素 4B）/ 5 Array 取下标（值类型，元素 4B）/
# 6 Dictionary 取活跃 entry 的 value（引用）/ 7 同 6，value 是 4B 值类型
HOST_STEP_PLAIN = 0
HOST_STEP_DEREF = 1
HOST_STEP_LIST = 2
HOST_STEP_ARRAY = 3
HOST_STEP_LIST_VAL = 4     # List<int> 这类值类型容器：元素是值不是指针
HOST_STEP_ARRAY_VAL = 5
HOST_STEP_DICT_VALUE = 6     # Dictionary<K,V>：跳过 Remove 空坑取第 k 个活跃 V
HOST_STEP_DICT_VALUE32 = 7   # V 是 int 值类型（int→int 字典）：读出来是值
HOST_STEP_NAMES = {
    "plain": HOST_STEP_PLAIN,
    "deref": HOST_STEP_DEREF,
    "list": HOST_STEP_LIST,
    "array": HOST_STEP_ARRAY,
    "list_val": HOST_STEP_LIST_VAL,
    "array_val": HOST_STEP_ARRAY_VAL,
    "dict": HOST_STEP_DICT_VALUE,
    "dict_val": HOST_STEP_DICT_VALUE32,
}       # 落点是 ObscuredInt（混淆 int），值 = hidden ^ key
# Dictionary 步的配置（写在步 dict 里，与 'list': i 并列）：
#   'dict': k 或 'dict_val': k —— k 是要取的活跃 entry 下标；写 'iter'
#   （或配 iter=True）表示遍历链：一次命中对每个活跃 value 各发一个事件。
#   步里还可以带 'value_off' / 'stride'：entry 内 value 字段偏移（默认 16）
#   和 entry 尺寸（默认 24），从 dump.cs 的 TKey/TValue 形状算出来 ——
#   int→引用 / 引用→引用 是 24/16，int→int 是 16/12，引用→引用且 key 在前
#   则 value_off 要自己数。C 侧没有类型信息，这两个数只能配置方给。
# 落盘时可以写数字，也可以写名字（插件侧更愿意写 'obscured' 而不是 4）
HOST_READ_INT = 0
HOST_READ_FLOAT = 1
HOST_READ_BOOL = 2
HOST_READ_PTR = 3
HOST_READ_OBSCURED = 4
HOST_READ_SUM = 5          # 落点是 List<int>：求和（值类型元素）
HOST_READ_COUNT = 6        # 落点是容器：只取元素个数
HOST_READ_TEXT = 7         # 落点是 il2cpp 字符串：取开头的数字（"86" → 86）
HOST_READ_BUFF_MASK = 8    # 落点是战斗单位：遍历 buff 链按关注表置位（BUF 行 m=）
HOST_READ_COUNT_DICT = 9   # 落点是 Dictionary：活跃 entry 数 = count-freeCount
                           # （注意 List/Array 的 count kind=6 读 +0x18，
                           #  字典活跃数读 +0x20 与 +0x28，两个 kind 别混用；
                           #  il2cpp 字段序是 count/freeList/freeCount/version，
                           #  +0x2C 是 version 不是 freeCount）
HOST_READ_NAMES = {
    'int': HOST_READ_INT,
    'float': HOST_READ_FLOAT,
    'bool': HOST_READ_BOOL,
    'ptr': HOST_READ_PTR,
    'obscured': HOST_READ_OBSCURED,
    'sum': HOST_READ_SUM,
    'count': HOST_READ_COUNT,
    'text': HOST_READ_TEXT,
    'buff_mask': HOST_READ_BUFF_MASK,
    'dict_count': HOST_READ_COUNT_DICT,
}
# 返回值类型：thunk 调完原函数后按什么形状取返回值（int 在 RAX、float 在 XMM0）
HOST_RET_VOID = 0
HOST_RET_INT32 = 1
HOST_RET_FLOAT = 2
HOST_RET_NAMES = {
    "void": HOST_RET_VOID,
    "int32": HOST_RET_INT32,
    "int": HOST_RET_INT32,
    "float": HOST_RET_FLOAT,
}
# 事件时机：PRE=原函数调用前发（老默认），POST=调用后发（要读「调用之后才有」
# 的字段，或者带返回值时自动转 POST）
HOST_WHEN_PRE = 0
HOST_WHEN_POST = 1
#: 全进程共用的读取链条数。
HOST_READ_MAX = 128
#: 全进程共用的读取链条数。
HOST_READ_MAX = 128
HOST_READ_SIZE = 80


HOST_HOOK_SIZE = 288
HOST_TEXTS_OFFSET = HOST_HOOK_OFFSET + HOST_MAX_HOOKS * HOST_HOOK_SIZE
HOST_TEXT_SIZE = HOST_TEXT_LEN
HOST_EXPORTS_OFFSET = HOST_TEXTS_OFFSET + HOST_MAX_TEXTS * HOST_TEXT_SIZE
HOST_EV_CTRL_OFFSET = HOST_EXPORTS_OFFSET + HOST_EXPORT_COUNT * HOST_NAME_MAX
HOST_EV_CTRL_SIZE = 16
HOST_EVENTS_OFFSET = HOST_EV_CTRL_OFFSET + HOST_EV_CTRL_SIZE
HOST_EVENT_COUNT = 2048
HOST_EVENT_SIZE = 60
HOST_EVENT_SLOTS = 12   # 读链的 out 能写到 0..11
HOST_READ_OFFSET = HOST_EVENTS_OFFSET + HOST_EVENT_COUNT * HOST_EVENT_SIZE
HOST_OBJECT_COUNT = 32      # 对象槽个数（与 C 侧 WARP_OBJECT_COUNT 一致）
HOST_OBJECT_SIZE = 8        # 一个 void*
HOST_OBJECTS_OFFSET = HOST_READ_OFFSET + HOST_READ_MAX * HOST_READ_SIZE
HOST_OBJ_ARG_BASE = 0x100   # 读取链的 arg 写 0x100+n = 从第 n 个对象槽出发
# buff 关注哈希表（v5）：成就规则里的 buff 名 fnv1a64 之后写在这，0 是哨兵。
# C 侧 buff_mask 读法按表置位 —— BUF 行的 m= 掩码就从这来（与 battle_watch
# 的 watched_buff_names() 名单顺序一一对应）。
HOST_BUFF_WATCH_COUNT = 32
HOST_BUFF_WATCH_SIZE = 8    # fnv1a64
HOST_BUFF_WATCH_OFFSET = HOST_OBJECTS_OFFSET + HOST_OBJECT_COUNT * HOST_OBJECT_SIZE
# v7：命令通道的「代读」读链（一条 WARP_READ，MAP 尾部追加）。
HOST_CMD_READ_OFFSET = HOST_BUFF_WATCH_OFFSET + HOST_BUFF_WATCH_COUNT * HOST_BUFF_WATCH_SIZE
# v8：钩子参数改写。每条钩子一对 (arg, slot)：命中时把第 arg 个参数换成
# 对象槽 slot 里的指针（通常是 make_str 放进去的 il2cpp String）。同在
# MAP 尾部追加，前面所有偏移不动；arg=0 或 slot<0 表示不改写。
HOST_REWRITE_COUNT = HOST_MAX_HOOKS
HOST_REWRITE_SIZE = 8
HOST_REWRITE_OFFSET = HOST_CMD_READ_OFFSET + HOST_READ_SIZE
# v9：命令的 out 参数缓冲。有些游戏方法要一个可写的值类型落点
# （``SoundManager.TryCreateInstance(string, out EventInstance)``），il2cpp 的
# runtime_invoke 要求参数直接指向那块内存。共享内存在游戏进程里就是可读写的，
# 把 MAP 尾部缓冲的地址当参数传进去：游戏写、Python 读同一块。
HOST_CMD_BUF_COUNT = 4
HOST_CMD_BUF_SIZE = 64
HOST_CMD_BUF_OFFSET = HOST_REWRITE_OFFSET + HOST_REWRITE_COUNT * HOST_REWRITE_SIZE
HOST_MAP_BYTES = HOST_CMD_BUF_OFFSET + HOST_CMD_BUF_COUNT * HOST_CMD_BUF_SIZE

# ---- 多作者分段（v0.9.2）------------------------------------------------
# 成就观测跑在独立子进程，它有自己的一份 Host；NoGacha 等插件在启动器主进程
# 也有一份。两个进程写的是同一块共享内存——v0.9.1 及之前 _write_config 每次都
# 把整张表清空重写，谁后 push 谁说了算：成就 push 完 25 条，NoGacha 一 push，
# 表里就只剩 NoGacha 的 2 条，C 只装 2 条，「成就钩子全死」（v0.9.1 真机实锤）。
# 现在改成按 owner 名分段、各写各的段，互不覆盖：
HOST_PRIMARY_MARKS = ('成就', 'achievement')   # owner 名含这些 → 主段作者
HOST_HOOKS_PRIMARY = 27    # 钩子槽：主段 0..26 / 辅段 27..31（成就 25 条 + 余量）
HOST_READS_PRIMARY = 96    # 读链条目：主段 0..95 / 辅段 96..127
HOST_TEXTS_PRIMARY = 192   # 文案段：主段 0..191 / 辅段 192..255


def _is_primary_owner(owner):
    """主段作者判定 —— 必须是纯名字运算：子进程和主进程对同一个
    owner 名要算出同一个答案，不能依赖任何运行时状态。"""
    name = str(owner).lower()
    return any(m in name for m in HOST_PRIMARY_MARKS)


#: 钩子动作位：把这次命中装进事件队列（见 :meth:`Host.events`）。
HOST_ACT_EVENT = 0x08


class HostEvent(ctypes.Structure):
    """环形队列里的一个事件。字段含义与 C 侧 ``WARP_EVENT`` 一一对应。"""

    _fields_ = [
        ("id", ctypes.c_int32),      # 事件号（钩子没填就用钩子下标）
        ("hook", ctypes.c_int32),    # 哪个钩子产生的
        ("tick", ctypes.c_int32),    # GetTickCount 低 32 位
        ("a", ctypes.c_int32),       # 第 1 个参数
        ("b", ctypes.c_int32),       # 第 2 个参数
        ("c", ctypes.c_int32),       # 第 3 个参数
        ("d", ctypes.c_int32),       # vars[0] 快照
        ("e", ctypes.c_int32),       # 第 5 格（读链 out=4）
        ("f", ctypes.c_int32),       # 第 6 格（读链 out=5）
        ("g", ctypes.c_int32),       # 第 7 格（读链 out=6）
        ("h", ctypes.c_int32),       # 第 8 格（读链 out=7）
        ("i", ctypes.c_int32),       # 第 9 格（读链 out=8）
        ("j", ctypes.c_int32),       # 第 10 格（读链 out=9）
        ("k", ctypes.c_int32),       # 第 11 格（读链 out=10）
        ("l", ctypes.c_int32),       # 第 12 格（读链 out=11）
    ]

# 动作位（与 warp_host.c 的 WARP_ACT_* 一致）
ACT_POPUP = 0x01     # 弹游戏原版系统弹窗
ACT_PANEL = 0x02     # 弹自建面板（宿主内置，后续版本）
ACT_KILL = 0x04      # 结束游戏进程

# 钩子标志（与 WARP_HF_* 一致）
HF_BLOCK = 0x01      # 跳过原方法（用于「拦截」类插件）
HF_ONCE = 0x02       # 只触发一次
HF_DEDUPE = 0x04     # 读链的值没变就不投递事件（配了 reads 才有意义）

# Host.call 的白名单：只有这些 runtime_invoke 调用在真机上验证过稳定。
# 0.9.10~0.9.14 的五次真机崩溃里，前面几次的锅是 invoke 进的游戏方法
# 本身，最后一次（0.9.15 查到的那条栈）却是对象槽里 il2cpp_gchandle_free
# —— 跟方法无关。句柄拆掉之后 get_Instance 连调 10 次全稳，换曲那几步也
# 一并放开；要再加新条目，先在真机上单独验证「连调 20 次不崩」再加。
SAFE_CALLS = frozenset((
    "BattleObjectManager::get_Instance",
    "GlobalGameManager::get_Instance",
    "SoundManager::get_Instance",
    # 纯读静态字段的无参 getter，实测 0.02s 返回、无副作用：
    "BattleSoundGenerator::IsBattleBgmPlaying",
    "BattleSoundGenerator::get_CurrentBgmIndex",
    # 换曲三步（旧插件 BattleBGMExtend 走的同一条 invoke 路，多年稳定）：
    "BattleSoundGenerator::StopBGM",
    "BattleSoundGenerator::StopAddedBGM",
    "BattleSoundGenerator::StartBGM",
    "BattleSoundGenerator::StartAddBGM",
    # StartAddBGM 只登记待播曲，真正建实例的是 StartAddBGMSystem（0.9.16 补）
    "BattleSoundGenerator::StartAddBGMSystem",
    "BattleSoundGenerator::PauseBGM",
    "BattleSoundGenerator::TryStartBattleBgmByName",
    "SoundManager::StopBGM",
    # v10：类型签名（sig='S'）能精确挑中 IsLoadedBank(string)，不再误选
    # AssetReference 重载，所以这条重新放开 —— 它只查状态、不改游戏。
    "SoundManager::IsLoadedBank",
    # 注意：**不要**放开 SoundManager::LoadBank / LoadBankFromLocal。
    # 0.9.16 真机实测：对一个已经加载过的 bank 重复 LoadBankFromLocal，
    # 崩在 GameAssembly 内部（栈 hk_warp_pump -> warp_pump_commands ->
    # warp_cmd_call -> runtime_invoke -> AV），第一次「成功」第二次就死。
    # 加载 Master.strings.bank 同样直接崩。音库这条路封了。
    # v9：换曲前预检（旧插件 switch_rule 的第一步）。第二个参数是
    # FMOD.Studio.EventInstance& —— 值类型 out，走 MAP 尾部的 out 缓冲。
    "SoundManager::TryCreateInstance",
    # 只读工厂：key -> BGMData，BGMData.Path@0x10 就是游戏真正的事件路径。
    # 纯查表构造，不改游戏状态（用来把「规则表里的曲名」翻成事件名）。
    "LimbusCompany.SoundLibs.BGMDataFactoryByKey::Get",
    # 注意：**不要**放宽 SoundManager::IsLoadedBank —— 它有两个 1 参重载
    # （AssetReference / string），宿主按「名字 + 参数个数」选方法，会把
    # string 当 AssetReference 传进去，游戏内部直接 AV（0.9.16 实测崩过一次）。
))

HOST_STATUS_TEXT = {
    0: "等待游戏",
    1: "引擎加载中",
    2: "装配钩子",
    3: "已挂钩",
    4: "出错",
}

HOST_ERROR_TEXT = {
    0: "",
    1: "没有读到宿主配置",
    2: "等待游戏超时",
    3: "取不到 il2cpp 接口",
    4: "找不到要钩的方法",
    5: "MinHook 初始化失败",
    6: "MinHook 创建钩子失败",
    7: "MinHook 启用钩子失败",
    8: "原版弹窗方法不可用",
}

HOST_EXPORT_ORDER = [
    "il2cpp_domain_get",
    "il2cpp_domain_get_assemblies",
    "il2cpp_assembly_get_image",
    "il2cpp_class_from_name",
    "il2cpp_class_get_method_from_name",
    "il2cpp_string_new",
    "il2cpp_runtime_invoke",
    "il2cpp_thread_attach",
    "il2cpp_object_new",
    "il2cpp_class_get_type",
    "il2cpp_type_get_object",
    "il2cpp_array_new",
    "il2cpp_class_get_parent",
    "il2cpp_gchandle_new",
    "il2cpp_gchandle_free",
    # v10：按参数类型选重载（重载区分）+ 读静态字段要用的元数据接口
    "il2cpp_class_get_methods",
    "il2cpp_method_get_name",
    "il2cpp_method_get_param_count",
    "il2cpp_method_get_param",
    "il2cpp_method_get_return_type",
    "il2cpp_type_get_name",
    "il2cpp_free",
]

class HostHeader(ctypes.Structure):
    """宿主状态头，160 字节。字段顺序与 warp_host.c 的 WARP_HEADER 一一对应。"""

    _fields_ = [
        ("magic", ctypes.c_uint32),
        ("version", ctypes.c_int32),
        ("enabled", ctypes.c_int32),
        ("hooked", ctypes.c_int32),
        ("status", ctypes.c_int32),
        ("last_error", ctypes.c_int32),
        ("heartbeat", ctypes.c_int32),
        ("standalone", ctypes.c_int32),
        ("evt_count", ctypes.c_int32),
        ("hook_installed", ctypes.c_int32),
        ("hook_total", ctypes.c_int32),
        ("panel_step", ctypes.c_int32),
        ("last_event", ctypes.c_int32),
        ("fired", ctypes.c_int32),
        ("ga_found", ctypes.c_int32),
        ("popup_ok", ctypes.c_int32),
        ("boot_at", ctypes.c_uint64),
        ("dedupe_ms", ctypes.c_int32),
        ("reserved0", ctypes.c_int32),
        ("log_tail", ctypes.c_char * HOST_LOG_LEN),
        ("vars", ctypes.c_int32 * HOST_VAR_COUNT),
        # ---- 命令槽：不是「配置」，而是「我让你现在做这件事」 ----
        ("cmd_seq", ctypes.c_int32),
        ("cmd_ack", ctypes.c_int32),
        ("cmd_type", ctypes.c_int32),
        ("cmd_result", ctypes.c_int32),
        ("cmd_text", ctypes.c_char * HOST_CMD_TEXT_LEN),
    ]


class HostHook(ctypes.Structure):
    """钩子表的一项，288 字节。"""

    _fields_ = [
        ("klass", ctypes.c_char * HOST_KLASS_LEN),
        ("method", ctypes.c_char * HOST_METHOD_LEN),
        ("argc", ctypes.c_int32),
        ("event_id", ctypes.c_int32),
        ("every", ctypes.c_int32),
        ("chance", ctypes.c_int32),
        ("actions", ctypes.c_int32),
        ("flags", ctypes.c_int32),
        ("hold_ms", ctypes.c_int32),
        ("delay_ms", ctypes.c_int32),
        ("guard_index", ctypes.c_int32),
        ("guard_value", ctypes.c_int32),
        ("probe_class", ctypes.c_char * HOST_KLASS_LEN),
        ("probe_method", ctypes.c_char * HOST_METHOD_LEN),
        ("probe_index", ctypes.c_int32),
        ("probe_slot", ctypes.c_int32),
        ("guard_var", ctypes.c_int32),
        ("text_base", ctypes.c_int32),
        ("read_base", ctypes.c_int32),
        ("read_count", ctypes.c_int32),
        ("cache_arg", ctypes.c_int32),
        ("cache_slot", ctypes.c_int32),
        ("hits", ctypes.c_int32),        # 命中数（运行时）
        ("blocked", ctypes.c_int32),     # 真正拦下原方法的次数（运行时）
        ("when", ctypes.c_int32),        # HOST_WHEN_PRE / HOST_WHEN_POST
        ("ret_kind", ctypes.c_int32),    # HOST_RET_*：thunk 按什么形状取返回值
        ("ret_slot", ctypes.c_int32),    # 返回值直出的事件格（-1 不用）
        ("pad", ctypes.c_int32),
    ]


class HostRead(ctypes.Structure):
    """一条读取链：从某个参数出发，按偏移跳几跳，把落点读成一个值。"""

    _fields_ = [
        ("arg", ctypes.c_int32),                        # 0=self 1..3=第几个参数
        ("nsteps", ctypes.c_int32),                     # 走几跳
        ("kind", ctypes.c_int32),                       # HOST_READ_*
        ("out", ctypes.c_int32),                        # 写进事件槽 0..3
        ("off", ctypes.c_int32 * HOST_READ_STEPS),      # 每跳偏移
        ("deref", ctypes.c_int32 * HOST_READ_STEPS),    # 每跳是否解引用
    ]


if ctypes.sizeof(HostHeader) != HOST_HEADER_SIZE:
    raise RuntimeError(
        f"HostHeader 尺寸 {ctypes.sizeof(HostHeader)} 与协议不符（应为 {HOST_HEADER_SIZE}）")
if ctypes.sizeof(HostHeader) != HOST_HEADER_SIZE:
    raise RuntimeError(
        f"HostHeader 尺寸 {ctypes.sizeof(HostHeader)} 与协议不符（应为 {HOST_HEADER_SIZE}）："
        "C 侧 WARP_HEADER 改了结构就必须同步这里")

if ctypes.sizeof(HostHook) != HOST_HOOK_SIZE:
    raise RuntimeError(
        f"HostHook 尺寸 {ctypes.sizeof(HostHook)} 与协议不符（应为 {HOST_HOOK_SIZE}）")


def _write_fixed(addr, text, size):
    """把一段 UTF-8 文本写进定长槽位（超长截断，尾部补零）。"""
    raw = str(text or "").encode("utf-8")[:size - 1]
    ctypes.memset(addr, 0, size)
    if raw:
        ctypes.memmove(addr, raw, len(raw))


def _warp_dir():
    """WarpHook 自己的目录 —— 宿主 DLL 就放在这里。

    不能用 ``_caller_dir()``：那个函数是给插件侧 :class:`Runtime` 推断「插件目录」
    用的，宿主 DLL 永远属于 WarpHook 自己。

    注意本文件住在 ``WarpHook/warphook/`` 里，DLL 在上一级 —— 拆包时这里踩过一次。
    """
    path = globals().get("__file__") or ""
    if path and os.path.isfile(path):
        pkg = os.path.dirname(os.path.abspath(path))
        parent = os.path.dirname(pkg)
        if os.path.isfile(os.path.join(parent, "addon_info.json")):
            return parent
        return pkg
    return os.getcwd()


def _read_fixed(addr, size):
    """从定长槽位读回文本。"""
    buf = ctypes.string_at(addr, size)
    return buf.split(b"\x00", 1)[0].decode("utf-8", "ignore")


_HOST_SINGLETON = None


# 注入是全进程一次性的事：多个插件可能同时起 _auto_worker，两边都在
# wait_for_gameassembly 里等到同一时刻，然后各注入一份 warp_host.dll。
# 一份宿主对应一套 detour，重复注入就会出现「钩子触发两次、弹窗弹两遍」。
_INJECT_LOCK = threading.Lock()


def _step_code(value):
    """把 deref 位的各种写法归一成步类型。"""
    if isinstance(value, str):
        return HOST_STEP_NAMES.get(value.strip().lower(), HOST_STEP_DEREF)
    if isinstance(value, bool):
        return HOST_STEP_DEREF if value else HOST_STEP_PLAIN
    try:
        return int(value) & 0x7
    except (TypeError, ValueError):
        return HOST_STEP_DEREF


def _encode_read(at, spec, default_arg=1):
    """把一条 Python 侧读法写进 ``at`` 处的 HostRead 结构，返回落点格号。

    ``spec`` 的写法与 ``hook(reads=[...])`` 里的元素完全一致::

        {'arg': 0, 'kind': 'int', 'out': 0,
         'off': [0x90, {'dict': 'iter'}, {'off': 0x10, 'deref': True}]}

    **钩子表与命令代读共用这一份编码。** 同一件事的两条配置路径各写一份代码，
    迟早有一边漏改（dict 步的缺省 value_off/stride 就这么漏过一次，落盘成 0，
    真机上读到一堆垃圾值）。所以 :meth:`Host._write_config` 与 :meth:`Host.read`
    都走这里，不要各自实现。
    """
    arg = int(spec.get("arg", default_arg))
    chain = list(spec.get("off") or spec.get("chain") or ())[:HOST_READ_STEPS]
    # 两种写法都收：元素级 {'off':..,'deref':..}，或者顶层并列写
    # off=[...] / deref=[True, False]（跟 C 那张表一样）。
    flags = list(spec.get("deref") or ())
    kind = spec.get("kind", HOST_READ_INT)
    if isinstance(kind, str):
        kind = HOST_READ_NAMES.get(kind.lower(), HOST_READ_INT)
    # out 是事件里的第几格：0..11（十二格）。不是 2 的幂，用钳制不用掩码。
    out = max(0, min(int(spec.get("out", 0)), HOST_EVENT_SLOTS - 1))

    ctypes.c_int32.from_address(at + HostRead.arg.offset).value = arg
    ctypes.c_int32.from_address(at + HostRead.nsteps.offset).value = len(chain)
    ctypes.c_int32.from_address(at + HostRead.kind.offset).value = int(kind)
    ctypes.c_int32.from_address(at + HostRead.out.offset).value = out

    for k, step in enumerate(chain):
        if isinstance(step, dict):
            if "list" in step:
                off, code = int(step["list"]), HOST_STEP_LIST
            elif "array" in step:
                off, code = int(step["array"]), HOST_STEP_ARRAY
            elif "list_val" in step:
                off, code = int(step["list_val"]), HOST_STEP_LIST_VAL
            elif "array_val" in step:
                off, code = int(step["array_val"]), HOST_STEP_ARRAY_VAL
            elif "dict" in step or "dict_val" in step:
                # Dictionary 步（v6）：'dict': 下标 / 'dict_val': 下标（值类型
                # value）。'iter': True 或下标写 'iter' 表示遍历链 —— 一次命中
                # 对每个活跃 value 各发一个事件。off 是打包位域不是普通偏移。
                if "dict" in step:
                    code, key = HOST_STEP_DICT_VALUE, step["dict"]
                else:
                    code, key = HOST_STEP_DICT_VALUE32, step["dict_val"]
                is_iter = (key == "iter") or bool(step.get("iter"))
                if isinstance(key, int) and not isinstance(key, bool):
                    idx = key
                else:
                    idx = int(step.get("index", 0))
                # 缺省值必须与 il2cpp 标准布局一致：entry =
                # {hashCode(4), next(4), key(4/8), value}，stride=24、
                # value_off=16。写 0 会退化成「永远取 entry[0] 的 hashCode
                # 当 value」——真机实测过一次，out 全是垃圾值。
                off = (((int(step.get("value_off", 16)) & 0xFF))
                       | ((int(step.get("stride", 24)) & 0xFF) << 8)
                       | ((idx & 0x7FFF) << 16))
                if is_iter:
                    off |= 0x80000000
            else:
                code = _step_code(step.get("deref", True))
                off = int(step.get("index", 0)) if code in (
                    HOST_STEP_LIST, HOST_STEP_ARRAY) else int(
                    step.get("off", 0))
        else:
            off = int(step)
            # 顶层 deref 没写到这一位，就按「解引用」处理：绝大多数跳到 next
            # 是对象引用，内嵌 struct 才显式写 False。
            code = _step_code(flags[k]) if k < len(flags) else 1
        off, code = int(off), int(code)
        if not (0 <= code <= HOST_STEP_DICT_VALUE32):
            code = HOST_STEP_DEREF
        if code >= HOST_STEP_DICT_VALUE:
            # 打包位域带 bit31 ITER 位：补码成 32 位有符号再落盘
            # （c_int32 收不下 0x80000000 的正数），不走钳制。
            if off >= 0x80000000:
                off -= 0x100000000
        else:
            off = max(-0x7FFFFF, min(0x7FFFFF, off))
        ctypes.c_int32.from_address(at + HostRead.off.offset + k * 4).value = off
        ctypes.c_int32.from_address(at + HostRead.deref.offset + k * 4).value = code
    return out


def host_alive(block):
    """宿主 DLL 是否已经在目标进程里跑。

    判据分两种情形：
    * 正常态：启动器进程活着、在写 heartbeat —— 心跳必须新鲜（10s 内）。
    * standalone 态：启动器退出后 DLL 独立存活（线程隔离设计），此时**没有
      心跳写方**，心跳必然过期，只能换证据：hooked=1 且 evt_count 还在推进
      才算活。别把 standalone 当死 —— 真机实测踩过：进阶后 age 涨到 41 万 ms，
      host_alive 一律 False，外部诊断脚本连不上。
    """
    if block is None:
        return False
    try:
        if int(block.cfg.magic) != HOST_MAGIC:
            return False
        # 版本协商（A3）：DLL 比这份 Python 老 → 它不认识新协议段/新读链步，
        # 配置写进去会全错，按没活处理。反之 DLL 更新则放行 —— 校验别写死
        # 等号（立绘淡出那次教训：hdr[1]!=4 一刀切，旧存档直接判死）。
        if int(block.cfg.version) < HOST_VERSION:
            return False
        if not int(block.cfg.ga_found):
            return False
        if abs(int(_tick32()) - int(block.cfg.heartbeat)) < 10000:
            return True
        if int(block.cfg.standalone):
            return int(block.cfg.hooked) > 0
        return False
    except Exception:  # noqa: BLE001
        return False


def host_build(log_path=None):
    """读宿主 DLL 自己打的那行构建戳，返回 `'Oct 31 2026 13:48:12'` 之类的字符串。

    DLL 启动时往 warp_host.log 写一行 ``build <__DATE__> <__TIME__> proto vN``。
    用途：确认游戏里跑的到底是哪一版 —— 只比 ``hdr.version`` 没用，同一个协议
    号的两次构建看不出新旧。真机上踩过：源码改完、编到 test/ 忘了拷，游戏里
    仍是上一版，读链新语义全落进旧分支，输出一堆垃圾值，从现象反推源码完全
    推不出来。
    """
    if log_path is None:
        log_path = os.path.join(_warp_dir(), "warp_host.log")
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()[-400:]
    except OSError:
        return None
    for line in reversed(lines):
        if " build " in line:
            return line.split(" build ", 1)[1].strip()
    return None


def _owner_of_caller():
    """反查调用栈里那个插件的 env.ADDON_NAME。

    插件是 exec 进来的模块，它们各自有全局 ``env.ADDON_NAME``；
    共用宿主时要靠它区分「这次 configure 是谁改的」，否则后注册的插件
    会把先注册的插件那几行钩子覆盖掉。
    """
    frame = sys._getframe(1)
    while frame is not None:
        if frame.f_globals is not globals():
            name = frame.f_globals.get("ADDON_NAME")
            if name:
                return str(name)
        frame = frame.f_back
    return None


class Host:
    """warp_host.dll 的配置端：写钩子表、注入宿主、读回状态。

    这个类的实例是全进程单例 —— 宿主 DLL 只认一块共享映射，
    多个插件都通过它登记自己的钩子与台词，互不覆盖。

    用法::

        PLUGIN = WARP.plugin.Host(
            addon_name=env.ADDON_NAME,
            hooks=[{"klass": "BattleActionModelManager",
                    "method": "OnRoundStart_Before",
                    "argc": 0, "actions": WARP.plugin.ACT_POPUP}],
            texts=["要说的话", ...],
        )
        PLUGIN.inject_now()      # 找游戏、注入 warp_host.dll
        print(PLUGIN.status_line())

    宿主 DLL 由 WarpHook 自带（同目录 ``warp_host.dll``），插件不需要提供任何
    C 代码；想自定义行为就改 ``hooks`` 与 ``texts``，想加业务字段就直接读写
    ``PLUGIN.block()`` 的那块共享内存。
    """

    def __new__(cls, *args, **kwargs):
        """单例，且**跨插件重载共享**。

        插件被重载时启动器会重新 exec WarpHook 的 scr.py，模块级
        ``_HOST_SINGLETON`` 会跟着重置；如果只靠它，重载前后两个插件就各拿一个
        Host，各写一次共享内存，后写的把先写的钩子槽覆盖掉（AutoBoom 装配两次、
        NoGacha 被顶掉就是这么来的）。所以真正的宿主挂在启动器的 AddonManager
        对象上 —— 它活多久，宿主就活多久。
        """
        global _HOST_SINGLETON

        holder = None
        arg = env.ADDON_ARG
        if isinstance(arg, dict):
            holder = arg.get("AddonManager")

        inst = getattr(holder, "_warphook_host", None) if holder is not None else None
        if inst is None:
            inst = super().__new__(cls)
            inst._inited = False
            if holder is not None:
                setattr(holder, "_warphook_host", inst)
        _HOST_SINGLETON = inst
        return inst

    def __init__(self, addon_name, hooks=None, texts=(), enabled=True,
                 dedupe_ms=800, map_name=None, log_prefix=None,
                 skip_env=None, menu_labels=("注入", "解除", "应用设置")):
        owner = str(addon_name)

        if not getattr(self, "_inited", False):
            self.addon_name = owner
            self.log_prefix = log_prefix or f"[{owner}]"
            # 映射名必须和 warp_host.dll 的默认值完全一致。插件传进来的
            # map_name 一律忽略 —— Host 是进程内单例，谁传谁生效的结果就是
            # DLL 打开了一块没人写过的空映射（bind exports failed (0)）。
            # 只有测试用环境变量 WARP_HOST_MAP 才可以换一块独立的映射。
            self.map_name = os.environ.get(HOST_MAP_ENV) or HOST_MAP_DEFAULT
            self.enabled = bool(enabled)
            self.dedupe_ms = int(dedupe_ms)
            self.skip_env = skip_env
            self.menu_labels = tuple(menu_labels)
            self._view_hooks = []
            self.texts = []
            self._owners = {}
            self._block = None
            self._closed = False
            # 引擎侧丢了多少条事件（读侧太慢、环形队列被覆盖）。累计值，
            # 只增不减；events() 每读一次就把增量并进来。
            self.events_lost = 0
            self._dropped_seen = 0
            self._inited = True

        self._owners[owner] = {
            "hooks": [dict(h or {}) for h in (hooks or [])],
            "texts": [str(t) for t in (texts or [])],
            "on": bool(enabled),
            "menu_labels": tuple(menu_labels),
        }
        self._sync_view(owner)

    def _current_owner(self):
        """这次操作属于哪个插件。

        直接从插件代码调用时靠调用栈里的 env.ADDON_NAME 认；
        从托盘菜单回调调用时没有那条栈，改用 ``_acting_owner``。
        """
        return getattr(self, "_acting_owner", None) or _owner_of_caller() or self.addon_name

    def _act(self, owner, fn):
        """以某个插件的身份执行一个动作（菜单回调走这里）。"""
        prev = getattr(self, "_acting_owner", None)
        self._acting_owner = owner
        try:
            return fn()
        finally:
            self._acting_owner = prev

    def _sync_view(self, owner=None):
        """把「本插件」的配置与开关同步到 self._view_hooks/self.texts/self.enabled。

        这几个属性是插件侧读的（比如 status() 里报钩子总数），
        必须反映调用者自己的那一份，而不是整块宿主的总表。
        """
        owner = owner or self._current_owner()
        entry = self._owners.get(owner)
        if entry is None:
            return
        self._view_hooks = entry["hooks"]
        self.texts = entry["texts"]
        self.enabled = entry["on"]

    def _layout(self):
        """把各插件登记的钩子与文案排成一张总表。

        v0.9.2 起按 owner 分段：主段作者（成就观测，名字含「成就」/
        achievement）占钩子槽 0..26、读链 0..95、文案 0..191；其余作者
        合占钩子槽 27..31、读链 96..127、文案 192..255。成就观测在子进程
        有一份独立的 Host，两边各自 push 同一块共享内存——只有分段各写各的，
        才不会互相把对方清掉（v0.9.1 真机事故：NoGacha 后 push，成就 25 条
        全被清掉，C 只装上 NoGacha 的 2 条）。

        返回的 hooks 列表按**最终槽号**排列（空洞为 None，由 _write_config
        跳过）；texts 同理按最终段号。超容量的钩子会被丢掉并打日志。
        """
        active = [(name, e) for name, e in self._owners.items() if e["on"]]
        primaries = [(n, e) for n, e in active if _is_primary_owner(n)]
        secondaries = [(n, e) for n, e in active if not _is_primary_owner(n)]

        hook_cap = (HOST_HOOKS_PRIMARY, HOST_MAX_HOOKS - HOST_HOOKS_PRIMARY)
        text_cap = (HOST_TEXTS_PRIMARY, HOST_MAX_TEXTS - HOST_TEXTS_PRIMARY)
        groups = []
        dropped = []
        text_dropped = 0
        for gi, members in enumerate((primaries, secondaries)):
            hooks = []
            texts = []
            for owner_name, entry in members:
                base = len(texts)
                for hook in entry["hooks"]:
                    if len(hooks) >= hook_cap[gi]:
                        dropped.append((owner_name, hook.get("method") or "?"))
                        continue
                    item = dict(hook)
                    item["text_base"] = base
                    item["owner"] = owner_name
                    hooks.append(item)
                # 先到先得，但不截断：每个插件能装多少装多少，只受**自己段**
                # 剩余容量约束（留一格给段尾空串当界标）。
                room = text_cap[gi] - len(texts) - 1
                if room <= 0:
                    text_dropped += len(entry["texts"])
                    continue
                take = entry["texts"][:room]
                text_dropped += len(entry["texts"]) - len(take)
                texts.extend(take)
                texts.append("")
            groups.append((hooks, texts))

        # 槽号拼装：主段从 0、辅段从 HOST_HOOKS_PRIMARY 起，中间的空洞留 None
        out_hooks = [None] * HOST_MAX_HOOKS
        out_texts = [None] * HOST_MAX_TEXTS
        primary_hooks, primary_texts = groups[0]
        secondary_hooks, secondary_texts = groups[1]
        for i, hook in enumerate(primary_hooks):
            out_hooks[i] = hook
        for i, hook in enumerate(secondary_hooks):
            out_hooks[HOST_HOOKS_PRIMARY + i] = hook
        for i, text in enumerate(primary_texts):
            out_texts[i] = text
        for i, text in enumerate(secondary_texts):
            out_texts[HOST_TEXTS_PRIMARY + i] = text
        if dropped:
            names = ", ".join(f"{o}.{m}" for o, m in dropped[:6])
            more = f" 等 {len(dropped)} 条" if len(dropped) > 6 else ""
            self.log(f"钩子分段容量不够，装不下的钩子被丢弃："
                     f"{names}{more} —— 检查各插件钩子总数", "warp")
        bands = tuple(
            gi for gi, group in enumerate(
                ([(n, e) for n, e in self._owners.items()
                  if _is_primary_owner(n)],
                 [(n, e) for n, e in self._owners.items()
                  if not _is_primary_owner(n)]))
            if group)   # 关掉的 owner 也要管段：全关 push 时才轮得到清自己的槽
        return out_hooks, out_texts, bands

    # ---------- 日志 ----------

    def log(self, message, owner=None):
        """按「这条日志属于哪个插件」加前缀。

        宿主是单例，``self.log_prefix`` 只反映第一个创建它的插件。一直用它，
        第二个插件的日志就全顶着第一个插件的名字（用户看到的是「NoGacha 显示成
        AutoBoom 格式」）。所以这里按当前 owner 现算前缀。
        """
        owner = owner or self._current_owner()
        log(message, f"[{owner}]")

    # ---------- 共享内存 ----------

    def block(self):
        """打开（必要时创建）宿主共享内存，返回 SharedMap；已关闭则返回 None。"""
        if getattr(self, "_closed", False):
            return None
        if self._block is not None:
            return self._block

        def _init(cfg):
            cfg.magic = HOST_MAGIC
            cfg.version = HOST_VERSION
            cfg.enabled = 1 if self.enabled else 0
            cfg.dedupe_ms = self.dedupe_ms
            cfg.heartbeat = int(_tick32())

        self._block = shm_open(
            self.map_name, HOST_MAP_BYTES, HostHeader,
            magic_field="magic", magic_value=HOST_MAGIC, init=_init,
        )
        if self._block is not None:
            self._write_config(self._block)
        return self._block

    def _write_config(self, block):
        """把钩子表、文案池、导出名表写进共享内存。

        v0.9.2 分段协议：只碰本实例 _owners 涉及的段（主段/辅段），别人的段
        一个字节都不动——成就观测子进程与主进程插件各自 push 互不覆盖。
        """
        base = block.address
        hdr = block.cfg
        # 只要还有任何一个插件是开着的，宿主就继续工作。全关时**不写 0**：
        # 别的进程（另一个 Host 实例）可能还开着——写 0 会把人家一起停掉。
        # 关掉的插件自己的钩子段会被清空，行为上已经「停」了。
        if any(e["on"] for e in self._owners.values()):
            hdr.enabled = 1
        hdr.dedupe_ms = self.dedupe_ms

        hooks, texts, bands = self._layout()

        # 读取链按段各自重建：主段 0..95、辅段 96..127，游标各走各的
        read_base_slot = (0, HOST_READS_PRIMARY)
        read_used = [0, 0]
        read_addr = base + HOST_READ_OFFSET
        for gi, cap in enumerate((HOST_READS_PRIMARY,
                                  HOST_READ_MAX - HOST_READS_PRIMARY)):
            if gi in bands:
                ctypes.memset(
                    read_addr + read_base_slot[gi] * HOST_READ_SIZE,
                    0, cap * HOST_READ_SIZE)

        # 钩子表：只清只写自己段的槽
        for i in range(HOST_MAX_HOOKS):
            gi = 0 if i < HOST_HOOKS_PRIMARY else 1
            if gi not in bands:
                continue
            slot = base + HOST_HOOK_OFFSET + i * HOST_HOOK_SIZE
            # 先记下旧槽位：DLL 会把「一次性钩子已经触发过」的标记写回 flags
            # 的最高位。反复 push 配置时若把这个标记清掉，同一个一次性钩子
            # （例如 AutoBoom）会被重新武装、再触发一次。
            old_flags = ctypes.c_int32.from_address(
                slot + HostHook.flags.offset).value
            old_klass = _read_fixed(slot + HostHook.klass.offset, HOST_KLASS_LEN)
            old_method = _read_fixed(slot + HostHook.method.offset, HOST_METHOD_LEN)
            ctypes.memset(slot, 0, HOST_HOOK_SIZE)
            # v8：改写规则一并归零（同一段语义：这格钩子被清掉了，改写也得清）
            ctypes.memset(base + HOST_REWRITE_OFFSET + i * HOST_REWRITE_SIZE,
                          0, HOST_REWRITE_SIZE)
            hook = hooks[i]
            if hook is None:
                continue
            hook = dict(hook)
            # 声明式 dict 也能写 cache=(arg, 槽)，与 Host.hook(cache=...) 同一套
            # 语义（arg 0=self / 1..3=第几个参数）。原来 dict 路径只认
            # cache_arg/cache_slot 两个平铺键，传 cache= 元组会被静默丢掉 ——
            # 真机踩过：钩子装上了、事件也有了，对象槽永远空。
            if hook.get("cache") is not None:
                c_arg, c_slot = list(hook["cache"])[:2]
                hook.setdefault("cache_arg", int(c_arg))
                hook.setdefault("cache_slot", int(c_slot))
            # 声明式 dict 也能直接写 event=事件号，效果等同 Host.hook(event=...)：
            # 少了这一位，DLL 只数命中次数、不往事件队列里塞东西。
            if hook.get("event") is not None:
                hook["event_id"] = int(hook["event"])
                hook["actions"] = int(hook.get("actions", 0)) | HOST_ACT_EVENT
            _write_fixed(slot + HostHook.klass.offset,
                         hook.get("klass", ""), HOST_KLASS_LEN)
            _write_fixed(slot + HostHook.method.offset,
                         hook.get("method", ""), HOST_METHOD_LEN)
            _write_fixed(slot + HostHook.probe_class.offset,
                         hook.get("probe_class", ""), HOST_KLASS_LEN)
            _write_fixed(slot + HostHook.probe_method.offset,
                         hook.get("probe_method", ""), HOST_METHOD_LEN)
            for name, default in (("argc", 0), ("event_id", i), ("every", 1),
                                  ("chance", 100), ("actions", 0),
                                  ("flags", 0), ("hold_ms", 0), ("delay_ms", 0),
                                  ("guard_index", -1), ("guard_value", 0),
                                  ("probe_index", 0), ("probe_slot", -1),
                                  ("guard_var", -1), ("text_base", 0),
                                  ("cache_arg", -1), ("cache_slot", -1),
                                  ("when", HOST_WHEN_PRE),
                                  ("ret_kind", HOST_RET_VOID),
                                  ("ret_slot", -1)):
                value = hook.get(name, default)
                if name == "ret_kind" and isinstance(value, str):
                    # dict 配置路径与 hook() 关键字路径同一套叫法：
                    # 'int32' / 'float' 按名翻译，认不出按 VOID。
                    value = HOST_RET_NAMES.get(value.strip().lower(),
                                               HOST_RET_VOID)
                try:
                    value = int(value)
                except (TypeError, ValueError):
                    value = default
                ctypes.c_int32.from_address(slot + getattr(HostHook, name).offset).value = value

            # 读取链：一条钩子最多占掉自己段里剩余的位置，写不下就少写几条
            reads = hook.get("reads") or ()
            if reads:
                rbase = read_base_slot[gi]
                room = (HOST_READ_MAX if gi == 0 else HOST_READ_MAX) - rbase \
                    - read_used[gi]
                take = min(len(reads), room)
                ctypes.c_int32.from_address(
                    slot + HostHook.read_base.offset).value = rbase + read_used[gi]
                ctypes.c_int32.from_address(
                    slot + HostHook.read_count.offset).value = take
                for j in range(take):
                    spec = dict(reads[j])
                    spec.setdefault("out", j)
                    at = read_addr + (rbase + read_used[gi] + j) * HOST_READ_SIZE
                    _encode_read(at, spec)
                read_used[gi] += take
            # v8：参数改写 —— (第几个参数, 从哪个对象槽取值)。
            # 声明式 dict 也能写 rewrite=(arg, slot)，和 hook(rewrite=...) 同义。
            rw = hook.get("rewrite")
            if rw:
                rw_arg, rw_slot = (list(rw) + [0, -1])[:2]
                try:
                    rw_arg, rw_slot = int(rw_arg), int(rw_slot)
                except (TypeError, ValueError):
                    rw_arg, rw_slot = 0, -1
                if rw_arg > 0 and rw_slot >= 0:
                    rw_at = base + HOST_REWRITE_OFFSET + i * HOST_REWRITE_SIZE
                    ctypes.c_int32.from_address(rw_at).value = rw_arg
                    ctypes.c_int32.from_address(rw_at + 4).value = rw_slot
            # 同一个钩子（类名与方法都没变）如果 DLL 已经标记过「触发过」，
            # 把标记补回去，一次性钩子才不会重复触发。
            if (old_flags & 0x100) and not hook.get("_reset"):
                same = (old_klass == hook.get("klass", "")
                        and old_method == hook.get("method", ""))
                if same:
                    addr = slot + HostHook.flags.offset
                    ctypes.c_int32.from_address(addr).value |= 0x100

        # 文案池：只写自己段的区间，别人的段不动
        text_base_slot = (0, HOST_TEXTS_PRIMARY)
        text_cap = (HOST_TEXTS_PRIMARY, HOST_MAX_TEXTS - HOST_TEXTS_PRIMARY)
        for gi in bands:
            for k in range(text_cap[gi]):
                i = text_base_slot[gi] + k
                slot = base + HOST_TEXTS_OFFSET + i * HOST_TEXT_SIZE
                value = texts[i]
                if value is None:
                    ctypes.memset(slot, 0, HOST_TEXT_SIZE)
                else:
                    _write_fixed(slot, value, HOST_TEXT_SIZE)

        # 导出名表：顺序错了会拿到别人的函数指针，所以统一走 ensure_exports，
        # 它内部负责把标准名映射成混淆名（这里必须传标准名，别再自己映射一遍）
        ensure_exports(block, HOST_EXPORT_ORDER, HOST_EXPORTS_OFFSET, HOST_NAME_MAX)

    def hook(self, klass, method, argc=0, block=False, actions=None,
             probe=None, guard=None, event=None, reads=None, dedupe=False,
             cache=None, rewrite=None, when=None, ret_kind=None, ret_slot=None,
             **extra):
        """登记一条钩子 —— 用法就是一次普通调用，不是填表格。

        ``klass`` / ``method`` 是要挂的方法（``argc`` 按「不含 this」数），
        ``block=True`` 表示拦下原方法，``probe=(类, 方法, 参数序号, 写到哪个槽)``
        表示顺手把某个参数对象的属性读进 ``vars[]``，
        ``guard=(槽号, 值)`` 表示那个槽等于该值时彻底放行，
        ``event=事件号`` 表示每次命中都往事件队列塞一条（见 :meth:`events`）。
        ``reads=[...]`` 是读取链列表，每项 ``(参数序号, 偏移链, 落点, 类型)``，
        引擎在命中时按链把值读出来写进事件的 a/b/c/d —— 见 :meth:`reads`。
        ``dedupe=True`` 加 ``reads=`` 表示「读出来的值跟上次一样就别投递」，
        挂在 ``FixedUpdate`` 这类每帧调用的方法上时必开，否则事件队列会被刷爆。
        ``cache=(参数序号, 槽号)`` 表示命中时把那个参数的指针留在对象槽里，
        之后可以用 ``arg=0x100+槽号`` 的读链从它出发，或者 :meth:`object_ptr`
        直接把地址拿出来 —— 这是老链路 `cache_self` 那类读法的通用版。
        ``rewrite=(参数序号, 槽号)`` 是 v8 的**改写**：命中时把第 N 个参数换成
        对象槽里的指针再调原函数（通常是先 ``make_str`` 好放进去的字符串）。
        它和 ``cache`` 方向相反 —— 一个把游戏的值取出来，一个把我们的值塞进去。
        ``when=1``（POST）表示事件在原函数调用**之后**发——构造函数里要读
        的字段是调用之后才填好的，必须配这个；带 ``ret_kind`` 时自动转 POST。
        ``ret_kind='int32'/'float'`` 让 thunk 按类型取返回值（int 在 RAX、
        float 在 XMM0），``ret_slot=格号`` 把返回值直出进事件的那一格；
        返回值是 Python 侧传名字，落盘前翻成 HOST_RET_* 常量。

        返回登记进去的那条 dict，方便调用方就地改。
        默认 ``actions=0``：只拦、只看，不弹窗 —— 要弹什么由 Python 自己调
        :meth:`popup`。
        """
        owner = self._current_owner()
        entry = self._owners.get(owner)
        if entry is None:
            entry = {"hooks": [], "texts": [], "on": True,
                     "menu_labels": self.menu_labels}
            self._owners[owner] = entry
        item = {"klass": klass, "method": method, "argc": int(argc),
                "actions": 0 if actions is None else int(actions)}
        if block:
            item["flags"] = int(extra.pop("flags", 0)) | int(HF_BLOCK)
        if dedupe:
            item["flags"] = int(extra.pop("flags", item.get("flags", 0))) | int(HF_DEDUPE)
        if probe is not None:
            p_class, p_method, p_index, p_slot = (list(probe) + [0, 0])[:4]
            if int(p_slot) in (6, 7):
                # vars[6]/vars[7] 是命令通道的返回值/输出槽，探针写进去会在
                # 命令执行的窗口里互相踩 —— 探针换一格。
                log(f"probe_slot={p_slot} 与命令通道冲突（6/7 保留），忽略该探针",
                    "[WarpHook.host]")
            else:
                item.update({"probe_class": p_class, "probe_method": p_method,
                             "probe_index": int(p_index), "probe_slot": int(p_slot)})
        if guard is not None:
            g_slot, g_value = list(guard)[:2]
            item.update({"guard_var": int(g_slot), "guard_value": int(g_value)})
        if event is not None:
            item["event_id"] = int(event)
            item["actions"] = int(item.get("actions", 0)) | HOST_ACT_EVENT
        if cache is not None:
            c_arg, c_slot = list(cache)[:2]
            item.update({"cache_arg": int(c_arg), "cache_slot": int(c_slot)})
        if rewrite is not None:
            # v8：(第几个参数, 从哪个对象槽取值)。槽里通常是 make_str 放好的
            # il2cpp String —— 命中时宿主把那个形参换成它，游戏拿到的就是
            # 我们想要的值，不用自己再去调游戏方法。
            r_arg, r_slot = (list(rewrite) + [0, -1])[:2]
            item["rewrite"] = (int(r_arg), int(r_slot))
        if when is not None:
            item["when"] = int(when)
        if ret_kind is not None:
            if isinstance(ret_kind, str):
                ret_kind = HOST_RET_NAMES.get(ret_kind.strip().lower(),
                                              HOST_RET_VOID)
            item["ret_kind"] = int(ret_kind)
            if int(ret_kind) != HOST_RET_VOID:
                item.setdefault("when", HOST_WHEN_POST)
        if ret_slot is not None:
            item["ret_slot"] = int(ret_slot)
        if reads:
            item["reads"] = list(reads)
        item.update(extra)
        entry["hooks"].append(item)
        self._sync_view(owner)
        return item

    def clear_hooks(self):
        """清空本插件登记的钩子（重新声明前调一次）。"""
        owner = self._current_owner()
        entry = self._owners.get(owner)
        if entry is not None:
            entry["hooks"] = []
        return self

    def hooks(self):
        """本插件当前登记的钩子（副本，改它不会影响宿主配置）。"""
        owner = self._current_owner()
        entry = self._owners.get(owner) or {}
        return [dict(h) for h in entry.get("hooks", [])]

    def configure(self, hooks=None, texts=None, dedupe_ms=None):
        """改钩子表 / 文案池，下次 :meth:`push` 生效。

        插件在设置面板里改完参数后调 ``configure(...)`` + ``push()`` 即可，
        不用重建 Host —— 重建会丢掉已注入的状态与心跳线程。
        """
        owner = self._current_owner()
        entry = self._owners.get(owner)
        if entry is None:
            entry = {"hooks": [], "texts": [], "on": True}
            self._owners[owner] = entry
        if hooks is not None:
            entry["hooks"] = [dict(h) for h in hooks]
        if texts is not None:
            entry["texts"] = [str(t) for t in texts]
        if dedupe_ms is not None:
            self.dedupe_ms = int(dedupe_ms)
        self._sync_view(owner)
        return self

    def push(self, enabled=None):
        """把当前配置刷进共享内存（改完设置调一次即可，宿主立刻生效）。"""
        block = self.block()
        if block is None:
            return "共享内存不可用"
        if enabled is not None:
            owner = self._current_owner()
            entry = self._owners.get(owner)
            if entry is not None:
                entry["on"] = bool(enabled)
            self.enabled = bool(enabled)
        self._write_config(block)
        return "已生效" if self.enabled else "已停用"

    def mapped_texts(self):
        """读回共享内存里已装填的文案池（非空项）。"""
        block = self.block()
        if block is None:
            return []
        base = block.address + HOST_TEXTS_OFFSET
        result = []
        for i in range(HOST_MAX_TEXTS):
            item = _read_fixed(base + i * HOST_TEXT_SIZE, HOST_TEXT_SIZE)
            if item:
                result.append(item)
        return result

    def read_mapped(self):
        """宿主已填好的 il2cpp 导出名数量（排错用）。"""
        block = self.block()
        if block is None:
            return 0
        base = block.address + HOST_EXPORTS_OFFSET
        return sum(1 for i in range(HOST_EXPORT_COUNT)
                   if _read_fixed(base + i * HOST_NAME_MAX, HOST_NAME_MAX))

    # ---------- 注入 ----------

    def dll_path(self):
        """宿主 DLL 的绝对路径（就在 WarpHook 目录里）。"""
        return os.path.join(_warp_dir(), HOST_DLL_NAME)

    def inject_now(self, wait=False, stop_event=None):
        """找到游戏、把 warp_host.dll 注进去。"""
        dll = self.dll_path()
        if not os.path.isfile(dll):
            self.log(f"注入失败：找不到宿主 DLL {dll}")
            return False

        stop = stop_event or threading.Event()
        pid = find_game_pid()
        if pid is None:
            if not wait:
                self.log("注入中止：没有找到运行中的游戏")
                return False
            self.log("等待游戏启动…")
            pid = wait_for_game(stop_event=stop)
            if pid is None:
                self.log("注入中止：等待游戏超时")
                return False

        if not wait_for_gameassembly(pid, stop_event=stop):
            self.log("注入中止：等待 GameAssembly.dll 超时")
            return False

        self.push()

        # 宿主是进程内唯一的 DLL：一个插件注入过就够了。两个插件可能同时
        # 走完 wait_for_gameassembly，所以判定 + 注入要在同一把锁里做。
        owner = self._current_owner()
        with _INJECT_LOCK:
            if host_alive(self.block()):
                self.log("宿主已在运行，跳过重复注入", owner=owner)
                return True
            ok, message = inject_dll(pid, dll)
        if not ok:
            self.log(f"注入失败：{message}")
            return False

        self.log(f"已注入（PID {pid}）")
        return True

    # ---------- 状态 ----------

    def _own_hits(self, cfg, owner=None, method=None, blocked=False):
        """本插件自己的钩子被命中多少次。

        header 上的 evt_count 是全局的，被每帧调用的钩子（AutoBoom 的
        FixedUpdate）一刷就是几千，放进插件状态行只会让人误会。

        ``method`` 只看某一个方法对应的钩子；``blocked`` 为真时读
        ``blocked`` 计数（真的把原方法拦下来的次数，参数门放行那次不算）。
        """
        owner = owner or self._current_owner()
        off = HostHook.blocked.offset if blocked else HostHook.hits.offset
        total = 0
        base = ctypes.addressof(cfg) + HOST_HOOK_OFFSET
        hooks, _, _ = self._layout()
        for i, hook in enumerate(hooks):
            if hook is None:
                continue
            if hook.get("owner") != owner:
                continue
            if method is not None and hook.get("method") != method:
                continue
            slot = base + i * HOST_HOOK_SIZE
            total += ctypes.c_int32.from_address(slot + off).value
        return total

    def events(self, limit=None):
        """把事件队列里攒下的条目读走，读的同时推进 tail。

        钩子登记时写 ``event=事件号``（或手动 ``actions |= HOST_ACT_EVENT``），
        引擎每命中一次就往环形队列塞一条，DLL 侧不关心谁在读、读多快；
        队列满了丢最旧的，所以这里读到的是「最近的一批」。

        返回 ``[{'id', 'hook', 'tick', 'a', 'b', 'c', 'd'}, ...]``，
        ``a/b/c`` 是这次命中的第 1~3 个参数（截成 32 位），``d`` 是 ``vars[0]``。
        """
        block = self.block()
        if block is None:
            return []
        base = block.address
        ctrl = ctypes.cast(base + HOST_EV_CTRL_OFFSET,
                           ctypes.POINTER(ctypes.c_int32 * 4)).contents
        head = int(ctrl[0])
        tail = int(ctrl[1])
        # ctrl[2] 是引擎侧累计丢弃数：环形队列被读侧追不上时会覆盖最旧的。
        # 差值累到 self.events_lost 上，成就那边才分得清「没发生」与「漏了」。
        dropped = int(ctrl[2])
        if dropped > self._dropped_seen:
            self.events_lost += dropped - self._dropped_seen
            self._dropped_seen = dropped
        if head <= tail:
            return []
        take = head - tail
        if limit is not None:
            take = min(take, max(0, int(limit)))
        if take <= 0:
            return []
        out = []
        for i in range(take):
            index = (tail + i) % HOST_EVENT_COUNT
            slot = ctypes.cast(base + HOST_EVENTS_OFFSET + index * HOST_EVENT_SIZE,
                               ctypes.POINTER(HostEvent)).contents
            out.append({
                "id": int(slot.id), "hook": int(slot.hook), "tick": int(slot.tick),
                "a": int(slot.a), "b": int(slot.b), "c": int(slot.c),
                "d": int(slot.d), "e": int(slot.e), "f": int(slot.f),
                "g": int(slot.g), "h": int(slot.h), "i": int(slot.i),
                "j": int(slot.j), "k": int(slot.k), "l": int(slot.l),
            })
        ctrl[1] = tail + take
        return out

    def hits(self, method=None, blocked=False, owner=None):
        """本插件钩子的命中次数。

        ``hits()`` 是所有钩子；``hits(method='OnGachaSelected', blocked=True)``
        是「这个钩子真的拦下来几次」——插件拿它当事件计数，看到数字变大就知道
        刚刚发生了一件事，然后用自己的代码决定接下来干什么。
        """
        block = self.block()
        if block is None:
            return 0
        return self._own_hits(block.cfg, owner, method, blocked)

    def status(self, owner=None):
        """读宿主状态，返回 dict。"""
        owner = owner or self._current_owner()
        block = self.block()
        result = {
            "ready": block is not None,
            "enabled": self.enabled,
            "hooked": False,
            "status": 0,
            "status_text": "未连接",
            "last_error": 0,
            "last_error_text": "",
            "evt_count": 0,
            "fired": 0,
            "hook_installed": 0,
            "hook_total": len(self._view_hooks),
            "ga_found": 0,
            "popup_ok": False,
            "standalone": False,
            "log_tail": "",
        }
        entry = self._owners.get(owner)
        if entry is not None:
            result["enabled"] = bool(entry["on"])
            result["hook_total"] = len(entry["hooks"])
        if block is None:
            return result
        cfg = block.cfg
        result.update({
            "hooked": bool(cfg.hooked),
            "status": int(cfg.status),
            "status_text": HOST_STATUS_TEXT.get(int(cfg.status), "未知"),
            "last_error": int(cfg.last_error),
            "last_error_text": HOST_ERROR_TEXT.get(int(cfg.last_error), ""),
            "evt_count": self._own_hits(cfg, owner),
            "fired": int(cfg.fired),
            "hook_installed": int(cfg.hook_installed),
            "hook_total": int(cfg.hook_total) or len(self._view_hooks),
            "ga_found": int(cfg.ga_found),
            "popup_ok": bool(cfg.popup_ok),
            "standalone": bool(cfg.standalone),
            "log_tail": _read_fixed(ctypes.addressof(cfg) + HostHeader.log_tail.offset,
                                    HOST_LOG_LEN),
        })
        # hook_total / enabled 必须按「问的人」算：上面的 update 用的是
        # cfg.hook_total（整块宿主的总数）和最近一次 _sync_view 的结果。
        entry = self._owners.get(owner)
        if entry is not None:
            result["enabled"] = bool(entry["on"])
            result["hook_total"] = len(entry["hooks"])
        return result

    def status_line(self, st=None):
        """一行中文状态，给菜单与日志用。"""
        st = st or self.status()
        if not st.get("ready"):
            return "宿主未连接"
        if st.get("last_error_text"):
            return f"出错：{st['last_error_text']}"
        if st.get("standalone"):
            return f"独立运行中（启动器已退出），命中 {st['evt_count']} 次"
        if st.get("hooked"):
            return (f"{st['status_text']}（{st['hook_installed']}/{st['hook_total']}），"
                    f"命中 {st['evt_count']} 次，触发 {st['fired']} 次")
        return st.get("status_text") or "未知状态"

    # ---------- 监视 ----------

    # ---------- 单步原语（插件自己决定什么时候调）----------

    def close(self):
        """关掉映射视图并标记这个 Host 已关闭。不碰任何线程 —— 线程归插件自己管。

        ``_closed`` 是必需的：``block()`` 是惰性打开的，只把 ``_block`` 置空的话，
        一个还在跑的后台线程下一次 ``beat()`` 就会把映射重新建起来；而卸载流程紧接
        着已经把 ``base._maps`` 里那块解除映射了 —— 线程随后读到释放的内存，就是
        进程级 AV（没有 traceback，启动器直接消失）。关掉之后 ``block()`` 一律返回
        ``None``，调用方只会拿到 ``False`` 或异常，不会再碰已释放的地址。
        """
        self._closed = True
        self._block = None

    def beat(self):
        """写一次心跳。插件自己的线程按它想要的节奏调，宿主据此判断启动器还在不在。"""
        block = self.block()
        if block is None:
            return False
        try:
            block.cfg.heartbeat = int(_tick32())
            return True
        except Exception:  # noqa: BLE001
            return False

    def poll(self):
        """读一次宿主状态。调不调、多久调一次、怎么播报，都由插件决定。"""
        return self.status()

    # ---- 主动命令：一行调用就让游戏做事 ---------------------------------
    def object_ptr(self, slot):
        """读对象槽里缓存的指针（钩子配了 ``cache=(arg, slot)`` 才会有值）。

        对象槽是「先记住对象在哪儿，回头再摸」的通用版：老链路里
        ``cache_self`` / ``cache_arg1`` 那几种读法就是靠它工作的 ——
        钩子命中时把 self 或某个参数存进槽里，采样线程隔一会儿再来读。

        槽里只有裸指针，不带引用计数：两次读取之间对象可能已经销毁，所以
        拿到的地址随时可能失效。要读内容请用读取链（``arg=0x100+槽号``），
        那条路上每一步都有 ``warp_can_read`` 校验；直接按地址读要自己当心。
        """
        slot = int(slot)
        if slot < 0 or slot >= HOST_OBJECT_COUNT:
            raise ValueError(f"对象槽 {slot} 超出 0..{HOST_OBJECT_COUNT - 1}")
        block = self.block()
        if block is None:
            return 0
        addr = block.address + HOST_OBJECTS_OFFSET + slot * HOST_OBJECT_SIZE
        return int(ctypes.c_uint64.from_address(addr).value)

    def read(self, slot, chain, kind="int", timeout=2.0, default=None,
             detail=False):
        """让游戏主线程代读：从第 slot 个对象槽出发，按链读一个值。

        **v7 起，插件读游戏对象一律走这里。** ``read_object`` 是在启动器进程里
        对本进程地址空间裸读，游戏对象的指针在别的进程里，裸读轻则读到垃圾、
        重则直接段错误（0.9.8 真机实测 exit 139）。这条命令把读链写进 MAP 尾部
        那一条 ``WARP_READ``，由 DLL 在游戏主线程上跑 ``warp_read_chain``，
        结果经 ``vars[6]`` 回来 —— 全程在游戏进程里，不会崩。

        链的写法与 ``reads=`` 完全一致（可以写 ``{'dict': 'iter'}``：遍历链在
        代读里只回报活跃数，不展开）；``detail=True`` 时返回
        ``{"value":..., "total":..., "ok":...}``，``total`` 是遍历链的活跃数。
        读不到（槽空 / 对象已销毁 / 链走岔）返回 ``default``。
        """
        slot = int(slot)
        if slot < 0 or slot >= HOST_OBJECT_COUNT:
            raise ValueError(f"对象槽 {slot} 超出 0..{HOST_OBJECT_COUNT - 1}")
        block = self.block()
        if block is None:
            return default if not detail else {"value": default,
                                               "total": 0, "ok": False}
        spec = {"arg": 0, "kind": kind, "out": 0, "off": list(chain or ())}
        _encode_read(block.address + HOST_CMD_READ_OFFSET, spec)
        msg = self._command(CMD_READ, slot=slot, timeout=timeout)
        ok = (msg == CMD_RES_NAMES.get(0, "已执行"))
        bits = int(block.cfg.vars[6]) & 0xFFFFFFFF
        total = int(block.cfg.vars[7])
        if isinstance(kind, str) and kind.strip().lower() == "float":
            value = struct.unpack("<f", struct.pack("<I", bits))[0]
        elif isinstance(kind, str) and kind.strip().lower() in ("int", "obscured"):
            # int 落点在 C 侧是有符号的，按 32 位补码还原，别把 -1 读成 42 亿。
            value = ctypes.c_int32(bits).value
        else:
            value = bits
        if not ok:
            value = default
        if detail:
            return {"value": value, "total": total, "ok": ok, "reason": msg}
        return value

    def read_local(self, slot, chain, kind="int"):
        """在**本进程**里裸读（只对同进程地址有效，跨进程必崩）。

        留给诊断和单测用；插件要读游戏对象请用 :meth:`read`。
        """
        ptr = self.object_ptr(slot)
        if not ptr:
            return None
        return read_chain(ptr, chain, kind)

    def read_object(self, slot, chain, kind="int", timeout=2.0, default=None):
        """从第 slot 个对象槽出发读一个值（走 DLL 代读，跨进程安全）。

        旧版是 ``read_local`` 那种本进程裸读，跨进程会崩，v7 起改为代读。
        """
        return self.read(slot, chain, kind=kind, timeout=timeout,
                         default=default)

    def object_slot(self, slot, out=0, kind="int"):
        """把「从第 slot 个对象槽出发」写成一条读链，配合 ``reads=`` 使用。

        例：``host.object_slot(3, out=0)`` 得到一条从槽 3 的对象里读第一个
        int 的链；要跳偏移就自己拼 ``{'arg': 0x100 + 3, ...}``。
        """
        slot = int(slot)
        if slot < 0 or slot >= HOST_OBJECT_COUNT:
            raise ValueError(f"对象槽 {slot} 超出 0..{HOST_OBJECT_COUNT - 1}")
        return {"arg": HOST_OBJ_ARG_BASE + slot, "off": [], "deref": [],
                "out": int(out), "kind": kind}

    def write_buff_watch(self, hashes):
        """重写 buff 关注哈希表（BUF 行的开关名单）。

        ``hashes`` 是 fnv1a64 之后的 64 位哈希序列，顺序即 BUF 行 m= 掩码的
        位序；表内写 0 做哨兵（C 侧遇到 0 停止扫描）。表为空 = 没有成就
        在看 buff，C 侧读法直接放弃，连链都不走。
        """
        values = [int(h) & 0xFFFFFFFFFFFFFFFF for h in (hashes or ())]
        if len(values) > HOST_BUFF_WATCH_COUNT:
            values = values[:HOST_BUFF_WATCH_COUNT]
        block = self.block()
        if block is None:
            return 0
        addr = block.address + HOST_BUFF_WATCH_OFFSET
        for i in range(HOST_BUFF_WATCH_COUNT):
            v = values[i] if i < len(values) else 0
            ctypes.c_uint64.from_address(addr + i * HOST_BUFF_WATCH_SIZE).value = v
        return len(values)

    def _command(self, cmd_type, text="", timeout=2.0, args=(), retkind=0,
                 slot=-1, out_slot=-1):
        """往命令槽里塞一条命令，等 DLL 在游戏主线程执行完。

        真实的 Unity UI 调用必须发生在游戏主线程，所以这里不自己动手，
        只写共享内存；DLL 那边每帧（或任何钩子命中时）会把命令取走执行。

        P6 起 cmd_type 是打包字：低 8 位命令号、8-11 位 argc、12-15 位返回值
        形状、16-23 位对象槽号。参数值写 vars[0..5]（引用参数在这里就解成
        对象槽里的真实指针），返回值读 vars[6]，CALL 的引用输出槽放 vars[7]。
        """
        block = self.block()
        if block is None:
            return "宿主未注入"
        hdr = block.cfg
        payload = str(text).encode("utf-8")[:HOST_CMD_TEXT_LEN - 1]
        argc = len(args)
        hdr.cmd_text = payload
        hdr.cmd_type = (int(cmd_type) & 0xFF) | ((argc & 0xF) << 8) | \
                       ((int(retkind) & 0xF) << 12) | ((int(slot) & 0xFF) << 16)
        for i, value in enumerate(args[:6]):
            hdr.vars[i] = int(value) & 0xFFFFFFFF
        hdr.vars[7] = int(out_slot)
        hdr.cmd_result = -1
        seq = int(hdr.cmd_seq) + 1
        if seq <= 0:
            seq = 1
        hdr.cmd_seq = seq

        deadline = time.time() + float(timeout)
        while time.time() < deadline:
            if int(hdr.cmd_ack) == seq:
                rc = int(hdr.cmd_result)
                if rc == CMD_RES_BUSY:
                    # DLL 已经把命令取走了，但还没跑完 —— 接着等，别把旧值当结果。
                    time.sleep(0.005)
                    continue
                return CMD_RES_NAMES.get(rc, "失败(%d)" % rc)
            time.sleep(0.02)
        return "超时"

    @staticmethod
    def _arg_bits(value):
        """把 py 参数折成 (vars 位模式, 类型字符)。

        int/float 直接按值折位模式；槽引用元组 ``('slot', n)`` 原样带过 ——
        指针要现场从对象槽里读（对象槽是活的），由调用方用 ``object_ptr``
        解析后再进这里。
        """
        if isinstance(value, tuple) and len(value) == 2 and value[0] == "slot":
            return None, "p"       # 占位：调用方先解析再填
        if isinstance(value, float):
            return struct.unpack("<I", struct.pack("<f", value))[0], "f"
        return int(value), "i"

    def _pack_args(self, args):
        """把参数序列折成 (位模式列表, 类型后缀字符串)；槽引用解成真实指针。"""
        bits_list = []
        kinds = []
        for value in args:
            if isinstance(value, tuple) and len(value) == 2 and value[0] == "slot":
                # v10.1：vars 是 32 位整数槽，只能传槽号；指针由宿主侧查对象表。
                idx = int(value[1])
                if not 0 <= idx < HOST_OBJECT_COUNT:
                    raise ValueError(f"对象槽 {idx} 超出 0..{HOST_OBJECT_COUNT - 1}")
                bits_list.append(idx)
                kinds.append("p")
                continue
            if isinstance(value, tuple) and len(value) == 2 and value[0] == "buf":
                # v9：out 参数，占磁盘里第 n 块缓冲（游戏往里写，我们 read_buf 读）
                bits_list.append(int(value[1]) * HOST_CMD_BUF_SIZE)
                kinds.append("m")
                continue
            bits, kind = self._arg_bits(value)
            bits_list.append(bits)
            kinds.append(kind)
        return bits_list, "".join(kinds)

    def read_buf(self, index=0, size=None):
        """读命令 out 参数缓冲的第 ``index`` 块（配合 ``args=(('buf', 0),)``）。

        调用完 ``host.call(..., args=(..., ('buf', 0)))`` 之后用这个把游戏写回来的
        值类型读出来 —— 比如 ``TryCreateInstance`` 的 ``EventInstance``。
        读不到返回 ``None``。
        """
        block = self.block()
        if block is None:
            return None
        index = int(index)
        if not 0 <= index < HOST_CMD_BUF_COUNT:
            return None
        if size is None:
            size = HOST_CMD_BUF_SIZE
        size = max(0, min(int(size), HOST_CMD_BUF_SIZE))
        base = block.address + HOST_CMD_BUF_OFFSET + index * HOST_CMD_BUF_SIZE
        return ctypes.string_at(base, size)

    def clear_buf(self, index=0):
        """把 out 缓冲第 ``index`` 块清零（调带 out 参数的方法前先调它）。"""
        block = self.block()
        if block is None:
            return False
        index = int(index)
        if not 0 <= index < HOST_CMD_BUF_COUNT:
            return False
        base = block.address + HOST_CMD_BUF_OFFSET + index * HOST_CMD_BUF_SIZE
        ctypes.memset(base, 0, HOST_CMD_BUF_SIZE)
        return True

    def make(self, klass, args=(), slot=24, timeout=2.0):
        """构造一个对象放进对象槽（挂 GC 强句柄）。

        ``host.make("TMPro.TextMeshProUGUI")`` —— 0 参构造；
        ``host.make("Foo", args=[1, 2.0])`` —— 带参构造（≤6 个，走 .ctor）。
        引用参数写 ``('slot', n)`` 引用别的槽里的对象。
        返回执行结果字符串（"已执行" / "类没找到" / ...）。
        """
        packed, kinds = self._pack_args(args)
        if len(packed) > 6:
            return "参数太多（vars 最多 6 个）"
        slot = int(slot)
        if not 0 <= slot < HOST_OBJECT_COUNT:
            return f"对象槽 {slot} 超出 0..{HOST_OBJECT_COUNT - 1}"
        text = klass if not kinds else f"{klass}#{kinds}"
        return self._command(CMD_MAKE, text, timeout, args=packed, slot=slot)

    def make_str(self, text, slot=24, timeout=2.0):
        """造一个 il2cpp 字符串放进对象槽：``host.make_str("你好")``。"""
        slot = int(slot)
        if not 0 <= slot < HOST_OBJECT_COUNT:
            return f"对象槽 {slot} 超出 0..{HOST_OBJECT_COUNT - 1}"
        return self._command(CMD_STR, text, timeout, slot=slot)

    def call(self, method, slot=None, args=(), ret="int32", out_slot=-1,
             timeout=2.0, unsafe=False, sig=None):
        """调一个方法：``host.call("Foo::get_value", slot=24, ret="int32")``。

        !! danger "默认只放白名单"
            真机上「调用游戏内部方法」是能崩游戏的：0.9.10~0.9.13 三次崩溃
            全是插件调了游戏自己的方法。所以除 `SAFE_CALLS` 里那几条之外，
            这个接口默认直接拒绝，要调必须显式传 `unsafe=True` 并自己承担
            后果（`unsafe=True` 也不会被异常保护兜住）。

        Args:
            method: "Ns.Klass::Method"（不带槽 = 静态调用；带槽 = slot 里的
                对象当 this）。
            slot: this 所在的对象槽；None 表示静态调用。
            args: 参数值（int/float/槽引用元组），≤6 个。
            ret: 返回值形状 —— "int32"/"float" 解包写回（返回该值）；
                "ref" 落 out_slot 槽（返回槽号）。
            out_slot: ret="ref" 时结果落的槽。
            unsafe: 允许调用不在白名单里的方法。
            sig: 参数类型签名，用来在同名同参数个数的重载里挑对那一个。
                逗号分隔，`S`=String `B`=bool `I`=int `F`=float
                `L`=long `D`=double `V`=void，`O`/`?` 表示不校验；
                末尾 `&` 表示 byref。例：`sig="S,B,B"`、
                `sig="S,FMOD.Studio.EventInstance&"`。

        Returns:
            ret 为 int32/float 时返回数值（失败返回结果字符串）；
            ret 为 ref 时返回落好的槽号（失败返回结果字符串）。
        """
        if not unsafe and str(method).split("#")[0] not in SAFE_CALLS:
            return (f"未在安全白名单（{method}）—— 真机上调游戏方法会崩，"
                    "确认要试就传 unsafe=True")
        packed, kinds = self._pack_args(args)
        if len(packed) > 6:
            return "参数太多（vars 最多 6 个）"
        retkind = CMD_RET_NAMES.get(str(ret).lower())
        if retkind is None:
            return f"未知返回值形状 {ret!r}（int32/float/ref）"
        if slot is not None and not 0 <= int(slot) < HOST_OBJECT_COUNT:
            return f"对象槽 {slot} 超出 0..{HOST_OBJECT_COUNT - 1}"
        if retkind == CMD_RET_REF and not 0 <= int(out_slot) < HOST_OBJECT_COUNT:
            return f"输出槽 {out_slot} 超出 0..{HOST_OBJECT_COUNT - 1}"
        if sig:
            # C 侧按 '|' 切出类型串，前提是 '#' 段存在
            text = f"{method}#{kinds or 'i' * len(packed)}|{sig}"
        else:
            text = method if not kinds else f"{method}#{kinds}"
        this_slot = -1 if slot is None else int(slot)
        result = self._command(CMD_CALL, text, timeout, args=packed,
                               retkind=retkind, slot=this_slot, out_slot=out_slot)
        if result != "已执行":
            return result
        if retkind == CMD_RET_REF:
            return out_slot
        block = self.block()
        if block is None:
            return "宿主未注入"
        bits = int(block.cfg.vars[6]) & 0xFFFFFFFF
        if retkind == CMD_RET_FLOAT:
            return struct.unpack("<f", struct.pack("<I", bits))[0]
        return bits - (1 << 32) if bits >= (1 << 31) else bits

    def release(self, slot, timeout=2.0):
        """解掉对象槽上的 GC 句柄并清槽：用完构造对象后还回去。"""
        slot = int(slot)
        if not 0 <= slot < HOST_OBJECT_COUNT:
            return f"对象槽 {slot} 超出 0..{HOST_OBJECT_COUNT - 1}"
        return self._command(CMD_RELEASE, "", timeout, slot=slot)

    def popup(self, text, timeout=2.0):
        """让游戏弹出原版系统弹窗：`host.popup("你好")`。"""
        return self._command(CMD_POPUP, text, timeout)

    def kill_game(self, timeout=2.0):
        """让游戏进程立刻结束。"""
        return self._command(CMD_KILL, "", timeout)

    def set_enabled(self, on):
        """开/关「本插件」的钩子，返回是否成功。

        共用宿主时不能直接关全局开关：关掉会把别的插件的钩子一起停掉。
        所以这里只是把自己登记的钩子从总表里摘出去 / 挂回去。
        """
        owner = self._current_owner()
        entry = self._owners.get(owner)
        if entry is None:
            entry = {"hooks": [], "texts": [], "on": True}
            self._owners[owner] = entry
        entry["on"] = bool(on)
        self._sync_view(owner)
        block = self.block()
        if block is None:
            self.log("设置失败：共享内存不可用")
            return False
        self._write_config(block)
        self.log("已开启" if self.enabled else "已解除")
        return True

    def arm(self):
        return self.set_enabled(True)

    def disarm(self):
        return self.set_enabled(False)
