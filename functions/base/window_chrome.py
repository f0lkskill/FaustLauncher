"""子窗口统一标题栏 + 窗口控制 (所有 frameless pywebview 子窗口共用)

主界面 (web/app) 自绘标题栏已经很久了: 无系统边框 + ``#titlebar``
(图标 / 标题 / 最小化 / 关闭) + 后端 ``begin_move_window`` / ``move_window``
精确拖动。但各个独立子窗口 (版本更新、Mod 管理器、扩展工具、自定汉化、
Nyos 预设、构建工具、Mod 加载器) 都是各自一个 pywebview 进程, 既拿不到
主界面的 js_api, 也带系统标题栏 —— 结果就是"每个子窗口长得都不一样"。

本模块把这件事抽成公共层:

* :func:`chrome_css` / :func:`chrome_js` 读 ``web/shared/chrome.*``
  (标题栏样式与交互, 与主界面同款);
* :func:`apply_window_chrome` 在窗口 ``loaded`` 时一次性注入
  「共享主题层 + 当前皮肤 + 标题栏样式 + 标题栏 JS」, 并可顺带 ``show()``
  窗口 (配合 ``create_window(hidden=True)``, 避免先默认配色再套皮肤的闪变);
* :class:`WindowChromeBridge` 是给各子窗口 ``js_api`` 继承的混入类, 对外暴露
  ``minimize_window`` / ``close_window`` / ``begin_move_window`` /
  ``move_window`` / ``end_move_window`` / ``theme_revision`` (以及
  ``SkinBridge`` 原有的皮肤读取方法)。

子窗口流程::

    class MyApi(WindowChromeBridge): ...

    win = webview.create_window(title, html, js_api=MyApi(...),
                                frameless=True, easy_drag=False, shadow=False,
                                hidden=True)
    apply_window_chrome(win, title="Mod管理器", show_when_ready=True)
    webview.start(debug=debug, icon=window_icon_path())

注意: 窗口一旦 ``frameless=True``, 就只能靠标题栏 JS 拖动 (``easy_drag=False``
关掉 pywebview 自带的"整个窗口都能拖")。
"""
from __future__ import annotations

import json
import os
import sys
import threading

from functions.base.skin_theme import SkinBridge, full_theme_css

# 标题栏高度 (与 web/shared/chrome.css 的 --titlebar-h 默认值一致)
TITLEBAR_HEIGHT = 40
CHROME_STYLE_ID = "fl-chrome"
THEME_STYLE_ID = "fl-theme"

# pywebview(Windows) 会把 create_window(width, height) 当成窗口外框, 自己再扣掉
# 系统标题栏与边框: 实测「请求尺寸 -> 页面可视区」恒差 (14, 37) 像素 (125% 缩放下
# 也一样)。child_window_size() 负责反推, 让内容区正好等于调用方要的尺寸。
FRAME_WIDTH = 14
FRAME_HEIGHT = 37


def child_window_size(width: int, height: int) -> tuple:
    """「想要的内容区尺寸」-> ``create_window`` 该填的尺寸 (含自绘标题栏)"""
    return int(width) + FRAME_WIDTH, int(height) + TITLEBAR_HEIGHT + FRAME_HEIGHT


# ============================================================
# 路径
# ============================================================
def _project_root() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))


def _web_shared(*parts) -> str:
    try:
        from functions.base.common.path_utils import get_web_root
        return get_web_root("shared", *parts)
    except Exception:
        return os.path.join(_project_root(), "web", "shared", *parts)


def _asset_path(*parts) -> str:
    """素材目录 (assets/...) —— 不入库, 由 tools/run/assets.bat 拉取"""
    return os.path.join(_project_root(), "assets", *parts)


def _read_text(path: str) -> str:
    try:
        if path and os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
    except Exception as e:
        print(f"[Chrome] 读取 {path} 失败: {e}")
    return ""


def chrome_css() -> str:
    """标题栏样式 (web/shared/chrome.css)"""
    return _read_text(_web_shared("chrome.css"))


def chrome_js() -> str:
    """标题栏交互 (web/shared/chrome.js)"""
    return _read_text(_web_shared("chrome.js"))


def icon_data_uri(path: str) -> str:
    """图标文件 -> data URI (子窗口不在 web 根下时只能这样给前端)"""
    try:
        import base64
        if path and os.path.isfile(path):
            with open(path, "rb") as f:
                data = f.read()
            ext = os.path.splitext(path)[1].lower().lstrip(".")
            mime = {
                "png": "image/png", "ico": "image/x-icon", "jpg": "image/jpeg",
                "jpeg": "image/jpeg", "webp": "image/webp", "gif": "image/gif",
            }.get(ext, "image/png")
            return f"data:{mime};base64," + base64.b64encode(data).decode("ascii")
    except Exception as e:
        print(f"[Chrome] 读取图标失败: {e}")
    return ""


def titlebar_icon_path(kind: str = "launcher") -> str:
    """标题栏图标 png: kind = launcher(启动器) / yisang(Mod 加载器: 李箱)

    图标属于素材, 不入库 (见 tools/build/assets_pack.py), 所以这里按
    运行期常见位置逐个探测, 找不到就返回空串 (标题栏退化成无图标)。
    """
    if kind == "yisang":
        cands = [
            # Mod 加载器自带的李箱头像 (旧 tkinter 版窗口图标用的就是它)
            os.path.join(_project_root(), "resources", "mod_loader", "_internal", "assets", "icon.png"),
            _asset_path("images", "character", "yisang.png"),
            _asset_path("images", "icon", "index.png"),
        ]
    else:
        cands = []
        try:
            from functions.base.common.path_utils import get_web_root
            cands.append(get_web_root("app", "assets", "icon", "icon.png"))
        except Exception:
            pass
        cands.append(_asset_path("images", "icon", "icon.png"))

    for p in cands:
        if p and os.path.isfile(p):
            return p
    return ""


def _is_real_ico(path: str) -> bool:
    """文件头是不是真正的 ICO

    素材目录里的 ``assets/images/icon/yisang.ico`` 其实是**改了扩展名的 PNG**,
    直接丢给 .NET 的 ``System.Drawing.Icon`` 会抛异常, 并连带 WebView2 初始化失败
    (``0x80004004 E_ABORT``) —— 所以这里必须验文件头。
    """
    try:
        if path and os.path.isfile(path):
            with open(path, "rb") as f:
                return f.read(4) == b"\x00\x00\x01\x00"
    except Exception:
        pass
    return False


def _ico_from_image(src: str, dest: str) -> str:
    """图片(PNG) -> 真正的多尺寸 .ico, 缓存到临时目录 (不入库、不动素材目录)"""
    try:
        from PIL import Image

        im = Image.open(src).convert("RGBA")
        side = max(im.size)
        canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
        canvas.paste(im, ((side - im.width) // 2, (side - im.height) // 2))
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        canvas.save(dest, format="ICO",
                    sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
        if _is_real_ico(dest):
            return dest
    except Exception as e:  # noqa: BLE001
        print(f"[Chrome] 生成窗口图标失败: {e}")
    return ""


def window_icon_path(kind: str = "launcher") -> str:
    """任务栏 / 窗口图标 (.ico), 传给 ``webview.start(icon=...)``

    ``kind="yisang"`` 时用李箱头像现做一个真 ICO 缓存到临时目录 (素材目录里那个
    ``yisang.ico`` 实际是 PNG); 找不到任何可用 .ico 时返回空串 (退回 python 默认
    图标, 不会报错)。
    """
    if kind == "yisang":
        import tempfile

        cache = os.path.join(tempfile.gettempdir(), "faust_launcher_icons", "yisang.ico")
        if _is_real_ico(cache):
            return cache
        src = titlebar_icon_path("yisang")
        made = _ico_from_image(src, cache) if src else ""
        if made:
            return made

    fallback = _asset_path("images", "icon", "icon.ico")
    return fallback if _is_real_ico(fallback) else ""


# ============================================================
# Win32 窗口控制
# ============================================================
def hwnd_of(window) -> int:
    """pywebview 窗口的原生句柄 (外层 BrowserForm, 不是 WebView2 子控件)"""
    if window is None:
        return 0
    try:
        native = getattr(window, "native", None)
        handle = getattr(native, "Handle", None)
        if handle is not None:
            try:
                return int(handle.ToInt64())
            except Exception:
                try:
                    return int(handle.ToInt32())
                except Exception:
                    pass
        title = getattr(window, "title", "") or ""
        if title:
            import ctypes
            return int(ctypes.windll.user32.FindWindowW(None, title))
    except Exception:
        pass
    return 0


def minimize_window(window) -> bool:
    """最小化 (SW_MINIMIZE)"""
    hwnd = hwnd_of(window)
    if not hwnd:
        return False
    try:
        import ctypes
        ctypes.windll.user32.ShowWindow(hwnd, 6)
        return True
    except Exception:
        return False


def close_window(window, fade: bool = True) -> bool:
    """淡出后再关闭 (与主界面退出同一观感); fade=False 则立刻关闭"""
    if fade:
        fade_out_window(window, then_close=True)
        return True
    _post_close(window)
    return True


_drag_lock = threading.Lock()
_drag_origins: dict[int, tuple] = {}


def begin_move_window(window, mouse_x, mouse_y) -> bool:
    """记录拖动起点 (鼠标绝对屏幕坐标 + 窗口左上角)"""
    hwnd = hwnd_of(window)
    if not hwnd:
        return False
    try:
        import ctypes
        import ctypes.wintypes as wt
        r = wt.RECT()
        ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(r))
        with _drag_lock:
            _drag_origins[hwnd] = (float(mouse_x), float(mouse_y), r.left, r.top)
        return True
    except Exception:
        return False


def move_window(window, mouse_x, mouse_y) -> bool:
    """按拖动起点平移窗口 (绝对坐标, 不做增量累加, 避免异步请求竞态)"""
    hwnd = hwnd_of(window)
    if not hwnd:
        return False
    with _drag_lock:
        origin = _drag_origins.get(hwnd)
    if not origin:
        return False
    try:
        import ctypes
        sx, sy, wx, wy = origin
        x = wx + round(float(mouse_x) - sx)
        y = wy + round(float(mouse_y) - sy)
        # SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE
        ctypes.windll.user32.SetWindowPos(hwnd, None, x, y, 0, 0, 0x0001 | 0x0004 | 0x0010)
        return True
    except Exception:
        return False


def end_move_window(window) -> bool:
    hwnd = hwnd_of(window)
    with _drag_lock:
        _drag_origins.pop(hwnd, None)
    return True


# ============================================================
# 边框缩放 / 最大化 (frameless 窗口没有系统边框, 这两件事要自己做)
# ============================================================
_resize_lock = threading.Lock()
_resize_origins: dict[int, tuple] = {}
_maximized: dict[int, tuple] = {}   # hwnd -> 最大化之前的窗口矩形


def _min_outer_size(window) -> tuple:
    """窗口最小尺寸

    ``min_size`` 传进来的已经是外框尺寸 (各窗口用 :func:`child_window_size`
    换算过), 所以这里不再叠加系统框, 只在缺失时给个兜底。
    """
    try:
        min_size = getattr(window, "min_size", None)
        if min_size:
            return int(min_size[0]), int(min_size[1])
    except Exception:
        pass
    return child_window_size(200, 100)


def begin_resize_window(window, edge, mouse_x, mouse_y) -> bool:
    """记录缩放起点 (edge 取 n/s/e/w/ne/nw/se/sw)"""
    hwnd = hwnd_of(window)
    if not hwnd:
        return False
    try:
        import ctypes
        import ctypes.wintypes as wt
        r = wt.RECT()
        ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(r))
        min_w, min_h = _min_outer_size(window)
        with _resize_lock:
            _resize_origins[hwnd] = (str(edge), float(mouse_x), float(mouse_y),
                                     r.left, r.top, r.right - r.left, r.bottom - r.top,
                                     min_w, min_h)
        return True
    except Exception:
        return False


def resize_window(window, mouse_x, mouse_y) -> bool:
    """按缩放起点计算新矩形 (绝对坐标, 不做增量累加, 避免异步竞态)"""
    hwnd = hwnd_of(window)
    if not hwnd:
        return False
    with _resize_lock:
        origin = _resize_origins.get(hwnd)
    if not origin:
        return False
    edge, mx, my, x0, y0, w0, h0, min_w, min_h = origin
    try:
        import ctypes
        dx = round(float(mouse_x) - mx)
        dy = round(float(mouse_y) - my)
        x, y, w, h = x0, y0, w0, h0
        if "e" in edge:
            w = w0 + dx
        if "s" in edge:
            h = h0 + dy
        if "w" in edge:
            w = w0 - dx
        if "n" in edge:
            h = h0 - dy
        # 撞到最小尺寸时, 让被拖动的那条边停在原位 (窗口不会"缩着跑")
        if w < min_w:
            if "w" in edge:
                x = x0 + (w0 - min_w)
            elif "e" not in edge:
                x = x0
            w = min_w
        if h < min_h:
            if "n" in edge:
                y = y0 + (h0 - min_h)
            h = min_h
        if "e" not in edge and "w" not in edge:
            x = x0
        if "n" not in edge and "s" not in edge:
            y = y0
        # 最大化状态下拖动边框 → 先还原, 保持和系统窗口一致的手感
        if hwnd in _maximized:
            _maximized.pop(hwnd, None)
        ctypes.windll.user32.SetWindowPos(hwnd, None, x, y, w, h,
                                          0x0004 | 0x0010)   # SWP_NOZORDER | SWP_NOACTIVATE
        return True
    except Exception:
        return False


def end_resize_window(window) -> bool:
    hwnd = hwnd_of(window)
    with _resize_lock:
        _resize_origins.pop(hwnd, None)
    return True


def _work_area() -> tuple:
    """主屏工作区 (去掉任务栏)"""
    try:
        import ctypes
        import ctypes.wintypes as wt
        r = wt.RECT()
        if ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(r), 0):
            return int(r.left), int(r.top), int(r.right - r.left), int(r.bottom - r.top)
    except Exception:
        pass
    return 0, 0, 0, 0


def toggle_maximize_window(window) -> bool:
    """最大化 / 还原 (手算工作区, frameless 窗口最大化了也不会盖住任务栏)

    Returns:
        True: 现在处于最大化状态
    """
    hwnd = hwnd_of(window)
    if not hwnd:
        return False
    try:
        import ctypes
        import ctypes.wintypes as wt
        saved = _maximized.get(hwnd)
        if saved:
            x, y, w, h = saved
            ctypes.windll.user32.SetWindowPos(hwnd, None, x, y, w, h,
                                              0x0020 | 0x0004 | 0x0010)  # SWP_FRAMECHANGED|NOZORDER|NOACTIVATE
            _maximized.pop(hwnd, None)
            return False
        ax, ay, aw, ah = _work_area()
        if not aw or not ah:
            return False
        cur = wt.RECT()
        ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(cur))
        _maximized[hwnd] = (cur.left, cur.top, cur.right - cur.left, cur.bottom - cur.top)
        ctypes.windll.user32.SetWindowPos(hwnd, None, ax, ay, aw, ah,
                                          0x0020 | 0x0004 | 0x0010)
        return True
    except Exception:
        return False


def is_maximized_window(window) -> bool:
    hwnd = hwnd_of(window)
    return bool(hwnd and hwnd in _maximized)


# ============================================================
# 注入
# ============================================================
def _inject_js(style_id: str, css: str) -> str:
    return (
        "(function(){var d=document,id=%s,s=d.getElementById(id);"
        "if(!s){s=d.createElement('style');s.id=id;(d.head||d.documentElement).appendChild(s);}"
        "s.textContent=%s;})();" % (json.dumps(style_id), json.dumps(css))
    )


def _plain_show(window):
    try:
        window.show()
    except Exception:
        pass


# ============================================================
# 淡入 / 淡出 (与主界面同一套: WS_EX_LAYERED + SetLayeredWindowAttributes)
# ============================================================
_layered_ready = set()   # 已加过 WS_EX_LAYERED 的 hwnd (幂等)


def ensure_layered(hwnd) -> bool:
    """给窗口加 WS_EX_LAYERED (淡入淡出必需, 幂等)"""
    if not hwnd:
        return False
    if hwnd in _layered_ready:
        return True
    try:
        import ctypes
        GWL_EXSTYLE, WS_EX_LAYERED = -20, 0x80000
        style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_LAYERED)
        _layered_ready.add(hwnd)
        return True
    except Exception:
        return False


def clear_layered(hwnd) -> None:
    """摘掉 WS_EX_LAYERED, 让窗口回到正常的 GPU 合成路径

    分层窗口走 DWM 软件合成 (逐帧拷贝), WebView2 内容在切页/滚动时容易撕裂、
    残留上帧画面 —— 所以淡入到 alpha=255 之后必须摘掉 (与主界面
    ``app_web._clear_layered`` 的原因一致)。
    """
    try:
        import ctypes
        GWL_EXSTYLE, WS_EX_LAYERED = -20, 0x80000
        style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        if style & WS_EX_LAYERED:
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style & ~WS_EX_LAYERED)
            _layered_ready.discard(hwnd)
            # 强制 DWM 重算窗口帧, 否则样式变更可能延迟生效
            SWP_FRAMECHANGED, SWP_NOMOVE, SWP_NOSIZE, SWP_NOZORDER = 0x20, 2, 1, 4
            ctypes.windll.user32.SetWindowPos(hwnd, None, 0, 0, 0, 0,
                                              SWP_FRAMECHANGED | SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER)
    except Exception:
        pass


def set_window_alpha(hwnd, alpha) -> None:
    """设置窗口透明度 0~255 (需先 ensure_layered)"""
    try:
        import ctypes
        ctypes.windll.user32.SetLayeredWindowAttributes(
            hwnd, 0, max(0, min(255, int(alpha))), 0x2)   # LWA_ALPHA
    except Exception:
        pass


def get_window_alpha(hwnd) -> int:
    """读当前窗口透明度 (读不到返回 -1)"""
    try:
        import ctypes
        import ctypes.wintypes as wt
        key = wt.COLORREF()
        alpha = wt.BYTE()
        flags = ctypes.wintypes.DWORD()
        if ctypes.windll.user32.GetLayeredWindowAttributes(
                hwnd, ctypes.byref(key), ctypes.byref(alpha), ctypes.byref(flags)):
            return int(alpha.value)
    except Exception:
        pass
    return -1


def fade_window(hwnd, start, end, step=20, delay=0.01) -> None:
    """同步阻塞的透明度渐变 (在后台线程里调用)"""
    import time

    if not hwnd or start == end:
        if hwnd:
            set_window_alpha(hwnd, end)
        return
    a = start
    while True:
        set_window_alpha(hwnd, a)
        time.sleep(delay)
        if start < end:
            a = min(a + step, end)
            if a >= end:
                break
        else:
            a = max(a - step, end)
            if a <= end:
                break
    set_window_alpha(hwnd, end)


def fade_in_window(window, *, step=15, delay=0.01) -> bool:
    """显示窗口并淡入 (先置为全透明再 show, 避免闪现; 结束后摘掉分层样式)"""
    hwnd = hwnd_of(window)
    if not hwnd:
        _plain_show(window)
        return False
    ensure_layered(hwnd)
    set_window_alpha(hwnd, 0)
    _plain_show(window)

    def _work():
        try:
            fade_window(hwnd, 0, 255, step=step, delay=delay)
        except Exception:
            pass
        finally:
            set_window_alpha(hwnd, 255)
            clear_layered(hwnd)

    threading.Thread(target=_work, daemon=True).start()
    return True


def _post_close(window, hwnd=0) -> None:
    """真正关闭窗口: 优先 WM_CLOSE (走 pywebview 正常关闭流程)"""
    try:
        import ctypes
        if not hwnd:
            hwnd = hwnd_of(window)
        if hwnd:
            ctypes.windll.user32.PostMessageW(hwnd, 0x0010, 0, 0)   # WM_CLOSE
            return
    except Exception:
        pass
    try:
        window.destroy()
    except Exception:
        pass


def fade_out_window(window, *, step=20, delay=0.008, then_close=False) -> bool:
    """淡出, 可选淡完自动关闭 (标题栏关闭按钮 / 页面关闭按钮都走这里)"""
    hwnd = hwnd_of(window)

    def _work():
        try:
            if hwnd:
                ensure_layered(hwnd)
                fade_window(hwnd, 255, 0, step=step, delay=delay)
        except Exception:
            pass
        finally:
            if then_close:
                _post_close(window, hwnd)

    threading.Thread(target=_work, daemon=True).start()
    return bool(hwnd)


_shown_hwnds = set()   # 已经"显示过"的窗口 (兜底定时器和 loaded 可能都想显示)


def _safe_show(window):
    """显示窗口 (淡入, 只做一次) —— 注入完主题再显示时用"""
    hwnd = hwnd_of(window)
    if hwnd and hwnd in _shown_hwnds:
        return          # 兜底定时器 / loaded 各调一次, 二次淡入会看到"闪一下"
    if hwnd:
        _shown_hwnds.add(hwnd)
    fade_in_window(window)


def theme_revision() -> str:
    """当前皮肤指纹 (子窗口用它判断主程序是否换了皮肤)"""
    sid = ""
    mtime = 0.0
    try:
        from functions.base import skin_theme as st
        sid = st.active_skin_id() or ""
        if sid:
            d = st.skin_dir(sid)
            if d:
                for name in ("style.css", "skin.css"):
                    p = os.path.join(d, "css", name)
                    if os.path.isfile(p):
                        mtime = max(mtime, os.path.getmtime(p))
    except Exception:
        pass
    return f"{sid}|{mtime:.3f}"


def apply_window_chrome(window, *, title: str = "", kind: str = "launcher",
                        icon: str = "", icon_path: str = "",
                        show_when_ready: bool = False, fallback_ms: int = 1500,
                        poll_ms: int = 1200, on_skin_change: str = "",
                        resizable: bool = True) -> bool:
    """把「主题 + 皮肤 + 统一标题栏」一次性注入子窗口

    必须在 ``webview.start()`` 之前调用 (这时还没有 DOM, 只能注册事件);
    窗口 ``loaded`` 后执行一次注入:

        <style id="fl-theme">   共享主题层 + 当前皮肤 (子页面 var(--x) 生效)
        <style id="fl-chrome">  标题栏样式
        window.__FL_CHROME__    标题 / 图标 / 轮询间隔
        chrome.js               建标题栏 + 拖动 + 最小化/关闭 + 皮肤热更新

    Args:
        title: 标题栏文字 (空则取窗口自身标题)
        kind:  ``launcher`` (启动器图标) / ``yisang`` (Mod 加载器: 李箱)
        icon:  直接给图标 data URI / URL (优先于 kind)
        icon_path: 图标文件路径 (优先于 kind, 会被转成 data URI)
        show_when_ready: 配合 ``create_window(hidden=True)``: 注入完再显示,
            避免"先默认配色后皮肤"的闪变; ``fallback_ms`` 后兜底强制显示。
        on_skin_change: 皮肤热更新后前端执行的可选 JS 片段。
    """
    if icon_path and not icon:
        icon = icon_data_uri(icon_path)
    if not icon:
        icon = icon_data_uri(titlebar_icon_path(kind))
    if not title:
        try:
            title = str(getattr(window, "title", "") or "")
        except Exception:
            title = ""

    def _apply():
        theme = ""
        try:
            theme = full_theme_css()
        except Exception as e:
            print(f"[Chrome] 主题读取失败: {e}")
        cfg = {"title": title, "icon": icon, "poll_ms": poll_ms,
               "resizable": bool(resizable)}
        if on_skin_change:
            cfg["on_skin_change"] = on_skin_change
        js = "".join([
            _inject_js(THEME_STYLE_ID, theme),
            _inject_js(CHROME_STYLE_ID, chrome_css()),
            "window.__FL_CHROME__=%s;" % json.dumps(cfg, ensure_ascii=False),
            chrome_js(),
        ])
        try:
            window.evaluate_js(js)
        except Exception as e:
            print(f"[Chrome] 注入失败: {e}")
        if show_when_ready:
            _safe_show(window)

    ok = False
    try:
        window.events.loaded += lambda *a, **k: _apply()
        ok = True
    except Exception as e:
        print(f"[Chrome] 无法监听 loaded 事件: {e}")

    if show_when_ready:
        t = threading.Timer(max(0.2, fallback_ms / 1000.0), lambda: _safe_show(window))
        t.daemon = True
        t.start()
    return ok


# ============================================================
# js_api 混入类
# ============================================================
class WindowChromeBridge(SkinBridge):
    """给子窗口 ``js_api`` 继承: 皮肤读取 + 统一标题栏的窗口控制

    窗口引用优先用 :meth:`attach_window` 显式给的; 没给就取本进程唯一的
    pywebview 窗口 (每个子窗口都是独立进程, 所以这总是对的)。
    """

    _fl_window = None

    def attach_window(self, window):
        """绑定 pywebview 窗口对象 (可选, 不调用也能自动找到)"""
        self._fl_window = window
        return True

    def _win(self):
        w = getattr(self, "_fl_window", None)
        if w is not None:
            return w
        try:
            import webview
            return webview.windows[0] if webview.windows else None
        except Exception:
            return None

    # ---- 标题栏按钮 ----
    def minimize_window(self):
        return minimize_window(self._win())

    def close_window(self):
        return close_window(self._win())

    # ---- 标题栏拖动 ----
    def begin_move_window(self, mouse_x, mouse_y):
        return begin_move_window(self._win(), mouse_x, mouse_y)

    def move_window(self, mouse_x, mouse_y):
        return move_window(self._win(), mouse_x, mouse_y)

    def end_move_window(self):
        return end_move_window(self._win())

    # ---- 边框缩放 / 最大化 ----
    def begin_resize_window(self, edge, mouse_x, mouse_y):
        return begin_resize_window(self._win(), edge, mouse_x, mouse_y)

    def resize_window(self, mouse_x, mouse_y):
        return resize_window(self._win(), mouse_x, mouse_y)

    def end_resize_window(self):
        return end_resize_window(self._win())

    def toggle_maximize_window(self):
        """最大化/还原切换; 返回切换后是否最大化"""
        return toggle_maximize_window(self._win())

    def is_maximized(self) -> bool:
        return is_maximized_window(self._win())

    # ---- 皮肤热更新 ----
    def theme_revision(self) -> str:
        """皮肤指纹: 主程序换皮肤/patch 皮肤文件后, 子窗口轮询到这里就会重建样式"""
        return theme_revision()
