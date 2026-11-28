"""版本更新提示窗口。"""

#! 版本更新提示窗口

import base64
import html
import json
import os
import subprocess
import sys
import time
from threading import Thread

if getattr(sys, "frozen", False):
    _PROJECT_ROOT = os.path.dirname(os.path.abspath(sys.executable))
else:
    _PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from functions.base.common.path_utils import get_web_root
from functions.base.common.markdown_render import md_to_html as _common_md_to_html
from functions.base.skin_theme import window_background
from functions.base.window_chrome import (
    WindowChromeBridge,
    apply_window_chrome,
    child_window_size,
    window_icon_path,
)

RESULT_FILE = os.path.join(_PROJECT_ROOT, "cache", "update_choice.json")
HTML_PATH = get_web_root("version_update", "index.html")

def _esc(text):
    """内部esc相关处理。"""
    return html.escape(text, quote=False)

class VersionUpdateApi(WindowChromeBridge):

    """版本更新Api类。"""
    def __init__(self, payload):
        """初始化对象状态。"""
        self._payload = payload

    def get_data(self):
        """获取数据。"""
        data = dict(self._payload)
        try:
            data['html'] = _common_md_to_html(data.get('description') or '')
        except Exception as e:
            print(f"[Update] Markdown 渲染失败: {e}")
            data['html'] = _esc(data.get('description') or '')
        data.pop('description', None)
        return data

    def choose(self, action):
        """choose相关处理。"""
        _write_choice(action)

    def assets(self):
        """assets相关处理。"""
        import base64 as _b64

        def data_uri(rel_path, mime):
            """数据uri相关处理。"""
            try:
                with open(os.path.join(_PROJECT_ROOT, rel_path), "rb") as f:
                    return f"data:{mime};base64," + _b64.b64encode(f.read()).decode("ascii")
            except Exception:
                return None

        return {"bg": data_uri(os.path.join("assets", "images", "icon", "icon.png"), "image/png")}

def _write_choice(action):
    """内部写入choice。"""
    try:
        os.makedirs(os.path.dirname(RESULT_FILE), exist_ok=True)
        with open(RESULT_FILE, "w", encoding="utf-8") as f:
            json.dump({"action": action}, f)
    except Exception as e:
        print(f"[Update] 写入选择结果失败: {e}")
    try:
        import webview
        if webview.windows:
            webview.windows[0].destroy()
    except Exception:
        pass

def _msgbox(title, text, is_error=True):
    """内部msgbox相关处理。"""
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, text, title, 0x10 if is_error else 0x40)
    except Exception:
        pass

def _center_xy(width, height):
    """内部centerxy相关处理。"""
    try:
        import ctypes
        u = ctypes.windll.user32
        screen_w = u.GetSystemMetrics(0)
        screen_h = u.GetSystemMetrics(1)
        return max((screen_w - width) // 2, 0), max((screen_h - height) // 2, 0)
    except Exception:
        return None, None

def run_update_window(payload_b64=None, debug: bool = False):
    """执行更新窗口。"""
    try:
        import webview
    except BaseException as e:
        import traceback
        try:
            with open(os.path.join(_PROJECT_ROOT, "update_window_error.log"), "a", encoding="utf-8") as f:
                f.write("import webview failed:\n" + traceback.format_exc())
        except Exception:
            pass
        _msgbox("版本更新", f"未安装 pywebview 依赖:\n{type(e).__name__}: {e}")
        raise SystemExit(1)

    if not os.path.exists(HTML_PATH):
        _msgbox("版本更新", f"找不到页面文件:\n{HTML_PATH}")
        raise SystemExit(1)

    payload = {}
    if payload_b64:
        try:
            raw = base64.urlsafe_b64decode(payload_b64.encode('ascii')).decode('utf-8')
            payload = json.loads(raw)
        except Exception as e:
            print(f"[Update] 解析参数失败: {e}")

    win_w, win_h = child_window_size(560, 640)
    min_w, min_h = child_window_size(440, 460)
    window_kwargs = dict(
        title="版本更新",
        url=HTML_PATH,
        js_api=VersionUpdateApi(payload),
        width=win_w,
        height=win_h,
        min_size=(min_w, min_h),
        background_color=window_background("#060f22"),
        on_top=True,
        frameless=True,
        easy_drag=False,
        shadow=False,
        hidden=True,
    )
    x, y = _center_xy(win_w, win_h)
    if x is not None and y is not None:
        window_kwargs["x"] = x # type: ignore
        window_kwargs["y"] = y # type: ignore

    try:
        _win = webview.create_window(**window_kwargs) # type: ignore
        apply_window_chrome(_win, show_when_ready=True)
        webview.start(debug=debug, icon=window_icon_path())
    except BaseException as e:
        import traceback
        try:
            with open(os.path.join(_PROJECT_ROOT, "update_window_error.log"), "a", encoding="utf-8") as f:
                f.write(traceback.format_exc())
        except Exception:
            pass
        _msgbox("版本更新", f"无法启动窗口:\n{type(e).__name__}: {e}")
        raise SystemExit(1)

def _build_payload(current_version, latest_info, info, ask_update):
    """内部构建载荷。"""
    def _dt(value):
        """内部dt相关处理。"""
        if hasattr(value, 'strftime'):
            return value.strftime('%Y-%m-%d %H:%M:%S')
        return str(value or '')

    description = latest_info.get('description') or latest_info.get('version_description') or ''
    date = latest_info.get('date') or latest_info.get('data') or latest_info.get('created_at')
    url = latest_info.get('bilibili_url') or latest_info.get('url') or ''

    return {
        'title': info,
        'current_version': str(current_version or ''),
        'new_version': str(latest_info.get('version_name', '') or ''),
        'date': _dt(date),
        'bilibili_url': url,
        'description': description,
        'can_update': bool(url),
        'ask_update': bool(ask_update),
    }

_ASK_WINDOW_OPENED = {'t': 0.0}

def ask_window_just_opened(within_seconds=5):
    """ask窗口justopened相关处理。"""
    return time.time() - _ASK_WINDOW_OPENED['t'] < within_seconds

def open_version_update_window(current_version, latest_info, info='发现新版本', root=None,
                               ask_update: bool = False, on_result=None, timeout: int = 600):
    """打开版本更新窗口。"""
    url = latest_info.get('bilibili_url') or latest_info.get('url') or ''
    if ask_update and not url:
        print("[Update] 无下载链接, 跳过更新询问")
        return False

    payload = _build_payload(current_version, latest_info, info, ask_update)
    payload_b64 = base64.urlsafe_b64encode(
        json.dumps(payload, ensure_ascii=False).encode('utf-8')
    ).decode('ascii')

    if getattr(sys, "frozen", False):
        cmd = [os.path.abspath(sys.executable), "--update-window", "--update-payload", payload_b64]
    else:
        script = os.path.join(_PROJECT_ROOT, "functions", "pages", "notice", "version_update_window.py")
        if not os.path.exists(script):
            print("[Update] 找不到窗口脚本, 已跳过")
            return None
        pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
        if not os.path.exists(pythonw):
            pythonw = sys.executable
        cmd = [pythonw, script, "--update-payload", payload_b64]

    try:
        if os.path.exists(RESULT_FILE):
            os.remove(RESULT_FILE)
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        proc = subprocess.Popen(cmd, cwd=_PROJECT_ROOT, creationflags=flags)
    except Exception as e:
        print(f"[Update] 无法启动窗口进程: {e}")
        return None

    if ask_update:
        _ASK_WINDOW_OPENED['t'] = time.time()

    if not ask_update or on_result is None:
        return True

    def _watch():
        """内部监听相关处理。"""
        action = None
        deadline = time.time() + timeout
        while time.time() < deadline:
            if os.path.exists(RESULT_FILE):
                try:
                    with open(RESULT_FILE, "r", encoding="utf-8") as f:
                        action = json.load(f).get("action")
                except Exception:
                    action = None
                break
            if proc.poll() is not None:
                break
            time.sleep(0.2)
        try:
            if os.path.exists(RESULT_FILE):
                os.remove(RESULT_FILE)
        except Exception:
            pass
        try:
            on_result(action)
        except Exception as e:
            print(f"[Update] 选择回调执行失败: {e}")

    Thread(target=_watch, daemon=True).start()
    return True

def show_version_update_window(current_version, latest_info, info='发现新版本', root=None,
                               ask_update: bool = False, timeout: int = 600):

    """显示版本更新窗口。"""
    return open_version_update_window(current_version, latest_info, info, root,
                                      ask_update=ask_update, on_result=None, timeout=timeout)

if __name__ == "__main__":
    payload_arg = None
    if "--update-payload" in sys.argv:
        idx = sys.argv.index("--update-payload")
        if idx + 1 < len(sys.argv):
            payload_arg = sys.argv[idx + 1]
    run_update_window(payload_arg, debug="--debug" in sys.argv)
