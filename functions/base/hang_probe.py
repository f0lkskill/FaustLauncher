"""游戏进程卡死的判定与收尾。

启动器与独立宿主只关心两件事: 游戏的窗口是不是已经不再回消息, 以及那个进程
还在不在。光看 ``IsHungAppWindow`` 不够 —— 加载场景、编译着色器时窗口同样会
显示「未响应」, 可 CPU 是满的, 那种情况不能杀。

所以判定要两条一起看: 窗口不回消息, 并且进程的 CPU 时间也停住了。真卡死的
进程正好是这样: 消息循环停了, 也没有线程在算东西。确认之后直接结束进程,
不再采线程现场 —— 之前那套采样在 2026-11 追了几天, 结论都是「主线程在等一个
不会来的唤醒」, 而进程早就不该继续存在了。
"""

import ctypes
import ctypes.wintypes as wt

_PROCESS_QUERY_INFORMATION = 0x0400
"""打开进程读 CPU 时间用的权限。"""

_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
"""受限的查询权限: 受保护进程也认这个, 和上面那个一起要。"""

_PROCESS_TERMINATE = 0x0001
"""结束进程需要的权限。"""

_STILL_ACTIVE = 259
"""``GetExitCodeProcess`` 表示「进程还在」的取值。"""


class _FILETIME(ctypes.Structure):
    """FILETIME: 64 位、单位 100 纳秒, 进程时间就是它。"""

    _fields_ = [
        ("dwLowDateTime", wt.DWORD),
        ("dwHighDateTime", wt.DWORD),
    ]


_K32 = None
"""kernel32 的函数表, 第一次用时装配。"""

_USER32 = None
"""user32 的函数表, 第一次用时装配。"""


def _kernel32():
    """装配 kernel32 里用得着的几个函数。"""

    global _K32
    if _K32 is not None:
        return _K32
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
    k32.OpenProcess.restype = wt.HANDLE
    k32.CloseHandle.argtypes = [wt.HANDLE]
    k32.CloseHandle.restype = wt.BOOL
    k32.GetProcessTimes.argtypes = [
        wt.HANDLE,
        ctypes.POINTER(_FILETIME),
        ctypes.POINTER(_FILETIME),
        ctypes.POINTER(_FILETIME),
        ctypes.POINTER(_FILETIME),
    ]
    k32.GetProcessTimes.restype = wt.BOOL
    k32.GetExitCodeProcess.argtypes = [wt.HANDLE, ctypes.POINTER(wt.DWORD)]
    k32.GetExitCodeProcess.restype = wt.BOOL
    k32.TerminateProcess.argtypes = [wt.HANDLE, wt.UINT]
    k32.TerminateProcess.restype = wt.BOOL
    _K32 = k32
    return k32


def _user32():
    """装配 user32 里用得着的几个函数。"""

    global _USER32
    if _USER32 is not None:
        return _USER32
    u32 = ctypes.WinDLL("user32", use_last_error=True)
    u32.EnumWindows.argtypes = [ctypes.c_void_p, wt.LPARAM]
    u32.EnumWindows.restype = wt.BOOL
    u32.IsWindowVisible.argtypes = [wt.HWND]
    u32.IsWindowVisible.restype = wt.BOOL
    u32.IsHungAppWindow.argtypes = [wt.HWND]
    u32.IsHungAppWindow.restype = wt.BOOL
    u32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
    u32.GetWindowThreadProcessId.restype = wt.DWORD
    _USER32 = u32
    return u32


def _visit_windows(pid: int, want_hung: bool = False) -> list:
    """枚举该进程的可见顶层窗口。

    ``want_hung`` 为真时只收「不回消息」的那些, 否则收全部可见窗口。
    返回 ``[(hwnd, is_hung), ...]``。
    """

    u32 = _user32()
    found = []
    target = int(pid)

    def _visit(hwnd, _lparam):
        owner = wt.DWORD()
        u32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value != target:
            return True
        if not u32.IsWindowVisible(hwnd):
            return True
        hung = bool(u32.IsHungAppWindow(hwnd))
        if want_hung and not hung:
            return True
        found.append((hwnd, hung))
        return True

    callback = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)(_visit)
    u32.EnumWindows(callback, 0)
    return found


def find_hung_windows(pid: int) -> list:
    """返回该进程「窗口还在但不回消息」的窗口句柄列表。"""

    try:
        return [hwnd for hwnd, _hung in _visit_windows(pid, want_hung=True)]
    except OSError:
        return []


def has_window(pid: int) -> bool:
    """该进程现在还有没有可见的顶层窗口。

    退出卡死时窗口已经销毁、进程却还赖着, 只能靠这个反向条件发现。
    """

    try:
        return bool(_visit_windows(pid))
    except OSError:
        return True


def cpu_seconds(pid: int) -> float:
    """读目标进程累计占用的 CPU 秒数（用户态 + 内核态）, 读不到返回 -1。

    用来区分两种「没响应」: 真卡死的进程没有线程在算东西, CPU 时间几乎不涨;
    加载场景、编译着色器时窗口也不回消息, 但 CPU 是满负荷的。
    """

    k32 = _kernel32()
    access = _PROCESS_QUERY_LIMITED_INFORMATION | _PROCESS_QUERY_INFORMATION
    handle = k32.OpenProcess(access, False, int(pid))
    if not handle:
        return -1.0
    try:
        times = [_FILETIME() for _ in range(4)]
        ok = k32.GetProcessTimes(
            handle,
            ctypes.byref(times[0]),
            ctypes.byref(times[1]),
            ctypes.byref(times[2]),
            ctypes.byref(times[3]),
        )
        if not ok:
            return -1.0
        total = (times[2].dwHighDateTime << 32) | times[2].dwLowDateTime
        total += (times[3].dwHighDateTime << 32) | times[3].dwLowDateTime
        return total / 10000000.0
    except OSError:
        return -1.0
    finally:
        k32.CloseHandle(handle)


def is_alive(pid: int) -> bool:
    """该进程还在不在跑。"""

    k32 = _kernel32()
    handle = k32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not handle:
        return False
    try:
        code = wt.DWORD()
        if not k32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return False
        return code.value == _STILL_ACTIVE
    finally:
        k32.CloseHandle(handle)


def terminate(pid: int) -> bool:
    """强杀该进程。已经自己退掉的按成功处理。"""

    k32 = _kernel32()
    handle = k32.OpenProcess(_PROCESS_TERMINATE, False, int(pid))
    if not handle:
        return not is_alive(pid)
    try:
        if k32.TerminateProcess(handle, 1):
            return True
        return not is_alive(pid)
    finally:
        k32.CloseHandle(handle)
