"""游戏进程卡死时的现场采集。

游戏退出时偶尔会停在「未响应」状态 —— 窗口还在、进程没死，但消息循环不再
处理任何东西。这种时候日志是最没用的东西：卡死发生在某个线程里，只有把
**每个线程当前停在哪** 取下来才能判断是谁的问题（我们注入的 DLL、别人的
DLL，还是游戏自己）。

本模块做三件事，全部只读、不需要管理员权限（同用户即可）：

* :func:`find_hung_windows` —— 用 ``IsHungAppWindow`` 找出目标进程里已经
  停止响应消息的顶层窗口；
* :func:`sample` —— 挂起每个线程、取一次 CPU 上下文，再按栈上的返回地址
  反查所属模块，得到「线程 N 停在 a.dll+0x1234，调用链 a.dll+0x1111 →
  b.dll+0x2222」这样的现场；
* :func:`write_report` —— 把现场写成文本文件，交给用户发回或自己翻。

栈回溯是**不依赖 PDB 的粗略扫描**：沿 RSP 往上逐 8 字节读，凡是落在某个
模块的代码段范围内就当候选返回地址，去掉相邻重复后最多保留 12 层。放在栈
上的旧值偶尔会混进来，但「哪个模块占了大多数帧」这一条信息已经足够定位问题
—— 卡死时我们关心的是「谁的代码在栈上」，不是精确到行。
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import os
import time

# ---------------------------------------------------------------- Win32 常量

_TH32CS_SNAPTHREAD = 0x00000004
_TH32CS_SNAPMODULE = 0x00000008
_TH32CS_SNAPMODULE32 = 0x00000010

_PROCESS_QUERY_INFORMATION = 0x0400
_PROCESS_VM_READ = 0x0010

_THREAD_SUSPEND_RESUME = 0x0002
_THREAD_GET_CONTEXT = 0x0008
_THREAD_QUERY_INFORMATION = 0x0040

_CONTEXT_AMD64 = 0x00100000
_CONTEXT_FULL = _CONTEXT_AMD64 | 0x00000001 | 0x00000002 | 0x00000004
"""CONTROL | INTEGER | SEGMENTS —— 只要得到 RIP/RSP，浮点与调试寄存器没用。"""

_CONTEXT_SIZE = 1232
_OFF_RSP = 0x98
_OFF_RIP = 0xF8

_LIST_MODULES_ALL = 0x03
_MAX_FRAMES = 12
_STACK_SCAN = 0x1200


class _MODULEENTRY32(ctypes.Structure):
    """``Module32First`` 用的结构（只关心基址、大小、名字）。"""

    _fields_ = [
        ("dwSize", wt.DWORD),
        ("th32ModuleID", wt.DWORD),
        ("th32ProcessID", wt.DWORD),
        ("GlblcntUsage", wt.DWORD),
        ("ProccntUsage", wt.DWORD),
        ("modBaseAddr", ctypes.c_void_p),
        ("modBaseSize", wt.DWORD),
        ("hModule", wt.HMODULE),
        ("szModule", ctypes.c_char * 256),
        ("szExePath", ctypes.c_char * 260),
    ]


class _MODULEINFO(ctypes.Structure):
    """``GetModuleInformation`` 的输出。"""

    _fields_ = [
        ("lpBaseOfDll", ctypes.c_void_p),
        ("SizeOfImage", wt.DWORD),
        ("EntryPoint", ctypes.c_void_p),
    ]


class _THREADENTRY32(ctypes.Structure):
    """``Thread32First`` 用的结构。"""

    _fields_ = [
        ("dwSize", wt.DWORD),
        ("cntUsage", wt.DWORD),
        ("th32ThreadID", wt.DWORD),
        ("th32OwnerProcessID", wt.DWORD),
        ("tpBasePri", ctypes.c_long),
        ("tpDeltaPri", ctypes.c_long),
        ("dwFlags", wt.DWORD),
    ]


def _kernel32():
    """延迟加载 kernel32 并声明用到的函数签名（64 位下指针必须显式声明）。"""

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
    k32.OpenProcess.restype = wt.HANDLE
    k32.CloseHandle.argtypes = [wt.HANDLE]
    k32.OpenThread.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
    k32.OpenThread.restype = wt.HANDLE
    k32.SuspendThread.argtypes = [wt.HANDLE]
    k32.SuspendThread.restype = wt.DWORD
    k32.ResumeThread.argtypes = [wt.HANDLE]
    k32.ResumeThread.restype = wt.DWORD
    k32.GetThreadContext.argtypes = [wt.HANDLE, ctypes.c_void_p]
    k32.GetThreadContext.restype = wt.BOOL
    k32.ReadProcessMemory.argtypes = [
        wt.HANDLE,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.POINTER(ctypes.c_size_t),
    ]
    k32.ReadProcessMemory.restype = wt.BOOL
    k32.CreateToolhelp32Snapshot.argtypes = [wt.DWORD, wt.DWORD]
    k32.CreateToolhelp32Snapshot.restype = wt.HANDLE
    k32.Thread32First.argtypes = [wt.HANDLE, ctypes.POINTER(_THREADENTRY32)]
    k32.Thread32Next.argtypes = [wt.HANDLE, ctypes.POINTER(_THREADENTRY32)]
    k32.Module32First.argtypes = [wt.HANDLE, ctypes.POINTER(_MODULEENTRY32)]
    k32.Module32Next.argtypes = [wt.HANDLE, ctypes.POINTER(_MODULEENTRY32)]
    return k32


def _user32():
    """窗口相关（``IsHungAppWindow`` 在 user32 里，不在 kernel32）。"""

    u32 = ctypes.WinDLL("user32", use_last_error=True)
    u32.IsHungAppWindow.argtypes = [wt.HWND]
    u32.IsHungAppWindow.restype = wt.BOOL
    u32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
    u32.GetWindowThreadProcessId.restype = wt.DWORD
    u32.EnumWindows.argtypes = [ctypes.c_void_p, wt.LPARAM]
    u32.EnumWindows.restype = wt.BOOL
    u32.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
    u32.GetWindowTextW.restype = ctypes.c_int
    u32.IsWindowVisible.argtypes = [wt.HWND]
    u32.IsWindowVisible.restype = wt.BOOL
    return u32


def _psapi():
    """``EnumProcessModules`` 一族在 psapi.dll 里。"""

    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    psapi.EnumProcessModulesEx.argtypes = [
        wt.HANDLE,
        ctypes.POINTER(wt.HMODULE),
        wt.DWORD,
        ctypes.POINTER(wt.DWORD),
        wt.DWORD,
    ]
    psapi.EnumProcessModulesEx.restype = wt.BOOL
    psapi.GetModuleInformation.argtypes = [
        wt.HANDLE,
        wt.HMODULE,
        ctypes.POINTER(_MODULEINFO),
        wt.DWORD,
    ]
    psapi.GetModuleInformation.restype = wt.BOOL
    psapi.GetModuleBaseNameW.argtypes = [wt.HANDLE, wt.HMODULE, wt.LPWSTR, wt.DWORD]
    psapi.GetModuleBaseNameW.restype = wt.DWORD
    return psapi


def list_modules(pid: int) -> list:
    """返回目标进程的模块表 ``[(基址, 大小, 文件名)]``，按基址排序。"""

    k32 = _kernel32()
    psapi = _psapi()
    hproc = k32.OpenProcess(
        _PROCESS_QUERY_INFORMATION | _PROCESS_VM_READ, False, int(pid)
    )
    if not hproc:
        return []
    try:
        needed = wt.DWORD(0)
        buf = (wt.HMODULE * 1024)()
        if not psapi.EnumProcessModulesEx(
            hproc, buf, ctypes.sizeof(buf), ctypes.byref(needed), _LIST_MODULES_ALL
        ):
            return []
        count = int(needed.value) // ctypes.sizeof(wt.HMODULE)
        out = []
        name = ctypes.create_unicode_buffer(260)
        for i in range(min(count, 1024)):
            info = _MODULEINFO()
            if not psapi.GetModuleInformation(
                hproc, buf[i], ctypes.byref(info), ctypes.sizeof(info)
            ):
                continue
            if not psapi.GetModuleBaseNameW(hproc, buf[i], name, 260):
                continue
            out.append((int(info.lpBaseOfDll or 0), int(info.SizeOfImage), name.value))
        out.sort()
        return out
    finally:
        k32.CloseHandle(hproc)


def _thread_ids(pid: int) -> list:
    """列出属于该进程的线程 id。"""

    k32 = _kernel32()
    snap = k32.CreateToolhelp32Snapshot(_TH32CS_SNAPTHREAD, 0)
    if snap in (None, 0, -1):
        return []
    ids = []
    try:
        entry = _THREADENTRY32()
        entry.dwSize = ctypes.sizeof(entry)
        ok = k32.Thread32First(snap, ctypes.byref(entry))
        while ok:
            if int(entry.th32OwnerProcessID) == int(pid):
                ids.append(int(entry.th32ThreadID))
            ok = k32.Thread32Next(snap, ctypes.byref(entry))
    finally:
        k32.CloseHandle(snap)
    return ids


def _module_at(addr: int, modules: list) -> str:
    """把地址翻译成 ``模块名+偏移``；不在任何模块里返回空串。"""

    if not addr:
        return ""
    for base, size, name in modules:
        if base <= addr < base + size:
            return "%s+0x%X" % (name, addr - base)
    return ""


def _read_memory(k32, hproc, addr: int, size: int) -> bytes:
    """读目标进程内存，读不到就返回空串。"""

    buf = ctypes.create_string_buffer(size)
    got = ctypes.c_size_t(0)
    if not k32.ReadProcessMemory(
        hproc, ctypes.c_void_p(addr), buf, size, ctypes.byref(got)
    ):
        return b""
    return buf.raw[: got.value]


def _stack_frames(k32, hproc, sp: int, modules: list) -> list:
    """沿 RSP 向上扫一段栈，把像返回地址的值挑出来（粗略回溯）。"""

    if not sp:
        return []
    raw = _read_memory(k32, hproc, sp, _STACK_SCAN)
    if len(raw) < 8:
        return []
    frames = []
    for off in range(0, len(raw) - 8 + 1, 8):
        value = int.from_bytes(raw[off : off + 8], "little")
        where = _module_at(value, modules)
        if not where:
            continue
        if frames and frames[-1] == where:
            continue
        frames.append(where)
        if len(frames) >= _MAX_FRAMES:
            break
    return frames


def _sample_thread(k32, hproc, tid: int, modules: list) -> dict:
    """取单个线程的现场：RIP/RSP + 粗略调用链。"""

    hthread = k32.OpenThread(
        _THREAD_SUSPEND_RESUME | _THREAD_GET_CONTEXT | _THREAD_QUERY_INFORMATION,
        False,
        int(tid),
    )
    if not hthread:
        return {"tid": tid, "error": "打不开线程"}
    try:
        k32.SuspendThread(hthread)
        try:
            ctx = (ctypes.c_char * _CONTEXT_SIZE)()
            ctypes.memmove(ctx, b"\x00" * _CONTEXT_SIZE, _CONTEXT_SIZE)
            ctypes.c_uint32.from_buffer(ctx, 0x30).value = _CONTEXT_FULL
            if not k32.GetThreadContext(hthread, ctypes.byref(ctx)):
                return {"tid": tid, "error": "取不到上下文"}
            rip = ctypes.c_uint64.from_buffer(ctx, _OFF_RIP).value
            rsp = ctypes.c_uint64.from_buffer(ctx, _OFF_RSP).value
        finally:
            k32.ResumeThread(hthread)
        frames = _stack_frames(k32, hproc, rsp, modules)
        return {
            "tid": tid,
            "rip": _module_at(rip, modules) or "0x%X" % rip,
            "frames": frames,
        }
    finally:
        k32.CloseHandle(hthread)


def sample(pid: int, max_threads: int = 64) -> dict:
    """采集整个进程的线程现场。

    返回 ``{"pid", "modules", "threads", "error"}``；``threads`` 每项是
    ``{"tid", "rip", "frames"}``，失败项带 ``error``。
    """

    k32 = _kernel32()
    modules = list_modules(pid)
    hproc = k32.OpenProcess(
        _PROCESS_QUERY_INFORMATION | _PROCESS_VM_READ, False, int(pid)
    )
    if not hproc:
        return {"pid": pid, "modules": [], "threads": [], "error": "打不开进程"}
    try:
        threads = []
        for tid in _thread_ids(pid)[:max_threads]:
            threads.append(_sample_thread(k32, hproc, tid, modules))
        return {"pid": pid, "modules": modules, "threads": threads, "error": ""}
    finally:
        k32.CloseHandle(hproc)


def find_hung_windows(pid: int) -> list:
    """返回该进程里「已停止响应」的顶层窗口 ``[(hwnd, 标题)]``。"""

    u32 = _user32()
    found = []

    def _visit(hwnd, _lparam):
        owner = wt.DWORD(0)
        u32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if int(owner.value) != int(pid):
            return True
        if not u32.IsWindowVisible(hwnd):
            return True
        if not u32.IsHungAppWindow(hwnd):
            return True
        title = ctypes.create_unicode_buffer(256)
        u32.GetWindowTextW(hwnd, title, 256)
        found.append((int(hwnd), title.value))
        return True

    # 回调必须在本函数内一直活着，否则 EnumWindows 会调到已回收的 thunk。
    callback = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)(_visit)
    u32.EnumWindows(callback, 0)
    return found


def _format(data: dict) -> str:
    """把采集结果排版成给人看的文本。"""

    lines = []
    lines.append("==== 进程 %s 线程现场 %s ====" % (data["pid"], time.strftime("%Y-%m-%d %H:%M:%S")))
    if data["error"]:
        lines.append("采集失败: " + data["error"])
        return "\n".join(lines)
    lines.append("模块 %d 个，线程 %d 个" % (len(data["modules"]), len(data["threads"])))
    lines.append("")
    for item in data["threads"]:
        if item.get("error"):
            lines.append("线程 %d: %s" % (item["tid"], item["error"]))
            continue
        lines.append("线程 %d  当前 %s" % (item["tid"], item["rip"]))
        for frame in item["frames"]:
            lines.append("    " + frame)
        lines.append("")
    return "\n".join(lines)


def _cache_root() -> str:
    """报告默认落在 ``<启动器根目录>/cache/hang``（打包版就是 exe 同级）。"""

    try:
        from functions.base.common.path_utils import get_app_root

        return os.path.join(get_app_root(), "cache", "hang")
    except Exception:
        here = os.path.dirname(os.path.abspath(__file__))
        return os.path.join(os.path.dirname(os.path.dirname(here)), "cache", "hang")


def save_report(data: dict, out_dir: str = "", tag: str = "hang") -> str:
    """把已经采好的现场落盘，返回报告路径（失败返回空串）。"""

    if data.get("error") and not data.get("threads"):
        return ""
    root = out_dir or _cache_root()
    os.makedirs(root, exist_ok=True)
    name = "%s_%s_%s.txt" % (tag, time.strftime("%Y%m%d_%H%M%S"), data.get("pid", 0))
    path = os.path.join(root, name)
    try:
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(_format(data))
    except OSError:
        return ""
    return path


def write_report(pid: int, out_dir: str = "", tag: str = "hang") -> str:
    """采集并落盘，返回报告路径（失败返回空串）。"""

    return save_report(sample(pid), out_dir=out_dir, tag=tag)


def summarize(data: dict, top: int = 4) -> str:
    """把现场压成一句话：谁在栈上出现得最多（用来看「卡在谁的代码里」）。"""

    counter = {}
    for item in data.get("threads", []):
        for frame in item.get("frames", [])[:top]:
            name = frame.split("+")[0]
            counter[name] = counter.get(name, 0) + 1
    if not counter:
        return ""
    ranked = sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))
    return "  ".join("%s×%d" % (name, count) for name, count in ranked[:5])
