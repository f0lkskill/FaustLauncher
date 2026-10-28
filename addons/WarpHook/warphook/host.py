"""warp.plugin.Host：一块共享映射的配置端。

插件用它登记「哪个类的哪个方法要被钩住」以及「钩住之后可能说什么」，
全部写进 warp_host.dll 认得的那块内存；DLL 侧只负责按表装配。
"""

import ctypes
import threading
import os, sys, time

from . import env
from .base import (
    SharedMap,
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
HOST_VERSION = 1
HOST_MAP_DEFAULT = "Local\\WarpHost_Default"
HOST_MAP_ENV = "WARP_HOST_MAP"
HOST_DLL_NAME = "warp_host.dll"

HOST_MAX_HOOKS = 16
HOST_MAX_TEXTS = 256
HOST_TEXT_LEN = 128
HOST_KLASS_LEN = 48
HOST_METHOD_LEN = 48
HOST_LOG_LEN = 48
HOST_EXPORT_COUNT = 13
HOST_NAME_MAX = 64
HOST_VAR_COUNT = 8
HOST_CMD_TEXT_LEN = 256

# 命令类型：py 一行调用 → 游戏主线程执行
CMD_NONE = 0
CMD_POPUP = 1     # 弹原版系统弹窗
CMD_KILL = 2      # 结束游戏进程

HOST_HEADER_SIZE = 432   # 160 状态头 + 命令槽（4 个 int + 256 字节文本）
HOST_HOOK_OFFSET = HOST_HEADER_SIZE
HOST_HOOK_SIZE = 256
HOST_TEXTS_OFFSET = HOST_HOOK_OFFSET + HOST_MAX_HOOKS * HOST_HOOK_SIZE
HOST_TEXT_SIZE = HOST_TEXT_LEN
HOST_EXPORTS_OFFSET = HOST_TEXTS_OFFSET + HOST_MAX_TEXTS * HOST_TEXT_SIZE
HOST_EV_CTRL_OFFSET = HOST_EXPORTS_OFFSET + HOST_EXPORT_COUNT * HOST_NAME_MAX
HOST_EV_CTRL_SIZE = 16
HOST_EVENTS_OFFSET = HOST_EV_CTRL_OFFSET + HOST_EV_CTRL_SIZE
HOST_EVENT_COUNT = 512
HOST_EVENT_SIZE = 28
HOST_MAP_BYTES = HOST_EVENTS_OFFSET + HOST_EVENT_COUNT * HOST_EVENT_SIZE

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
    ]

# 动作位（与 warp_host.c 的 WARP_ACT_* 一致）
ACT_POPUP = 0x01     # 弹游戏原版系统弹窗
ACT_PANEL = 0x02     # 弹自建面板（宿主内置，后续版本）
ACT_KILL = 0x04      # 结束游戏进程

# 钩子标志（与 WARP_HF_* 一致）
HF_BLOCK = 0x01      # 跳过原方法（用于「拦截」类插件）
HF_ONCE = 0x02       # 只触发一次

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
    """钩子表的一项，256 字节。"""

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
        ("reserved", ctypes.c_int32 * 2),
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
    """
    path = globals().get("__file__") or ""
    if path and os.path.isfile(path):
        return os.path.dirname(os.path.abspath(path))
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


def host_alive(block):
    """宿主 DLL 是否已经在目标进程里跑（看心跳是否新鲜）。"""
    if block is None:
        return False
    try:
        if int(block.cfg.magic) != HOST_MAGIC:
            return False
        if not int(block.cfg.ga_found):
            return False
        return abs(int(_tick32()) - int(block.cfg.heartbeat)) < 10000
    except Exception:  # noqa: BLE001
        return False


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

        钩子按注册顺序首尾相接；文案按插件分段，段尾补一个空串当界标
        （DLL 的 warp_pick_text 从 text_base 起扫到空槽为止）。
        """
        active = [(name, e) for name, e in self._owners.items() if e["on"]]

        hooks = []
        texts = []
        for owner_name, entry in active:
            base = len(texts)
            for hook in entry["hooks"]:
                if len(hooks) >= HOST_MAX_HOOKS:
                    break
                item = dict(hook)
                item["text_base"] = base
                item["owner"] = owner_name
                hooks.append(item)
            # 先到先得，但不截断：每个插件能装多少装多少，只受池子剩余容量约束
            # （留一格给段尾空串当界标）。池子够大时谁都不会被砍。
            room = HOST_MAX_TEXTS - len(texts) - 1
            if room <= 0:
                continue
            texts.extend(entry["texts"][:room])
            texts.append("")
        return hooks[:HOST_MAX_HOOKS], texts[:HOST_MAX_TEXTS]

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
        """打开（必要时创建）宿主共享内存，返回 SharedMap。"""
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
        """把钩子表、文案池、导出名表写进共享内存。"""
        base = block.address
        hdr = block.cfg
        # 只要还有任何一个插件是开着的，宿主就继续工作
        hdr.enabled = 1 if any(e["on"] for e in self._owners.values()) else 0
        hdr.dedupe_ms = self.dedupe_ms

        hooks, texts = self._layout()

        # 钩子表
        for i in range(HOST_MAX_HOOKS):
            slot = base + HOST_HOOK_OFFSET + i * HOST_HOOK_SIZE
            # 先记下旧槽位：DLL 会把「一次性钩子已经触发过」的标记写回 flags
            # 的最高位。反复 push 配置时若把这个标记清掉，同一个一次性钩子
            # （例如 AutoBoom）会被重新武装、再触发一次。
            old_flags = ctypes.c_int32.from_address(
                slot + HostHook.flags.offset).value
            old_klass = _read_fixed(slot + HostHook.klass.offset, HOST_KLASS_LEN)
            old_method = _read_fixed(slot + HostHook.method.offset, HOST_METHOD_LEN)
            ctypes.memset(slot, 0, HOST_HOOK_SIZE)
            if i >= len(hooks):
                continue
            hook = hooks[i] or {}
            _write_fixed(slot + HostHook.klass.offset,
                         hook.get("klass", ""), HOST_KLASS_LEN)
            _write_fixed(slot + HostHook.method.offset,
                         hook.get("method", ""), HOST_METHOD_LEN)
            _write_fixed(slot + HostHook.probe_class.offset,
                         hook.get("probe_class", ""), HOST_KLASS_LEN)
            _write_fixed(slot + HostHook.probe_method.offset,
                         hook.get("probe_method", ""), HOST_METHOD_LEN)
            for name, default in (("argc", 0), ("event_id", i), ("every", 1),
                                  ("chance", 100), ("actions", ACT_POPUP),
                                  ("flags", 0), ("hold_ms", 0), ("delay_ms", 0),
                                  ("guard_index", -1), ("guard_value", 0),
                                  ("probe_index", 0), ("probe_slot", -1),
                                  ("guard_var", -1), ("text_base", 0)):
                value = hook.get(name, default)
                try:
                    value = int(value)
                except (TypeError, ValueError):
                    value = default
                ctypes.c_int32.from_address(slot + getattr(HostHook, name).offset).value = value
            # 同一个钩子（类名与方法都没变）如果 DLL 已经标记过「触发过」，
            # 把标记补回去，一次性钩子才不会重复触发。
            if (old_flags & 0x100) and not hook.get("_reset"):
                same = (old_klass == hook.get("klass", "")
                        and old_method == hook.get("method", ""))
                if same:
                    addr = slot + HostHook.flags.offset
                    ctypes.c_int32.from_address(addr).value |= 0x100

        # 文案池
        for i in range(HOST_MAX_TEXTS):
            slot = base + HOST_TEXTS_OFFSET + i * HOST_TEXT_SIZE
            if i < len(texts):
                _write_fixed(slot, texts[i], HOST_TEXT_SIZE)
            else:
                ctypes.memset(slot, 0, HOST_TEXT_SIZE)

        # 导出名表：顺序错了会拿到别人的函数指针，所以统一走 ensure_exports，
        # 它内部负责把标准名映射成混淆名（这里必须传标准名，别再自己映射一遍）
        ensure_exports(block, HOST_EXPORT_ORDER, HOST_EXPORTS_OFFSET, HOST_NAME_MAX)

    def hook(self, klass, method, argc=0, block=False, actions=None,
             probe=None, guard=None, event=None, **extra):
        """登记一条钩子 —— 用法就是一次普通调用，不是填表格。

        ``klass`` / ``method`` 是要挂的方法（``argc`` 按「不含 this」数），
        ``block=True`` 表示拦下原方法，``probe=(类, 方法, 参数序号, 写到哪个槽)``
        表示顺手把某个参数对象的属性读进 ``vars[]``，
        ``guard=(槽号, 值)`` 表示那个槽等于该值时彻底放行，
        ``event=事件号`` 表示每次命中都往事件队列塞一条（见 :meth:`events`）。

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
        if probe is not None:
            p_class, p_method, p_index, p_slot = (list(probe) + [0, 0])[:4]
            item.update({"probe_class": p_class, "probe_method": p_method,
                         "probe_index": int(p_index), "probe_slot": int(p_slot)})
        if guard is not None:
            g_slot, g_value = list(guard)[:2]
            item.update({"guard_var": int(g_slot), "guard_value": int(g_value)})
        if event is not None:
            item["event_id"] = int(event)
            item["actions"] = int(item.get("actions", 0)) | HOST_ACT_EVENT
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
        ``reserved[1]``（真的把原方法拦下来的次数，参数门放行那次不算）。
        """
        owner = owner or self._current_owner()
        off = HostHook.reserved.offset + (4 if blocked else 0)
        total = 0
        base = ctypes.addressof(cfg) + HOST_HOOK_OFFSET
        hooks, _ = self._layout()
        for i, hook in enumerate(hooks):
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
                "d": int(slot.d),
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
        """关掉映射视图。不碰任何线程 —— 线程归插件自己管。"""
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
    def _command(self, cmd_type, text="", timeout=2.0):
        """往命令槽里塞一条命令，等 DLL 在游戏主线程执行完。

        真实的 Unity UI 调用必须发生在游戏主线程，所以这里不自己动手，
        只写共享内存；DLL 那边每帧（或任何钩子命中时）会把命令取走执行。
        """
        block = self.block()
        if block is None:
            return "宿主未注入"
        hdr = block.cfg
        payload = str(text).encode("utf-8")[:HOST_CMD_TEXT_LEN - 1]
        hdr.cmd_text = payload
        hdr.cmd_type = int(cmd_type)
        hdr.cmd_result = -1
        seq = int(hdr.cmd_seq) + 1
        if seq <= 0:
            seq = 1
        hdr.cmd_seq = seq

        deadline = time.time() + float(timeout)
        while time.time() < deadline:
            if int(hdr.cmd_ack) == seq:
                rc = int(hdr.cmd_result)
                return "已执行" if rc == 0 else "失败(%d)" % rc
            time.sleep(0.02)
        return "超时"

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
