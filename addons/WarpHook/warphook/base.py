"""WarpHook 底层：Win32 调用、共享内存、il2cpp 导出名解析、注入。

这里没有任何业务概念 —— 只负责「找到游戏、把 DLL 塞进去、按名字读写那块内存」。
业务语义在 host.py（钩子表）与 game.py（抽卡）里。
"""

import ctypes
import os
import sys
import threading
import time
from ctypes import wintypes

from . import env

WARP_HOOK_VERSION = env.WARP_HOOK_VERSION

GAME_PROCESS = "LimbusCompany.exe"
GAME_DLL_NAME = "GameAssembly.dll"

# 注入时机：等游戏进程出现 / 等 GameAssembly.dll 加载完，各给一个上限
WAIT_GAME_TIMEOUT = 300.0
WAIT_DLL_TIMEOUT = 120.0
POLL_INTERVAL = 0.5

# ========== Win32 基础 ==========

_LPVOID = ctypes.c_void_p
_HANDLE = _LPVOID
_LPCWSTR = ctypes.c_wchar_p

FILE_MAP_ALL_ACCESS = 0x000F001F
PAGE_READWRITE = 0x04
INVALID_HANDLE_VALUE = _HANDLE(-1).value
PROCESS_ACCESS = 0x0002 | 0x0400 | 0x0008 | 0x0020 | 0x0010
MEM_COMMIT_RESERVE = 0x3000
MEM_RELEASE = 0x8000
TH32CS_SNAPPROCESS = 0x00000002
TH32CS_SNAPMODULE = 0x00000008
TH32CS_SNAPMODULE32 = 0x00000010

# 每个插件各自 new 一个 CDLL 实例。绝不能用 ctypes.windll.kernel32：
# 那是 ctypes 内部共享的全局实例，argtypes 挂在函数对象上，两个插件各自定义
# 同名结构体（PROCESSENTRY32W）时会互相覆盖，表现为
# "expected LP_PROCESSENTRY32W instance instead of pointer to PROCESSENTRY32W"。
_kernel32 = ctypes.WinDLL("kernel32.dll")

_kernel32.CreateFileMappingW.restype = _HANDLE
_kernel32.CreateFileMappingW.argtypes = [_HANDLE, _LPVOID, wintypes.DWORD,
                                         wintypes.DWORD, wintypes.DWORD, _LPCWSTR]
_kernel32.OpenFileMappingW.restype = _HANDLE
_kernel32.OpenFileMappingW.argtypes = [wintypes.DWORD, wintypes.BOOL, _LPCWSTR]
_kernel32.MapViewOfFile.restype = _LPVOID
_kernel32.MapViewOfFile.argtypes = [_HANDLE, wintypes.DWORD, wintypes.DWORD,
                                    wintypes.DWORD, ctypes.c_size_t]
_kernel32.UnmapViewOfFile.argtypes = [_LPVOID]
_kernel32.CloseHandle.argtypes = [_HANDLE]
_kernel32.OpenProcess.restype = _HANDLE
_kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
_kernel32.VirtualAllocEx.restype = _LPVOID
_kernel32.VirtualAllocEx.argtypes = [_HANDLE, _LPVOID, ctypes.c_size_t,
                                     wintypes.DWORD, wintypes.DWORD]
_kernel32.VirtualFreeEx.argtypes = [_HANDLE, _LPVOID, ctypes.c_size_t, wintypes.DWORD]
_kernel32.WriteProcessMemory.argtypes = [_HANDLE, _LPVOID, _LPVOID,
                                         ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
_kernel32.CreateRemoteThread.restype = _HANDLE
_kernel32.CreateRemoteThread.argtypes = [_HANDLE, _LPVOID, ctypes.c_size_t, _LPVOID,
                                         _LPVOID, wintypes.DWORD, _LPVOID]
_kernel32.WaitForSingleObject.argtypes = [_HANDLE, wintypes.DWORD]
_kernel32.GetExitCodeThread.argtypes = [_HANDLE, ctypes.POINTER(wintypes.DWORD)]
_kernel32.GetModuleHandleW.restype = _HANDLE
_kernel32.GetModuleHandleW.argtypes = [_LPCWSTR]
_kernel32.GetProcAddress.restype = _LPVOID
_kernel32.GetProcAddress.argtypes = [_HANDLE, ctypes.c_char_p]
_kernel32.CreateToolhelp32Snapshot.restype = _HANDLE
_kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", ctypes.c_wchar * 260),
    ]


class MODULEENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("th32ModuleID", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("GlblcntUsage", wintypes.DWORD),
        ("ProccntUsage", wintypes.DWORD),
        ("modBaseAddr", ctypes.POINTER(ctypes.c_byte)),
        ("modBaseSize", wintypes.DWORD),
        ("hModule", wintypes.HMODULE),
        ("szModule", ctypes.c_wchar * 256),
        ("szExePath", ctypes.c_wchar * 260),
    ]


# 快照句柄是 64 位的，必须显式声明 argtypes，否则 ctypes 按 int(32 位) 传参会
# 抛 OverflowError: int too long to convert。
_kernel32.Process32FirstW.argtypes = [_HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
_kernel32.Process32NextW.argtypes = [_HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
_kernel32.Module32FirstW.argtypes = [_HANDLE, ctypes.POINTER(MODULEENTRY32W)]
_kernel32.Module32NextW.argtypes = [_HANDLE, ctypes.POINTER(MODULEENTRY32W)]


def _valid_snapshot(handle):
    """CreateToolhelp32Snapshot 失败时返回 INVALID_HANDLE_VALUE（按 64 位无符号比较）。"""
    return bool(handle) and (handle & 0xFFFFFFFFFFFFFFFF) != 0xFFFFFFFFFFFFFFFF


def log(message, prefix="[WarpHook]"):
    """统一前缀日志，插件可传自己的前缀便于区分。"""
    print(f"{prefix} {message}")


# ========== warp.inject：进程与注入 ==========


def find_game_pid(process=GAME_PROCESS):
    """按进程名找游戏 PID；找不到返回 ``None``。

    Args:
        process: 可执行文件名，默认 ``LimbusCompany.exe``。
    """
    snapshot = _kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not _valid_snapshot(snapshot):
        return None
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        if not _kernel32.Process32FirstW(snapshot, ctypes.byref(entry)):
            return None
        target = str(process).lower()
        while True:
            if str(entry.szExeFile).lower() == target:
                return int(entry.th32ProcessID)
            if not _kernel32.Process32NextW(snapshot, ctypes.byref(entry)):
                break
    finally:
        _kernel32.CloseHandle(snapshot)
    return None


def has_gameassembly(pid, module=GAME_DLL_NAME):
    """检查目标进程里 ``GameAssembly.dll`` 是否已加载。

    注入必须等它加载完，否则 DLL 里 ``il2cpp_*`` 取不到任何东西。
    """
    snapshot = _kernel32.CreateToolhelp32Snapshot(
        TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32, pid)
    if not _valid_snapshot(snapshot):
        return False
    try:
        entry = MODULEENTRY32W()
        entry.dwSize = ctypes.sizeof(MODULEENTRY32W)
        if not _kernel32.Module32FirstW(snapshot, ctypes.byref(entry)):
            return False
        target = str(module).lower()
        while True:
            if str(entry.szModule).lower() == target:
                return True
            if not _kernel32.Module32NextW(snapshot, ctypes.byref(entry)):
                break
    finally:
        _kernel32.CloseHandle(snapshot)
    return False


def wait_for_game(timeout=WAIT_GAME_TIMEOUT, stop_event=None, process=GAME_PROCESS):
    """等游戏进程出现，返回 PID 或 ``None``（超时/被取消）。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if stop_event is not None and stop_event.is_set():
            return None
        pid = find_game_pid(process)
        if pid is not None:
            return pid
        time.sleep(POLL_INTERVAL)
    return None


def wait_for_gameassembly(pid, timeout=WAIT_DLL_TIMEOUT, stop_event=None,
                          module=GAME_DLL_NAME):
    """等目标进程把 ``GameAssembly.dll`` 加载完，返回是否等到。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if stop_event is not None and stop_event.is_set():
            return False
        if has_gameassembly(pid, module):
            return True
        time.sleep(POLL_INTERVAL)
    return False


def inject_dll(pid, dll_path):
    """把 DLL 注入到 pid（CreateRemoteThread + LoadLibraryW）。

    Args:
        pid: 目标进程 ID。
        dll_path: DLL 的**绝对路径**（相对路径在目标进程里会被解释成对方的工作
            目录，几乎必然加载失败）。

    Returns:
        ``(ok, message)``。常见失败原因：启动器权限不足、杀毒软件拦截。
    """
    if not os.path.isfile(dll_path):
        return False, f"找不到 {dll_path}"

    proc = _kernel32.OpenProcess(PROCESS_ACCESS, False, pid)
    if not proc:
        return False, "打开游戏进程失败（请用管理员权限运行启动器）"

    remote = None
    try:
        path_w = ctypes.c_wchar_p(dll_path)
        size = (len(dll_path) + 1) * 2
        remote = _kernel32.VirtualAllocEx(proc, None, size,
                                          MEM_COMMIT_RESERVE, PAGE_READWRITE)
        if not remote:
            return False, "VirtualAllocEx 失败"

        written = ctypes.c_size_t()
        if not _kernel32.WriteProcessMemory(proc, remote, path_w, size,
                                            ctypes.byref(written)):
            return False, "WriteProcessMemory 失败"

        kernel32 = _kernel32.GetModuleHandleW("kernel32.dll")
        load_library = _kernel32.GetProcAddress(kernel32, b"LoadLibraryW")
        if not load_library:
            return False, "无法定位 LoadLibraryW"

        thread = _kernel32.CreateRemoteThread(proc, None, 0, load_library,
                                              remote, 0, None)
        if not thread:
            return False, "CreateRemoteThread 失败（杀毒软件可能拦截）"
        code = wintypes.DWORD()
        try:
            _kernel32.WaitForSingleObject(thread, 10000)
            _kernel32.GetExitCodeThread(thread, ctypes.byref(code))
        finally:
            _kernel32.CloseHandle(thread)

        if not code.value:
            return False, "DLL 加载失败（远程线程退出码为 0）"
        return True, f"已注入 {os.path.basename(dll_path)} (PID {pid})"
    finally:
        if remote:
            _kernel32.VirtualFreeEx(proc, remote, 0, MEM_RELEASE)
        _kernel32.CloseHandle(proc)


# ========== warp.shm：共享内存 ==========


class SharedMap:
    """一块共享内存的句柄。

    DLL 侧按同样的名字 ``MapViewOfFile`` 打开，把这块内存 cast 成自己的配置
    结构体，就得到了一个跨进程的双向通道：Python 写配置/台词/导出名表，DLL
    读；DLL 写状态/计数/错误码，Python 读。

    典型用法::

        block = WARP.shm.open("Local\\\\My_Plugin", 1024, MyConfig)
        block.cfg.enabled = 1
        block.write_text(MyConfig, "popup_text", "你好", 256)
        block.write_table(368, IL2CPP_EXPORTS, 64)

    Attributes:
        name: 共享内存名字（``Local\\`` 前缀只在本会话内可见，够用）。
        size: 字节数。
        cfg: 映射后按 ``struct_cls`` 解释出来的结构体实例。
    """

    __slots__ = ('name', 'size', 'struct_cls', '_handle', '_view', 'cfg')

    def __init__(self, name, size, struct_cls, handle, view, cfg):
        self.name = name
        self.size = size
        self.struct_cls = struct_cls
        self._handle = handle
        self._view = view
        self.cfg = cfg

    @property
    def address(self):
        """共享内存起始地址（``ctypes.addressof(cfg)``）。"""
        return ctypes.addressof(self.cfg)

    def write_text(self, field, value, size):
        """把 UTF-8 文本写进结构体里定长的 ``c_char * N`` 字段。

        ctypes 读取结构体内的 ``c_char * N`` 字段会直接返回 bytes（不可赋值），
        所以这里按字段偏移往裸内存写：先清零，再 memmove，尾部天然留一个 0。
        超长文案截断到 ``size - 1`` 字节，不会抛异常。
        """
        raw = str(value).encode('utf-8')[:size - 1]
        base = ctypes.addressof(self.cfg) + getattr(self.struct_cls, field).offset
        ctypes.memset(base, 0, size)
        if raw:
            ctypes.memmove(base, raw, len(raw))

    def write_table(self, offset, names, name_max=64):
        """把一串名字（通常是混淆导出名）写进结构体后面的定长槽位。

        Args:
            offset: 相对共享内存起始地址的字节偏移。
            names: 名字序列，空串表示该项跳过（清零即可）。
            name_max: 每个槽位宽度。

        Returns:
            实际写入的非空项数。
        """
        base = ctypes.addressof(self.cfg) + offset
        written = 0
        for index, name in enumerate(names):
            raw = str(name or "").encode("ascii", "ignore")[:name_max - 1]
            slot = base + index * name_max
            ctypes.memset(slot, 0, name_max)
            if raw:
                ctypes.memmove(slot, raw, len(raw))
                written += 1
        return written

    def read_table(self, offset, count, name_max=64):
        """读回槽位里非空的项数（用来确认 DLL 侧拿到了多少项）。"""
        base = ctypes.addressof(self.cfg) + offset
        mapped = 0
        for index in range(count):
            raw = ctypes.string_at(base + index * name_max, name_max)
            if raw.split(b'\0', 1)[0]:
                mapped += 1
        return mapped

    def read_text(self, field, size):
        """读回结构体里的定长文本字段。"""
        base = ctypes.addressof(self.cfg) + getattr(self.struct_cls, field).offset
        raw = ctypes.string_at(base, size)
        return raw.split(b'\0', 1)[0].decode('utf-8', 'replace')

    def close(self):
        """解除映射并关句柄；之后这个对象不可再用。"""
        try:
            if self._view:
                _kernel32.UnmapViewOfFile(self._view)
            if self._handle:
                _kernel32.CloseHandle(self._handle)
        finally:
            self._view = None
            self._handle = None


# 同名共享内存只建一次，避免多个插件重复映射同一块
_maps = {}


def shm_open(name, size, struct_cls, magic_field=None, magic_value=None,
             init=None):
    """建立或打开共享内存，返回 :class:`SharedMap`；失败返回 ``None``。

    Args:
        name: 共享内存名，例如 ``Local\\\\My_Plugin``。
        size: 总字节数（配置结构体 + 各种表）。
        struct_cls: 配置部分的 ctypes 结构体类型。
        magic_field: 可选，结构体里用作「是否已初始化」标记的字段名。
        magic_value: 该标记应有的值；不相等时调用 ``init(cfg)`` 初始化。
        init: 可选的初始化回调。

    Returns:
        :class:`SharedMap` 或 ``None``（建不起来时）。
    """
    cached = _maps.get(name)
    if cached is not None:
        return cached

    handle = _kernel32.OpenFileMappingW(FILE_MAP_ALL_ACCESS, False, name)
    if not handle:
        handle = _kernel32.CreateFileMappingW(
            INVALID_HANDLE_VALUE, None, PAGE_READWRITE, 0, size, name)
    if not handle:
        log(f"创建共享内存失败（错误码 {ctypes.get_last_error()}）", "[WarpHook.shm]")
        return None

    view = _kernel32.MapViewOfFile(handle, FILE_MAP_ALL_ACCESS, 0, 0, size)
    if not view:
        _kernel32.CloseHandle(handle)
        log("映射共享内存失败", "[WarpHook.shm]")
        return None

    cfg = struct_cls.from_address(view)
    if magic_field and magic_value is not None:
        if getattr(cfg, magic_field) != magic_value:
            setattr(cfg, magic_field, magic_value)
            if callable(init):
                try:
                    init(cfg)
                except Exception as exc:  # noqa: BLE001 - 初始化失败也要把句柄交出去
                    log(f"共享内存初始化回调失败: {exc}", "[WarpHook.shm]")

    block = SharedMap(name, size, struct_cls, handle, view, cfg)
    _maps[name] = block
    return block


# ========== warp.il2cpp：混淆导出名解析 ==========


_export_cache = None


def _addon_root():
    """插件根目录（含 ``addon_info.json`` 的那层）。

    拆包之后 ``__file__`` 在 ``warphook/`` 子目录里，直接 ``dirname`` 会指到子包，
    所以统一往上找到 ``addon_info.json`` 为止 —— 宿主 DLL、基准名字表这些跟着
    插件走的资源都在那一层。
    """
    here = os.path.dirname(os.path.abspath(__file__))
    parent = here
    for _ in range(4):
        if os.path.isfile(os.path.join(parent, "addon_info.json")):
            return parent
        parent = os.path.dirname(parent)
    return os.path.dirname(here)


def names_table():
    """返回 WarpHook 自带的那份 il2cpp 基准名字表路径。

    表放在插件根目录（``il2cpp-api-names.txt``），因此 WarpHook 完全自包含。
    文件缺失时返回空串，交给 :func:`functions.base.il2cpp_exports.resolve`
    用它自己的默认来源（新版启动器内置了同一张表）。
    """
    path = os.path.join(_addon_root(), "il2cpp-api-names.txt")
    return path if os.path.isfile(path) else ""


def resolve_exports(refresh=False):
    """取 ``{il2cpp 标准名: 混淆导出名}``，失败返回空字典。

    当前版本的 GameAssembly.dll 把 ``il2cpp_*`` 导出改名成了随机串，DLL 里按
    标准名 GetProcAddress 会全部落空。启动器的
    :mod:`functions.base.il2cpp_exports` 能算出这份映射（按 GameAssembly 的
    sha256 缓存，同一版本只扫一次），这里直接复用并进程内缓存。

    Args:
        refresh: 忽略缓存重新计算。

    Returns:
        映射字典；算不出来时是空字典（DLL 会退回按标准名取，老版本游戏仍可用）。
    """
    global _export_cache
    if _export_cache is not None and not refresh:
        return dict(_export_cache)
    try:
        from functions.base import il2cpp_exports as ix

        result = ix.resolve(refresh=refresh, names_path=names_table())
        if result.get("ok"):
            _export_cache = dict(result.get("mapping") or {})
        else:
            _export_cache = {}
            log(f"il2cpp 导出映射不可用：{result.get('reason') or '未知原因'}",
                "[WarpHook.il2cpp]")
    except Exception as exc:  # noqa: BLE001 - 映射失败只影响弹窗，不影响其他功能
        _export_cache = {}
        log(f"读取 il2cpp 导出映射失败：{exc}", "[WarpHook.il2cpp]")
    return dict(_export_cache)


def export_mapped(names, block, offset, count=None, name_max=64):
    """读回共享内存里已写入的导出名项数，方便插件显示「8/8 已映射」。"""
    if block is None:
        return 0
    return block.read_table(offset, count if count is not None else len(names),
                            name_max)


def ensure_exports(block, names, offset, name_max=64):
    """把 ``{标准名: 混淆名}`` 按 ``names`` 的固定顺序写进共享内存槽位。

    插件只需要声明「C 侧按什么顺序取这 8 个（或 13 个）导出」，解析与填充由这里
    统一完成 —— 顺序决定了 DLL 拿到的是谁的函数指针，所以不能各自实现一遍。

    Args:
        block: :class:`SharedMap`。
        names: 标准导出名序列，顺序必须与 C 侧 ``kExportNames`` 完全一致。
        offset: 名字表相对共享内存起始地址的偏移（通常是 ``config_size``）。
        name_max: 每个槽位宽度。

    Returns:
        实际写入的非空项数；映射不可用时返回 0。
    """
    if block is None:
        return 0
    aliases = resolve_exports()
    if not aliases:
        log("il2cpp 导出映射为空，依赖 il2cpp 的功能可能不可用", "[WarpHook.il2cpp]")
        return 0
    written = block.write_table(
        offset, [aliases.get(name, '') for name in names], name_max)
    if written < len(names):
        log(f"导出名只填了 {written}/{len(names)} 项", "[WarpHook.il2cpp]")
    return written

def _tick32():
    """GetTickCount64 的低 32 位，与宿主 DLL 的心跳比较同源。"""
    try:
        k32 = ctypes.WinDLL("kernel32.dll")
        k32.GetTickCount64.restype = ctypes.c_ulonglong
        return int(k32.GetTickCount64()) & 0xFFFFFFFF
    except Exception:
        return int(time.monotonic() * 1000) & 0xFFFFFFFF


# ----------------------------------------------------------------------
# 在 Python 侧按读取链读内存
# ----------------------------------------------------------------------
# 钩子里的读取链是 C 侧在命中那一刻跑的。对象槽把「那一刻的对象」留了下来，
# 但要过一会儿再来读（老链路的 cache_self 那几种读法就是这样的），就得在
# Python 里再走一遍同样的链。规则完全一致：每步加偏移、按需解引用、容器取
# 元素，落点按 kind 解释。
#
# 与 C 侧唯一的区别是安全性：C 侧每一步都问 VirtualQuery，这里也一样 ——
# Python 进程读非法地址是直接段错误的，没有异常可捕获，所以校验必须自己做。

class _MEMORY_BASIC_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BaseAddress", ctypes.c_void_p),
        ("AllocationBase", ctypes.c_void_p),
        ("AllocationProtect", wintypes.DWORD),
        ("RegionSize", ctypes.c_size_t),
        ("State", wintypes.DWORD),
        ("Protect", wintypes.DWORD),
        ("Type", wintypes.DWORD),
    ]


_vq_lib = ctypes.WinDLL("kernel32.dll")
_vq = _vq_lib.VirtualQuery
_vq.restype = ctypes.c_size_t
_vq.argtypes = [ctypes.c_void_p,
                             ctypes.POINTER(_MEMORY_BASIC_INFORMATION),
                             ctypes.c_size_t]

_MEM_COMMIT = 0x1000
_PAGE_GUARD = 0x100
_PAGE_NOACCESS = 0x01
_PAGE_READABLE = 0x02 | 0x04 | 0x08 | 0x20 | 0x40 | 0x80

STEP_PLAIN = 0
STEP_DEREF = 1
STEP_LIST = 2
STEP_ARRAY = 3

_STEP_NAMES = {'plain': 0, 'deref': 1, 'list': 2, 'array': 3}


def can_read(addr, size=8):
    """这段地址能不能读。与 C 侧 `warp_can_read` 同一套判据。"""
    addr = int(addr or 0)
    if addr <= 0 or size <= 0:
        return False
    mbi = _MEMORY_BASIC_INFORMATION()
    cur = addr
    end = addr + size
    while cur < end:
        if not _vq(ctypes.c_void_p(cur), ctypes.byref(mbi), ctypes.sizeof(mbi)):
            return False
        if mbi.State != _MEM_COMMIT:
            return False
        if mbi.Protect & (_PAGE_GUARD | _PAGE_NOACCESS):
            return False
        if not mbi.Protect & _PAGE_READABLE:
            return False
        base = int(mbi.BaseAddress or 0)
        span = base + int(mbi.RegionSize) - cur
        if span <= 0:
            return False
        cur += span
    return True


def _step_code(value):
    if isinstance(value, str):
        return _STEP_NAMES.get(value.lower(), STEP_DEREF)
    if isinstance(value, bool):
        return STEP_DEREF if value else STEP_PLAIN
    try:
        return int(value) & 0x3
    except (TypeError, ValueError):
        return STEP_DEREF


def read_chain(addr, chain, kind='int'):
    """从 addr 出发按链读一个值，读不到返回 None。

    chain 的每一项与 ``Host.hook(reads=...)`` 的写法完全一致：``(偏移, 是否解引用)``
    或 ``{'off': .., 'deref': ..}``；``deref`` 也可以写 ``'list'`` / ``'array'``。
    链长为 0 表示「addr 本身就是值」。
    """
    steps = []
    for item in list(chain or ()):
        if isinstance(item, dict):
            if 'list' in item or 'array' in item:
                code = STEP_LIST if 'list' in item else STEP_ARRAY
                steps.append((int(item.get('list', item.get('array', 0))), code, None))
            else:
                steps.append((int(item.get('off', 0)),
                              _step_code(item.get('deref', True)),
                              item.get('index')))
        else:
            steps.append((int(item[0]), _step_code(item[1] if len(item) > 1 else True),
                          None))
    if not steps:
        return int(addr) if kind != 'float' else _as_float(int(addr))

    cur = int(addr or 0)
    if not can_read(cur, 8):
        return None
    for off, step, index in steps:
        if step == STEP_LIST or step == STEP_ARRAY:
            if not can_read(cur, 0x20):
                return None
            if step == STEP_LIST:
                arr = ctypes.c_uint64.from_address(cur + 0x10).value
                count = ctypes.c_int32.from_address(cur + 0x18).value
            else:
                arr = cur
                count = ctypes.c_int32.from_address(cur + 0x18).value
            idx = int(index if index is not None else off)
            if not arr or idx < 0 or idx >= count:
                return None
            if not can_read(arr + 0x20 + idx * 8, 8):
                return None
            cur = ctypes.c_uint64.from_address(arr + 0x20 + idx * 8).value
            continue
        cur = cur + off
        if step == STEP_DEREF:
            if not can_read(cur, 8):
                return None
            cur = ctypes.c_uint64.from_address(cur).value
            if not cur:
                return None
    if not can_read(cur, 16):
        return None
    if kind == 'float':
        return ctypes.c_float.from_address(cur).value
    if kind == 'bool':
        return 1 if ctypes.c_uint8.from_address(cur).value else 0
    if kind == 'ptr':
        return ctypes.c_uint64.from_address(cur).value
    if kind == 'obscured':
        key = ctypes.c_int32.from_address(cur).value
        hidden = ctypes.c_int32.from_address(cur + 4).value
        return hidden ^ key
    return ctypes.c_int32.from_address(cur).value


def _as_float(bits):
    return ctypes.c_float.from_address(ctypes.addressof(ctypes.c_int32(bits))).value
