#! Mod管理器窗口 (工具页)
#? 使用 pywebview 展示: html/mod_manager/index.html (与版本更新窗口同一深色 GitHub 风格)
#? 管理 %APPDATA%/LimbusCompanyMods 下的单文件 Mod (.bank 音效 / .carra2 贴图)
#? - 支持从资源管理器拖拽文件到窗口 (pywebview DOM drop 事件, 可批量), 或点击选择文件
#? - 启用/禁用通过重命名 .disabled 后缀实现 (与旧版 mod_manager 行为一致)
#? pywebview 6 要求 webview.start() 运行在主线程, 与 tkinter 主循环互斥,
#? 故以独立子进程方式拉起窗口 (与今日指令/版本更新同一模式):
#? - 源码模式: 用 pythonw 运行本脚本子进程
#? - 打包模式 (sys.frozen): 用自身 exe 以 --mod-manager-window 参数二次启动

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

from functions.base.common.path_utils import get_mod_root_dir

HTML_PATH = os.path.join(_PROJECT_ROOT, "html", "mod_manager", "index.html")

ALLOWED_EXTENSIONS = {'.bank', '.carra2'}
DISABLED_SUFFIX = '.disabled'
EXT_INFO = {
    '.bank': {'icon': '🔊', 'type_label': '🎵 音效文件'},
    '.carra2': {'icon': '🖼️', 'type_label': '🖼️ 贴图文件'},
}


# ============================================================
# 文件操作 (与旧版 mod_manager.py 行为一致)
# ============================================================

def _get_mod_dir():
    """Mod 单文件存放目录 (APPDATA/LimbusCompanyMods)"""
    return get_mod_root_dir()


def _split_disabled(filename):
    """返回 (原始文件名, 是否被禁用)"""
    if filename.endswith(DISABLED_SUFFIX):
        return filename[:-len(DISABLED_SUFFIX)], True
    return filename, False


def _is_mod_file(filename):
    """判断是否是可管理的 Mod 单文件 (考虑禁用后缀)"""
    original, _ = _split_disabled(filename)
    return os.path.splitext(original)[1].lower() in ALLOWED_EXTENSIONS


def _scan_files():
    """扫描 Mod 目录中的单文件, 返回列表 (按名称排序)"""
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
    files.sort(key=lambda f: f['name'].lower())
    return files


def _copy_into_mod_dir(path):
    """复制单个文件到 Mod 目录, 返回 (ok, name, msg)"""
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
    """批量添加文件 (拖拽/文件对话框), 返回结果列表"""
    if not paths:
        return []
    results = []
    for p in paths:
        ok, name, msg = _copy_into_mod_dir(p)
        results.append({'ok': ok, 'name': name, 'msg': msg})
    return results


def _toggle_file(raw_name):
    """启用/禁用 (重命名 .disabled 后缀)"""
    mod_dir = _get_mod_dir()
    src = os.path.join(mod_dir, raw_name)
    if not os.path.exists(src):
        return {'error': f"文件不存在: {raw_name}"}
    original, disabled = _split_disabled(raw_name)
    dst = os.path.join(mod_dir, original if disabled else raw_name + DISABLED_SUFFIX)
    try:
        os.rename(src, dst)
        return {'error': None}
    except Exception as e:
        return {'error': f"操作失败: {e}"}


def _delete_file(raw_name):
    """删除文件"""
    mod_dir = _get_mod_dir()
    path = os.path.join(mod_dir, raw_name)
    if not os.path.exists(path):
        return {'error': f"文件不存在: {raw_name}"}
    try:
        os.remove(path)
        return {'error': None}
    except Exception as e:
        return {'error': f"删除失败: {e}"}


# ============================================================
# pywebview js_api 与窗口
# ============================================================

class ModManagerApi:
    """pywebview js_api: 供前端读取列表与执行文件操作"""

    def get_data(self):
        return {'mod_dir': _get_mod_dir(), 'files': _scan_files()}

    def pick_files(self):
        """打开文件选择对话框并添加选中的文件"""
        try:
            import webview
            window = webview.windows[0]
            # file_types 格式: 单个 "描述 (*.ext;*.ext)" 字符串 (parse_file_type 校验)
            paths = window.create_file_dialog(
                webview.FileDialog.OPEN,
                allow_multiple=True,
                file_types=('Mod文件 (*.bank;*.carra2)',))
        except Exception as e:
            print(f"[Mod管理器] 打开文件对话框失败: {e}")
            return []
        if not paths:
            return []
        return _add_files(paths)

    def confirm_delete(self, name):
        """原生确认对话框 (WebView2 环境可靠, 替代页面 confirm)"""
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

    def open_file(self, raw_name):
        """用资源管理器打开文件所在位置并选中该文件"""
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
        """返回背景装饰图的 base64 data URI (使用 icon.png)"""
        try:
            icon_path = os.path.join(_PROJECT_ROOT, "assets", "images", "icon", "icon.png")
            with open(icon_path, "rb") as f:
                return {"bg": "data:image/png;base64," + base64.b64encode(f.read()).decode("ascii")}
        except Exception:
            return {"bg": None}


def _safe_js_str(obj):
    """json 转 JS 字面量, 处理 U+2028/2029 (JS 字符串字面量中的非法字符)"""
    return json.dumps(obj, ensure_ascii=False).replace('\u2028', '\\u2028').replace('\u2029', '\\u2029')


def _notify(window, func_name, arg):
    """从 Python 侧调用页面 JS 全局函数 (刷新列表/提示)"""
    try:
        window.evaluate_js(f"window.{func_name} && window.{func_name}({_safe_js_str(arg)})")
    except Exception as e:
        print(f"[Mod管理器] 通知页面失败: {e}")


def _on_drop(event):
    """DOM drop 事件: 处理拖入的文件 (运行在 pywebview 桥接线程)"""
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
    """主屏居中坐标, 失败时返回 (None, None)"""
    try:
        import ctypes
        u = ctypes.windll.user32
        screen_w = u.GetSystemMetrics(0)  # SM_CXSCREEN
        screen_h = u.GetSystemMetrics(1)  # SM_CYSCREEN
        return max((screen_w - width) // 2, 0), max((screen_h - height) // 2, 0)
    except Exception:
        return None, None


def run_mod_manager_window(debug: bool = False):
    """子进程入口: 直接运行 Mod管理器 pywebview 窗口"""
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

    window_kwargs = dict(
        title="Mod管理器",
        url=HTML_PATH,
        js_api=ModManagerApi(),
        width=760,
        height=600,
        min_size=(560, 420),
        background_color="#060f22",
    )
    x, y = _center_xy(760, 600)
    if x is not None and y is not None:
        window_kwargs["x"] = x
        window_kwargs["y"] = y

    try:
        window = webview.create_window(**window_kwargs)

        # 页面加载完成后注册 DOM drop 事件, 捕获从资源管理器拖入的文件
        def _register_dnd():
            try:
                window.dom.document.events.drop += _on_drop
                print("[Mod管理器] 拖拽监听已注册")
            except Exception as e:
                print(f"[Mod管理器] 注册拖拽监听失败: {e}")

        window.events.loaded += _register_dnd

        webview.start(debug=debug)
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
    """非阻塞拉起 Mod管理器窗口 (与今日指令同一模式, 立即返回)

    Returns:
        True: 窗口成功拉起; None: 拉起失败
    """
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
