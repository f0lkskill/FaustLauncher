#! 扩展工具窗口 (工具页)

import base64
import json
import os
import subprocess
import sys

if getattr(sys, "frozen", False):
    _PROJECT_ROOT = os.path.dirname(os.path.abspath(sys.executable))
else:
    _PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from functions.tools.post_extension_tools import (
    MODS_DIR,
    ADDONS_DIR,
    spawn_extension,
    wrap_mod,
    load_mod_info,
    load_addon_info,
    publish_mod as _publish_mod_full,
    publish_addon as _publish_addon_full,
    _scan_mod_files,
    _validate_wrap_source,
)

from functions.base.common.path_utils import get_web_root
from functions.base.skin_theme import window_background
from functions.base.window_chrome import (
    WindowChromeBridge,
    apply_window_chrome,
    child_window_size,
    window_icon_path,
)

HTML_PATH = get_web_root("extension_tools", "index.html")

def _safe_js_str(obj):
    return json.dumps(obj, ensure_ascii=False).replace('\u2028', '\\u2028').replace('\u2029', '\\u2029')

def _notify(func_name, arg):
    try:
        import webview
        for w in webview.windows:
            try:
                w.evaluate_js(f"window.{func_name} && window.{func_name}({_safe_js_str(arg)})")
            except Exception:
                pass
    except Exception:
        pass

class ExtensionToolsApi(WindowChromeBridge):

    def assets(self):
        try:
            icon_path = os.path.join(_PROJECT_ROOT, "assets", "images", "icon", "icon.png")
            with open(icon_path, "rb") as f:
                return {"bg": "data:image/png;base64," + base64.b64encode(f.read()).decode("ascii")}
        except Exception:
            return {"bg": None}

    def list_mods(self):
        try:
            mods_dir = os.path.join(_PROJECT_ROOT, MODS_DIR)
            result = []
            if os.path.isdir(mods_dir):
                for d in sorted(os.listdir(mods_dir)):
                    path = os.path.join(mods_dir, d)
                    if os.path.isdir(path):
                        result.append({
                            'name': d,
                            'path': path,
                            'wrapped': os.path.isfile(os.path.join(path, 'mod_info.json')),
                        })
            return result
        except Exception as e:
            print(f"[Extensions] 获取 mods 列表失败: {e}")
            return []

    def list_addons(self):
        try:
            addons_dir = os.path.join(_PROJECT_ROOT, ADDONS_DIR)
            result = []
            if os.path.isdir(addons_dir):
                for d in sorted(os.listdir(addons_dir)):
                    path = os.path.join(addons_dir, d)
                    if os.path.isdir(path):
                        result.append({
                            'name': d,
                            'path': path,
                            'wrapped': os.path.isfile(os.path.join(path, 'addon_info.json')),
                        })
            return result
        except Exception as e:
            print(f"[Extensions] 获取 addons 列表失败: {e}")
            return []

    def pick_folder(self):
        try:
            import webview
            paths = webview.windows[0].create_file_dialog(
                webview.FileDialog.FOLDER)
            return paths[0] if paths else None
        except Exception as e:
            print(f"[Extensions] 打开文件夹对话框失败: {e}")
            return None

    def pick_files(self):
        try:
            import webview
            paths = webview.windows[0].create_file_dialog(
                webview.FileDialog.OPEN,
                allow_multiple=True,
                file_types=('Mod文件 (*.bank;*.carra2)',))
            return list(paths) if paths else []
        except Exception as e:
            print(f"[Extensions] 打开文件对话框失败: {e}")
            return []

    def pick_icon(self):
        try:
            import webview
            paths = webview.windows[0].create_file_dialog(
                webview.FileDialog.OPEN,
                file_types=('图片文件 (*.png;*.jpg;*.jpeg;*.ico)',))
            return paths[0] if paths else None
        except Exception as e:
            print(f"[Extensions] 打开图标对话框失败: {e}")
            return None

    def scan_mod_files(self, folder, single_file=False):
        folder = (folder or '').strip()
        if not folder:
            return {'ok': False, 'files': [], 'error': '请先选择原始文件夹'}
        if not os.path.isdir(folder):
            return {'ok': False, 'files': [], 'error': f'原始文件夹不存在: {folder}'}
        if not single_file:
            err = _validate_wrap_source(folder)
            if err:
                return {'ok': False, 'files': [], 'error': err}
        return {'ok': True, 'files': _scan_mod_files(folder), 'error': ''}

    def wrap_mod(self, data):
        try:
            data = data or {}
            info = {
                'name': data.get('name', ''),
                'desc': data.get('desc', ''),
                'version': data.get('version', '0.0.1'),
                'authors': data.get('authors') or {},
                'file_names': data.get('files') or [],
                'extra_files': data.get('extra_files') or [],
            }
            icon_path = data.get('icon_path') or None
            ok, msg = wrap_mod(data.get('folder', ''), info=info,
                               icon_path=icon_path,
                               single_file=bool(data.get('single_file')))
            return {'ok': ok, 'msg': msg}
        except Exception as e:
            return {'ok': False, 'msg': f'包装 Mod 失败: {e}'}

    def spawn_extension(self, data):
        try:
            data = data or {}
            ok, msg = spawn_extension(
                data.get('name', ''),
                info={
                    'desc': data.get('desc', ''),
                    'version': data.get('version', '0.0.1'),
                    'authors': data.get('authors') or {},
                    'icon_path': data.get('icon_path') or None,
                })
            return {'ok': ok, 'msg': msg}
        except Exception as e:
            return {'ok': False, 'msg': f'生成插件模板失败: {e}'}

    def preview_mod(self, folder):
        info, err = load_mod_info(folder)
        if err:
            return {'ok': False, 'info': {}, 'max_size_mb': None, 'error': err}
        try:
            from functions.base.web_config import get_lanzou_config
            max_mb = int(get_lanzou_config().get('max_size_mb') or 66)
        except Exception:
            max_mb = 66
        return {'ok': True, 'info': info, 'max_size_mb': max_mb, 'error': ''}

    def publish_mod(self, folder):
        logs = []

        def _log(s):
            logs.append(s)
            _notify("__onPublishLog", s)

        def _progress(percent, text):
            _notify("__onPublishProgress", {'percent': percent, 'text': text})

        info, err = load_mod_info(folder)
        try:
            ok, msg = _publish_mod_full(folder, log=_log, progress=_progress)
            _progress(100, '完成')
            return {
                'ok': ok,
                'msg': msg,
                'log': '\n'.join(logs),
                'info': info if not err else {},
            }
        except Exception as e:
            return {'ok': False, 'msg': f'发布失败: {e}', 'log': '\n'.join(logs), 'info': {}}

    def preview_addon(self, folder):
        info, err = load_addon_info(folder)
        if err:
            return {'ok': False, 'info': {}, 'max_size_mb': None, 'error': err}
        try:
            from functions.base.web_config import get_lanzou_config
            max_mb = int(get_lanzou_config().get('max_size_mb') or 66)
        except Exception:
            max_mb = 66
        return {'ok': True, 'info': info, 'max_size_mb': max_mb, 'error': ''}

    def publish_addon(self, folder):
        logs = []

        def _log(s):
            logs.append(s)
            _notify("__onAddonLog", s)

        def _progress(percent, text):
            _notify("__onAddonProgress", {'percent': percent, 'text': text})

        info, err = load_addon_info(folder)
        try:
            ok, msg = _publish_addon_full(folder, log=_log, progress=_progress)
            _progress(100, '完成')
            return {
                'ok': ok,
                'msg': msg,
                'log': '\n'.join(logs),
                'info': info if not err else {},
            }
        except Exception as e:
            return {'ok': False, 'msg': f'发布失败: {e}', 'log': '\n'.join(logs), 'info': {}}

def _center_xy(width, height):
    try:
        import ctypes
        u = ctypes.windll.user32
        screen_w = u.GetSystemMetrics(0)
        screen_h = u.GetSystemMetrics(1)
        return max((screen_w - width) // 2, 0), max((screen_h - height) // 2, 0)
    except Exception:
        return None, None

def _error_dialog(title, text):
    import ctypes
    try:
        ctypes.windll.user32.MessageBoxW(None, text, title, 0x10)
    except Exception:
        pass

def _write_error_log(exc_info):
    try:
        with open(os.path.join(_PROJECT_ROOT, "extension_tools_window_error.log"), "a", encoding="utf-8") as f:
            f.write(exc_info)
    except Exception:
        pass

def run_extension_tools_window(debug: bool = False):
    try:
        import webview
    except BaseException as e:
        import traceback
        _write_error_log("import webview failed:\n" + traceback.format_exc())
        _error_dialog("扩展工具", f"未安装 pywebview 依赖:\n{type(e).__name__}: {e}")
        raise SystemExit(1)

    if not os.path.exists(HTML_PATH):
        _error_dialog("扩展工具", f"找不到页面文件:\n{HTML_PATH}")
        raise SystemExit(1)

    win_w, win_h = child_window_size(820, 660)
    min_w, min_h = child_window_size(680, 520)
    window_kwargs = dict(
        title="扩展工具",
        url=HTML_PATH,
        js_api=ExtensionToolsApi(),
        width=win_w,
        height=win_h,
        min_size=(min_w, min_h),
        background_color=window_background("#060f22"),
        frameless=True,
        easy_drag=False,
        shadow=False,
        hidden=True,
    )
    x, y = _center_xy(win_w, win_h)
    if x is not None and y is not None:
        window_kwargs["x"] = x
        window_kwargs["y"] = y

    try:
        _win = webview.create_window(**window_kwargs)
        apply_window_chrome(_win, show_when_ready=True)
        webview.start(debug=debug, icon=window_icon_path())
    except BaseException as e:
        import traceback
        _write_error_log(traceback.format_exc())
        _error_dialog("扩展工具", f"无法启动窗口:\n{type(e).__name__}: {e}")
        raise SystemExit(1)

def open_extension_tools_window(root=None):
    if getattr(sys, "frozen", False):
        cmd = [os.path.abspath(sys.executable), "--extension-tools-window"]
    else:
        script = os.path.join(_PROJECT_ROOT, "functions", "pages", "tools", "extension_tools_window.py")
        if not os.path.exists(script):
            print("[Extensions] 找不到窗口脚本, 已跳过")
            return None
        pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
        if not os.path.exists(pythonw):
            pythonw = sys.executable
        cmd = [pythonw, script]

    try:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.Popen(cmd, cwd=_PROJECT_ROOT, creationflags=flags)
    except Exception as e:
        print(f"[Extensions] 无法启动窗口进程: {e}")
        return None
    return True

if __name__ == "__main__":
    run_extension_tools_window(debug="--debug" in sys.argv)
