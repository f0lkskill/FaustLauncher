#! Mod管理器窗口 (工具页)

import base64
import json
import os
import shutil
import subprocess
import sys
from threading import Thread

if getattr(sys, "frozen", False):
    _PROJECT_ROOT = os.path.dirname(os.path.abspath(sys.executable))
else:
    _PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from functions.base.common.path_utils import get_mod_root_dir, get_web_root
from functions.base.skin_theme import window_background
from functions.base.window_chrome import (
    WindowChromeBridge,
    apply_window_chrome,
    child_window_size,
    window_icon_path,
)

HTML_PATH = get_web_root("mod_manager", "index.html")

ALLOWED_EXTENSIONS = {'.bank', '.carra2', '.rebank'}
DISABLED_SUFFIX = '.disabled'
MANIFEST_NAME = 'launcher_manifest.json'
EXT_INFO = {
    '.bank': {'icon': '🔊', 'type_label': '🎵 音效文件'},
    '.carra2': {'icon': '🖼️', 'type_label': '🖼️ 贴图文件'},
    '.rebank': {'icon': '🧩', 'type_label': '🧩 rebank 差分文件'},
}

def _get_mod_dir():
    return get_mod_root_dir()

def _sync_manifest(add=(), remove=()):
    try:
        mod_dir = _get_mod_dir()
        path = os.path.join(mod_dir, MANIFEST_NAME)
        data = {}
        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f) or {}
            except (OSError, ValueError):
                data = {}
        names = [str(n) for n in (data.get("manual") or [])]
        for name in add:
            if name not in names:
                names.append(name)
        for name in remove:
            if name in names:
                names.remove(name)
        data["manual"] = names
        data.setdefault("package", [])
        data["version"] = 1
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except OSError as e:
        print(f"[Mod管理器] 同步 mod 清单失败: {e}")

def _safe_raw_name(raw_name):
    n = str(raw_name or '').strip()
    if not n or n in ('.', '..'):
        return ''
    if os.path.basename(n) != n:
        return ''
    if os.sep in n or (os.altsep and os.altsep in n):
        return ''
    return n

def _split_disabled(filename):
    s = str(filename)
    if s.lower().endswith(DISABLED_SUFFIX):
        return s[:-len(DISABLED_SUFFIX)], True
    return s, False

def _is_mod_file(filename):
    original, _ = _split_disabled(filename)
    return os.path.splitext(original)[1].lower() in ALLOWED_EXTENSIONS

def _scan_files():
    mod_dir = _get_mod_dir()
    files = []
    if os.path.exists(mod_dir):
        for raw_name in os.listdir(mod_dir):
            full_path = os.path.join(mod_dir, raw_name)
            if not os.path.isfile(full_path):
                continue
            original, disabled = _split_disabled(raw_name)
            ext = os.path.splitext(original)[1].lower()
            if ext not in ALLOWED_EXTENSIONS:
                continue
            info = EXT_INFO.get(ext, {'icon': '📄', 'type_label': '❓ 未知文件'})
            size = os.path.getsize(full_path)
            if size < 1024:
                size_str = f"{size} B"
            elif size < 1024 * 1024:
                size_str = f"{size / 1024:.1f} KB"
            else:
                size_str = f"{size / (1024 * 1024):.1f} MB"
            files.append({
                'name': os.path.splitext(original)[0],
                'ext': ext,
                'raw_name': raw_name,
                'icon': info['icon'],
                'type_label': info['type_label'],
                'size': size_str,
                'enabled': not disabled,
            })
    files.sort(key=lambda f: (not f['enabled'], f['name'].lower()))
    return files

def _copy_into_mod_dir(path):
    if not os.path.isfile(path):
        return False, os.path.basename(path), "不是有效文件"
    ext = os.path.splitext(os.path.basename(path))[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        return False, os.path.basename(path), f"不支持的类型 {ext}，仅支持 .bank / .carra2"
    try:
        mod_dir = _get_mod_dir()
        dest = os.path.join(mod_dir, os.path.basename(path))
        shutil.copy2(path, dest)
        return True, os.path.basename(path), ""
    except Exception as e:
        return False, os.path.basename(path), f"复制失败: {e}"

def _add_files(paths):
    if not paths:
        return []
    results = []
    for p in paths:
        ok, name, msg = _copy_into_mod_dir(p)
        results.append({'ok': ok, 'name': name, 'msg': msg})
    added = [r['name'] for r in results if r['ok']]
    if added:
        _sync_manifest(add=added)
    return results

def _toggle_file(raw_name):
    mod_dir = _get_mod_dir()
    safe = _safe_raw_name(raw_name)
    if not safe:
        return {'error': f"文件名不合法: {raw_name!r}"}
    src = os.path.join(mod_dir, safe)
    if not os.path.exists(src):
        return {'error': f"文件不存在: {safe}"}
    original, disabled = _split_disabled(safe)
    dst = os.path.join(mod_dir, original if disabled else safe + DISABLED_SUFFIX)
    try:
        os.rename(src, dst)
        return {'error': None}
    except Exception as e:
        return {'error': f"操作失败: {e}"}

def _delete_file(raw_name):
    mod_dir = _get_mod_dir()
    safe = _safe_raw_name(raw_name)
    if not safe:
        return {'error': f"文件名不合法: {raw_name!r}"}
    path = os.path.join(mod_dir, safe)
    if not os.path.exists(path):
        return {'error': f"文件不存在: {safe}"}
    try:
        os.remove(path)
    except Exception as e:
        return {'error': f"删除失败: {e}"}
    original, _ = _split_disabled(safe)
    removed = [original]
    ext = os.path.splitext(original)[1].lower()
    if ext in ('.bank', '.rebank'):
        stem = os.path.splitext(original)[0]
        for extra in (stem + '.rebank', stem + '.rebank.src'):
            extra_path = os.path.join(mod_dir, extra)
            try:
                if os.path.isfile(extra_path):
                    os.remove(extra_path)
                    removed.append(extra)
            except OSError:
                pass
    _sync_manifest(remove=removed)
    return {'error': None}

def _rebank_info(raw_name):
    safe = _safe_raw_name(raw_name)
    if not safe:
        return {'error': f"文件名不合法: {raw_name!r}"}
    path = os.path.join(_get_mod_dir(), safe)
    if not os.path.exists(path):
        return {'error': f"文件不存在: {safe}"}
    script = os.path.join(_PROJECT_ROOT, "resources", "mod_loader", "_internal", "rebank.py")
    py = os.path.join(_PROJECT_ROOT, "resources", "mod_loader", "_internal",
                      "venv", "Bins", "python.exe")
    if not os.path.exists(script):
        return {'error': f"找不到 rebank 工具: {script}"}
    if not os.path.exists(py):
        py = sys.executable
    code = ("import sys;"
            "sys.path.insert(0, %r);"
            "sys.argv = ['rebank.py', 'info', %r];"
            "import runpy;"
            "runpy.run_path(%r, run_name='__main__')" % (os.path.dirname(script), path, script))
    try:
        proc = subprocess.run(
            [py, "-c", code],
            capture_output=True, timeout=120,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        out = (proc.stdout or b"").decode("utf-8", "replace")
        err = (proc.stderr or b"").decode("utf-8", "replace")
        text = (out or err).strip()
        if proc.returncode != 0 and not text:
            return {'error': f"查看信息失败 (退出码 {proc.returncode})"}
        return {'error': None, 'text': text or "(无输出)"}
    except Exception as e:
        return {'error': f"查看信息失败: {e}"}

class ModManagerApi(WindowChromeBridge):

    def get_data(self):
        return {'mod_dir': _get_mod_dir(), 'files': _scan_files()}

    def pick_files(self):
        try:
            import webview
            window = webview.windows[0]
            paths = window.create_file_dialog(
                webview.FileDialog.OPEN,
                allow_multiple=True,
                file_types=('Mod文件 (*.bank;*.carra2;*.rebank)',))
        except Exception as e:
            print(f"[Mod管理器] 打开文件对话框失败: {e}")
            return []
        if not paths:
            return []
        return _add_files(paths)

    def confirm_delete(self, name):
        try:
            import webview
            return bool(webview.windows[0].create_confirmation_dialog(
                "删除确认", f"确定要删除文件 {name} 吗？"))
        except Exception as e:
            print(f"[Mod管理器] 确认对话框失败: {e}")
            return True

    def toggle(self, raw_name):
        return _toggle_file(raw_name)

    def delete_file(self, raw_name):
        return _delete_file(raw_name)

    def rebank_info(self, raw_name):
        return _rebank_info(raw_name)

    def open_file(self, raw_name):
        try:
            path = os.path.join(_get_mod_dir(), raw_name)
            if os.path.exists(path):
                subprocess.Popen(f'explorer.exe /select, "{path}"')
        except Exception as e:
            print(f"[Mod管理器] 打开文件位置失败: {e}")
        return {'error': None}

    def open_dir(self):
        try:
            mod_dir = _get_mod_dir()
            if os.path.exists(mod_dir):
                os.startfile(mod_dir)
        except Exception as e:
            print(f"[Mod管理器] 打开目录失败: {e}")
        return {'error': None}

    def assets(self):
        try:
            icon_path = os.path.join(_PROJECT_ROOT, "assets", "images", "icon", "icon.png")
            with open(icon_path, "rb") as f:
                return {"bg": "data:image/png;base64," + base64.b64encode(f.read()).decode("ascii")}
        except Exception:
            return {"bg": None}

def _safe_js_str(obj):
    return json.dumps(obj, ensure_ascii=False).replace('\u2028', '\\u2028').replace('\u2029', '\\u2029')

def _notify(window, func_name, arg):
    try:
        window.evaluate_js(f"window.{func_name} && window.{func_name}({_safe_js_str(arg)})")
    except Exception as e:
        print(f"[Mod管理器] 通知页面失败: {e}")

def _on_drop(event):
    try:
        files = (event.get('dataTransfer') or {}).get('files', [])
        paths = [f.get('pywebviewFullPath') for f in files if f.get('pywebviewFullPath')]
        if not paths:
            return
        results = _add_files(paths)
        ok_count = sum(1 for r in results if r['ok'])
        print(f"[Mod管理器] 拖拽添加 {len(results)} 个文件, 成功 {ok_count}")
        import webview
        _notify(webview.windows[0], "__onFilesAdded", results)
    except Exception as e:
        print(f"[Mod管理器] 处理拖拽失败: {e}")

def _center_xy(width, height):
    try:
        import ctypes
        u = ctypes.windll.user32
        screen_w = u.GetSystemMetrics(0)
        screen_h = u.GetSystemMetrics(1)
        return max((screen_w - width) // 2, 0), max((screen_h - height) // 2, 0)
    except Exception:
        return None, None

def run_mod_manager_window(debug: bool = False):
    try:
        import webview
    except BaseException as e:
        import traceback
        try:
            with open(os.path.join(_PROJECT_ROOT, "mod_manager_window_error.log"), "a", encoding="utf-8") as f:
                f.write("import webview failed:\n" + traceback.format_exc())
        except Exception:
            pass
        import ctypes
        try:
            ctypes.windll.user32.MessageBoxW(
                None, f"未安装 pywebview 依赖:\n{type(e).__name__}: {e}", "Mod管理器", 0x10)
        except Exception:
            pass
        raise SystemExit(1)

    if not os.path.exists(HTML_PATH):
        import ctypes
        try:
            ctypes.windll.user32.MessageBoxW(None, f"找不到页面文件:\n{HTML_PATH}", "Mod管理器", 0x10)
        except Exception:
            pass
        raise SystemExit(1)

    win_w, win_h = child_window_size(760, 600)
    min_w, min_h = child_window_size(560, 420)
    window_kwargs = dict(
        title="Mod管理器",
        url=HTML_PATH,
        js_api=ModManagerApi(),
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
        window = webview.create_window(**window_kwargs)
        apply_window_chrome(window, show_when_ready=True)

        def _register_dnd():
            try:
                window.dom.document.events.drop += _on_drop
                print("[Mod管理器] 拖拽监听已注册")
            except Exception as e:
                print(f"[Mod管理器] 注册拖拽监听失败: {e}")

        window.events.loaded += _register_dnd

        webview.start(debug=debug, icon=window_icon_path())
    except BaseException as e:
        import traceback
        try:
            with open(os.path.join(_PROJECT_ROOT, "mod_manager_window_error.log"), "a", encoding="utf-8") as f:
                f.write(traceback.format_exc())
        except Exception:
            pass
        import ctypes
        try:
            ctypes.windll.user32.MessageBoxW(
                None, f"无法启动窗口:\n{type(e).__name__}: {e}", "Mod管理器", 0x10)
        except Exception:
            pass
        raise SystemExit(1)

def open_mod_manager_window(root=None):
    if getattr(sys, "frozen", False):
        cmd = [os.path.abspath(sys.executable), "--mod-manager-window"]
    else:
        script = os.path.join(_PROJECT_ROOT, "functions", "pages", "tools", "mod_manager_window.py")
        if not os.path.exists(script):
            print("[Mod管理器] 找不到窗口脚本, 已跳过")
            return None
        pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
        if not os.path.exists(pythonw):
            pythonw = sys.executable
        cmd = [pythonw, script]

    try:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.Popen(cmd, cwd=_PROJECT_ROOT, creationflags=flags)
    except Exception as e:
        print(f"[Mod管理器] 无法启动窗口进程: {e}")
        return None
    return True

if __name__ == "__main__":
    run_mod_manager_window(debug="--debug" in sys.argv)
