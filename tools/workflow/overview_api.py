"""总览页：包列表、游戏路径、文件管理、启动打包 worker。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import core

try:
    from functions.base.window_chrome import WindowChromeBridge
except Exception:  # pragma: no cover - 启动器模块缺失时仍允许打开页面
    class WindowChromeBridge:  # type: ignore
        pass


class OverviewApi(WindowChromeBridge):
    def __init__(self):
        self._window = None
        self._project_root = str(core.PROJECT_ROOT)
        if self._project_root not in sys.path:
            sys.path.insert(0, self._project_root)

    def attach(self, window) -> None:
        self._window = window

    def _win(self):
        if self._window is not None:
            return self._window
        try:
            import webview
            return webview.windows[0] if webview.windows else None
        except Exception:
            return None

    def get_state(self):
        try:
            return core.overview_state()
        except Exception as exc:
            return {"ok": False, "error": str(exc), "packages": [], "game": {}, "threads": 5}

    def refresh(self):
        return self.get_state()

    def create_package(self, name=""):
        try:
            result = core.create_package(name)
            result["state"] = self.get_state()
            return result
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def add_files(self, name):
        try:
            import webview
            window = self._win()
            if window is None:
                return {"ok": False, "error": "窗口未就绪"}
            paths = window.create_file_dialog(
                webview.FileDialog.OPEN,
                allow_multiple=True,
                file_types=(
                    "打包文件 (*.zip;*.bank;*.carra2;*.rebank)",
                    "所有文件 (*.*)",
                ),
            )
            if not paths:
                return {"ok": False, "canceled": True, "error": ""}
            result = core.add_files(name, list(paths))
            result["state"] = self.get_state()
            return result
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def remove_file(self, name, filename):
        try:
            result = core.remove_file(name, filename)
            result["state"] = self.get_state()
            return result
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def delete_package(self, name):
        try:
            result = core.delete_package(name)
            result["state"] = self.get_state()
            return result
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def start_package(self, name):
        try:
            result = core.start_package(name)
            result["state"] = self.get_state()
            return result
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def open_package(self, name):
        return core.open_package(name)

    def open_mods_dir(self):
        return core.open_mods_dir()

    def pick_game_dir(self):
        try:
            import webview
            window = self._win()
            if window is None:
                return {"ok": False, "error": "窗口未就绪"}
            paths = window.create_file_dialog(webview.FileDialog.FOLDER)
            if not paths:
                return {"ok": False, "canceled": True, "error": ""}
            path = core.normalize_game_path(paths[0])
            if os.path.basename(path).lower() == "limbuscompany_data":
                path = os.path.dirname(path)
            core.set_game_path(path)
            return {"ok": True, "game": core.game_info(), "state": self.get_state()}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def set_game_path(self, path):
        try:
            core.set_game_path(path)
            return {"ok": True, "game": core.game_info(), "state": self.get_state()}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def set_threads(self, value):
        try:
            result = core.set_threads(value)
            result["ok"] = True
            return result
        except Exception as exc:
            return {"ok": False, "error": str(exc)}


def _center_xy(width: int, height: int):
    try:
        import ctypes
        user32 = ctypes.windll.user32
        screen_w = user32.GetSystemMetrics(0)
        screen_h = user32.GetSystemMetrics(1)
        return max((screen_w - width) // 2, 0), max((screen_h - height) // 2, 0)
    except Exception:
        return None, None


def run_overview(debug: bool = False) -> int:
    try:
        import webview
    except Exception as exc:
        print("[workflow] 未安装 pywebview: %s" % exc)
        return 1

    try:
        from functions.base.common.path_utils import get_web_root
        from functions.base.skin_theme import window_background
        from functions.base.window_chrome import (
            apply_window_chrome, child_window_size, window_icon_path,
        )
        html = get_web_root("mod_workflow", "index.html")
    except Exception:
        html = str(core.PROJECT_ROOT / "web" / "mod_workflow" / "index.html")
        from functions.base.skin_theme import window_background  # type: ignore
        from functions.base.window_chrome import (  # type: ignore
            apply_window_chrome, child_window_size, window_icon_path,
        )

    if not os.path.isfile(html):
        print("[workflow] 找不到总览页: %s" % html)
        return 1

    api = OverviewApi()
    win_w, win_h = child_window_size(1000, 660)
    min_w, min_h = child_window_size(780, 520)
    kwargs = dict(
        title="YisangMirrorFlow",
        url=html,
        js_api=api,
        width=win_w,
        height=win_h,
        min_size=(min_w, min_h),
        resizable=True,
        frameless=True,
        easy_drag=False,
        shadow=False,
        background_color=window_background("#0b0e14"),
        hidden=True,
    )
    x, y = _center_xy(win_w, win_h)
    if x is not None and y is not None:
        kwargs["x"] = x
        kwargs["y"] = y

    try:
        window = webview.create_window(**kwargs)
        api.attach(window)
        apply_window_chrome(window, title="YisangMirrorFlow", kind="launcher",
                            show_when_ready=True, fallback_ms=1500,
                            resizable=True)
        webview.start(debug=debug, icon=window_icon_path("launcher"))
        return 0
    except Exception as exc:
        print("[workflow] 启动总览页失败: %s" % exc)
        return 1
