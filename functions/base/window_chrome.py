from __future__ import annotations

import json
import os
import sys
import threading

from functions.base.skin_theme import SkinBridge, full_theme_css

TITLEBAR_HEIGHT = 40
CHROME_STYLE_ID = "fl-chrome"
THEME_STYLE_ID = "fl-theme"

FRAME_WIDTH = 14
FRAME_HEIGHT = 37

def child_window_size(width: int, height: int) -> tuple:
    return int(width) + FRAME_WIDTH, int(height) + TITLEBAR_HEIGHT + FRAME_HEIGHT

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
    return _read_text(_web_shared("chrome.css"))

def chrome_js() -> str:
    return _read_text(_web_shared("chrome.js"))

def icon_data_uri(path: str) -> str:
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
    if kind == "yisang":
        cands = [
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
    try:
        if path and os.path.isfile(path):
            with open(path, "rb") as f:
                return f.read(4) == b"\x00\x00\x01\x00"
    except Exception:
        pass
    return False

def _ico_from_image(src: str, dest: str) -> str:
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

def hwnd_of(window) -> int:
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
    if fade:
        fade_out_window(window, then_close=True)
        return True
    _post_close(window)
    return True

_drag_lock = threading.Lock()
_drag_origins: dict[int, tuple] = {}

def begin_move_window(window, mouse_x, mouse_y) -> bool:
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
        ctypes.windll.user32.SetWindowPos(hwnd, None, x, y, 0, 0, 0x0001 | 0x0004 | 0x0010)
        return True
    except Exception:
        return False

def end_move_window(window) -> bool:
    hwnd = hwnd_of(window)
    with _drag_lock:
        _drag_origins.pop(hwnd, None)
    return True

_resize_lock = threading.Lock()
_resize_origins: dict[int, tuple] = {}
_maximized: dict[int, tuple] = {}

def _min_outer_size(window) -> tuple:
    try:
        min_size = getattr(window, "min_size", None)
        if min_size:
            return int(min_size[0]), int(min_size[1])
    except Exception:
        pass
    return child_window_size(200, 100)

def begin_resize_window(window, edge, mouse_x, mouse_y) -> bool:
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
        if hwnd in _maximized:
            _maximized.pop(hwnd, None)
        ctypes.windll.user32.SetWindowPos(hwnd, None, x, y, w, h,
                                          0x0004 | 0x0010)
        return True
    except Exception:
        return False

def end_resize_window(window) -> bool:
    hwnd = hwnd_of(window)
    with _resize_lock:
        _resize_origins.pop(hwnd, None)
    return True

def _work_area() -> tuple:
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
                                              0x0020 | 0x0004 | 0x0010)
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

_layered_ready = set()

def ensure_layered(hwnd) -> bool:
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
    try:
        import ctypes
        GWL_EXSTYLE, WS_EX_LAYERED = -20, 0x80000
        style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        if style & WS_EX_LAYERED:
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style & ~WS_EX_LAYERED)
            _layered_ready.discard(hwnd)
            SWP_FRAMECHANGED, SWP_NOMOVE, SWP_NOSIZE, SWP_NOZORDER = 0x20, 2, 1, 4
            ctypes.windll.user32.SetWindowPos(hwnd, None, 0, 0, 0, 0,
                                              SWP_FRAMECHANGED | SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER)
    except Exception:
        pass

def set_window_alpha(hwnd, alpha) -> None:
    try:
        import ctypes
        ctypes.windll.user32.SetLayeredWindowAttributes(
            hwnd, 0, max(0, min(255, int(alpha))), 0x2)
    except Exception:
        pass

def get_window_alpha(hwnd) -> int:
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
    try:
        import ctypes
        if not hwnd:
            hwnd = hwnd_of(window)
        if hwnd:
            ctypes.windll.user32.PostMessageW(hwnd, 0x0010, 0, 0)
            return
    except Exception:
        pass
    try:
        window.destroy()
    except Exception:
        pass

def fade_out_window(window, *, step=20, delay=0.008, then_close=False) -> bool:
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

_shown_hwnds = set()

def _safe_show(window):
    hwnd = hwnd_of(window)
    if hwnd and hwnd in _shown_hwnds:
        return
    if hwnd:
        _shown_hwnds.add(hwnd)
    fade_in_window(window)

def theme_revision() -> str:
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

class WindowChromeBridge(SkinBridge):

    _fl_window = None

    def attach_window(self, window):
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

    def minimize_window(self):
        return minimize_window(self._win())

    def close_window(self):
        return close_window(self._win())

    def begin_move_window(self, mouse_x, mouse_y):
        return begin_move_window(self._win(), mouse_x, mouse_y)

    def move_window(self, mouse_x, mouse_y):
        return move_window(self._win(), mouse_x, mouse_y)

    def end_move_window(self):
        return end_move_window(self._win())

    def begin_resize_window(self, edge, mouse_x, mouse_y):
        return begin_resize_window(self._win(), edge, mouse_x, mouse_y)

    def resize_window(self, mouse_x, mouse_y):
        return resize_window(self._win(), mouse_x, mouse_y)

    def end_resize_window(self):
        return end_resize_window(self._win())

    def toggle_maximize_window(self):
        return toggle_maximize_window(self._win())

    def is_maximized(self) -> bool:
        return is_maximized_window(self._win())

    def theme_revision(self) -> str:
        return theme_revision()
