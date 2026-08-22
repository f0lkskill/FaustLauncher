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
    """读取快捷方式卡片素材为压缩后的 data URI (pywebview http 服务器拒绝相对路径, 需内嵌)"""
    if not image_name:
        return ""
    for root in (
        os.path.join(_PROJECT_ROOT, "assets", "images", "features"),
        os.path.join(_PROJECT_ROOT, "_internal", "assets", "images", "features"),
    ):
        p = os.path.join(root, image_name)
        if os.path.isfile(p):
            break
    else:
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
    """读取工具卡片素材为压缩后的 data URI (从 assets/images/tools 读取)"""
    if not image_name:
        return ""
    for root in (
        os.path.join(_PROJECT_ROOT, "assets", "images", "tools"),
        os.path.join(_PROJECT_ROOT, "_internal", "assets", "images", "tools"),
    ):
        p = os.path.join(root, image_name)
        if os.path.isfile(p):
            break
    else:
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


def check_single_instance():
    """检测是否已有实例在运行 (按主窗口标题识别)"""
    try:
        import ctypes
        user32 = ctypes.windll.user32
        hwnd = user32.FindWindowW(None, "Faust Launcher")
        if hwnd:
            user32.MessageBoxW(
                None,
                "已经有启动器实例在运行！请检查你的系统托盘！",
                "Faust Launcher",
                0x40)  # MB_ICONINFORMATION
            return True
    except Exception:
        pass
    return False


def _patch_network_timeouts():
    """给所有 requests 请求补默认超时, 防止断网/网络缓慢时无限阻塞线程 (卡死);
    同时禁用 InsecureRequestWarning (textdb 等源使用 verify=False 的合法请求)"""
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


# ============================================================
# 无头下载进度 shim: 兼容 DownloadGUI 的鸭子类型接口
# ============================================================

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
# js_api 桥接
# ============================================================

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
        self.core = core
        self.window_ref = window_ref

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
        ]
        for t in tools:
            t["image_uri"] = _tool_image_uri(t.get("image", ""))
        icon_uri = ""
        for cand in (
            os.path.join(_PROJECT_ROOT, "assets", "images", "icon", "icon.png"),
            os.path.join(_PROJECT_ROOT, "_internal", "assets", "images", "icon", "icon.png"),
        ):
            if os.path.isfile(cand):
                try:
                    with open(cand, "rb") as f:
                        icon_uri = "data:image/png;base64," + base64.b64encode(f.read()).decode("ascii")
                except Exception:
                    pass
                break
        return {
            "version": str(sm.get_setting("version_info")),
            "game_path": str(sm.get_setting("game_path") or ""),
            "bg_color": str(sm.get_setting("bg_color") or "#181818"),
            "features": features,
            "tools": tools,
            "settings_schema": sm.get_all_settings(),
            "is_frozen": bool(getattr(sys, "frozen", False)),
            "project_root": _PROJECT_ROOT,
            "icon_uri": icon_uri,
        }

    def get_backgrounds(self):
        """返回背景图 data URI 列表, 应用 bg_gaussian_blur 模糊设置 (限制数量并压缩)"""
        uris = []
        try:
            from PIL import Image, ImageFilter
            from functions.base.settings_manager import get_settings_manager
            blur = 0.0
            try:
                blur = float(get_settings_manager().get_setting("bg_gaussian_blur") or 0.0)
            except Exception:
                blur = 0.0
            bg_dir = os.path.join(_PROJECT_ROOT, "assets", "images", "background")
            if os.path.isdir(bg_dir):
                for name in sorted(os.listdir(bg_dir)):
                    if len(uris) >= 4:
                        break
                    if not name.lower().endswith((".png", ".jpg", ".jpeg")):
                        continue
                    try:
                        img = Image.open(os.path.join(bg_dir, name)).convert("RGB")
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
    def launch_game(self):
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
        # 必须阻塞等待下载线程真正完成, 否则前端 await 立即返回,
        # 800ms 后 pipelineDone 会在后端仍在下载时就显示"流水线完成"
        from threading import Event as _Event
        done = _Event()
        def _run():
            from functions.pages.app.page_loader import download_and_launch
            try:
                download_and_launch(obj=None, need_run_game=False)
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
                    with open(root, 'r', encoding='utf-8') as f:
                        data = json.load(f)
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
                        with open(info_path, 'r', encoding='utf-8') as f:
                            info = json.load(f)
                    except Exception:
                        info = {}
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
                        with open(info_path, 'r', encoding='utf-8') as f:
                            info = json.load(f)
                    except Exception:
                        info = {}
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
                    })
        except Exception as e:
            print(f"读取目录 Mod 失败: {e}")
        return {
            'addons': addons,
            'dir_mods': dir_mods,
            'single_files': [],
            'single_dir': '',
        }

    def install_addon_dialog(self):
        """选择本地插件目录安装到 addons/ (临时 Tk 文件夹选择)"""
        try:
            import tkinter as tk
            from tkinter import filedialog
            from functions.extension.addon.addon_utils import AddonManager
            root = tk.Tk()
            root.withdraw()
            path = filedialog.askdirectory(title='选择插件目录 (包含 addon_info.json)')
            root.destroy()
            if not path:
                return {'ok': False, 'error': None}
            am = AddonManager()
            ok = am.add_addon(path)
            return {'ok': bool(ok), 'error': None}
        except Exception as e:
            return {'ok': False, 'error': str(e)}

    def set_mod_settings(self, name, settings):
        """更新 Mod 的 mod_info.json settings 字段 (含 enable)"""
        import json, os
        path = os.path.join('mods', str(name), 'mod_info.json')
        if not os.path.exists(path):
            return {'error': f"Mod 信息文件不存在: {path}"}
        try:
            with open(path, 'r', encoding='utf-8') as f:
                info = json.load(f)
            info['settings'] = dict(settings or {})
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(info, f, ensure_ascii=False, indent=4)
            return {'error': None}
        except Exception as e:
            return {'error': str(e)}

    def set_addon_settings(self, name, settings):
        """更新插件 addon_info.json 的 settings 字段 (含 enable 与各项自定义设置)"""
        import json, os
        path = os.path.join('addons', str(name), 'addon_info.json')
        if not os.path.exists(path):
            return {'error': f"插件信息文件不存在: {path}"}
        try:
            with open(path, 'r', encoding='utf-8') as f:
                info = json.load(f)
            info['settings'] = dict(settings or {})
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(info, f, ensure_ascii=False, indent=4)
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
            with open(path, 'r', encoding='utf-8') as f:
                info = json.load(f)
            info.setdefault('settings', {})['enable'] = bool(enabled)
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(info, f, ensure_ascii=False, indent=4)
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
            with open(path, 'r', encoding='utf-8') as f:
                info = json.load(f)
            info.setdefault('settings', {})['enable'] = bool(enabled)
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(info, f, ensure_ascii=False, indent=4)
            return {'error': None}
        except Exception as e:
            return {'error': str(e)}

    def delete_addon(self, name):
        """删除插件 (整个目录)"""
        import os, shutil
        path = os.path.join('addons', str(name))
        if not os.path.isdir(path):
            return {'error': f"插件目录不存在: {path}"}
        try:
            shutil.rmtree(path, ignore_errors=False)
            return {'error': None}
        except Exception as e:
            return {'error': str(e)}

    def delete_mod(self, name):
        """删除目录 Mod (整个文件夹)"""
        import os, shutil
        path = os.path.join('mods', str(name))
        if not os.path.isdir(path):
            return {'error': f"Mod 目录不存在: {path}"}
        try:
            shutil.rmtree(path, ignore_errors=False)
            return {'error': None}
        except Exception as e:
            return {'error': str(e)}

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
        """初始化后只爬取一次数据库, 之后永久使用内存缓存 (不再访问网络)"""
        if not getattr(self, '_dc_cache', None):
            self._dc_cache = {'addon': None, 'mod': None}
        if self._dc_cache.get(kind) is None:
            wt = self._get_web_trigger()
            data = (wt.fetch_all_addon_info() if kind == 'addon'
                    else wt.fetch_all_mod_info())
            self._dc_cache[kind] = data if data else [] # type: ignore
        return self._dc_cache[kind]

    @staticmethod
    def _name_common_sub(s1, s2):
        """返回两字符串最长公共子串长度 (用于云端中文名与本地显示名微变匹配)"""
        a, b = s1, s2
        best = 0
        for i in range(len(a)):
            for j in range(len(b)):
                k = 0
                while i + k < len(a) and j + k < len(b) and a[i + k] == b[j + k]:
                    k += 1
                if k > best:
                    best = k
        return best

    def check_item_downloaded(self, kind, name):
        """检测插件/Mod 是否已下载安装 (每次刷新下载中心都会重新检测, 用户可能手动删除)
        本地目录名是英文, 云端 name 是中文显示名, 需按 addon_info.json/mod_info.json 的 name 匹配,
        同时兼容目录名直查与公共子串微变匹配 (如 '原神启动!自动下载' vs '云原神-自动下载')。"""
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
                        with open(info_file, 'r', encoding='utf-8') as f:
                            info = _json.load(f)
                        local_name = str(info.get('name', '')).strip()
                        if local_name == name:
                            return {'downloaded': True}
                        if len(name) > 2 and len(local_name) > 2 and self._name_common_sub(name, local_name) >= 3:
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
                    print(f"插件 {name} 下载完成")
                    try:
                        self.core.addon_manager.reload_all_addons()
                    except Exception:
                        pass
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
                    print(f"Mod {name} 下载完成")
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
        import hashlib
        cache_dir = os.path.join(_PROJECT_ROOT, 'cache', 'icons')
        os.makedirs(cache_dir, exist_ok=True)
        url_hash = hashlib.md5(icon_url.encode('utf-8')).hexdigest()[:12]
        icon_filename = f"{item_name.replace(' ', '_')}_{url_hash}_icon.png"
        icon_path = os.path.join(cache_dir, icon_filename)
        if not os.path.exists(icon_path):
            try:
                import requests
                r = requests.get(icon_url, timeout=10, verify=False)
                if r.status_code == 200:
                    with open(icon_path, 'wb') as f:
                        f.write(r.content)
                else:
                    return ''
            except Exception:
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
        """更新内容: 优先云端 version_info 最新版本说明, 失败回退本地 CHANGELOG.md"""
        try:
            from functions.base.web_config import get_webnote
            from functions.webFunc.Webnote import Note
            from json import loads
            note = Note(get_webnote('version_info')[0])
            note.fetch_note_info()
            if note.note_content.strip():
                info = loads(note.note_content)
                latest = (info.get('latest_release_version') or '').strip()
                entry = info.get('versions', {}).get(latest, {}) if latest else {}
                desc = entry.get('description', '')
                if desc:
                    return desc
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
    def check_update(self):
        """检查版本更新, 返回最新版本信息"""
        try:
            from functions.base.web_config import get_webnote
            from functions.webFunc.Webnote import Note
            from json import loads
            from functions.base.settings_manager import get_settings_manager
            sm = get_settings_manager()
            current = str(sm.get_setting('version_info') or '')
            note = Note(get_webnote('version_info')[0])
            note.fetch_note_info()
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
        lang_dir = os.path.join(game_path, 'LimbusCompany_Data', 'lang', 'LLC_zh-CN')
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
                if waited > 120:
                    print("等待游戏启动超时 (2 分钟)")
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

    ico_path = os.path.join(_PROJECT_ROOT, "assets", "images", "icon", "icon.ico")
    try:
        ico = Image.open(ico_path)
    except Exception:
        ico = Image.new("RGBA", (64, 64), (99, 102, 241, 255))

    def _tray_window_op(show):
        """在独立线程执行窗口显示/隐藏, 绝不阻塞 pystray 回调线程"""
        def _do():
            try:
                win32_show(show)
            except Exception:
                pass
        threading.Thread(target=_do, daemon=True).start()

    def show_win(icon=None, item=None):
        _tray_window_op(True)

    def hide_win(icon=None, item=None):
        _tray_window_op(False)

    def when_exit(icon=None, item=None):
        try:
            assert icon is not None
            icon.stop()
        except Exception:
            pass
        import os
        os._exit(0)

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
    """主入口: 启动 pywebview 主窗口 (必须运行在主线程)"""
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

    if os.path.exists(os.path.join(_PROJECT_ROOT, "updater.vbs")):
        try:
            os.remove(os.path.join(_PROJECT_ROOT, "updater.vbs"))
        except Exception:
            pass

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

    window_holder = {}

    def _evaluate_js(code):
        win = window_holder.get("win")
        if win is None:
            return
        try:
            win.evaluate_js(code)
        except Exception:
            pass

    def _push_log(text):
        try:
            payload = json.dumps(text, ensure_ascii=False)
            _evaluate_js(f"window.__onLog({payload})")
        except Exception:
            pass

    log_redirector = WebLogRedirector(_push_log)
    log_redirector.start()

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
    # 窗口居中显示
    _win_x = _win_y = None
    try:
        import ctypes
        _sw = ctypes.windll.user32.GetSystemMetrics(0)
        _sh = ctypes.windll.user32.GetSystemMetrics(1)
        _win_x = max(0, (_sw - 1000) // 2)
        _win_y = max(0, (_sh - 740) // 2)
    except Exception:
        pass
    window = webview.create_window(
        "Faust Launcher",
        HTML_PATH,
        js_api=api,
        width=1000,
        height=740,
        x=_win_x,
        y=_win_y,
        min_size=(860, 620),
        background_color="#0b0e14",
        frameless=False,
    )
    window_holder["win"] = window

    # 通用 Win32 显示/隐藏主窗口 (线程安全, 供托盘与关闭事件共用)
    def _win32_show_window(show=True):
        """用 Win32 ShowWindow 显示/隐藏主窗口 (不经 pywebview 跨线程调用)"""
        import ctypes
        hwnd = 0
        try:
            import webview.platforms.winforms as _wf
            bv = _wf.BrowserView.instances.get(getattr(window, 'uid', ''))
            if bv is not None:
                try:
                    hwnd = int(bv.Handle.ToInt64())
                except Exception:
                    try:
                        hwnd = int(bv.Handle.ToInt32())
                    except Exception:
                        hwnd = int(bv.Handle)
        except Exception:
            pass
        if not hwnd:
            try:
                hwnd = ctypes.windll.user32.FindWindowW(None, "Faust Launcher")
            except Exception:
                pass
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 1 if show else 0)  # SW_SHOWNORMAL / SW_HIDE
            if show:
                ctypes.windll.user32.SetForegroundWindow(hwnd)
            return True
        return False

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
            hide_to_tray = True
            try:
                hide_to_tray = int(core.settings_manager.get_setting("after_gui_exit") or 0) == 0
            except Exception:
                hide_to_tray = True
            if hide_to_tray:
                # 只阻止关闭; 隐藏放后台线程, 避免阻塞 UI 线程
                def _do():
                    try:
                        _win32_show_window(False)
                    except Exception:
                        pass
                    try:
                        _evaluate_js("window.__onLog('程序已最小化到系统托盘, 右键托盘图标可退出')")
                    except Exception:
                        pass
                threading.Thread(target=_do, daemon=True).start()
                return False
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
        time.sleep(6)
        try:
            core.check_settings(skip_auto_download=True, interactive=False)
        except Exception as e:
            print(f"设置检查失败: {e}")

    threading.Thread(target=_delayed_check, daemon=True).start()

    try:
        webview.start(debug=debug)
    except BaseException as e:
        import traceback
        try:
            with open(os.path.join(_PROJECT_ROOT, "web_ui_error.log"), "a", encoding="utf-8") as f:
                f.write(traceback.format_exc())
        except Exception:
            pass
        _msgbox("FaustLauncher", f"无法启动窗口:\n{type(e).__name__}: {e}")
        raise SystemExit(1)