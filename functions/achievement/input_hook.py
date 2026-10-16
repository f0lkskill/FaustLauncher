
import ctypes
import ctypes.wintypes as wt
import threading

LRESULT = ctypes.c_ssize_t
WPARAM = ctypes.c_size_t
LPARAM = ctypes.c_ssize_t
HHOOK = ctypes.c_void_p
HWND = wt.HWND
HINSTANCE = wt.HINSTANCE
DWORD = wt.DWORD
LPMSG = wt.LPMSG
POINT = wt.POINT

try:
    HHOOK = wt.HHOOK
except AttributeError:
    pass

WH_KEYBOARD_LL = 13
WH_MOUSE_LL = 14
WM_KEYDOWN = 0x0100
WM_LBUTTONDOWN = 0x0201
WM_RBUTTONDOWN = 0x0204
VK_P = 0x50
WM_QUIT = 0x0012

GAME_EXE = "LimbusCompany.exe"

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

_SetWindowsHookExW = _user32.SetWindowsHookExW
_SetWindowsHookExW.argtypes = [ctypes.c_int, ctypes.c_void_p, HINSTANCE, DWORD]
_SetWindowsHookExW.restype = HHOOK

_CallNextHookEx = _user32.CallNextHookEx
_CallNextHookEx.argtypes = [HHOOK, ctypes.c_int, WPARAM, LPARAM]
_CallNextHookEx.restype = LRESULT

_UnhookWindowsHookEx = _user32.UnhookWindowsHookEx
_UnhookWindowsHookEx.argtypes = [HHOOK]
_UnhookWindowsHookEx.restype = wt.BOOL

_GetMessageW = _user32.GetMessageW
_GetMessageW.argtypes = [wt.LPMSG, wt.HWND, wt.UINT, wt.UINT]
_GetMessageW.restype = wt.BOOL

_GetForegroundWindow = _user32.GetForegroundWindow
_GetForegroundWindow.restype = wt.HWND

_GetWindowThreadProcessId = _user32.GetWindowThreadProcessId
_GetWindowThreadProcessId.argtypes = [wt.HWND, wt.LPDWORD]

_GetModuleHandleW = _kernel32.GetModuleHandleW
_GetModuleHandleW.argtypes = [wt.LPCWSTR]
_GetModuleHandleW.restype = wt.HMODULE

_OpenProcess = _kernel32.OpenProcess
_OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
_OpenProcess.restype = wt.HANDLE

_QueryFullProcessImageNameW = _kernel32.QueryFullProcessImageNameW
_QueryFullProcessImageNameW.argtypes = [wt.HANDLE, wt.DWORD, wt.LPWSTR, ctypes.POINTER(wt.DWORD)]
_QueryFullProcessImageNameW.restype = wt.BOOL

_CloseHandle = _kernel32.CloseHandle
_CloseHandle.argtypes = [wt.HANDLE]
_CloseHandle.restype = wt.BOOL

class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wt.DWORD),
        ("scanCode", wt.DWORD),
        ("flags", wt.DWORD),
        ("time", wt.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]

class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("pt", wt.POINT),
        ("mouseData", wt.DWORD),
        ("flags", wt.DWORD),
        ("time", wt.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]

class InputCounter:

    def __init__(self):
        self._running = False
        self._thread: threading.Thread | None = None
        self._kbd_hook = None
        self._mouse_hook = None
        self._kbd_cb = None
        self._mouse_cb = None
        self._state = None
        self._lock = threading.Lock()

    def _inc_p(self):
        from functions.achievement.achievements import get_state
        try:
            with self._lock:
                s = get_state()
                s.press_p_count += 1
        except Exception:
            pass

    def _inc_click(self):
        from functions.achievement.achievements import get_state
        try:
            with self._lock:
                s = get_state()
                s.click_count += 1
        except Exception:
            pass

    @staticmethod
    def _game_foreground() -> bool:
        try:
            hwnd = _GetForegroundWindow()
            pid = wt.DWORD(0)
            _GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value == 0:
                return False

            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            h = _kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
            if not h:
                return False
            try:
                buf = ctypes.create_unicode_buffer(4096)
                size = wt.DWORD(4096)
                if _kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                    exe = buf.value.lower()
                    return exe.endswith(GAME_EXE.lower())
            finally:
                _kernel32.CloseHandle(h)
        except Exception:
            pass
        return False

    def _kbd_proc(self, nCode, wParam, lParam):
        if nCode >= 0 and wParam == WM_KEYDOWN:
            kb = ctypes.cast(lParam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
            if kb.vkCode == VK_P:
                if self._game_foreground():
                    self._inc_p()
        return _CallNextHookEx(self._kbd_hook, nCode, wParam, lParam)

    def _mouse_proc(self, nCode, wParam, lParam):
        if nCode >= 0 and wParam in (WM_LBUTTONDOWN, WM_RBUTTONDOWN):
            if self._game_foreground():
                self._inc_click()
        return _CallNextHookEx(self._mouse_hook, nCode, wParam, lParam)

    def _thread_main(self):
        try:
            module = _GetModuleHandleW(None)
        except Exception:
            module = None

        self._kbd_cb = ctypes.WINFUNCTYPE(
            LRESULT, ctypes.c_int, WPARAM, LPARAM)(self._kbd_proc)
        self._mouse_cb = ctypes.WINFUNCTYPE(
            LRESULT, ctypes.c_int, WPARAM, LPARAM)(self._mouse_proc)

        self._kbd_hook = _SetWindowsHookExW(
            WH_KEYBOARD_LL, self._kbd_cb, module, 0)
        self._mouse_hook = _SetWindowsHookExW(
            WH_MOUSE_LL, self._mouse_cb, module, 0)

        msg = wt.MSG()
        while self._running:
            r = _GetMessageW(ctypes.byref(msg), None, 0, 0)
            if r in (0, -1):
                break

        if self._kbd_hook:
            _UnhookWindowsHookEx(self._kbd_hook)
        if self._mouse_hook:
            _UnhookWindowsHookEx(self._mouse_hook)

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._thread_main, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)

_counter: InputCounter | None = None

def start_input_monitoring() -> InputCounter:
    global _counter
    if _counter is None:
        _counter = InputCounter()
        _counter.start()
    return _counter

def stop_input_monitoring():
    global _counter
    if _counter:
        _counter.stop()
        _counter = None
