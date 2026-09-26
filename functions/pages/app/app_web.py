"""FaustLauncher Web UI — pywebview 主窗口桥接层

现代 UI 入口 (main.py --web-ui):
- pywebview 6 要求 webview.start() 运行在主线程, 与 tkinter 主循环互斥,
  故 web 模式完全独立于 tkinter, 不创建任何 Tk 窗口。
- 业务逻辑全部复用: settings_manager / download_and_launch / AddonManager /
  ModManager / web_update 等, 仅 UI 层替换为 Web 前端 (html/app/)。
- 前端通过 window.pywebview.api.* 调用本模块 AppApi;
  后端通过 evaluate_js 推送日志/进度/事件到前端。
"""

import base64
import json
import os
import sys
import threading
import time
from io import BytesIO
from functions.base.common.json_io import read_json, write_json

if getattr(sys, "frozen", False):
    # 打包环境下模块在临时解压目录, 以 exe 所在目录为项目根目录
    _PROJECT_ROOT = os.path.dirname(os.path.abspath(sys.executable))
else:
    _PROJECT_ROOT = os.path.abspath(os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

def _resolve_html_path():
    """定位前端页面: onedir 打包时数据位于 _internal/ 下"""
    if getattr(sys, "frozen", False):
        for candidate in (
            os.path.join(_PROJECT_ROOT, "_internal", "html", "app", "index.html"),
            os.path.join(_PROJECT_ROOT, "html", "app", "index.html"),
        ):
            if os.path.exists(candidate):
                return candidate
    return os.path.join(_PROJECT_ROOT, "html", "app", "index.html")


def _feature_image_uri(image_name):
    """读取快捷方式卡片素材为压缩后的 data URI (pywebview http 服务器拒绝相对路径, 需内嵌)

    皮肤 <skin>/assets/launcher/features/<name> 存在时优先使用, 否则回退默认素材。
    """
    if not image_name:
        return ""
    p = _launcher_asset_file(_active_skin_id(), "features", image_name)
    if not p:
        for root in (
            os.path.join(_PROJECT_ROOT, "assets", "images", "features"),
            os.path.join(_PROJECT_ROOT, "_internal", "assets", "images", "features"),
        ):
            cand = os.path.join(root, image_name)
            if os.path.isfile(cand):
                p = cand
                break
    if not p:
        return ""
    try:
        from PIL import Image
        from io import BytesIO as _Bio
        img = Image.open(p)
        img.thumbnail((720, 720), Image.Resampling.LANCZOS)
        if img.mode in ("RGBA", "LA", "P"):
            buf = _Bio()
            img.convert("RGBA").save(buf, "PNG")
        else:
            buf = _Bio()
            img.convert("RGB").save(buf, "JPEG", quality=80)
        return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception:
        return ""


def _tool_image_uri(image_name):
    """读取工具卡片素材为压缩后的 data URI (从 assets/images/tools 读取)

    皮肤 <skin>/assets/launcher/tools/<name> 存在时优先使用。
    """
    if not image_name:
        return ""
    p = _launcher_asset_file(_active_skin_id(), "tools", image_name)
    if not p:
        for root in (
            os.path.join(_PROJECT_ROOT, "assets", "images", "tools"),
            os.path.join(_PROJECT_ROOT, "_internal", "assets", "images", "tools"),
        ):
            cand = os.path.join(root, image_name)
            if os.path.isfile(cand):
                p = cand
                break
    if not p:
        return ""
    try:
        from PIL import Image
        from io import BytesIO as _Bio
        img = Image.open(p)
        img.thumbnail((720, 720), Image.Resampling.LANCZOS)
        if img.mode in ("RGBA", "LA", "P"):
            buf = _Bio()
            img.convert("RGBA").save(buf, "PNG")
        else:
            buf = _Bio()
            img.convert("RGB").save(buf, "JPEG", quality=80)
        return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception:
        return ""


HTML_PATH = _resolve_html_path()

_log_lock = threading.Lock()
_log_lines: list[str] = []


def _msgbox(title, text, is_error=True):
    """原生消息框 (ctypes MessageBoxW), 不依赖 tkinter"""
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(
            None, text, title, 0x10 if is_error else 0x40)
    except Exception:
        pass


MAIN_WINDOW_TITLE = "Faust Launcher"


def _find_main_hwnd():
    """查找已运行实例的主窗口句柄 (找不到返回 0)"""
    try:
        import ctypes
        return int(ctypes.windll.user32.FindWindowW(None, MAIN_WINDOW_TITLE) or 0)
    except Exception:
        return 0


def activate_existing_window(hwnd):
    """把已运行实例的窗口带到用户面前 (重复双击 exe 时调用)。

    不再弹系统警告框, 而是直接让老实例的窗口现身, 按窗口当前状态分三种处理:
      1. 已隐藏(最小化到托盘 / SW_HIDE) -> ShowWindow(SW_SHOWNORMAL) 恢复显示;
      2. 已最小化(图标化)              -> ShowWindow(SW_RESTORE) 还原;
      3. 可见且未最小化                -> 只"置顶一次"(HWND_TOPMOST 后立刻恢复
         HWND_NOTOPMOST), 不改动尺寸/位置/最大化状态, 让用户能立刻看到它。

    这里只调用 Win32 窗口 API, 天然可跨进程操作别的进程的窗口, 因此第二个实例
    无需与第一个实例通信即可把它叫出来。

    返回 True 表示找到了窗口并已尝试激活。
    """
    if not hwnd:
        return False
    try:
        import ctypes
        user32 = ctypes.windll.user32
        SW_SHOWNORMAL, SW_RESTORE = 1, 9
        HWND_TOPMOST, HWND_NOTOPMOST = -1, -2
        SWP_NOMOVE, SWP_NOSIZE, SWP_SHOWWINDOW = 0x0002, 0x0001, 0x0040
        _no_move_size = SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW

        if not user32.IsWindowVisible(hwnd):
            # 隐藏(含托盘驻留) -> 显示 (SW_SHOWNORMAL 与托盘"显示窗口"用的是同一种)
            user32.ShowWindow(hwnd, SW_SHOWNORMAL)
        elif user32.IsIconic(hwnd):
            # 已最小化 -> 还原
            user32.ShowWindow(hwnd, SW_RESTORE)
        else:
            # 已经看得见 -> 置顶一次, 让用户不用去任务栏里翻
            user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, _no_move_size)
            user32.SetWindowPos(hwnd, HWND_NOTOPMOST, 0, 0, 0, 0, _no_move_size)

        # 拉到前台。Windows 的前台锁可能拒绝跨进程抢焦点, 此时退化为闪动任务栏
        # 按钮, 保证用户至少能注意到窗口在哪。
        brought = False
        try:
            brought = bool(user32.SetForegroundWindow(hwnd))
        except Exception:
            brought = False
        if not brought:
            try:
                user32.FlashWindow(hwnd, True)
            except Exception:
                pass
        return True
    except Exception:
        return False


def check_single_instance():
    """检测是否已有实例在运行。

    有 -> 激活那个实例的窗口(显示/还原/置顶)并返回 True, 由调用方直接退出本进程。
    这里刻意不弹任何系统消息框: 用户重复双击只为"看到那个窗口", 不是在等一句提示。
    """
    hwnd = _find_main_hwnd()
    if hwnd:
        activate_existing_window(hwnd)
        return True
    return False


def _win32_hwnd(window):
    """获取主窗口原生句柄 (线程安全)"""
    try:
        import ctypes
        # 必须使用外层 BrowserForm 句柄。BrowserView 是 WebView2 子控件，
        # 对它设置主窗口样式/拖动策略不会影响顶层窗口。
        native = getattr(window, "native", None)
        handle = getattr(native, "Handle", None)
        if handle is not None:
            try:
                return int(handle.ToInt64())
            except Exception:
                return int(handle.ToInt32())
        return int(ctypes.windll.user32.FindWindowW(None, MAIN_WINDOW_TITLE))
    except Exception:
        return 0


_faust_wndproc = None   # 保持窗口过程引用, 防 GC
_faust_enum_proc = None
_faust_subclass_hwnds = set()
_system_shutdown_requested = False


def _disable_system_drag(window):
    """彻底禁止 frameless 窗口整窗系统拖动, 仅标题栏 JS 拖动有效.
    组合: 移除 WS_THICKFRAME + SetWindowPos(SWP_FRAMECHANGED) 强制 DWM 重算 +
    SetWindowSubclass 拦截 WM_NCHITTEST → HTCLIENT."""
    global _faust_wndproc, _faust_enum_proc, _faust_subclass_hwnds
    try:
        import ctypes
        from ctypes import wintypes
        hwnd = _win32_hwnd(window)
        if not hwnd:
            return
        # 1) 移除可调大小边框
        GWL_STYLE = -16
        WS_CAPTION = 0x00C00000
        WS_THICKFRAME = 0x00040000
        WS_MINIMIZEBOX = 0x00020000
        WS_MAXIMIZEBOX = 0x00010000
        style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_STYLE)
        style &= ~(WS_CAPTION | WS_THICKFRAME | WS_MINIMIZEBOX | WS_MAXIMIZEBOX)
        ctypes.windll.user32.SetWindowLongW(hwnd, GWL_STYLE, style)
        # 2) 强制 DWM 重算窗口帧 (不含 WS_THICKFRAME, 不再提供系统拖动/调整)
        SWP_FRAMECHANGED = 0x0020
        SWP_NOMOVE = 0x0002
        SWP_NOSIZE = 0x0001
        SWP_NOZORDER = 0x0004
        ctypes.windll.user32.SetWindowPos(
            hwnd, None, 0, 0, 0, 0,
            SWP_FRAMECHANGED | SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER)
        # 3) SetWindowSubclass 拦截系统命中测试。整个窗口都返回 HTCLIENT；
        # 标题栏移动只由前端 move_window 处理，不能让 DWM 再启动全局拖动。
        WM_NCHITTEST = 0x0084
        WM_NCLBUTTONDOWN = 0x00A1
        WM_NCLBUTTONDBLCLK = 0x00A3
        WM_SYSCOMMAND = 0x0112
        WM_QUERYENDSESSION = 0x0011
        WM_ENDSESSION = 0x0016
        SC_MOVE = 0xF010
        HTCLIENT = 1
        SUBCLASSID = 0xFA01
        SUBCLASSPROC = ctypes.WINFUNCTYPE(
            ctypes.c_ssize_t, wintypes.HWND, ctypes.c_uint,
            wintypes.WPARAM, wintypes.LPARAM,
            ctypes.c_size_t, ctypes.c_size_t)

        subclass_proc = ctypes.windll.comctl32.DefSubclassProc
        subclass_proc.argtypes = [wintypes.HWND, ctypes.c_uint,
                                   wintypes.WPARAM, wintypes.LPARAM]
        subclass_proc.restype = ctypes.c_ssize_t

        def _proc(hwnd, msg, wParam, lParam, uIdSubclass, dwRefData):
            global _system_shutdown_requested
            if msg == WM_QUERYENDSESSION:
                # 系统重启/注销时允许会话结束，不能被托盘驻留策略拦截。
                _system_shutdown_requested = True
                return 1
            if msg == WM_ENDSESSION and wParam:
                _system_shutdown_requested = True
                threading.Thread(target=_terminate_now, daemon=True).start()
                return 0
            if msg == WM_NCHITTEST:
                return HTCLIENT
            # 即使系统/窗口管理器绕过命中测试，也不允许启动系统移动。
            # 标题栏移动完全由前端 move_window + SetWindowPos 实现，不受此拦截影响。
            if msg in (WM_NCLBUTTONDOWN, WM_NCLBUTTONDBLCLK):
                return 0
            if msg == WM_SYSCOMMAND and (int(wParam) & 0xFFF0) == SC_MOVE:
                return 0
            return subclass_proc(hwnd, msg, wParam, lParam)

        _faust_wndproc = SUBCLASSPROC(_proc)
        set_subclass = ctypes.windll.comctl32.SetWindowSubclass
        set_subclass.argtypes = [wintypes.HWND, SUBCLASSPROC,
                                  ctypes.c_size_t, ctypes.c_size_t]
        set_subclass.restype = wintypes.BOOL
        set_subclass(hwnd, _faust_wndproc, SUBCLASSID, 0)
        _faust_subclass_hwnds.add(hwnd)
        # WebView2 自己也是子窗口，顶层 Form 的命中测试不一定覆盖它。
        # 对所有现有子窗口安装同一个子类过程，保证客户区始终不可拖。
        enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def _enum_child(child_hwnd, _lparam):
            try:
                set_subclass(child_hwnd, _faust_wndproc, SUBCLASSID, 0)
                _faust_subclass_hwnds.add(child_hwnd)
            except Exception:
                pass
            return True

        _faust_enum_proc = enum_proc(_enum_child)
        ctypes.windll.user32.EnumChildWindows(hwnd, _faust_enum_proc, 0)
    except Exception:
        pass


_layered_ready = set()   # 记录已添加 WS_EX_LAYERED 的 hwnd (幂等, 不重复添加)


def _ensure_layered(hwnd):
    """首次调用时为窗口添加 WS_EX_LAYERED 样式 (用于 SetLayeredWindowAttributes 渐变).
    幂等: 同一 hwnd 只添加一次, 避免反复修改样式导致闪烁."""
    if hwnd in _layered_ready:
        return True
    try:
        import ctypes
        GWL_EXSTYLE = -20
        WS_EX_LAYERED = 0x80000
        style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_LAYERED)
        _layered_ready.add(hwnd)
        return True
    except Exception:
        return False


def _clear_layered(hwnd):
    """移除 WS_EX_LAYERED 样式。

    分层窗口 (WS_EX_LAYERED + SetLayeredWindowAttributes) 会让整个窗口走
    DWM 的软件合成路径 —— 内容是逐帧拷贝上去的, 于是切页/动画时极易撕裂、
    残留旧画面。启动渐入到 alpha=255 之后这个样式就不再需要了, 必须摘掉,
    让窗口回到正常的 GPU 合成路径。
    (再次需要淡入淡出时, _ensure_layered 会重新加上。)
    """
    try:
        import ctypes
        GWL_EXSTYLE = -20
        WS_EX_LAYERED = 0x80000
        style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        if style & WS_EX_LAYERED:
            ctypes.windll.user32.SetWindowLongW(
                hwnd, GWL_EXSTYLE, style & ~WS_EX_LAYERED)
            _layered_ready.discard(hwnd)
            # 强制 DWM 重算窗口帧, 否则样式变更可能延迟生效
            SWP_FRAMECHANGED, SWP_NOMOVE, SWP_NOSIZE, SWP_NOZORDER = 0x20, 2, 1, 4
            ctypes.windll.user32.SetWindowPos(
                hwnd, None, 0, 0, 0, 0,
                SWP_FRAMECHANGED | SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER)
    except Exception:
        pass


def _set_window_alpha(hwnd, alpha):
    """设置窗口透明度 (0~255). 需先调用 _ensure_layered 添加 WS_EX_LAYERED."""
    try:
        import ctypes
        LWA_ALPHA = 0x2
        ctypes.windll.user32.SetLayeredWindowAttributes(
            hwnd, 0, max(0, min(255, int(alpha))), LWA_ALPHA)
    except Exception:
        pass


def _fade_window(hwnd, start, end, step=20, delay=0.01):
    """同步阻塞式透明度渐变 (在后台线程调用)."""
    import time
    if start == end:
        _set_window_alpha(hwnd, end)
        return
    a = start
    while True:
        _set_window_alpha(hwnd, a)
        time.sleep(delay)
        if start < end:
            a = min(a + step, end)
            if a >= end:
                break
        else:
            a = max(a - step, end)
            if a <= end:
                break
    _set_window_alpha(hwnd, end)


def _win32_show_window_impl(window, show=True):
    """用 Win32 ShowWindow 显示/隐藏主窗口 (线程安全, 供托盘/关闭/预加载显示共用;
    不用 AnimateWindow: 其对 WebView2 内容渲染有干扰, 会显示纯色)"""
    try:
        import ctypes
        hwnd = _win32_hwnd(window)
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 1 if show else 0)  # SW_SHOWNORMAL / SW_HIDE
            if show:
                ctypes.windll.user32.SetForegroundWindow(hwnd)
            return True
    except Exception:
        pass
    return False


def _patch_network_timeouts():
    """给所有 requests 请求补默认超时, 防止断网/网络缓慢时无限阻塞线程 (卡死);
    同时禁用 InsecureRequestWarning (云端笔记等源使用 verify=False 的合法请求)"""
    try:
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    except Exception:
        pass
    try:
        import requests
        if getattr(requests, "_faust_web_patched", False):
            return
        _orig_get = requests.get
        _orig_post = requests.post

        def _get(url, *args, **kwargs):
            kwargs.setdefault("timeout", (5, 15))
            return _orig_get(url, *args, **kwargs)

        def _post(url, *args, **kwargs):
            kwargs.setdefault("timeout", (5, 15))
            return _orig_post(url, *args, **kwargs)

        requests.get = _get
        requests.post = _post
        requests._faust_web_patched = True # type: ignore
    except Exception:
        pass


def _patch_tk_dialogs(push_event):
    """把 tkinter.messagebox / simpledialog 全部拦截转发到 Web 前端。

    旧代码里的模态 Tk 对话框在 pywebview 模式下会阻塞后台线程 (表现为"卡死"),
    这里统一替换为前端 toast 通知, 并返回安全默认值:
    - show*            -> True   (仅提示)
    - askyesno/askokcancel/askretrycancel/askquestion/askyesnocancel
                       -> False/'no' (视为用户拒绝, 绝不自动执行破坏性操作)
    - simpledialog     -> None   (视为用户取消)
    """
    try:
        import tkinter.messagebox as mb
    except Exception:
        return

    _DEFAULTS = {
        "showinfo": True, "showwarning": True, "showerror": True,
        "askyesno": False, "askokcancel": False, "askretrycancel": False,
        "askquestion": "no", "askyesnocancel": "no",
    }
    for _kind, _default in _DEFAULTS.items():
        def _make_handler(kind, default):
            def _handler(*args, **kwargs):
                title = args[0] if len(args) > 0 else kwargs.get("title", "提示")
                message = args[1] if len(args) > 1 else kwargs.get("message", "")
                try:
                    push_event("dialog", {
                        "kind": kind, "title": str(title), "message": str(message),
                    })
                except Exception:
                    pass
                return default
            return _handler
        setattr(mb, _kind, _make_handler(_kind, _default))

    try:
        import tkinter.simpledialog as sd
        sd.askstring = lambda *a, **k: None
        sd.askinteger = lambda *a, **k: None
        sd.askfloat = lambda *a, **k: None
    except Exception:
        pass


# ============================================================
# 日志重定向: print/stdout/stderr -> Web 前端终端
# ============================================================

class WebLogRedirector:
    """把 stdout/stderr 重定向到 Web 前端迷你终端 (保留 ANSI 转义序列由前端解析)"""

    def __init__(self, pusher):
        self.pusher = pusher          # callable(text)
        self.original_stdout = sys.stdout
        self.original_stderr = sys.stderr
        self.buffer = ""

    def write(self, message):
        if not message:
            return
        try:
            self.original_stdout.write(message)
            self.original_stdout.flush()
        except Exception:
            pass
        try:
            from functions.base.log_manager import log_message
            log_message(message)
        except Exception:
            pass
        self.buffer += message
        while "\n" in self.buffer:
            line, self.buffer = self.buffer.split("\n", 1)
            if line.strip():
                self._push(line.rstrip("\r"))
        # 无换行的部分行 (如进度条) 按行缓存, 前端定时刷新
        if self.buffer.strip():
            pass

    def flush(self):
        if self.buffer.strip():
            self._push(self.buffer.rstrip("\r\n"))
            self.buffer = ""

    def _push(self, line):
        if line.startswith("|"):
            return
        with _log_lock:
            _log_lines.append(line)
        try:
            self.pusher(line)
        except Exception:
            pass

    def start(self):
        sys.stdout = self
        sys.stderr = self

    def stop(self):
        self.flush()
        sys.stdout = self.original_stdout
        sys.stderr = self.original_stderr


# 无头下载进度 shim: 兼容 DownloadGUI 的鸭子类型接口
class _VarHook:
    """模拟 tkinter StringVar 的 .set()/.get(), 值变化时回调"""

    def __init__(self, on_change=None, initial=""):
        self._value = initial
        self._on_change = on_change

    def set(self, value):
        self._value = str(value)
        if self._on_change:
            try:
                self._on_change(self._value)
            except Exception:
                pass

    def get(self):
        return self._value

    def trace(self, *args):
        pass


class _RootShim:
    """模拟下载 GUI 所需的 root 接口: after/destroy/deiconify/update_idletasks"""

    def __init__(self, owner):
        self._owner = owner
        self._closed = False

    def after(self, ms, cb):
        def _run():
            if not self._closed:
                try:
                    cb()
                except Exception:
                    pass
        threading.Timer(ms / 1000.0, _run).start()

    def destroy(self):
        self._closed = True
        self._owner.is_downloading = False

    def deiconify(self):
        pass

    def update_idletasks(self):
        pass


class HeadlessDownloadGUI:
    """无头下载进度容器, 与 DownloadGUI 接口兼容, 进度推送到 Web 前端。

    通过 monkeypatch zeroasso_download.main_gui / DownloadGUI 注入,
    使 download_and_launch 流水线在 web 模式下无需 tkinter 窗口。
    """

    def __init__(self, config_path: str = "", auto_start: bool = True,
                 download_func=None, task: str = None): # type: ignore
        self.config_path = config_path
        self.is_downloading = True
        self.task = task
        self._push_progress = None
        self._on_done = None
        self.current_file_var = _VarHook(self._on_status, "初始化下载组件...")
        self.progress_var = _VarHook(initial="0")
        self.progress_text_var = _VarHook(initial="0%")
        self.speed_var = _VarHook(initial="0 KB/s")
        self.status_var = _VarHook(initial="准备开始下载...")
        self.root = _RootShim(self)

        if auto_start:
            self.start_download(download_func)

    def _on_status(self, text):
        import functions.web_update.zeroasso_download as zd
        try:
            getattr(zd, "_web_progress", lambda e, d: None)("status", {
                "task": self.task, "text": text,
            })
        except Exception:
            pass

    def update_progress(self, percent, downloaded, total, speed):
        import functions.web_update.zeroasso_download as zd
        try:
            getattr(zd, "_web_progress", lambda e, d: None)("progress", {
                "task": self.task,
                "percent": round(float(percent), 1),
                "downloaded": downloaded, "total": total, "speed": speed,
            })
        except Exception:
            pass
        self.progress_var.set(percent)
        self.speed_var.set(f"速度: {speed:.1f} KB/s" if speed < 1024 else f"速度: {speed / 1024:.1f} MB/s")

    def start_download(self, download_func=None):
        self.is_downloading = True
        threading.Thread(target=self.run_download, args=(download_func,),
                         daemon=True).start()

    def run_download(self, download_func=None):
        try:
            success = download_func(self, self.config_path)  # type: ignore
            if success:
                self.root.after(500, self.root.destroy)
            else:
                self.current_file_var.set("下载失败, 请检查错误信息")
                self.root.after(1000, self.root.destroy)
        except Exception as e:
            self.current_file_var.set(f"下载过程中出现错误: {e}")
        finally:
            self.is_downloading = False
            self.root.after(500, self.root.destroy)
            if self._on_done:
                try:
                    self._on_done()
                except Exception:
                    pass


# ============================================================
# 皮肤 (html/app_skins/<id>) —— "玻璃窗"页面
# ============================================================
# 目录结构与覆盖规则:
#   <skin>/config.json         元信息 (name / id / description / authors / theme_color)
#   <skin>/profile.png         玻璃窗左侧列表的卡片展示图
#   <skin>/css/style.css       覆盖层样式: **追加**在默认 style.css 之后, 两者合并生效,
#                              所以皮肤里只写"要改的那部分"(配色等), 不必复制整份默认样式
#   <skin>/assets/launcher/…   替换启动器基础资源 (对应项目根 assets/images/…)
#                              例: assets/launcher/background/ 存在 -> 整体接管背景图,
#                              默认 assets/images/background 立刻弃用
#   <skin>/assets/web/…        替换 html/app/assets/… (例: icon/icon.png)
#
# 皮肤目录不在 pywebview 的 http 根目录下 (root = html/app), 前端无法用相对路径取用,
# 因此一律由后端读成 data URI / 文本再下发。
SKIN_SETTING_KEY = "skin"
_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")


def _skins_root():
    """皮肤根目录 (打包后在 _internal/html/app_skins)"""
    for cand in (
        os.path.join(_PROJECT_ROOT, "html", "app_skins"),
        os.path.join(_PROJECT_ROOT, "_internal", "html", "app_skins"),
    ):
        if os.path.isdir(cand):
            return cand
    return os.path.join(_PROJECT_ROOT, "html", "app_skins")


def _skin_dir(skin_id):
    """皮肤目录; 空 id 表示内置默认皮肤 (返回空串); 拒绝目录穿越"""
    sid = str(skin_id or "").strip()
    if not sid or sid in (".", "..") or os.path.basename(sid) != sid:
        return ""
    d = os.path.join(_skins_root(), sid)
    return d if os.path.isdir(d) else ""


def _active_skin_id():
    """当前启用的皮肤 id (空串 = 默认皮肤)"""
    try:
        from functions.base.settings_manager import get_settings_manager
        return str(get_settings_manager().get_setting(SKIN_SETTING_KEY) or "").strip()
    except Exception:
        return ""


def _file_uri(path, max_side=1600, quality=82):
    """图片文件 -> data URI; 超出 max_side 的按比例缩小 (省内存与传输量)"""
    try:
        from PIL import Image
        if not path or not os.path.isfile(path):
            return ""
        if os.path.splitext(path)[1].lower() == ".gif":
            with open(path, "rb") as f:
                return "data:image/gif;base64," + base64.b64encode(f.read()).decode("ascii")
        img = Image.open(path)
        if max_side and max(img.size) > max_side:
            img.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
        buf = BytesIO()
        if img.mode in ("RGBA", "LA", "P"):
            img.convert("RGBA").save(buf, "PNG")
            mime = "image/png"
        else:
            img.convert("RGB").save(buf, "JPEG", quality=quality)
            mime = "image/jpeg"
        return "data:" + mime + ";base64," + base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception:
        return ""


def _image_files_in(d):
    if not d or not os.path.isdir(d):
        return []
    return [os.path.join(d, n) for n in sorted(os.listdir(d))
            if n.lower().endswith(_IMAGE_EXTS) and os.path.isfile(os.path.join(d, n))]


def _skin_background_dir(skin_id):
    """皮肤的 background 目录 (兼容 …/launcher/background 与 …/launcher/images/background)"""
    sd = _skin_dir(skin_id)
    if not sd:
        return ""
    for prefix in (("assets", "launcher"), ("assets", "launcher", "images")):
        d = os.path.join(sd, *prefix, "background")
        if os.path.isdir(d) and _image_files_in(d):
            return d
    return ""


def _default_background_dir():
    return os.path.join(_PROJECT_ROOT, "assets", "images", "background")


def _background_files(skin_id=""):
    """背景图文件列表。

    皮肤提供了 background 目录时**整体接管** —— 默认 assets/images/background 立刻弃用,
    这正是"皮肤替换启动器基础资源"的规则。
    """
    d = _skin_background_dir(skin_id)
    if d:
        return _image_files_in(d)
    return _image_files_in(_default_background_dir())


def _launcher_asset_file(skin_id, *rel):
    """皮肤 assets/launcher 优先的资源文件 (对应默认 assets/images/<rel>)"""
    sd = _skin_dir(skin_id)
    if not sd:
        return ""
    for prefix in (("assets", "launcher"), ("assets", "launcher", "images")):
        p = os.path.join(sd, *prefix, *rel)
        if os.path.isfile(p):
            return p
    return ""


def _web_asset_file(skin_id, *rel):
    """皮肤 assets/web 优先, 否则回退 html/app/assets/<rel>"""
    sd = _skin_dir(skin_id)
    if sd:
        p = os.path.join(sd, "assets", "web", *rel)
        if os.path.isfile(p):
            return p
    for cand in (
        os.path.join(_PROJECT_ROOT, "html", "app", "assets", *rel),
        os.path.join(_PROJECT_ROOT, "_internal", "html", "app", "assets", *rel),
    ):
        if os.path.isfile(cand):
            return cand
    return ""


def _skin_meta(skin_id):
    """读皮肤 config.json (失败返回空 dict)"""
    sd = _skin_dir(skin_id)
    if not sd:
        return {}
    try:
        p = os.path.join(sd, "config.json")
        if os.path.isfile(p):
            return read_json(p) or {}
    except Exception:
        pass
    return {}


def _skin_profile_file(skin_id):
    """皮肤卡片展示图 (profile.*)"""
    sd = _skin_dir(skin_id)
    if not sd:
        return ""
    for n in ("profile.png", "profile.jpg", "profile.jpeg", "profile.webp"):
        p = os.path.join(sd, n)
        if os.path.isfile(p):
            return p
    return ""


# js_api 桥接
def _res_icon_uri(base_dir, name):
    """读取插件/Mod 目录下的 icon.png/jpg 转 data URI"""
    try:
        for fn in ('icon.png', 'icon.jpg', 'icon.jpeg'):
            p = os.path.join(base_dir, name, fn)
            if os.path.isfile(p):
                with open(p, 'rb') as f:
                    b64 = base64.b64encode(f.read()).decode('ascii')
                return 'data:image/png;base64,' + b64
    except Exception:
        pass
    return ''


def _get_project_icon_uri():
    """项目图标 data URI (供 get_bootstrap 与 HTML 首载注入复用)

    皮肤优先: <skin>/assets/web/icon/icon.png 替换 html/app/assets/icon/icon.png;
    皮肤没提供时回退默认 assets/images/icon/icon.png。
    """
    p = _web_asset_file(_active_skin_id(), "icon", "icon.png")
    if p:
        try:
            with open(p, "rb") as f:
                return "data:image/png;base64," + base64.b64encode(f.read()).decode("ascii")
        except Exception:
            pass
    for cand in (
        os.path.join(_PROJECT_ROOT, "assets", "images", "icon", "icon.png"),
        os.path.join(_PROJECT_ROOT, "_internal", "assets", "images", "icon", "icon.png"),
    ):
        if os.path.isfile(cand):
            try:
                with open(cand, "rb") as f:
                    return "data:image/png;base64," + base64.b64encode(f.read()).decode("ascii")
            except Exception:
                pass
    return ""


def _goodbye_to_console():
    """退出时输出 GoodBye 美化艺术字。
    仅写原始 stdout (控制台)。绝不走 print —— 它会被重定向到前端 evaluate_js,
    在 closing 事件 (UI 线程) 调用时会导致死锁卡死; 无控制台时静默跳过。"""
    try:
        from functions.base.terminal_banner import get_banner_with_random_style
        banner = get_banner_with_random_style('GoodBye')
        out = sys.__stdout__
        if out is not None:
            out.write('\n\n' + banner + '\n')
            out.flush()
    except Exception:
        pass


def _terminate_now():
    """立即终止进程: TerminateProcess 跳过 DLL 卸载钩子。
    os._exit 会触发 WebView2 的卸载钩子 (报 1411 错误) 且可能有 ~1s 延时;
    TerminateProcess 直接终止, 无清理、无报错、无延时。"""
    _goodbye_to_console()
    try:
        import ctypes
        ctypes.windll.kernel32.TerminateProcess(
            ctypes.windll.kernel32.GetCurrentProcess(), 0)
    except Exception:
        pass
    os._exit(0)


def _is_system_shutting_down():
    """系统是否正在关机 / 重启 / 注销。

    两个来源, 任一成立即算:
      1. 我们的窗口子类过程收到过 WM_QUERYENDSESSION;
      2. 直接问系统: GetSystemMetrics(SM_SHUTTINGDOWN)。
    第 2 条是关键 —— 子类是在 ui_ready 之后延迟安装的, 没装成功时第 1 条
    永远是 False, 那样就会把系统关机当成"用户点了关闭", 返回 False 阻止关机。
    """
    if _system_shutdown_requested:
        return True
    try:
        import ctypes
        SM_SHUTTINGDOWN = 0x2000
        return bool(ctypes.windll.user32.GetSystemMetrics(SM_SHUTTINGDOWN))
    except Exception:
        return False


def _fmt_author_links(authors):
    """作者字段转链接列表 [{name, url}] (dict: 名字->链接; 其它则无链接)"""
    if isinstance(authors, dict):
        return [{'name': str(k), 'url': str(v)} for k, v in authors.items()]
    return []


def _fmt_authors(authors):
    """作者字段可能是 dict(名字->链接) / list / str, 统一转成显示名"""
    if isinstance(authors, dict):
        return ', '.join(str(k) for k in authors.keys())
    if isinstance(authors, list):
        return ', '.join(str(a) for a in authors)
    if authors is None:
        return ''
    return str(authors)


class AppApi:
    """供前端调用的 pywebview js_api"""

    def __init__(self, core, window_ref):
        """初始化 AppApi 实例

        Args:
            core (_type_): 核心后端实例
            window_ref (_type_): 窗口引用字典, 包含 win 键
        """
        self.core = core
        self.window_ref = window_ref
        self.ready_callback = None
        self._window_drag_lock = threading.Lock()
        self._window_drag_origin = None

    def set_window_opacity(self, alpha):
        """设置窗口透明度 (0~255), 供前端/渐变控制"""
        try:
            win = self.window_ref.get("win") if self.window_ref else None
            if win is not None:
                hwnd = _win32_hwnd(win)
                if hwnd:
                    _ensure_layered(hwnd)
                    _set_window_alpha(hwnd, alpha)
        except Exception:
            pass
        return True

    def ui_ready(self):
        """前端 Splash 首帧就绪后显示主窗口，不等待业务数据初始化"""
        try:
            win = self.window_ref.get("win") if self.window_ref else None
            if win is not None:
                # 由 run_web_ui 注入唯一的显示回调, 避免跨作用域调用局部函数。
                if self.ready_callback is not None:
                    self.ready_callback()
                # 延迟禁用整窗拖动 (窗口完全初始化后更可靠)
                def _later():
                    try:
                        time.sleep(0.5)
                        _disable_system_drag(win)
                    except Exception:
                        pass
                threading.Thread(target=_later, daemon=True).start()
        except Exception:
            pass
        return True

    def minimize_window(self):
        """最小化窗口"""
        try:
            win = self.window_ref.get("win") if self.window_ref else None
            if win is not None:
                import ctypes
                hwnd = _win32_hwnd(win)
                if hwnd:
                    # 最小化直接交给系统处理，不播放透明度动画。
                    ctypes.windll.user32.ShowWindow(hwnd, 6)  # SW_MINIMIZE
        except Exception:
            pass
        return True

    def begin_move_window(self, mouse_x, mouse_y):
        """记录拖动开始时的鼠标位置和窗口位置。"""
        try:
            win = self.window_ref.get("win") if self.window_ref else None
            if win is not None:
                import ctypes
                import ctypes.wintypes as _wt
                hwnd = _win32_hwnd(win)
                if hwnd:
                    r = _wt.RECT()
                    ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(r))
                    with self._window_drag_lock:
                        self._window_drag_origin = (
                            float(mouse_x), float(mouse_y), r.left, r.top)
        except Exception:
            pass
        return True

    def move_window(self, mouse_x, mouse_y):
        """根据鼠标绝对屏幕坐标移动窗口，避免异步增量请求产生竞态。"""
        try:
            win = self.window_ref.get("win") if self.window_ref else None
            if win is not None:
                import ctypes
                from ctypes import wintypes
                hwnd = _win32_hwnd(win)
                with self._window_drag_lock:
                    origin = self._window_drag_origin
                if hwnd and origin is not None:
                    start_x, start_y, window_x, window_y = origin
                    x = window_x + round(float(mouse_x) - start_x)
                    y = window_y + round(float(mouse_y) - start_y)
                    ctypes.windll.user32.SetWindowPos(
                        hwnd, None, x, y, 0, 0,
                        0x0001 | 0x0004 | 0x0010)  # NOSIZE | NOZORDER | NOACTIVATE
        except Exception:
            pass
        return True

    def end_move_window(self):
        """清除当前拖动状态。"""
        with self._window_drag_lock:
            self._window_drag_origin = None
        return True

    def close_window(self):
        """触发窗口关闭 (走关闭事件: 托盘/退出)"""
        try:
            win = self.window_ref.get("win") if self.window_ref else None
            if win is not None:
                import ctypes
                hwnd = _win32_hwnd(win)
                if hwnd:
                    ctypes.windll.user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE
        except Exception:
            pass
        return True

    # ---- 基础信息 ----
    def get_bootstrap(self):
        from functions.base.settings_manager import get_settings_manager
        sm = get_settings_manager()
        features = [
            {"name": "📁 游戏目录", "desc": "打开边狱巴士安装目录", "image": "game_directory.png"},
            {"name": "🔄 零协会", "desc": "前往零协会汉化组主页", "image": "zeroasso.png"},
            {"name": "📝 维基", "desc": "边狱巴士灰机 Wiki", "image": "wiki.png"},
            {"name": "📖 N网", "desc": "下载边狱巴士 Mod", "image": "nexus.png"},
            {"name": "📦 GitHub", "desc": "查看本项目源码", "image": "github.png"},
        ]
        for f in features:
            f["image_uri"] = _feature_image_uri(f.get("image", ""))
        tools = [
            { "id": 'custom_translation', "name": '🔧 自定义汉化', "desc": '可视化编辑 lang 下任意 JSON 文本\n一键编辑替换汉化文本\n自动记录差异性文本，汉化更新也不丢失修改内容！', "image": "custom_translation.png" },
            {"id": "font", "name": "📝 字体修改", "desc": "选择字体替换汉化包字体", "image": "font.png"},
            { "id": 'gradient', "name": '💻 渐变文本处理器', "desc": '生成 Unity 富文本渐变色代码', "image": "gradient.png" },
            { "id": 'folder_link', "name": '📂 文件夹超链接', "desc": '创建符号链接, 转移C盘资源文件', "image": "folder_link.png" },
            { "id": 'nyos', "name": '📖 今日指令', "desc": '获取食指的最新指令\n仅供娱乐，请勿上升到指令成瘾。', "image": "nyos.png" },
            { "id": 'extension_tools', "name": '🧩 扩展工具', "desc": '插件模板 / 打包发布\n给开发者提供的工具\n需要输入开发者密钥。', "image": "extension_tools.png" },
            { "id": 'cdn', "name": '🚀 零协会CDN优选', "desc": '自动选择最优质的CDN\n优化游戏资源下载和服务器连接', "image": "cdn.png" },
        ]
        for t in tools:
            t["image_uri"] = _tool_image_uri(t.get("image", ""))
        icon_uri = _get_project_icon_uri()
        try:
            from functions.base.steam_locator import resolve_game_dir as _rgd
            _boot_game_path_ok = bool(_rgd(str(sm.get_setting("game_path") or "")))
        except Exception as _e:
            print(f"[设置] 启动时校验游戏路径失败(按有效处理, 不锁界面): {_e}")
            _boot_game_path_ok = True
        return {
            "version": str(sm.get_setting("version_info")),
            "game_path": str(sm.get_setting("game_path") or ""),
            # 路径里是否有 LimbusCompany.exe: 前端据此在启动瞬间就锁住界面
            # (异常时给 True, 宁可不在启动瞬间锁, 也不能因为一个 import 失败把界面锁死;
            #  真正的检测结果随后仍由 check_settings 推送的 path_confirm 兜底)
            "game_path_ok": _boot_game_path_ok,
            "bg_color": str(sm.get_setting("bg_color") or "#181818"),
            "features": features,
            "tools": tools,
            "settings_schema": sm.get_all_settings(),
            "is_frozen": bool(getattr(sys, "frozen", False)),
            "project_root": _PROJECT_ROOT,
            "icon_uri": icon_uri,
            # 当前皮肤 id (空串 = 默认皮肤); 前端启动时据此加载皮肤覆盖层
            "active_skin": _active_skin_id(),
        }

    def get_backgrounds(self):
        """返回**一张随机背景图**的 data URI 列表, 应用 bg_gaussian_blur 模糊设置

        2026-09-25 修: 以前是 sorted() 取前 4 张 —— 文件名靠后的图永远轮不到, 前端又每
        25 秒在这 4 张里换, 看着就是"轮询"。现在每次调用都从 background 目录的**全部**
        图片里随机抽 1 张 (顺带省掉 3/4 的编码开销与传输量)。
        """
        uris = []
        try:
            import random
            from PIL import Image, ImageFilter
            from functions.base.settings_manager import get_settings_manager
            blur = 0.0
            try:
                blur = float(get_settings_manager().get_setting("bg_gaussian_blur") or 0.0)
            except Exception:
                blur = 0.0
            # 背景来源跟随当前皮肤: 皮肤提供 background 目录就整体接管, 否则用默认目录
            paths = _background_files(_active_skin_id())
            random.shuffle(paths)
            for path in paths:
                if uris:
                    break        # 已经拿到一张 (解码失败会顺延到下一张)
                try:
                    img = Image.open(path).convert("RGB")
                    img.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
                    if blur > 0:
                        img = img.filter(ImageFilter.GaussianBlur(radius=blur))
                    buf = BytesIO()
                    img.save(buf, "JPEG", quality=78)
                    uris.append("data:image/jpeg;base64," + base64.b64encode(
                        buf.getvalue()).decode("ascii"))
                except Exception:
                    continue
        except Exception:
            pass
        return uris

    # ---- 皮肤 (玻璃窗) ----
    def get_skins(self):
        """玻璃窗左侧列表: 内置"默认皮肤" + html/app_skins 下的全部皮肤。

        每项只带**卡片展示图**(profile) 与背景数量; 背景图数据量大, 选中后再由
        get_skin_backgrounds 按需拉取, 避免一次把所有皮肤的所有图都塞进前端。
        """
        skins = [{
            "id": "",
            "name": "默认皮肤",
            "builtin": True,
            "description": "不加载任何皮肤, 使用启动器原始外观与资源",
            "authors": {},
            "theme_color": "",
            "profile_uri": _get_project_icon_uri(),
            "background_count": len(_background_files("")),
        }]
        root = _skins_root()
        try:
            names = sorted(n for n in os.listdir(root)
                           if os.path.isdir(os.path.join(root, n)) and _skin_dir(n))
        except Exception:
            names = []
        for sid in names:
            meta = _skin_meta(sid)
            skins.append({
                "id": sid,
                "name": str(meta.get("name") or sid),
                "builtin": False,
                "description": str(meta.get("description") or ""),
                "authors": meta.get("authors") or {},
                "theme_color": str(meta.get("theme_color") or ""),
                "profile_uri": _file_uri(_skin_profile_file(sid), max_side=640, quality=85),
                "background_count": len(_background_files(sid)),
            })
        return {"skins": skins, "active": _active_skin_id()}

    def get_skin_backgrounds(self, skin_id=""):
        """某个皮肤的背景图 (右侧欣赏区轮播 / 主背景预览), 按需拉取"""
        sid = str(skin_id or "").strip()
        if sid and not _skin_dir(sid):
            return {"error": "皮肤不存在: " + sid, "backgrounds": []}
        out = []
        for p in _background_files(sid):
            u = _file_uri(p, max_side=1600, quality=82)
            if u:
                out.append({"name": os.path.basename(p), "uri": u})
        return {"backgrounds": out}

    def get_skin_css(self, skin_id=""):
        """皮肤覆盖层 CSS 文本。

        前端把它作为 <style> 追加在默认 style.css **之后** —— 两者合并生效,
        所以皮肤里只写要覆盖的部分即可。
        """
        sd = _skin_dir(str(skin_id or "").strip())
        if not sd:
            return ""
        for rel in (("css", "style.css"), ("css", "skin.css")):
            p = os.path.join(sd, *rel)
            if os.path.isfile(p):
                try:
                    with open(p, "r", encoding="utf-8") as f:
                        return f.read()
                except Exception:
                    return ""
        return ""

    def get_active_skin_css(self):
        """当前皮肤的覆盖层 CSS 文本。

        专门给"启动早期"用: Splash 在 bootstrap/render 之前就显示了,
        若等到 render() 才注入皮肤, 启动转圈界面会一直是默认样式,
        注入那一刻还会明显闪一下。前端探测到 api 后立刻调用本接口。
        """
        try:
            return self.get_skin_css(_active_skin_id())
        except Exception:
            return ""

    def set_active_skin(self, skin_id=""):
        """切换皮肤: 只写 settings.json 的 skin 键。

        刻意**不**注册进 settings_schema —— 皮肤只能在"玻璃窗"里改, 设置页不出现该配置项。
        前端拿到 ok 后立即重载样式/背景/图标, 无需重启。
        """
        sid = str(skin_id or "").strip()
        if sid and not _skin_dir(sid):
            return {"error": "皮肤不存在: " + sid}
        # print(f"[皮肤] 已切换: {sid or '默认皮肤'}")
        # ↓↓ 写入逻辑 (曾整段丢失, 导致"切皮肤后只有样式变、背景不跟着变":
        #    背景是后端按 settings.json 里的 skin 决定的 —— 设置没写进去,
        #    _active_skin_id() 就一直是旧皮肤, get_backgrounds() 自然永远给旧背景)
        try:
            sm = self.core.settings_manager
            # 老配置里可能还没有 skin 这一项 (SettingsManager.set_setting 对未知键
            # 直接返回 False 而不创建), 这里现场补一个 schema 项。
            # 刻意**不给 page 字段** —— 设置页只渲染带 page 的项, 所以它不会出现在
            # 设置页里, 皮肤只能在"玻璃窗"里改。
            if SKIN_SETTING_KEY not in sm.settings:
                sm.settings[SKIN_SETTING_KEY] = {
                    "name": "启动器皮肤",
                    "type": "string",
                    "default": "",
                    "value": "",
                    "description": "当前启用的启动器皮肤, 只能在\"玻璃窗\"页面切换",
                }
            if not sm.set_setting(SKIN_SETTING_KEY, sid):
                sm.settings[SKIN_SETTING_KEY]["value"] = sid
            sm.save_settings()
        except Exception as e:
            return {"error": str(e)}
        return {"ok": True, "active": sid}

    def get_characters(self):
        """返回角色小人图列表 (含图片名, 供随机探头摇摆与问候语匹配)"""
        items = []
        try:
            from PIL import Image
            for root in (
                os.path.join(_PROJECT_ROOT, "assets", "images", "character"),
                os.path.join(_PROJECT_ROOT, "_internal", "assets", "images", "character"),
            ):
                if not os.path.isdir(root):
                    continue
                for name in sorted(os.listdir(root)):
                    if not name.lower().endswith((".png", ".jpg", ".jpeg")):
                        continue
                    try:
                        img = Image.open(os.path.join(root, name))
                        img.thumbnail((800, 800), Image.Resampling.LANCZOS)
                        img = img.convert("RGBA")
                        # 透明裁切: 裁掉四周透明像素, 让 box 贴合实际内容 (角色/气泡定位更准)
                        try:
                            bbox = img.split()[3].getbbox()
                            if bbox and bbox != (0, 0, img.width, img.height):
                                img = img.crop(bbox)
                        except Exception:
                            pass
                        buf = BytesIO()
                        img.save(buf, "PNG")
                        items.append({
                            "name": name,
                            "uri": "data:image/png;base64," + base64.b64encode(
                                buf.getvalue()).decode("ascii"),
                        })
                    except Exception:
                        continue
                break
        except Exception:
            pass
        return items

    def get_character_greetings(self):
        """返回角色问候语映射: 图片名 -> 问候语列表 (config/character_greetings.json)"""
        try:
            for root in (
                os.path.join(_PROJECT_ROOT, "config"),
                os.path.join(_PROJECT_ROOT, "_internal", "config"),
            ):
                p = os.path.join(root, "character_greetings.json")
                if os.path.isfile(p):
                    with open(p, "r", encoding="utf-8") as f:
                        return json.load(f)
        except Exception as e:
            print(f"读取角色问候语失败: {e}")
        return {}

    def get_terminal(self):
        with _log_lock:
            return list(_log_lines)

    def clear_terminal(self):
        with _log_lock:
            _log_lines.clear()
        return True

    # ---- 设置 ----
    def get_setting(self, key):
        return self.core.settings_manager.get_setting(key)

    def _notify_path_synced(self):
        """通知前端同步设置页输入框与主页路径芯片"""
        try:
            win = self.window_ref.get("win") if self.window_ref else None
            if win is not None:
                win.evaluate_js("window.__onPathSynced()")
        except Exception as e:
            print(f"通知前端同步游戏路径失败: {e}")

    # ---- 游戏路径 (Steam VDF 自动检测 -> 用户确认) ----
    def get_pending_steam_path(self):
        """待确认的 Steam 自动检测结果 (前端兜底轮询用)

        Returns: {checked: 后端是否已完成检测, path: 检测到的路径(可能为空串),
                  path_ok: 该路径下是否确实有 LimbusCompany.exe,
                  game_exe: 游戏主程序名(仅供界面提示)}
        """
        from functions.base.steam_locator import GAME_EXE, resolve_game_dir
        path = str(getattr(self.core, "pending_steam_path", "") or "")
        return {
            "checked": bool(getattr(self.core, "_steam_path_checked", False)),
            "path": path,
            # path_ok=False: 这个路径下没有 LimbusCompany.exe, 视为无效路径 (不能直接确认)
            "path_ok": bool(resolve_game_dir(path)),
            "game_exe": GAME_EXE,
        }

    def confirm_steam_game_path(self, accept):
        """用户对"自动检测到的游戏路径"的回答

        accept=True  -> 写入该路径 (仍然必须过 LimbusCompany.exe 硬校验,
                        目录里没有这个文件会返回 error='no_exe');
        accept=False -> 丢弃, 等前端让用户自己选。
        """
        path = str(getattr(self.core, "pending_steam_path", "") or "").strip()
        if not accept:
            self.core.pending_steam_path = ""
            print("[设置] 用户否认了自动检测到的游戏路径, 等待手动选择")
            return {"ok": True, "accepted": False, "path": ""}
        if not path:
            # 检测到的是空路径: 不能写, 让用户自己选
            return {"ok": False, "error": "empty", "path": ""}
        result = self.apply_game_path(path)
        if result.get("ok"):
            return result
        # 用户点了"是"却被拒: 现场重新检测一次再试一遍 —— "看到的路径"与"校验的路径"
        # 不一致 (Steam 刚改写 VDF / 游戏刚被挪到别的库) 时, 不能拿过期路径下结论
        from functions.base.steam_locator import find_steam_game_path, normalize_game_path
        fresh = find_steam_game_path() or ""
        if fresh and os.path.normcase(normalize_game_path(fresh)) != os.path.normcase(
                normalize_game_path(path)):
            print(f"[设置] 确认 {path} 失败({result.get('error')}), 现场检测到 {fresh}, 再试一次")
            retry = self.apply_game_path(fresh)
            if retry.get("ok"):
                return retry
        print(f"[设置] 确认自动检测到的路径失败: error={result.get('error')} "
              f"path={result.get('path')!r} reason={result.get('reason')}")
        return result

    def apply_game_path(self, path):
        """写入游戏路径: 非空 -> 目录存在 -> 目录里必须有 LimbusCompany.exe (硬校验)

        - 找不到 exe 的目录一律拒绝 (error='no_exe'), Steam 自动检测到的路径同样对待;
        - 用户少点一层 (例如选了 steamapps\\common 或游戏目录的父级) 时,
          自动下探到唯一含 exe 的子目录, 返回 auto_fixed=True 让前端提示一下。

        Returns: {ok, path, has_exe, auto_fixed, error}
        """
        from functions.base.steam_locator import (
            GAME_EXE, normalize_game_path, resolve_game_dir_ex,
        )
        raw = str(path or "").strip()
        if not raw:
            print("[设置] 游戏路径为空, 拒绝写入")
            return {"ok": False, "error": "empty", "path": ""}
        norm = normalize_game_path(raw)
        picked, reason = resolve_game_dir_ex(norm)
        if not picked:
            exe_file = os.path.join(norm, GAME_EXE)
            # 诊断要足够具体: 用户报"明明有 exe 却不认"时, 这行日志就是结论
            print(f"[设置] 路径校验失败: path={norm!r} 是目录={os.path.isdir(norm)} "
                  f"exe存在={os.path.isfile(exe_file)} reason={reason}")
            if reason == "not_dir":
                print(f"[设置] 游戏路径不存在: {norm}")
                return {"ok": False, "error": "not_found", "path": norm, "reason": reason}
        # 注意: 这里**不**替用户换成别的目录 —— 用户明确给了这个路径, 就只校验它;
        # "点『是』却被拒" 的自愈在 confirm_steam_game_path 里做 (那里的路径是我们自己检测的)
        if not picked:
            print(f"[设置] 目录下没有 {GAME_EXE}, 拒绝写入: {norm} (reason={reason})")
            return {"ok": False, "error": reason or "no_exe", "path": norm,
                    "game_exe": GAME_EXE, "reason": reason}
        auto_fixed = os.path.normcase(picked) != os.path.normcase(norm)
        game_path = picked
        self.core.settings_manager.set_setting("game_path", game_path)
        self.core.settings_manager.save_settings()
        self.core.pending_steam_path = ""
        try:
            page = self.core.page_loader.get_page("settings")   # Tk 设置页(Web 模式下通常为空)
            if page:
                page.refresh_all_displays()
        except Exception:
            pass
        self._notify_path_synced()
        print(f"[设置] 游戏路径已写入: {game_path} (LimbusCompany.exe: 有)"
              + (f" [自动下探一层: {norm} -> {game_path}]" if auto_fixed else ""))
        return {"ok": True, "path": game_path, "has_exe": True,
                "auto_fixed": auto_fixed}

    def get_translate_source_name(self):
        """主页"汉化源"显示名: 插件注册的自定义汉化源优先(取第一个), 否则内置平台名"""
        try:
            from functions.web_update.translation_source import get_translate_source_name
            return get_translate_source_name()
        except Exception as e:
            print(f"读取汉化源名称失败: {e}")
            return ""

    def set_setting(self, key, value):
        self.core.settings_manager.set_setting(key, value)
        self.core.settings_manager.save_settings()
        return True

    def save_settings(self, changes: dict):
        for key, value in (changes or {}).items():
            self.core.settings_manager.set_setting(key, value)
        self.core.settings_manager.save_settings()
        return True

    def pick_folder(self):
        """原生文件夹选择对话框 (临时 Tk, 独立于 webview 主循环)"""
        import tkinter as tk
        from tkinter import filedialog
        try:
            root = tk.Tk()
            root.withdraw()
            path = filedialog.askdirectory(title="选择文件夹", parent=root)
            root.destroy()
            return path or ""
        except Exception as e:
            print(f"选择文件夹失败: {e}")
            return ""

    def open_url(self, url):
        import webbrowser
        try:
            webbrowser.open(url)
        except Exception as e:
            print(f"打开链接失败: {e}")
        return True

    # ---- 启动/更新 ----
    def _require_game_path(self):
        """游戏路径硬校验: 返回 None 表示可用, 否则返回给前端的错误对象

        路径必须存在, 且目录里 (或其唯一子目录) 有 LimbusCompany.exe ——
        没通过校验前, 任何依赖游戏目录的功能一律拒绝执行, 并把路径确认窗口
        重新推给前端 (force=True: 界面重新锁住, 直到用户选出有效路径)。
        """
        from functions.base.steam_locator import resolve_game_dir, find_steam_game_path
        try:
            cur = self.core.settings_manager.get_setting("game_path") or ""
        except Exception:
            cur = ""
        if resolve_game_dir(cur):
            return None
        print(f"[设置] 游戏路径无效, 拒绝执行该功能: {cur or '(未设置)'}")
        try:
            fresh = find_steam_game_path() or ""
            print(f"[设置] 重新检测 Steam 路径: {fresh or '(没找到)'}")
            self.core._ask_web_game_path(fresh, force=True)
        except Exception as e:
            print(f"[设置] 重新推送游戏路径确认窗口失败: {e}")
        return {"ok": False, "error": "no_game_path", "path": cur}

    def launch_game(self):
        blocked = self._require_game_path()
        if blocked:
            return blocked
        def _run():
            from functions.pages.app.page_loader import download_and_launch
            obj = type("WebAppShim", (), {"root": None, "core": self.core})()
            try:
                download_and_launch(obj=obj, need_run_game=True)
                _monitor_game_process(self.window_ref)
            except Exception as e:
                print(f"启动游戏失败: {e}")
        threading.Thread(target=_run, daemon=True).start()
        return True

    def update_translation(self):
        blocked = self._require_game_path()
        if blocked:
            return blocked
        # 必须阻塞等待下载线程真正完成, 否则前端 await 立即返回,
        # 800ms 后 pipelineDone 会在后端仍在下载时就显示"流水线完成"
        from threading import Event as _Event
        done = _Event()
        def _run():
            from functions.pages.app.page_loader import download_and_launch
            try:
                # manual=True: 手动更新不受 check_translate_update 禁用限制
                download_and_launch(obj=None, need_run_game=False, manual=True)
            except Exception as e:
                print(f"更新汉化失败: {e}")
            finally:
                done.set()
        threading.Thread(target=_run, daemon=True).start()
        done.wait()
        return True

    # ---- 入口 ----
    def verify_extension_key(self, key):
        """验证开发者工具密钥"""
        try:
            from functions.base.web_config import get_web_config
            secret = get_web_config().get('extension_tool_key', '')
            if not secret:
                return {'ok': False, 'error': '未配置开发者工具密钥'}
            if str(key).strip() == str(secret):
                return {'ok': True, 'error': None}
            return {'ok': False, 'error': '密钥错误'}
        except Exception as e:
            return {'ok': False, 'error': str(e)}

    def open_extension_tools_window(self):
        """拉起扩展工具窗口"""
        try:
            from functions.pages.tools.extension_tools_window import open_extension_tools_window as _open
            return bool(_open(self.core))
        except Exception as e:
            print(f"打开扩展工具失败: {e}")
            return False

    def open_feature(self, name):
        self.core.open_feature({"name": name})
        return True

    def open_website(self):
        self.core.open_website()
        return True

    def open_tool(self, tool_id):
        if tool_id == "nyos":
            from functions.pages.tools.nyos_prescript import open_prescript_window
            open_prescript_window()
        elif tool_id == "mod_manager":
            self.core.open_mod_manager()
        elif tool_id == "custom_translation":
            self.core.open_custom_translation_tool()
        elif tool_id == "folder_link":
            self._open_folder_link()
        elif tool_id == "extension_tools":
            self.core.open_post_extension_tools()
        elif tool_id == "font":
            print("字体修改工具将在后续版本接入 Web UI")
        elif tool_id == "auto_translate":
            print("自动汉化工具将在后续版本接入 Web UI")
        elif tool_id == "gradient":
            print("渐变文本处理器将在后续版本接入 Web UI")
        elif tool_id == "cdn":
            from functions.web_tool.launch_babel import launch_babel
            threading.Thread(target=launch_babel, daemon=True).start()
        else:
            print(f"未知工具: {tool_id}")
        return True

    # ---- Mod 管理 (本地移植) ----
    def get_contributors(self):
        """返回关于页数据: 程序介绍 + 贡献者列表 (图标转 data URI)"""
        import os
        data = {'program': {'title': '关于 Faust Launcher', 'version': '', 'description': ''}, 'contributors': []}
        try:
            for root in (
                os.path.join(_PROJECT_ROOT, "config", "contributors.json"),
                os.path.join(_PROJECT_ROOT, "_internal", "config", "contributors.json"),
            ):
                if os.path.isfile(root):
                    data = read_json(root)
                    break
        except Exception as e:
            print(f"读取贡献者配置失败: {e}")
        # 填充版本号
        try:
            from functions.base.settings_manager import get_settings_manager
            data.setdefault('program', {})
            data['program']['version'] = str(get_settings_manager().get_setting('version_info') or '')
        except Exception:
            pass
        # 图标 data URI
        for c in data.get('contributors', []):
            icon = c.get('icon', '')
            if icon:
                for base in (
                    os.path.join(_PROJECT_ROOT, "assets", "images", "contributor"),
                    os.path.join(_PROJECT_ROOT, "_internal", "assets", "images", "contributor"),
                ):
                    p = os.path.join(base, icon)
                    if os.path.isfile(p):
                        try:
                            with open(p, 'rb') as f:
                                b64 = base64.b64encode(f.read()).decode('ascii')
                            ext = os.path.splitext(p)[1].lower()
                            mime = 'image/png' if ext == '.png' else 'image/jpeg'
                            c['icon_uri'] = 'data:' + mime + ';base64,' + b64
                        except Exception:
                            pass
                        break
            c.pop('icon', None)
        return data

    def get_sound(self, kind):
        """返回音效 data URI (kind: welcome / click), 供前端浏览器内核播放"""
        try:
            if kind == 'welcome':
                from functions.base.settings_manager import get_settings_manager
                p = str(get_settings_manager().get_setting("welcome_sound") or '')
            else:
                p = 'assets/voices/click.wav'
            if not p or not os.path.isfile(p):
                return ''
            with open(p, 'rb') as f:
                b64 = base64.b64encode(f.read()).decode('ascii')
            ext = os.path.splitext(p)[1].lower()
            mime = 'audio/wav' if ext == '.wav' else ('audio/mpeg' if ext in ('.mp3',) else 'audio/ogg')
            return 'data:' + mime + ';base64,' + b64
        except Exception:
            return ''

    def open_mod_item_dir(self, kind, name):
        """打开某个插件/Mod 的具体目录"""
        import os
        try:
            base = 'addons' if kind == 'addon' else 'mods'
            d = os.path.abspath(os.path.join(base, str(name)))
            if not os.path.isdir(d):
                return {'error': f'目录不存在: {d}'}
            os.startfile(d)
            return {'error': None}
        except Exception as e:
            return {'error': str(e)}

    
    def get_mods_data(self):
        """插件 (addons/) + 目录 Mod (mods/) 数据 (直接读 JSON 正确解析字段)"""
        import os, json
        # 插件: addons/<目录>/addon_info.json
        addons = []
        try:
            base = os.path.abspath('addons')
            if os.path.isdir(base):
                for name in sorted(os.listdir(base)):
                    info_path = os.path.join(base, name, 'addon_info.json')
                    if not os.path.isfile(info_path):
                        continue
                    try:
                        info = read_json(info_path)
                    except Exception:
                        info = {}
                    local_name = str(info.get('name') or name)
                    addons.append({
                        'dir': name,   # 文件夹名 (供后端操作)
                        'name': str(info.get('name') or name),
                        'version': str(info.get('version', '')),
                        'author': _fmt_authors(info.get('authors')),
                        'author_links': _fmt_author_links(info.get('authors')),
                        'description': str(info.get('desc') or info.get('description', '')),
                        'enabled': bool(info.get('settings', {}).get('enable', True)),
                        'icon': _res_icon_uri('addons', name),
                        'settings': info.get('settings', {}),
                        'reinstall_available': self._cached_resource(kind='addon', name=local_name) is not None,
                    })
        except Exception as e:
            print(f"读取插件失败: {e}")
        # 目录 Mod: mods/<目录>/mod_info.json
        dir_mods = []
        try:
            base = os.path.abspath('mods')
            if os.path.isdir(base):
                for name in sorted(os.listdir(base)):
                    info_path = os.path.join(base, name, 'mod_info.json')
                    if not os.path.isfile(info_path):
                        continue
                    try:
                        info = read_json(info_path)
                    except Exception:
                        info = {}
                    local_name = str(info.get('name') or name)
                    dir_mods.append({
                        'dir': name,
                        'name': str(info.get('name') or name),
                        'version': str(info.get('version', '')),
                        'author': _fmt_authors(info.get('authors')),
                        'author_links': _fmt_author_links(info.get('authors')),
                        'description': str(info.get('desc') or info.get('description', '')),
                        'files': list(info.get('file_names', [])),
                        'has_installer': bool(os.path.exists(os.path.join(base, name, 'Installer.bat'))),
                        'enabled': bool(info.get('settings', {}).get('enable', False)),
                        'icon': _res_icon_uri('mods', name),
                        'settings': info.get('settings', {}),
                        'reinstall_available': self._cached_resource(kind='mod', name=local_name) is not None,
                    })
        except Exception as e:
            print(f"读取目录 Mod 失败: {e}")
        return {
            'addons': addons,
            'dir_mods': dir_mods,
            'single_files': [],
            'single_dir': '',
        }

    def _cached_resource(self, kind, name):
        """只从启动时已有的云端缓存读取资源，禁止这里触发网络查询。"""
        try:
            from functions.pages.app import page_loader as _pl
            wanted = str(name).strip()
            items = _pl._cloud_sync_cache.get(kind) or []
            pending = list(items) if isinstance(items, list) else [items]
            while pending:
                item = pending.pop(0)
                if isinstance(item, list):
                    pending.extend(item)
                    continue
                if isinstance(item, dict) and str(item.get('name') or '').strip() == wanted:
                    url = item.get('dowload_url') or item.get('download_url') or item.get('url')
                    if url:
                        return item
        except Exception:
            pass
        return None

    def _reinstall_local(self, kind, local_dir):
        """从缓存精确匹配本地资源后重新下载；local_dir 是实际目录名。"""
        import json, shutil
        root = 'addons' if kind == 'addon' else 'mods'
        info_name = 'addon_info.json' if kind == 'addon' else 'mod_info.json'
        local_dir = str(local_dir)
        local_path = os.path.join(root, local_dir)
        info_path = os.path.join(local_path, info_name)
        if not os.path.isfile(info_path):
            return {'ok': False, 'error': f'资源信息不存在: {local_dir}'}
        try:
            info = read_json(info_path)
            cloud = self._cached_resource(kind, str(info.get('name') or local_dir))
            if cloud is None:
                return {'ok': False, 'error': f'缓存中没有与 {info.get("name") or local_dir} 完全匹配的云端资源'}
            cloud_name = str(cloud.get('name'))
            url = cloud.get('dowload_url') or cloud.get('download_url') or cloud.get('url')

            if kind == 'mod':
                try:
                    from functions.extension.mod.mod_utils import ModManager
                    ModManager().unload_mod(local_dir)
                except Exception:
                    pass
            shutil.rmtree(local_path, ignore_errors=True)
            from functions.web_update.zeroasso_download import download_and_extract_mod
            gui = HeadlessDownloadGUI(root, auto_start=False, task=cloud_name)
            ok = download_and_extract_mod(gui, root, [{
                'url': url, 'name': cloud_name, 'temp_filename': f'{cloud_name}.7z'
            }])
            if not ok:
                return {'ok': False, 'error': f'下载失败: {cloud_name}'}
            self._notify_res_changed(kind)
            return {'ok': True, 'error': None}
        except Exception as e:
            return {'ok': False, 'error': str(e)}

    def reinstall_resource(self, kind, local_dir):
        """后台重装单个资源；云端数据只取启动缓存。"""
        def _run():
            result = self._reinstall_local(kind, local_dir)
            if not result.get('ok'):
                self._notify_res_changed(kind, error=result.get('error'))
        threading.Thread(target=_run, daemon=True).start()
        return {'ok': True, 'error': None}

    def prepare_reinstall(self, kind, local_dir):
        """为标准下载流程准备重装：校验启动缓存并删除旧资源。

        本方法不下载、不解压；前端拿到返回的云端条目后必须调用
        startDownloadItem，从而沿用下载抽屉和统一进度事件。
        """
        import json, shutil
        root = 'addons' if kind == 'addon' else 'mods'
        info_name = 'addon_info.json' if kind == 'addon' else 'mod_info.json'
        local_dir = str(local_dir)
        local_path = os.path.join(root, local_dir)
        info_path = os.path.join(local_path, info_name)
        if not os.path.isfile(info_path):
            return {'ok': False, 'error': f'资源信息不存在: {local_dir}'}
        try:
            info = read_json(info_path)
            cloud = self._cached_resource(kind, str(info.get('name') or local_dir))
            if cloud is None:
                return {'ok': False, 'error': '缓存中没有完全匹配的云端资源'}
            if kind == 'mod':
                try:
                    from functions.extension.mod.mod_utils import ModManager
                    ModManager().unload_mod(local_dir)
                except Exception as e:
                    return {'ok': False, 'error': f'卸载旧 Mod 失败: {e}'}
            shutil.rmtree(local_path, ignore_errors=False)
            return {'ok': True, 'error': None, 'item': cloud}
        except Exception as e:
            return {'ok': False, 'error': str(e)}

    def reinstall_resources(self, kind, local_dirs):
        """后台按顺序重装多个资源；每项均要求缓存中的精确名称匹配。"""
        dirs = [str(x) for x in (local_dirs or [])]
        def _run():
            for local_dir in dirs:
                result = self._reinstall_local(kind, local_dir)
                if not result.get('ok'):
                    print(f'重装 {kind} {local_dir} 失败: {result.get("error")}')
        threading.Thread(target=_run, daemon=True).start()
        return {'ok': True, 'error': None}

    def _install_from_archive(self, archive, kind):
        """从 zip/7z 压缩包安装插件或 Mod (解压后识别 info 文件所在目录)"""
        import tempfile, shutil
        tmp = tempfile.mkdtemp(prefix='faust_inst_')
        try:
            if archive.lower().endswith('.zip'):
                import zipfile
                with zipfile.ZipFile(archive) as zf:
                    zf.extractall(tmp)
            elif archive.lower().endswith('.7z'):
                from functions.web_update.zeroasso_download import extract_with_7zip
                if not extract_with_7zip(archive, tmp):
                    return {'ok': False, 'error': '7z 解压失败'}
            else:
                return {'ok': False, 'error': '仅支持 zip/7z 压缩包'}
            info_name = 'addon_info.json' if kind == 'addon' else 'mod_info.json'
            target = None
            for root, dirs, files in os.walk(tmp):
                if info_name in files:
                    target = root
                    break
            if not target:
                return {'ok': False, 'error': f'压缩包中未找到 {info_name}'}
            if kind == 'addon':
                from functions.extension.addon.addon_utils import AddonManager
                ok = AddonManager().add_addon(target)
            else:
                import shutil as _sh
                name = os.path.basename(target) or 'mod'
                dest = os.path.join('mods', name)
                if os.path.exists(dest):
                    _sh.rmtree(dest, ignore_errors=True)
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                _sh.copytree(target, dest)
                ok = True
            return {'ok': bool(ok), 'error': None}
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def install_addon_dialog(self):
        """选择本地插件压缩包 (zip/7z) 或目录安装到 addons/"""
        try:
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            path = filedialog.askopenfilename(
                title='选择插件压缩包 (zip/7z)',
                filetypes=[('压缩包', '*.zip *.7z'), ('所有文件', '*.*')])
            root.destroy()
            if not path:
                return {'ok': False, 'error': None}
            if path.lower().endswith(('.zip', '.7z')):
                return self._install_from_archive(path, 'addon')
            from functions.extension.addon.addon_utils import AddonManager
            ok = AddonManager().add_addon(path)
            return {'ok': bool(ok), 'error': None}
        except Exception as e:
            return {'ok': False, 'error': str(e)}

    def install_mod_dialog(self):
        """选择本地 Mod 压缩包 (zip/7z) 安装到 mods/"""
        try:
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            path = filedialog.askopenfilename(
                title='选择 Mod 压缩包 (zip/7z)',
                filetypes=[('压缩包', '*.zip *.7z'), ('所有文件', '*.*')])
            root.destroy()
            if not path:
                return {'ok': False, 'error': None}
            return self._install_from_archive(path, 'mod')
        except Exception as e:
            return {'ok': False, 'error': str(e)}

    def set_mod_settings(self, name, settings):
        """更新 Mod 的 mod_info.json settings 字段 (含 enable)"""
        import json, os
        path = os.path.join('mods', str(name), 'mod_info.json')
        if not os.path.exists(path):
            return {'error': f"Mod 信息文件不存在: {path}"}
        try:
            info = read_json(path)
            info['settings'] = dict(settings or {})
            write_json(path, info, indent=4)
            return {'error': None}
        except Exception as e:
            return {'error': str(e)}

    def _reload_addons_async(self):
        """后台线程重载插件 (设置修改/启用禁用后调用)"""
        def _run():
            try:
                self.core._on_reload_addons()
            except Exception as e:
                print(f"重载插件失败: {e}")
        threading.Thread(target=_run, daemon=True).start()

    def set_addon_settings(self, name, settings):
        """更新插件 addon_info.json 的 settings 字段 (含 enable 与各项自定义设置)"""
        import json, os
        path = os.path.join('addons', str(name), 'addon_info.json')
        if not os.path.exists(path):
            return {'error': f"插件信息文件不存在: {path}"}
        try:
            info = read_json(path)
            info['settings'] = dict(settings or {})
            write_json(path, info, indent=4)
            self._reload_addons_async()   # 设置修改后自动重载插件
            return {'error': None}
        except Exception as e:
            return {'error': str(e)}

    def set_mod_enabled(self, name, enabled):
        """启用/禁用目录 Mod (写入 mod_info.json 的 settings.enable)"""
        import json, os
        path = os.path.join('mods', str(name), 'mod_info.json')
        if not os.path.exists(path):
            return {'error': f"Mod 信息文件不存在: {path}"}
        try:
            info = read_json(path)
            info.setdefault('settings', {})['enable'] = bool(enabled)
            write_json(path, info, indent=4)
            return {'error': None}
        except Exception as e:
            return {'error': str(e)}

    def set_addon_enabled(self, name, enabled):
        """启用/禁用插件 (写入 addon_info.json 的 settings.enable)"""
        import json, os
        path = os.path.join('addons', str(name), 'addon_info.json')
        if not os.path.exists(path):
            return {'error': f"插件信息文件不存在: {path}"}
        try:
            info = read_json(path)
            info.setdefault('settings', {})['enable'] = bool(enabled)
            write_json(path, info, indent=4)
            self._reload_addons_async()   # 启用/禁用后自动重载插件
            return {'error': None}
        except Exception as e:
            return {'error': str(e)}

    def _rmtree_robust(self, path, max_tries=5, delay=1.5):
        """删除目录, 被占用时自动重试; 仍失败则逐文件报告被占用的路径"""
        import time, shutil
        for attempt in range(max_tries):
            try:
                shutil.rmtree(path)
                return None
            except Exception as e:
                print(f"删除 {path} 失败 (第{attempt+1}/{max_tries}次): {type(e).__name__}: {e}", flush=True)
                time.sleep(delay)
        errors = []
        try:
            shutil.rmtree(path, onerror=lambda fn, p, exc: errors.append((p, exc)))
        except Exception:
            pass
        for p, exc in errors:
            msg = str(exc[1]) if exc and len(exc) > 1 else str(exc)
            print(f"  被占用无法删除: {p} ({msg})")
        return errors

    def _notify_res_changed(self, kind, error=None):
        """卸载/安装后通知前端立即刷新已安装状态 (下载中心/每日推荐/资源管理)"""
        try:
            win = self.window_ref.get("win") if self.window_ref else None
            if win is None:
                return
            if error:
                import json as _json
                win.evaluate_js("window.__onResError(" + _json.dumps(str(error), ensure_ascii=False) + ")")
            else:
                win.evaluate_js("window.__onResChanged('%s')" % kind)
        except Exception:
            pass

    def delete_addon(self, name):
        """删除插件: 走 AddonManager.remove_addon (执行插件注册的删除回调+重扫),
        成功后重载插件 (含托盘菜单) 并通知前端立即刷新状态。"""
        try:
            am = getattr(self.core, 'addon_manager', None)
            ok = False
            if am is not None and hasattr(am, 'remove_addon'):
                ok = bool(am.remove_addon(str(name)))
            else:
                import os, shutil
                path = os.path.join('addons', str(name))
                if os.path.isdir(path):
                    shutil.rmtree(path, ignore_errors=False)
                    ok = True
            if not ok:
                return {'error': f'插件 {name} 删除失败'}
            # 卸载后重载插件 (含托盘菜单更新), 后台线程执行
            def _reload():
                try:
                    self.core._on_reload_addons()
                except Exception as e:
                    print(f"卸载后重载插件失败: {e}")
            threading.Thread(target=_reload, daemon=True).start()
            self._notify_res_changed('addon')
            return {'error': None}
        except Exception as e:
            return {'error': str(e)}

    def delete_mod(self, name):
        """删除目录 Mod: 后台线程先 unload_mod (执行卸载脚本/清理游戏目录副本/语言文件),
        再删除 mods/<name> 目录, 完成后通知前端刷新状态。
        后台线程避免 Uninstaller.bat 等阻塞 js_api 调用 (否则前端会无响应)。"""
        def _run():
            try:
                from functions.extension.mod.mod_utils import ModManager
                import os
                mm = ModManager()
                path = os.path.join('mods', str(name))
                if not os.path.isdir(path):
                    print(f"删除 Mod {name} 失败: 目录不存在 {path}", flush=True)
                    return
                print(f"开始删除 Mod: {name} (目录 {path})", flush=True)
                # 串行执行 unload_mod: 先运行 Uninstaller.bat (含 echo 输出日志) +
                # MD5 清理游戏目录副本 + 清理语言文件; 结束后释放文件句柄再删除 mods 目录
                try:
                    mm.unload_mod(str(name), run_bat=True)
                    print(f"Mod {name} 卸载缓存完成", flush=True)
                except Exception as e:
                    print(f"卸载 Mod {name} 缓存失败(继续删除): {e}", flush=True)
                errs = self._rmtree_robust(path)
                if errs:
                    print(f"删除 Mod {name} 失败: 部分文件被占用无法删除", flush=True)
                    self._notify_res_changed('mod', error=f"删除失败: 有文件被其他程序占用 (可能是游戏或资源管理器) \n{errs[0][0]}")
                else:
                    print(f"已删除 Mod 目录: {path}", flush=True)
                    self._notify_res_changed('mod')
            except Exception as e:
                import traceback
                print(f"删除 Mod {name} 失败: {e}", flush=True)
                print(traceback.format_exc(), flush=True)
                self._notify_res_changed('mod', error=f"删除失败: {e}")
        threading.Thread(target=_run, daemon=True).start()
        return {'error': None}

    def apply_mods(self):
        """立即应用 Mod (load_all_mods), 后台线程执行"""
        def _run():
            from functions.extension.mod.mod_utils import ModManager
            try:
                loaded = ModManager().load_all_mods()
                print(f"Mod 应用完成, 已加载 {len(loaded)} 个")
            except Exception as e:
                print(f"应用 Mod 失败: {e}")
        threading.Thread(target=_run, daemon=True).start()
        return True

    def toggle_single_file(self, raw_name):
        from functions.pages.tools.mod_manager_window import _toggle_file
        return _toggle_file(raw_name)

    def delete_single_file(self, raw_name):
        from functions.pages.tools.mod_manager_window import _delete_file
        return _delete_file(raw_name)

    def open_mods_dir(self, which):
        import os
        try:
            if which == "single":
                from functions.pages.tools.mod_manager_window import _get_mod_dir
                d = _get_mod_dir()
            elif which == "addon":
                d = os.path.abspath("addons")
            else:
                d = os.path.abspath("mods")
            if os.path.exists(d):
                os.startfile(d)
                return {'error': None}
            return {'error': f"目录不存在: {d}"}
        except Exception as e:
            return {'error': str(e)}

    def open_mod_manager_window(self):
        """拉起独立 Mod 管理器窗口 (支持拖拽安装)"""
        try:
            from functions.pages.tools.mod_manager_window import open_mod_manager_window as _open
            return bool(_open(self.core))
        except Exception as e:
            print(f"打开独立 Mod 管理器失败: {e}")
            return False

    def _open_folder_link(self):
        """文件夹超链接: tkinter 对话框在 pywebview 主循环下可短暂独立运行"""
        import tkinter as tk
        from tkinter import filedialog, messagebox
        try:
            root = tk.Tk()
            root.withdraw()
            messagebox.showinfo("选择源文件夹", "请选择要创建链接的源文件夹", parent=root)
            source = filedialog.askdirectory(title="选择源文件夹", parent=root)
            if not source:
                root.destroy()
                return
            messagebox.showinfo("选择目标位置", "请选择链接要放置的目标文件夹", parent=root)
            target = filedialog.askdirectory(title="选择目标文件夹", parent=root)
            if not target:
                root.destroy()
                return
            root.destroy()
            self._create_junction(source, target)
        except Exception as e:
            print(f"创建文件夹链接失败: {e}")

    @staticmethod
    def _create_junction(source_path, target_path):
        import subprocess
        from tkinter import messagebox, Tk
        source_name = os.path.basename(source_path)
        link_path = os.path.join(target_path, source_name)
        if os.path.exists(link_path):
            root = Tk()
            root.withdraw()
            overwrite = messagebox.askyesno(
                "确认覆盖", f"目标位置已存在同名文件夹 '{source_name}', 是否覆盖？", parent=root)
            root.destroy()
            if not overwrite:
                return
        batch_content = f'''@echo off
echo 正在创建文件夹链接...
mklink /J "{link_path}" "{source_path}"
if %errorlevel% equ 0 (
    echo 文件夹链接创建成功！
    echo 源文件夹: {source_path}
    echo 链接位置: {link_path}
    pause
) else (
    echo 创建文件夹链接失败, 请检查权限或路径是否正确
)
'''
        batch_file = os.path.join(_PROJECT_ROOT, "create_link.bat")
        with open(batch_file, "w", encoding="gbk") as f:
            f.write(batch_content)
        subprocess.Popen(
            f'powershell Start-Process "{batch_file}" -Verb runAs', shell=True)

    def quit_app(self):
        import os
        try:
            self.window_ref.destroy()
        except Exception:
            pass
        os._exit(0)
        return True

    # ---- 下载中心 (在线) ----
    def _get_web_trigger(self):
        """懒加载 WebTrigger (在线 Mod/插件列表客户端)"""
        if not getattr(self, '_web_trigger', None):
            from functions.web_update.web_trigger import WebTrigger
            self._web_trigger = WebTrigger()
        return self._web_trigger

    def _check_dc_config(self):
        """检查下载中心是否已配置云端地址"""
        try:
            from functions.base.web_config import get_webnote
            addon_addr = get_webnote('addon_info')[0]
            mod_addr = get_webnote('mod_info')[0]
            if not addon_addr or not mod_addr:
                return '下载中心未配置: 请在 config/web_config.json 中填写 webnote.addon_info.address 和 webnote.mod_info.address'
        except Exception as e:
            return f'读取配置失败: {e}'
        return None

    def _get_cached_list(self, kind):
        """云端列表: 复用启动同步的内存缓存 (每次启动只获取一次, 下载中心与同步共享, 不重复爬取)"""
        from functions.pages.app import page_loader as _pl
        if _pl._cloud_sync_cache.get(kind):
            print(f"获取到 {kind} 云端资源缓存。")
            return _pl._cloud_sync_cache[kind]
        wt = self._get_web_trigger()
        print(f"初始化云端 {kind} 资源...")
        data = (wt.fetch_all_addon_info() if kind == 'addon'
                else wt.fetch_all_mod_info())
        data = data if data else []
        _pl._cloud_sync_cache[kind] = data
        print(f'初始化云端 {kind} 资源完成。')
        return data

    def check_item_downloaded(self, kind, name):
        """检测插件/Mod 是否已下载安装 (每次刷新下载中心都会重新检测, 用户可能手动删除)
        本地目录名是英文, 云端 name 是中文显示名, 需按 addon_info.json/mod_info.json 的 name 匹配,
        仅接受目录名或 info 文件 name 与云端 name 的完全匹配。"""
        import os
        try:
            root = 'addons' if kind == 'addon' else 'mods'
            if not os.path.isdir(root):
                return {'downloaded': False}
            name = str(name)
            for folder in os.listdir(root):
                path = os.path.join(root, folder)
                if not os.path.isdir(path):
                    continue
                if folder == name:
                    return {'downloaded': True}
                info_file = os.path.join(path, 'addon_info.json' if kind == 'addon' else 'mod_info.json')
                try:
                    if os.path.isfile(info_file):
                        import json as _json
                        info = read_json(info_file)
                        local_name = str(info.get('name', '')).strip()
                        if local_name == name:
                            return {'downloaded': True}
                except Exception:
                    continue
            return {'downloaded': False}
        except Exception as e:
            return {'downloaded': False, 'error': str(e)}

    def get_addon_list(self):
        """获取插件列表 (内存缓存, 不再爬取)"""
        try:
            return {'pages': self._get_cached_list('addon'), 'error': None}
        except Exception as e:
            return {'pages': [], 'error': str(e)}

    def get_mod_list(self):
        """获取 Mod 列表 (内存缓存, 不再爬取)"""
        try:
            return {'pages': self._get_cached_list('mod'), 'error': None}
        except Exception as e:
            return {'pages': [], 'error': str(e)}

    def increase_download_count(self, kind, name):
        """下载计数 +1 并上传到云端 (静默失败, 不影响下载)"""
        try:
            wt = self._get_web_trigger()

            if kind == 'addon':
                wt.add_download_number_addon(name)
            else:
                wt.add_download_number_mod(name)
            return True
        except Exception as e:
            print(f"上传下载计数失败: {e}")
            return False

    def download_addon(self, name, url):
        """下载并安装插件 (后台线程, 对齐主分支: 解压识别后落入 addons/<name>/)"""
        def _run():
            try:
                from functions.web_update.zeroasso_download import download_and_extract_mod
                import shutil
                target = 'addons'
                try:
                    shutil.rmtree(os.path.join(target, name), ignore_errors=True)
                except Exception:
                    pass
                download_files = [{'url': url, 'name': name, 'temp_filename': f"{name}.7z"}]
                gui = HeadlessDownloadGUI(target, auto_start=False, task=name)
                ok = download_and_extract_mod(gui, target, download_files)
                if ok:
                    print(f"插件 {name} 下载并解压完成")
                    try:
                        self.core.addon_manager.reload_all_addons()
                    except Exception:
                        pass
                    # 解压落盘完成后再通知前端刷新 (资源管理/下载中心/推荐)
                    self._notify_res_changed('addon')
                else:
                    print(f"插件 {name} 下载失败")
            except Exception as e:
                print(f"下载插件 {name} 失败: {e}")
        threading.Thread(target=_run, daemon=True).start()
        return True

    def download_mod(self, name, url):
        """下载并安装 Mod (后台线程)"""
        def _run():
            try:
                from functions.web_update.zeroasso_download import download_and_extract_mod
                from functions.extension.mod.mod_utils import ModManager
                import shutil
                target = 'mods'
                download_files = [{'url': url, 'name': name, 'temp_filename': f"{name}.7z"}]
                try:
                    ModManager().unload_mod(name)
                except Exception:
                    pass
                try:
                    shutil.rmtree(os.path.join('mods', name), ignore_errors=True)
                except Exception:
                    pass
                gui = HeadlessDownloadGUI(target, auto_start=False, task=name)
                ok = download_and_extract_mod(gui, target, download_files)
                if ok:
                    print(f"Mod {name} 下载并解压完成")
                    # 解压落盘完成后再通知前端刷新 (资源管理/下载中心/推荐)
                    self._notify_res_changed('mod')
                else:
                    print(f"Mod {name} 下载失败")
            except Exception as e:
                print(f"下载 Mod {name} 失败: {e}")
        threading.Thread(target=_run, daemon=True).start()
        return True

    def get_icon(self, icon_url, item_name):
        """下载并缓存图标, 返回 base64 data URI"""
        if not icon_url:
            return ''
        from functions.base.common import icon_cache
        cache_dir = os.path.join(_PROJECT_ROOT, 'cache', 'icons')
        os.makedirs(cache_dir, exist_ok=True)
        # 查找按 icon_url 哈希兜底: 条目名不同(云端名/目录名/改名)也要能命中已有缓存
        icon_path = icon_cache.find_cached_icon(icon_url, item_name, cache_dir)
        if not (icon_path and os.path.exists(icon_path)):
            # 落盘统一用标准命名
            icon_path = icon_cache.icon_cache_path(icon_url, item_name, cache_dir)
            # 刚失败过的图标先跳过, 前端反复重绘时不必反复请求
            if icon_cache.icon_failed_recently(icon_url):
                return ''
            try:
                # 解析直链 + 取内容; 直链失效会自动丢缓存重解析一次
                from functions.web_update.lanzou_utils import GetWithDirectLink
                r = GetWithDirectLink(
                    icon_url,
                    accept=lambda resp: resp.status_code == 200
                    and icon_cache.looks_like_image(resp.content),
                    timeout=15, verify=False)
                if r is not None and r.status_code == 200 \
                        and icon_cache.looks_like_image(r.content):
                    with open(icon_path, 'wb') as f:
                        f.write(r.content)
                    icon_cache.note_icon_success(icon_url)
                else:
                    icon_cache.note_icon_failure(icon_url)
                    return ''
            except Exception:
                icon_cache.note_icon_failure(icon_url)
                return ''
        try:
            with open(icon_path, 'rb') as f:
                return "data:image/png;base64," + base64.b64encode(f.read()).decode('ascii')
        except Exception:
            return ''

    # ---- 自动汉化 ----
    def start_auto_translate(self, source, target, blacklist):
        """启动自动汉化 (后台线程)"""
        def _run():
            try:
                from functions.translate.auto_translate import auto_translate
                def progress_cb(percent, msg):
                    try:
                        self.window_ref.evaluate_js(
                            "window.__onEvent('translate_progress', {percent:" + str(percent) +
                            ",message:" + json.dumps(msg) + "})")
                    except Exception:
                        pass
                auto_translate(source, target, blacklist, progress_callback=progress_cb)
            except Exception as e:
                print(f"自动汉化失败: {e}")
        threading.Thread(target=_run, daemon=True).start()
        return True

    # ---- 主页: 更新内容 / 随机推荐 ----
    def get_changelog(self):
        """更新内容: 优先云端 version_info 全部历史版本说明, 失败回退本地 CHANGELOG.md"""
        try:
            from functions.base.web_config import get_webnote
            from functions.webFunc.Webnote import Note
            from json import loads
            note = Note("version_info", get_webnote('version_info')[0])
            note.fetch_note_info()
            if note.note_content.strip():
                info = loads(note.note_content)
                versions = info.get('versions', {})
                if versions:
                    # 版本号排序键: 取每段开头的数字 (兼容 v1.2.3 / 1.2.3-beta 等)
                    def _ver_key(v):
                        nums = []
                        for seg in str(v).lstrip('vV').split('.'):
                            n = ''
                            for ch in seg:
                                if ch.isdigit():
                                    n += ch
                                else:
                                    break
                            nums.append(int(n) if n else 0)
                        return tuple(nums)
                    ordered = sorted(versions.keys(), key=_ver_key, reverse=True)
                    blocks = []
                    for ver in ordered:
                        entry = versions.get(ver, {}) or {}
                        desc = (entry.get('description') or '').strip()
                        if not desc:
                            continue
                        date = entry.get('date') or entry.get('data') or ''
                        time = ((' (' + str(date) + ')') if date else '')
                        lines = desc.split('\n')
                        lines[0] = lines[0] + ' ' + time # type: ignore
                        blocks.append('\n'.join(lines))
                    if blocks:
                        return ('\n'+60*'-'+'\n').join(blocks)
        except Exception as e:
            print(f"云端更新内容获取失败, 使用本地 CHANGELOG: {e}")
        for candidate in (
            os.path.join(_PROJECT_ROOT, "CHANGELOG.md"),
            os.path.join(_PROJECT_ROOT, "_internal", "CHANGELOG.md"),
        ):
            if os.path.isfile(candidate):
                try:
                    with open(candidate, encoding="utf-8") as f:
                        return f.read()
                except Exception:
                    return ""
        return ""

    def get_random_recommend(self):
        """随机返回一个插件或 Mod 推荐条目 (含图标/描述/下载量)"""
        import random
        items = []
        try:
            for page in self._get_cached_list('addon'): # type: ignore
                for it in page:
                    if not it.get("disabled"):
                        items.append((it, "addon"))
            for page in self._get_cached_list('mod'): # type: ignore
                for it in page:
                    if not it.get("disabled"):
                        items.append((it, "mod"))
        except Exception as e:
            print(f"获取推荐失败: {e}")
        if not items:
            return {"kind": None, "item": None, "error": "暂无可用推荐"}
        kind, item = random.choice(items)
        return {
            "kind": kind,
            "item": {
                "name": item.get("name", "未知"),
                "desc": item.get("desc", ""),
                "icon_url": item.get("icon_url", ""),
                "version": item.get("version", ""),
                "download_count": item.get("download_count", 0),
                "authors": item.get("authors", {}),
                "url": item.get("dowload_url") or item.get("download_url", ""),
            },
            "error": None,
        }

    # ---- 版本更新 ----
    def refresh_cloud_list(self, kind='both'):
        """从云端强制重新获取插件/Mod 列表 (忽略本次启动的内存缓存, 供下载中心"刷新"按钮用)"""
        try:
            from functions.pages.app import page_loader as _pl
            from functions.webFunc.Webnote import memo_clear
            kinds = ['addon', 'mod'] if kind in ('both', None, '') else [str(kind)]
            for k in kinds:
                _pl._cloud_sync_cache[k] = None
            memo_clear()                      # 清掉进程内记忆, 强制重新请求云端
            wt = self._get_web_trigger()
            counts = {}
            for k in kinds:
                data = (wt.fetch_all_addon_info(allow_refresh=True) if k == 'addon'
                        else wt.fetch_all_mod_info(allow_refresh=True))
                data = data or []
                _pl._cloud_sync_cache[k] = data
                counts[k] = sum(len(p) for p in data)
            print(f"[下载中心] 已从云端刷新: {counts}")
            return {'ok': True, 'counts': counts, 'error': None}
        except Exception as e:
            print(f"[下载中心] 云端刷新失败: {e}")
            return {'ok': False, 'counts': {}, 'error': str(e)}

    def check_update(self):
        """检查版本更新, 返回最新版本信息"""
        try:
            from functions.base.web_config import get_webnote
            from functions.webFunc.Webnote import Note
            from json import loads
            from functions.base.settings_manager import get_settings_manager
            sm = get_settings_manager()
            current = str(sm.get_setting('version_info') or '')
            note = Note("version_info", get_webnote('version_info')[0])
            # 手动检查更新: 强制联网取最新 (不走本次启动的已获取内容)
            note.fetch_note_info(allow_refresh=True)
            if not note.note_content.strip():
                return {'current': current, 'has_update': False, 'error': '未配置版本信息'}
            info = loads(note.note_content)
            latest = (info.get('latest_release_version') or '').strip()
            entry = info.get('versions', {}).get(latest, {}) if latest else {}
            return {
                'current': current,
                'latest': latest,
                'has_update': bool(latest and latest != current),
                'description': entry.get('description', ''),
                'date': entry.get('data') or entry.get('date', ''),
                'bilibili_url': entry.get('url', ''),
                'error': None,
            }
        except Exception as e:
            return {'error': str(e)}

    # ---- 版本更新 (应用内二级模态窗口) ----
    def _push_event(self, event, data=None):
        """向前端推送事件 (window.__onEvent), 失败返回 False"""
        try:
            win = self.window_ref.get("win") if self.window_ref else None
            if win is None:
                return False
            payload = json.dumps(data if data is not None else {}, ensure_ascii=False)
            win.evaluate_js("window.__onEvent(%s, %s)" % (json.dumps(str(event)), payload))
            return True
        except Exception as e:
            print(f"[推送事件] {event} 失败: {e}")
            return False

    def push_version_modal(self, payload):
        """version_notify 注册的推送函数: 前端弹出应用内版本更新模态窗口"""
        try:
            win = self.window_ref.get("win") if self.window_ref else None
            if win is None:
                return False
            self._version_payload = dict(payload or {})
            win.evaluate_js("window.__onVersionModal(%s)" % json.dumps(payload, ensure_ascii=False))
            return True
        except Exception as e:
            print(f"[版本更新] 推送应用内模态窗口失败: {e}")
            return False

    def get_version_modal(self):
        """读取云端版本信息, 返回版本模态窗口数据 (手动打开, 不强制下载)"""
        try:
            from functions.pages.notice.version_notify import manual_payload
            payload = manual_payload()
            self._version_payload = dict(payload)
            return payload
        except Exception as e:
            print(f"[版本更新] 读取版本信息失败: {e}")
            return {'error': str(e), 'has_update': False, 'can_update': False, 'forced': False}

    def start_version_update(self):
        """开始下载并安装新版本 (后台线程, 进度经 __onEvent('version_update') 推送)"""
        try:
            from functions.pages.notice.version_notify import (
                collect_version_info, start_version_download,
            )
            payload = getattr(self, '_version_payload', None) or {}
            url = str(payload.get('url') or '')
            version = str(payload.get('latest') or '')
            if not url:
                info = collect_version_info(allow_refresh=True)
                entry = info.get('entry') or {}
                url = str(entry.get('url') or entry.get('bilibili_url') or '')
                version = str(info.get('latest') or version)
            if not url:
                return {'ok': False, 'error': '未获取到新版本下载地址, 请稍后重试'}

            def _push(data):
                self._push_event('version_update', data)

            ok = start_version_download(version, url, _push)
            if not ok:
                return {'ok': False, 'error': '更新包正在下载中, 请稍候'}
            return {'ok': True, 'error': None}
        except Exception as e:
            print(f"[版本更新] 启动下载失败: {e}")
            return {'ok': False, 'error': str(e)}

    # ---- 汉化状态 ----
    def get_translation_status(self):
        """检查汉化文件状态"""
        import os
        game_path = ''
        try:
            from functions.base.settings_manager import get_settings_manager
            game_path = str(get_settings_manager().get_setting('game_path') or '')
        except Exception:
            pass
        if not game_path or not os.path.isdir(game_path):
            return {'status': 'no_game', 'label': '游戏未配置'}
        from functions.web_update.translation_source import get_translation_dir_name
        # 汉化目录名跟随当前平台 (零协会 LLC_zh-CN / OurPlay OurPlayHanHua / 插件自定义), 不再写死
        lang_dir = os.path.join(game_path, 'LimbusCompany_Data', 'lang', get_translation_dir_name())
        if not os.path.isdir(lang_dir):
            return {'status': 'not_installed', 'label': '未安装'}
        try:
            count = len([f for f in os.listdir(lang_dir) if not f.startswith('.')])
            if count == 0:
                return {'status': 'empty', 'label': '空目录'}
            return {'status': 'installed', 'label': f'已安装 ({count} 项)'}
        except Exception:
            return {'status': 'error', 'label': '无法读取'}

    # ---- 字体管理 ----
    def get_font_info(self):
        """获取当前字体信息"""
        import os
        result = {}
        for kind in ('context', 'title'):
            path = os.path.join('assets', 'Font', kind, 'ChineseFont.ttf')
            exists = os.path.exists(path)
            result[kind] = {
                'exists': exists,
                'size': os.path.getsize(path) if exists else 0,
                'path': path,
            }
        return result

    def get_font_data(self, kind):
        """返回当前自定义字体的 data URI (供前端 FontFace 真实加载预览)"""
        import os
        try:
            if kind not in ('context', 'title'):
                return {'uri': ''}
            path = os.path.join('assets', 'Font', kind, 'ChineseFont.ttf')
            if not os.path.exists(path) or os.path.getsize(path) == 0:
                return {'uri': ''}
            if os.path.getsize(path) > 20 * 1024 * 1024:
                return {'uri': '', 'error': '字体文件过大, 无法预览'}
            with open(path, 'rb') as f:
                b64 = base64.b64encode(f.read()).decode('ascii')
            return {'uri': 'data:font/ttf;base64,' + b64}
        except Exception as e:
            return {'uri': '', 'error': str(e)}

    def upload_font(self, kind, file_data_b64):
        """上传并替换字体 (kind = 'context' 或 'title')"""
        import base64 as _b64
        try:
            if kind not in ('context', 'title'):
                return {'error': '无效的字体类型'}
            dest = os.path.join('assets', 'Font', kind, 'ChineseFont.ttf')
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            data = _b64.b64decode(file_data_b64)
            with open(dest, 'wb') as f:
                f.write(data)
            return {'error': None, 'size': len(data)}
        except Exception as e:
            return {'error': str(e)}

    def delete_font(self, kind):
        """删除自定义字体"""
        import os
        try:
            if kind not in ('context', 'title'):
                return {'error': '无效的字体类型'}
            dest = os.path.join('assets', 'Font', kind, 'ChineseFont.ttf')
            if os.path.exists(dest):
                os.remove(dest)
            return {'error': None}
        except Exception as e:
            return {'error': str(e)}



    # ---- 渐变文本处理器 ----
    def generate_gradient_text(self, text, start_color, end_color, gradient_rate=2.0):
        """生成 Unity 富文本渐变色代码"""
        try:
            from functions.fancy.dialog_colorful import apply_color_gradient_custom
            result = apply_color_gradient_custom(text, start_color, end_color, float(gradient_rate))
            return {'result': result, 'error': None}
        except Exception as e:
            return {'result': '', 'error': str(e)}

# ============================================================
# 游戏进程监视: 启动成功/退出 -> 推送前端流水线事件
# ============================================================

def _game_process_running():
    """检测 LimbusCompany.exe 是否在运行 (tasklist, 不依赖 psutil)"""
    try:
        import subprocess
        out = subprocess.check_output(
            'tasklist /FI "IMAGENAME eq LimbusCompany.exe" /FO CSV /NH',
            shell=True, creationflags=0x08000000)  # CREATE_NO_WINDOW
        return b"LimbusCompany.exe" in out
    except Exception:
        return False


def _monitor_game_process(window_ref):
    """后台监听游戏进程: 出现推送 game_started, 退出推送 game_exited 后结束"""
    def _push(event, data=None):
        try:
            win = window_ref.get("win")
            if win is None:
                return
            payload = json.dumps(data or {}, ensure_ascii=False)
            win.evaluate_js(f"window.__onEvent({json.dumps(event)}, {payload})")
        except Exception:
            pass

    def _run():
        started = False
        exited_at = None
        waited = 0.0
        while True:
            running = _game_process_running()
            if running and not started:
                started = True
                exited_at = None
                print("检测到游戏进程已启动")
                _push("game_started")
            elif not running and started:
                if exited_at is None:
                    exited_at = time.time()
                elif time.time() - exited_at > 2:
                    print("游戏进程已退出")
                    _push("game_exited")
                    return
            elif not running and not started:
                waited += 2
                if waited > 480:
                    print("等待游戏启动超时 (8 分钟)")
                    _push("game_timeout")
                    return
            time.sleep(2)

    threading.Thread(target=_run, daemon=True).start()


# ============================================================
# 托盘
# ============================================================

def _start_tray(core, window, win32_show):
    import pystray
    from PIL import Image

    # 设置应用用户模型 ID: 否则 Windows 通知气泡标题会显示进程名 (python)
    ico_path = os.path.join(_PROJECT_ROOT, "assets", "images", "icon", "icon.ico")
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("FaustLauncher")
    except Exception:
        pass
    # 注册 AUMID 图标/名称: 否则 Windows 通知中心 (toast) 找不到 AUMID 对应图标, 气泡提示无项目图标
    try:
        import winreg
        _aumid_key = winreg.CreateKey(winreg.HKEY_CURRENT_USER,
                                      r"Software\Classes\AppUserModelId\FaustLauncher")
        _ico_abs = os.path.abspath(ico_path)
        winreg.SetValueEx(_aumid_key, "DisplayIcon", 0, winreg.REG_SZ, _ico_abs)
        winreg.SetValueEx(_aumid_key, "DisplayName", 0, winreg.REG_SZ, "FaustLauncher")
        winreg.CloseKey(_aumid_key)
    except Exception:
        pass

    try:
        ico = Image.open(ico_path)
    except Exception:
        ico = Image.new("RGBA", (64, 64), (99, 102, 241, 255))

    def _tray_window_op(show):
        """在独立线程执行窗口显示/隐藏 (带透明度渐变), 绝不阻塞 pystray 回调线程"""
        def _do():
            try:
                hwnd = _win32_hwnd(window)
                if show:
                    if hwnd:
                        _ensure_layered(hwnd)
                        _set_window_alpha(hwnd, 0)    # 先设透明再显示, 避免闪现
                    win32_show(True)
                    if hwnd:
                        _fade_window(hwnd, 0, 255)    # 渐变出现
                        _clear_layered(hwnd)   # 渐入完成 -> 摘掉分层, 回到 GPU 合成
                else:
                    if hwnd:
                        _ensure_layered(hwnd)
                        _fade_window(hwnd, 255, 0)    # 渐变消失
                    win32_show(False)
            except Exception:
                pass
        threading.Thread(target=_do, daemon=True).start()

    def show_win(icon=None, item=None):
        _tray_window_op(True)

    def hide_win(icon=None, item=None):
        _tray_window_op(False)

    def when_exit(icon=None, item=None):
        # 退出前先完成淡出, 否则立即 TerminateProcess 会截断所有视觉动画。
        def _quit():
            try:
                hwnd = _win32_hwnd(window)
                if hwnd:
                    _ensure_layered(hwnd)
                    _fade_window(hwnd, 255, 0)
                win32_show(False)
            finally:
                # 不调用 icon.stop(), 避免托盘回调线程阻塞。
                _terminate_now()
        threading.Thread(target=_quit, daemon=True).start()

    def build_addon_menu():
        items = []
        try:
            for addon in core.addon_manager.get_all_addons():
                name = addon["name"]
                try:
                    enabled = bool(addon.get("info", {}).get("settings", {}).get("enable", True))
                except Exception:
                    enabled = True

                def _make_runner(n):
                    def _run(icon=None, item=None):
                        try:
                            core.addon_manager.run_addon(n)
                        except Exception as e:
                            print(f"手动运行插件 {n} 失败: {e}")
                    return _run

                label = f"🔧 {name}" if enabled else f"⚙️ {name} (已禁用)"
                items.append(pystray.MenuItem(label, _make_runner(name)))
        except Exception:
            pass
        if not items:
            items.append(pystray.MenuItem("（暂无可用插件）", None, enabled=False))
        return pystray.Menu(*items)

    menu = pystray.Menu(
        pystray.MenuItem("显示窗口", show_win, default=True),
        pystray.MenuItem("隐藏", hide_win),
        pystray.MenuItem("插件", lambda icon, item: build_addon_menu()),
        pystray.MenuItem("重载插件", lambda icon=None, item=None: core._on_reload_addons()),
        pystray.MenuItem("退出", when_exit),
    )
    tray = pystray.Icon("FaustLauncher", ico, "浮士德启动器", menu)
    tray.on_activate = show_win   # type: ignore # 单击/双击托盘图标时显示窗口
    threading.Thread(target=tray.run, daemon=True).start()
    return tray


# ============================================================
# 窗口入口
# ============================================================

def run_web_ui(debug: bool = False):
    """主入口: 启动 pywebview 主窗口 (必须运行在主线程)

    Args:
        debug (bool, optional): 是否开启调试模式. 

    Raises:
        SystemExit: 未安装 pywebview 依赖
        SystemExit: 页面文件不存在

    Returns:
        _type_: _description_
    """
    try:
        import webview
    except BaseException as e:
        _msgbox("FaustLauncher", f"未安装 pywebview 依赖:\n{type(e).__name__}: {e}")
        raise SystemExit(1)

    if not os.path.exists(HTML_PATH):
        _msgbox("FaustLauncher", f"找不到页面文件:\n{HTML_PATH}")
        raise SystemExit(1)

    from functions.base.log_manager import init_logger
    init_logger()

    # 清理旧的更新脚本
    if os.path.exists(os.path.join(_PROJECT_ROOT, "updater.vbs")):
        try:
            os.remove(os.path.join(_PROJECT_ROOT, "updater.vbs"))
        except Exception:
            pass

    # stdout/stderr 加固: 无控制台打包(console=False)时它们都是 None,
    # rich 会退回它自己用 locale 编码(cp950 等)打开的 devnull, 打印简体字直接崩
    from functions.base.common.stdio import harden_stdio
    harden_stdio()

    # 先把 stdout/stderr 接到 Web 终端, 再创建核心对象:
    # 这样 FaustLauncherCore 初始化期间(加载背景图/扫描 mod 等)的 print 也能在界面终端里看到,
    # 而不再是无处可去(以前这段在 core 之后, 早期输出全丢)
    window_holder = {}

    def _evaluate_js(code):
        win = window_holder.get("win")
        if win is None:
            return
        try:
            # 执行JS代码
            win.evaluate_js(code)
        except Exception as e:
            print(f"执行JS代码失败: {e}")

    def _push_log(text):
        try:
            payload = json.dumps(text, ensure_ascii=False)
            _evaluate_js(f"window.__onLog({payload})")
        except Exception:
            pass

    log_redirector = WebLogRedirector(_push_log)
    log_redirector.start()

    from functions.pages.app.app_core import FaustLauncherCore
    from functions.extension.addon.addon_utils import AddonManager
    from functions.extension.mod.mod_utils import ModManager

    core = FaustLauncherCore()

    # 全局防卡死: 所有网络请求默认带超时; Tk 模态对话框转发到前端
    _patch_network_timeouts()

    # 无头下载注入: 流水线在 web 模式使用 HeadlessDownloadGUI
    import functions.web_update.zeroasso_download as zd
    zd.main_gui = lambda parent, config_path="": HeadlessDownloadGUI(
        config_path, download_func=zd.download_and_extract_gui)
    zd.DownloadGUI = lambda parent=None, config_path="", auto_start=True, download_func=None, task=None: HeadlessDownloadGUI(
        config_path, auto_start=auto_start, download_func=download_func, task=task) # type: ignore

    def _web_progress(event, data):
        try:
            payload = json.dumps(data, ensure_ascii=False)
            _evaluate_js(f"window.__onEvent({json.dumps(event)}, {payload})")
        except Exception:
            pass

    zd._web_progress = _web_progress # type: ignore

    # 拦截旧代码的 Tk 模态对话框 (必须在任何业务代码使用 messagebox 之前)
    _patch_tk_dialogs(_web_progress)

    # 版本更新流程的下载组件同样换成无头版
    try:
        import functions.update.version_utils as vu
        vu.DownloadGUI = zd.DownloadGUI # type: ignore
    except Exception:
        pass

    core.addon_manager = AddonManager([], app=type("WebAppShim", (), {"core": core})())
    try:
        core.addon_manager.run_all_addon()
    except Exception as e:
        print(f"插件初始化失败: {e}")
    core.mod_manager = ModManager()

    api = AppApi(core, window_holder)
    # 版本更新: Web 界面下走应用内二级模态窗口 (注册前端推送函数)
    try:
        from functions.pages.notice.version_notify import register_web_pusher
        register_web_pusher(api.push_version_modal)
    except Exception as e:
        print(f"[版本更新] 注册应用内模态窗口失败: {e}")
    # 窗口居中显示
    _win_x = _win_y = None
    try:
        import ctypes
        _sw = ctypes.windll.user32.GetSystemMetrics(0)
        _sh = ctypes.windll.user32.GetSystemMetrics(1)
        _win_x = max(0, (_sw - 1000) // 2)
        _win_y = max(0, (_sh - 760) // 2)
    except Exception:
        pass
    window = webview.create_window(
        "Faust Launcher",
        HTML_PATH,
        js_api=api,
        width=1000,
        height=760,
        x=_win_x,
        y=_win_y,
        min_size=(860, 740),
        background_color="#0b0e14",
        frameless=True,   # 去除原生标题栏, 使用自定义 HTML/CSS 标题栏
        easy_drag=False,  # 禁用 pywebview 默认的整窗拖动, 仅保留自定义标题栏拖动
        shadow=False,     # 禁用 DWM 无边框玻璃扩展, 消除整窗可拖
        hidden=True,      # 启动默认隐藏, ui_ready 透明度渐变出现 (无纯色闪现)
    )
    window_holder["win"] = window
    startup_state = {"shown": False}
    startup_lock = threading.Lock()

    def _show_after_load():
        """先以透明度显示已加载的 Splash，再渐入窗口，避免纯色窗口闪现。"""
        with startup_lock:
            if startup_state["shown"]:
                return
            startup_state["shown"] = True
        hwnd = _win32_hwnd(window)
        if not hwnd:
            _win32_show_window(True)
            return
        # 在第一次显示前完成命中测试拦截, 避免窗口显示后的早期鼠标事件走系统拖动。
        _disable_system_drag(window)
        _ensure_layered(hwnd)
        _set_window_alpha(hwnd, 0)
        _win32_show_window(True)

        # 窗口从隐藏变为可见后，先给 WebView 一次提交 Splash 首帧的机会；
        # 立即开始渐入会在低性能机器上先露出未绘制完成的纯色底。
        time.sleep(0.05)
        def _fade_in_then_unlayer():
            # 渐入到完全不透明后, 立刻摘掉 WS_EX_LAYERED:
            # 分层窗口会让整个窗口走 DWM 软件合成, 切页/动画时必然撕裂。
            # 摘掉后窗口回到正常 GPU 合成路径 (托盘淡出时会再临时加上)。
            _fade_window(hwnd, 0, 255, step=15, delay=0.01)
            _clear_layered(hwnd)

        threading.Thread(target=_fade_in_then_unlayer, daemon=True).start()

    try:
        api.ready_callback = _show_after_load # type: ignore
    except Exception:
        pass

    # loaded 事件独立于 JS API 调用队列。延迟一小段时间让 Splash 完成首帧
    # 绘制，再由原生侧显示窗口，避免 get_bootstrap 阻塞 ui_ready。
    try:
        assert window is not None
        window.events.loaded += lambda: threading.Timer(
            0.15, _show_after_load).start()
    except Exception:
        pass

    # 保底: 若页面加载事件异常, 12 秒后也按同一套渐入流程显示窗口。
    def _force_show():
        time.sleep(12)
        try:
            _show_after_load()
        except Exception:
            pass
    threading.Thread(target=_force_show, daemon=True).start()

    # 通用 Win32 显示/隐藏主窗口 (线程安全, 供托盘/关闭/预加载显示共用)
    def _win32_show_window(show=True):
        return _win32_show_window_impl(window, show)

    # 托盘
    try:
        tray = _start_tray(core, window, _win32_show_window)
    except Exception as e:
        print(f"托盘初始化失败: {e}")
        tray = None

    # 关闭行为: 按设置驻留托盘或退出 (读取设置失败时默认隐藏到托盘)
    # 注意: closing 事件运行在 UI 线程 (FormClosing), 不能 print/调用 evaluate_js,
    #       否则等待前端响应会死锁。窗口隐藏放后台线程执行。
    def _on_closing():
        try:
            if _is_system_shutting_down():
                # 系统关机/重启/注销时必须真正结束进程并放行,
                # 否则会被系统判定为"正在阻止关机"。
                # (不依赖子类消息, 见 _is_system_shutting_down)
                threading.Thread(target=_terminate_now, daemon=True).start()
                return True
            hide_to_tray = True
            try:
                hide_to_tray = int(core.settings_manager.get_setting("after_gui_exit") or 0) == 0
            except Exception:
                hide_to_tray = True
            if hide_to_tray:
                # 只阻止关闭; 后台线程透明度渐出后隐藏窗口, 不依赖前端 toast
                def _hide():
                    try:
                        _hwnd = _win32_hwnd(window)
                        if _hwnd:
                            _ensure_layered(_hwnd)
                            _fade_window(_hwnd, 255, 0)
                        _win32_show_window(False)
                    except Exception:
                        pass
                threading.Thread(target=_hide, daemon=True).start()
                # 首次隐藏到托盘时弹系统托盘气泡提示 (mems.tray_hint 记录, 只提示一次)
                try:
                    _mems = core.settings_manager.get_setting("mems")
                    if isinstance(_mems, dict) and not _mems.get("tray_hint"):
                        _mems["tray_hint"] = True
                        core.settings_manager.set_setting("mems", _mems)
                        core.settings_manager.save_settings()
                        if tray is not None:
                            try:
                                tray.notify("程序已最小化到系统托盘, 右键托盘图标可退出", "浮士德启动器")
                            except Exception:
                                pass
                except Exception:
                    pass
                return False
        except Exception:
            pass
        # 关闭程序退出: 在 FormClosing 返回前完成淡出, 再允许 pywebview 关闭。
        # 不能只放到后台线程, 否则进程会先结束而用户看不到动画。
        try:
            _hwnd = _win32_hwnd(window)
            if _hwnd:
                _ensure_layered(_hwnd)
                _fade_window(_hwnd, 255, 0)
            _win32_show_window(False)
        except Exception:
            pass
        return True

    try:
        if window is not None:
            window.events.closing += _on_closing
    except Exception as e:
        print(f"注册关闭事件失败: {e}")

    # 启动后检查设置 (延迟到前端就绪; web 模式无交互, 不弹 Tk 对话框)
    def _delayed_check():
        # 游戏路径检测尽量提前: 前端在启动瞬间就锁屏等这个结果 (避免"先说没检测到又改口")
        try:
            time.sleep(1)
            core.ensure_game_path(interactive=False)
        except Exception as e:
            print(f"游戏路径检查失败: {e}")
        time.sleep(5)
        try:
            # 只做设置检查, 不触发 check_settings 内部的简单汉化下载 (汉化由 download_and_launch 内部控制)
            core.check_settings(skip_auto_download=True, interactive=False)
            # 启动更新流程: 资源更新/插件Mod同步始终执行; 汉化部分受 check_translate_update 设置控制

            # 检查可能自动设置了 Steam 游戏路径, 通知前端同步设置页与首页路径显示
            
            _evaluate_js("window.__onPathSynced()")
        except Exception as e:
            print(f"设置检查失败: {e}")

    threading.Thread(target=_delayed_check, daemon=True).start()

    # 硬件加速(GPU渲染)设置: 关闭时给 WebView2 传 --disable-gpu (需重启生效)
    try:
        if not bool(core.settings_manager.get_setting("hw_accel")):
            import os as _os
            _args = _os.environ.get("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", "")
            if "--disable-gpu" not in _args:
                _os.environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = (_args + " --disable-gpu").strip()
            print("硬件加速已关闭 (WebView GPU 渲染禁用)")
    except Exception:
        pass

    try:
        webview.start(debug=debug, gui='edgechromium')
    except BaseException as e:
        import traceback
        try:
            with open(os.path.join(_PROJECT_ROOT, "web_ui_error.log"), "a", encoding="utf-8") as f:
                f.write(traceback.format_exc())
        except Exception:
            pass
        _msgbox("FaustLauncher", f"无法启动窗口:\n{type(e).__name__}: {e}")
        raise SystemExit(1)

    # webview 主循环退出: 立即终止进程, 不等后台线程 (否则退出有 ~1s 延迟,
    # 更新流程替换 exe 时会因文件占用而失败)
    _terminate_now()
