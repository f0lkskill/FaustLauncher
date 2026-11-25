"""扩展工具后端（并入 YisangMirrorFlow 合并前端）。

原实现位于 functions/pages/tools/extension_tools_window.py 的 ExtensionToolsApi，
这里只保留功能方法（包装 Mod / 生成插件模板 / 发布 Mod·插件），
窗口相关逻辑交给总览页的 OverviewApi（继承 WindowChromeBridge）。

`post_extension_tools` 里 mods/ addons/ 是相对路径；这里统一锚定到仓库根，
这样总览进程无论从哪个工作目录启动都能找到正确的目录。
"""

from __future__ import annotations

import base64
import json
import os

import core
import package_publish
from functions.tools import post_extension_tools as pet

# 包装/发布 Mod 统一使用 workflow 下的 mods（tools/workflow/mods），
# 与打包工作流的包目录一致；插件模板仍放在仓库根的 addons/。
pet.MODS_DIR = str(core.MODS_DIR)
pet.ADDONS_DIR = os.path.join(str(core.PROJECT_ROOT), "addons")


def _safe_js_str(obj) -> str:
    return json.dumps(obj, ensure_ascii=False).replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")


def _notify(func_name: str, arg) -> None:
    try:
        import webview
        for w in webview.windows:
            try:
                w.evaluate_js("window.%s && window.%s(%s)" % (func_name, func_name, _safe_js_str(arg)))
            except Exception:
                pass
    except Exception:
        pass


class ExtensionToolsMixin:
    """给 OverviewApi 提供扩展工具的全部 js_api 方法。"""

    def _default_pick_dir(self):
        """文件夹/文件对话框的默认打开目录：优先 tools/workflow/mods。"""
        for cand in (pet.MODS_DIR, str(core.WORKFLOW_DIR)):
            try:
                if cand and os.path.isdir(cand):
                    return cand
            except Exception:
                pass
        return pet.MODS_DIR

    def get_package_info(self, name):
        """读取包的信息（用于发布信息编辑模态）。"""
        try:
            kind, info = core.package_info(name)
            return {
                "ok": True,
                "name": name,
                "kind": kind,
                "info": {
                    "name": str(info.get("name") or ""),
                    "desc": str(info.get("desc") or ""),
                    "version": str(info.get("version") or ""),
                    "authors": info.get("authors") or {},
                },
                "icon": core.package_icon_uri(name),
                "load_files": core.scan_load_files(name),
                "last_version": core.last_published_version(name),
                "missing": core.publish_missing(name),
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def save_package_info(self, name, data):
        """就地保存包信息（先手动包装再发布）。"""
        try:
            result = package_publish.save_info(name, data or {})
            result["state"] = self.get_state()
            return result
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def publish_package(self, name):
        """发布包：校验 → 版本自增 → 上传；日志经 __onPublishLog/Progress 推送。"""
        logs = []

        def _log(s):
            text = str(s)
            logs.append(text)
            _notify("__onPublishLog", text)

        def _progress(percent, text):
            _notify("__onPublishProgress", {"percent": percent, "text": text})

        try:
            result = package_publish.publish(name, log=_log, progress=_progress)
            result["log"] = "\n".join(logs)
            result["state"] = self.get_state()
            return result
        except Exception as e:
            return {"ok": False, "msg": f"发布失败: {e}",
                    "log": "\n".join(logs), "state": self.get_state()}

    def assets(self):
        try:
            icon_path = os.path.join(str(core.PROJECT_ROOT), "assets", "images", "icon", "icon.png")
            with open(icon_path, "rb") as f:
                return {"bg": "data:image/png;base64," + base64.b64encode(f.read()).decode("ascii")}
        except Exception:
            return {"bg": None}

    def list_mods(self):
        result = []
        try:
            mods_dir = pet.MODS_DIR
            if os.path.isdir(mods_dir):
                for d in sorted(os.listdir(mods_dir)):
                    path = os.path.join(mods_dir, d)
                    if os.path.isdir(path):
                        result.append({
                            "name": d,
                            "path": path,
                            "wrapped": os.path.isfile(os.path.join(path, "mod_info.json")),
                        })
        except Exception as e:
            print(f"[Extensions] 获取 mods 列表失败: {e}")
        return result

    def list_addons(self):
        result = []
        try:
            addons_dir = pet.ADDONS_DIR
            if os.path.isdir(addons_dir):
                for d in sorted(os.listdir(addons_dir)):
                    path = os.path.join(addons_dir, d)
                    if os.path.isdir(path):
                        result.append({
                            "name": d,
                            "path": path,
                            "wrapped": os.path.isfile(os.path.join(path, "addon_info.json")),
                        })
        except Exception as e:
            print(f"[Extensions] 获取 addons 列表失败: {e}")
        return result

    def pick_folder(self):
        try:
            import webview
            window = self._win()
            if window is None:
                return None
            paths = window.create_file_dialog(
                webview.FileDialog.FOLDER, directory=self._default_pick_dir())
            return paths[0] if paths else None
        except Exception as e:
            print(f"[Extensions] 打开文件夹对话框失败: {e}")
            return None

    def pick_files(self):
        try:
            import webview
            window = self._win()
            if window is None:
                return []
            paths = window.create_file_dialog(
                webview.FileDialog.OPEN,
                directory=self._default_pick_dir(),
                allow_multiple=True,
                file_types=("Mod文件 (*.bank;*.carra2;*.rebank;*.json)", "所有文件 (*.*)"))
            return list(paths) if paths else []
        except Exception as e:
            print(f"[Extensions] 打开文件对话框失败: {e}")
            return []

    def pick_icon(self):
        try:
            import webview
            window = self._win()
            if window is None:
                return None
            paths = window.create_file_dialog(
                webview.FileDialog.OPEN,
                file_types=("图片文件 (*.png;*.jpg;*.jpeg;*.ico)",))
            return paths[0] if paths else None
        except Exception as e:
            print(f"[Extensions] 打开图标对话框失败: {e}")
            return None

    def read_image_data_uri(self, path):
        """读取本地图片为 data URI（图标预览用，避免 file:// 破图/缓存问题）。"""
        try:
            import base64
            import mimetypes
            p = str(path or "")
            if not p or not os.path.isfile(p):
                return {"ok": False, "error": "图片文件不存在"}
            mime, _ = mimetypes.guess_type(p)
            with open(p, "rb") as f:
                data = f.read()
            return {"ok": True, "uri": "data:%s;base64,%s" % (
                mime or "image/png", base64.b64encode(data).decode("ascii"))}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def scan_mod_files(self, folder, single_file=False):
        folder = (folder or "").strip()
        if not folder:
            return {"ok": False, "files": [], "error": "请先选择原始文件夹"}
        if not os.path.isdir(folder):
            return {"ok": False, "files": [], "error": f"原始文件夹不存在: {folder}"}
        if not single_file:
            err = pet._validate_wrap_source(folder)
            if err:
                return {"ok": False, "files": [], "error": err}
        return {"ok": True, "files": pet._scan_mod_files(folder), "error": ""}

    def wrap_mod(self, data):
        try:
            data = data or {}
            info = {
                "name": data.get("name", ""),
                "desc": data.get("desc", ""),
                "version": data.get("version", "0.0.1"),
                "authors": data.get("authors") or {},
                "file_names": data.get("files") or [],
                "extra_files": data.get("extra_files") or [],
            }
            icon_path = data.get("icon_path") or None
            ok, msg = pet.wrap_mod(data.get("folder", ""), info=info,
                                   icon_path=icon_path,
                                   single_file=bool(data.get("single_file")))
            return {"ok": ok, "msg": msg}
        except Exception as e:
            return {"ok": False, "msg": f"包装 Mod 失败: {e}"}

    def spawn_extension(self, data):
        try:
            data = data or {}
            ok, msg = pet.spawn_extension(
                data.get("name", ""),
                info={
                    "desc": data.get("desc", ""),
                    "version": data.get("version", "0.0.1"),
                    "authors": data.get("authors") or {},
                    "icon_path": data.get("icon_path") or None,
                })
            return {"ok": ok, "msg": msg}
        except Exception as e:
            return {"ok": False, "msg": f"生成插件模板失败: {e}"}

    def _max_size_mb(self):
        try:
            from functions.base.web_config import get_lanzou_config
            return int(get_lanzou_config().get("max_size_mb") or 66)
        except Exception:
            return 66

    def preview_mod(self, folder):
        info, err = pet.load_mod_info(folder)
        if err:
            return {"ok": False, "info": {}, "max_size_mb": None, "error": err}
        return {"ok": True, "info": info, "max_size_mb": self._max_size_mb(), "error": ""}

    def publish_mod(self, folder, tags=None, tags_style=None):
        logs = []

        def _log(s):
            logs.append(s)
            _notify("__onPublishLog", s)

        def _progress(percent, text):
            _notify("__onPublishProgress", {"percent": percent, "text": text})

        info, err = pet.load_mod_info(folder)
        try:
            ok, msg = pet.publish_mod(
                folder, log=_log, progress=_progress, tags=tags, tags_style=tags_style,
            )
            _progress(100, "完成")
            return {"ok": ok, "msg": msg, "log": "\n".join(logs), "info": info if not err else {}}
        except Exception as e:
            return {"ok": False, "msg": f"发布失败: {e}", "log": "\n".join(logs), "info": {}}

    def preview_addon(self, folder):
        info, err = pet.load_addon_info(folder)
        if err:
            return {"ok": False, "info": {}, "max_size_mb": None, "error": err}
        return {"ok": True, "info": info, "max_size_mb": self._max_size_mb(), "error": ""}

    def publish_addon(self, folder, tags=None, tags_style=None):
        logs = []

        def _log(s):
            logs.append(s)
            _notify("__onAddonLog", s)

        def _progress(percent, text):
            _notify("__onAddonProgress", {"percent": percent, "text": text})

        info, err = pet.load_addon_info(folder)
        try:
            ok, msg = pet.publish_addon(
                folder, log=_log, progress=_progress, tags=tags, tags_style=tags_style,
            )
            _progress(100, "完成")
            return {"ok": ok, "msg": msg, "log": "\n".join(logs), "info": info if not err else {}}
        except Exception as e:
            return {"ok": False, "msg": f"发布失败: {e}", "log": "\n".join(logs), "info": {}}
