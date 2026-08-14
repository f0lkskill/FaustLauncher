#! 扩展工具窗口 (工具页)
#? 使用 pywebview 展示: html/extension_tools/index.html (与 Mod管理器同一深色 GitHub 风格)
#? 三种模式:
#? - 包装 Mod: 选择原始文件夹(Installer.bat / Assets / Uninstaller.bat) -> 填写信息表单 -> 复制到 mods/
#? - 生成插件模板: 填写插件信息 -> addons/ 下生成 scr.py + icon.png + addon_info.json
#? - 发布 Mod 信息: 选择 mods/ 下的 Mod -> 上传 mod_info.json 到云端 textdb
#? 后端操作全部位于 functions/tools/post_extension_tools.py
#? pywebview 6 要求 webview.start() 运行在主线程, 与 tkinter 主循环互斥,
#? 故以独立子进程方式拉起窗口 (与 Mod管理器同一模式):
#? - 源码模式: 用 pythonw 运行本脚本子进程
#? - 打包模式 (sys.frozen): 用自身 exe 以 --extension-tools-window 参数二次启动

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
    spawn_extension,
    wrap_mod,
    load_mod_info,
    publish_mod as _publish_mod_full,
    _scan_mod_files,
    _validate_wrap_source,
)

HTML_PATH = os.path.join(_PROJECT_ROOT, "html", "extension_tools", "index.html")


# ============================================================
# 页面通知 (进度/日志实时推送)
# ============================================================

def _safe_js_str(obj):
    """json 转 JS 字面量, 处理 U+2028/2029 (JS 字符串字面量中的非法字符)"""
    return json.dumps(obj, ensure_ascii=False).replace('\u2028', '\\u2028').replace('\u2029', '\\u2029')


def _notify(func_name, arg):
    """从 Python 侧调用页面 JS 全局函数 (发布进度/日志推送)"""
    try:
        import webview
        for w in webview.windows:
            try:
                w.evaluate_js(f"window.{func_name} && window.{func_name}({_safe_js_str(arg)})")
            except Exception:
                pass
    except Exception:
        pass


# ============================================================
# pywebview js_api
# ============================================================

class ExtensionToolsApi:
    """pywebview js_api: 供前端调用包装/生成/发布等后端操作"""

    # ---- 通用 ----

    def assets(self):
        """返回背景装饰图的 base64 data URI (使用 icon.png)"""
        try:
            icon_path = os.path.join(_PROJECT_ROOT, "assets", "images", "icon", "icon.png")
            with open(icon_path, "rb") as f:
                return {"bg": "data:image/png;base64," + base64.b64encode(f.read()).decode("ascii")}
        except Exception:
            return {"bg": None}

    def list_mods(self):
        """mods/ 下所有子文件夹 [{name, path, wrapped}] (wrapped=是否已有 mod_info.json)

        未打包的原始 Mod 文件夹也可选 (用于包装)
        """
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
            print(f"[扩展工具] 获取 mods 列表失败: {e}")
            return []

    def pick_folder(self):
        """原生文件夹选择对话框 (create_file_dialog 始终返回元组, 需解包)"""
        try:
            import webview
            paths = webview.windows[0].create_file_dialog(
                webview.FileDialog.FOLDER)
            return paths[0] if paths else None
        except Exception as e:
            print(f"[扩展工具] 打开文件夹对话框失败: {e}")
            return None

    def pick_files(self):
        """原生多选文件对话框 (Mod 单文件)"""
        try:
            import webview
            paths = webview.windows[0].create_file_dialog(
                webview.FileDialog.OPEN,
                allow_multiple=True,
                file_types=('Mod文件 (*.bank;*.carra2)',))
            return list(paths) if paths else []
        except Exception as e:
            print(f"[扩展工具] 打开文件对话框失败: {e}")
            return []

    def pick_icon(self):
        """原生选择图标文件对话框 (create_file_dialog 始终返回元组, 需解包)"""
        try:
            import webview
            paths = webview.windows[0].create_file_dialog(
                webview.FileDialog.OPEN,
                file_types=('图片文件 (*.png;*.jpg;*.jpeg;*.ico)',))
            return paths[0] if paths else None
        except Exception as e:
            print(f"[扩展工具] 打开图标对话框失败: {e}")
            return None

    # ---- 包装 Mod ----

    def scan_mod_files(self, folder):
        """校验原始文件夹并扫描可载入文件, 返回 {ok, files, error}"""
        err = _validate_wrap_source(folder)
        if err:
            return {'ok': False, 'files': [], 'error': err}
        return {'ok': True, 'files': _scan_mod_files(folder), 'error': ''}

    def wrap_mod(self, data):
        """按表单填写的信息包装 Mod"""
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
                               icon_path=icon_path)
            return {'ok': ok, 'msg': msg}
        except Exception as e:
            return {'ok': False, 'msg': f'包装 Mod 失败: {e}'}

    # ---- 生成插件 ----

    def spawn_extension(self, data):
        """按表单填写的信息生成插件模板"""
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

    # ---- 发布 Mod ----

    def preview_mod(self, folder):
        """读取 mod_info.json 用于预览, 返回 {ok, info, error}"""
        info, err = load_mod_info(folder)
        if err:
            return {'ok': False, 'info': {}, 'error': err}
        return {'ok': True, 'info': info, 'error': ''}

    def publish_mod(self, folder):
        """完整发布: 压缩+上传蓝奏云(图标→FaustLauncher.icons, 本体→FaustLauncher.Mods)
        → 直链解析 URL → 发布 Mod 信息到云端 textdb
        返回 {ok, msg, log, info}; 期间实时推送进度到页面 (__onPublishProgress/__onPublishLog)
        """
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


# ============================================================
# 窗口启动
# ============================================================

def _center_xy(width, height):
    """主屏居中坐标, 失败时返回 (None, None)"""
    try:
        import ctypes
        u = ctypes.windll.user32
        screen_w = u.GetSystemMetrics(0)  # SM_CXSCREEN
        screen_h = u.GetSystemMetrics(1)  # SM_CYSCREEN
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
    """子进程入口: 直接运行扩展工具 pywebview 窗口"""
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

    window_kwargs = dict(
        title="扩展工具",
        url=HTML_PATH,
        js_api=ExtensionToolsApi(),
        width=820,
        height=660,
        min_size=(680, 520),
        background_color="#060f22",
    )
    x, y = _center_xy(820, 660)
    if x is not None and y is not None:
        window_kwargs["x"] = x
        window_kwargs["y"] = y

    try:
        webview.create_window(**window_kwargs)
        webview.start(debug=debug)
    except BaseException as e:
        import traceback
        _write_error_log(traceback.format_exc())
        _error_dialog("扩展工具", f"无法启动窗口:\n{type(e).__name__}: {e}")
        raise SystemExit(1)


def open_extension_tools_window(root=None):
    """非阻塞拉起扩展工具窗口 (与 Mod管理器同一模式, 立即返回)

    Returns:
        True: 窗口成功拉起; None: 拉起失败
    """
    if getattr(sys, "frozen", False):
        cmd = [os.path.abspath(sys.executable), "--extension-tools-window"]
    else:
        script = os.path.join(_PROJECT_ROOT, "functions", "pages", "tools", "extension_tools_window.py")
        if not os.path.exists(script):
            print("[扩展工具] 找不到窗口脚本, 已跳过")
            return None
        pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
        if not os.path.exists(pythonw):
            pythonw = sys.executable
        cmd = [pythonw, script]

    try:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.Popen(cmd, cwd=_PROJECT_ROOT, creationflags=flags)
    except Exception as e:
        print(f"[扩展工具] 无法启动窗口进程: {e}")
        return None
    return True


if __name__ == "__main__":
    run_extension_tools_window(debug="--debug" in sys.argv)
