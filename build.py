"""FaustLauncher 可视化构建工具（pywebview 版）。

界面在 ``web/build_ui/``（HTML/CSS/JS，与 web/version_update、web/mod_manager 同层），
本文件只做两件事：

1. **搬运构建步骤**（与旧 Tk 版逐条一致：PyInstaller → 清理 → 目录 → 运行环境 → 资产 →
   字体 → 配置 → 资源 → 文档 → exe → 压缩 zip），每步的状态/日志/进度推给前端；
2. **暴露 JS API**（``BuildApi``）：前端每 150ms 轮询 ``poll()`` 取事件队列。

与原 Tk 版的差异（按需求）：
  · **取消"版本信息地址"配置** —— 上传统一用 ``functions.base.web_config.get_webnote()``
    里的配置（与 mod/addon/hook 索引同一套），界面上不再有输入框；
  · 上传发布有**真实进度条**：蓝奏云 ``UploadFile`` 自带 ``progress_callback``（真百分比），
    版本信息上传则是阶段式进度（笔记接口是单次 POST，拿不到字节级进度）。
"""

from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime

from functions.base.web_config import get_webnote

# 与 build_ui/style.css 里的配色保持一致的语义（前端按 level 着色）
LEVEL_OK, LEVEL_BAD, LEVEL_WARN = "ok", "bad", "warn"

BUILD_STEPS = [
    ("pyinstaller", "PyInstaller 打包"),
    ("cleanup", "清理旧构建"),
    ("mkdir", "创建版本目录"),
    ("runtime", "复制运行环境"),
    ("assets", "复制资产文件"),
    ("font", "重置字体目录"),
    ("config", "复制配置文件"),
    ("resources", "复制资源文件"),
    ("docs", "复制文档文件"),
    ("exe", "复制可执行文件"),
    ("compress", "压缩打包 zip"),
]


# --------------------------------------------------------------------------- 上传版本信息
def upload_version_info(version, download_url: str = "", log=None) -> bool:
    """上传版本信息到 webnote —— 与其它笔记 (mod/addon/hook 索引) **完全同一套读写构造**。

    ⚠ 地址**不再由界面传入**：统一取 ``get_webnote('version_info')`` 的配置。

    构造（别再自己 requests，见 ``functions/webFunc/Webnote.py``）：
      · 读: ``read_note_live()`` —— 多源 + IPv4 优先 + DoH 直连兜底；
        **200 + 0 字节 / HTML 错误页一律算读取失败**，绝不当作"笔记是空的"
        （以前自己 requests 读到空响应 → 当成全新笔记 → 上传后抹掉云端几十个版本历史）；
      · 写: ``write_note()`` —— POST(/update/) + 小内容 GET 兜底 + 连接类错误重试
        + 严格响应解析（HTML/414/非 JSON/status!=1 都算失败）。

    规则：读不到云端内容 → **跳过上传**；版本号已存在 → 跳过；只登记版本号与上传时间。
    """
    log = log or (lambda text, level="": None)
    try:
        from functions.webFunc.Webnote import read_note_live, write_note

        address = str(get_webnote("version_info")[0] or "").strip()
        if not address:
            log("⚠ 未配置版本信息笔记名（config/web_config.json），跳过上传\n", LEVEL_WARN)
            return False

        log(f"· 读取云端版本信息（{address}）…\n")
        text, used_key, err = read_note_live("version_info", address)
        if not str(text or "").strip():
            log("⚠ 读不到云端版本信息内容，为避免覆盖已有版本历史已跳过上传"
                f"{f' ({err})' if err else ''}\n", LEVEL_WARN)
            return False

        try:
            data = json.loads(text)
        except Exception as exc:  # noqa: BLE001
            log(f"⚠ 云端版本信息不是合法 JSON ({exc})，已跳过上传\n", LEVEL_WARN)
            return False
        if not isinstance(data, dict):
            log("⚠ 云端版本信息结构异常（顶层不是对象），已跳过上传\n", LEVEL_WARN)
            return False

        versions = data.get("versions")
        versions = versions if isinstance(versions, dict) else {}
        if version in versions:
            log(f"⏭ 版本 {version} 已存在于云端，跳过上传\n")
            return True

        new_versions = {version: {
            "data": datetime.now().strftime("%Y-%m-%d-%H:%M:%S"),
            "description": "",
            "url": download_url or "",
        }}
        new_versions.update(versions)          # 新版本插到最前（dict 顺序 = JSON 顺序）
        data["versions"] = new_versions
        if not data.get("latest_release_version"):
            data["latest_release_version"] = ""   # 预置空值键，由服务器侧填写

        log(f"· 上传版本信息 {version} …\n")
        result = write_note(used_key, json.dumps(data, ensure_ascii=False, indent=4)) or {}
        if result.get("status") == 1:
            log(f"✔ 版本信息上传成功：{version}\n", LEVEL_OK)
            return True
        log(f"✕ 版本信息上传失败：{result.get('error') or result}\n", LEVEL_BAD)
        return False
    except Exception as exc:  # noqa: BLE001
        log(f"⚠ 上传版本信息失败（不影响构建结果）：{exc}\n", LEVEL_BAD)
        return False


# --------------------------------------------------------------------------- JS API
class BuildApi:
    """暴露给前端（``pywebview`` 的 js_api）。所有耗时活儿都在后台线程里跑。"""

    def __init__(self, version_info: str):
        self.version_info = str(version_info or "unknown")
        self._events: "queue.Queue[dict]" = queue.Queue()
        self._window = None
        self._zip_path = ""
        self._building = False
        self._published = False

    # ---- 事件推给前端用的内部工具 ----
    def _emit(self, **event) -> None:
        self._events.put(event)

    def _log(self, text: str, level: str = "", color: str | None = None) -> None:
        """记一行日志。

        ``level`` 是给前端着色的语义（ok/bad/warn）；``color`` 是为了兼容旧调用方
        （蓝奏那套助手是按 ``log(text, color='#ef4444')`` 调的）—— 传了颜色就按颜色归类。
        """
        if not level and color:
            low = str(color).lower().strip()
            if low.startswith("#") and len(low) >= 7:
                try:
                    r = int(low[1:3], 16)
                    g = int(low[3:5], 16)
                    b = int(low[5:7], 16)
                    # 偏红=错误 / 偏绿=成功 / 其它=提示（不猜具体色号，按通道算）
                    level = (LEVEL_BAD if (r > g + 40 and r > b + 40)
                             else LEVEL_OK if (g > r + 40 and g > b + 40)
                             else LEVEL_WARN)
                except ValueError:
                    level = LEVEL_WARN
            else:
                level = (LEVEL_BAD if "red" in low
                         else LEVEL_OK if "green" in low else LEVEL_WARN)
        self._emit(type="log", text=str(text), level=level)

    def _step(self, index: int, state: str) -> None:
        self._emit(type="step", index=index, state=state)

    def _progress(self, value: float, cls: str = "") -> None:
        self._emit(type="progress", value=value, cls=cls)

    def _status(self, text: str, level: str = "") -> None:
        self._emit(type="status", text=str(text), level=level)

    def _upload(self, percent: float, text: str = "") -> None:
        self._emit(type="upload", percent=percent, text=text)

    # ---- 前端调用 ----
    def get_state(self) -> dict:
        return {
            "version": self.version_info,
            "steps": [{"key": k, "name": n} for k, n in BUILD_STEPS],
            "building": self._building,
            "zip": self._zip_path,
        }

    def poll(self) -> dict:
        """取走事件队列（前端每 150ms 调一次）。"""
        events: list[dict] = []
        while True:
            try:
                events.append(self._events.get_nowait())
            except queue.Empty:
                break
        return {"ok": True, "events": events}

    def start_build(self) -> dict:
        if self._building:
            return {"ok": False, "error": "构建已在进行中"}
        self._building = True
        threading.Thread(target=self._run_all_steps, name="faust-build", daemon=True).start()
        return {"ok": True}

    def publish(self) -> dict:
        if self._published:
            return {"ok": False, "error": "已发起过发布"}
        self._published = True
        threading.Thread(target=self._publish_release, name="faust-publish", daemon=True).start()
        return {"ok": True}

    def open_build_dir(self) -> dict:
        target = f"build_{self.version_info}"
        try:
            os.startfile(target)               # noqa: S606（Windows 专用）
            return {"ok": True}
        except Exception as exc:  # noqa: BLE001
            self._log(f"打开目录失败：{exc}\n", LEVEL_BAD)
            return {"ok": False, "error": str(exc)}

    def close(self) -> dict:
        try:
            if self._window is not None:
                self._window.destroy()
        except Exception:  # noqa: BLE001
            pass
        return {"ok": True}

    # ---- 构建步骤（与旧 Tk 版逐条一致） ----
    def _run_pyinstaller(self) -> int:
        py = sys.executable
        venv_py = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "venv", "Scripts", "python.exe")
        if os.path.isfile(venv_py):
            py = venv_py
            self._log(f"· 使用项目 venv 解释器打包：{venv_py}\n")
        else:
            self._log(f"· 未找到项目 venv，使用当前解释器：{sys.executable}\n", LEVEL_WARN)
        proc = subprocess.Popen(
            [py, "-m", "PyInstaller", "--noconfirm", "FaustLauncher.spec"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
        )
        for line in proc.stdout:  # type: ignore[union-attr]
            self._log(line)
        proc.wait()
        return int(proc.returncode)

    def _fail(self, index: int, message: str) -> None:
        self._step(index, "failed")
        self._status(message, LEVEL_BAD)
        self._log(f"\n✕ {message}\n", LEVEL_BAD)
        self._emit(type="done", ok=False)

    def _run_all_steps(self) -> None:
        vi = self.version_info

        # ---- 0. PyInstaller ----
        self._step(0, "running")
        self._status("正在运行 PyInstaller…")
        self._progress(3)
        try:
            rc = self._run_pyinstaller()
        except Exception as exc:  # noqa: BLE001
            self._fail(0, f"PyInstaller 异常：{exc}")
            self._building = False
            return
        if rc != 0:
            self._fail(0, f"PyInstaller 失败（code {rc}）")
            self._building = False
            return
        self._step(0, "done")
        self._progress(12)

        # ---- 1. 清理旧构建 ----
        self._step(1, "running")
        self._status("清理旧版本文件夹…")
        shutil.rmtree(f"build_{vi}", ignore_errors=True)
        self._step(1, "done")
        self._progress(20)

        # ---- 2. 创建版本目录 ----
        self._step(2, "running")
        self._status("创建版本目录…")
        os.makedirs(f"build_{vi}", exist_ok=True)
        self._step(2, "done")
        self._progress(30)

        # ---- 3. 复制运行环境（取自 PyInstaller 产物） ----
        self._step(3, "running")
        self._status("复制运行环境（来自 dist）…")
        try:
            if not os.path.isdir("dist/FaustLauncher/_internal"):
                raise FileNotFoundError("未找到 dist/FaustLauncher/_internal")
            shutil.copytree("dist/FaustLauncher/_internal", f"build_{vi}/_internal",
                            dirs_exist_ok=True)
            for d in ("addons", "mods"):
                os.makedirs(f"build_{vi}/{d}", exist_ok=True)
            from functions.web_update.translation_source import get_translation_dir
            os.makedirs(f"build_{vi}/{get_translation_dir()}", exist_ok=True)
            if not os.path.isfile("build_temp/updater.vbs"):
                raise FileNotFoundError("未找到 build_temp/updater.vbs（版本更新器必备）")
            shutil.copy("build_temp/updater.vbs", f"build_{vi}/updater.vbs")
            if os.path.isdir("functions/webFunc"):
                shutil.copytree("functions/webFunc", f"build_{vi}/_internal/webFunc",
                                dirs_exist_ok=True)
            pyz_toc = os.path.join("build", "FaustLauncher", "PYZ-00.toc")
            pyz_txt = ""
            try:
                with open(pyz_toc, encoding="utf-8", errors="replace") as fh:
                    pyz_txt = fh.read()
            except Exception:  # noqa: BLE001
                pass
            for module, tip in (("pystray", "系统托盘不可用"),
                                ("webview", "新版 Web 界面无法启动"),
                                ("cffi", "pywebview 依赖缺失")):
                if f"'{module}'" not in pyz_txt:
                    raise FileNotFoundError(
                        f"PyInstaller 未收集 {module}（{tip}），请用项目 venv 运行本构建工具")
            pr_dll = os.path.join("dist", "FaustLauncher", "_internal", "pythonnet",
                                  "runtime", "Python.Runtime.dll")
            if not os.path.isfile(pr_dll):
                raise FileNotFoundError(
                    "PyInstaller 未收集 pythonnet runtime（Python.Runtime.dll），Web 界面无法启动")
            web_index = os.path.join("dist", "FaustLauncher", "_internal", "web", "app",
                                     "index.html")
            if not os.path.isfile(web_index):
                raise FileNotFoundError(
                    "PyInstaller 未把 web/ 收进 _internal/web（Web 界面无法启动）；"
                    "请确认 FaustLauncher.spec 的 web/ 收集逻辑与 web/app/index.html 存在")
        except Exception as exc:  # noqa: BLE001
            self._fail(3, f"复制运行环境失败：{exc}")
            self._building = False
            return
        self._step(3, "done")
        self._progress(38)

        # ---- 4. 复制资产（web/ 已由 spec 收进 _internal） ----
        self._step(4, "running")
        self._status("复制资产文件…")
        try:
            shutil.copytree("assets", f"build_{vi}/assets", dirs_exist_ok=True)
        except Exception as exc:  # noqa: BLE001
            self._fail(4, f"复制 assets 失败：{exc}")
            self._building = False
            return
        self._step(4, "done")
        self._progress(46)

        # ---- 5. 重置字体 ----
        self._step(5, "running")
        self._status("重置字体目录…")
        shutil.rmtree(f"build_{vi}/assets/Font", ignore_errors=True)
        os.makedirs(f"build_{vi}/assets/Font", exist_ok=True)
        self._step(5, "done")
        self._progress(54)

        # ---- 6. 复制配置（排除内嵌的 web_config.json） ----
        self._step(6, "running")
        self._status("复制配置文件…")
        try:
            sys.path.insert(0, ".")
            from functions.base.settings_manager import get_settings_manager
            get_settings_manager().reset_all_settings()
        except Exception:  # noqa: BLE001
            pass
        try:
            shutil.copytree("config", f"build_{vi}/config", dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns("web_config.json"))
        except Exception as exc:  # noqa: BLE001
            self._fail(6, f"复制 config 失败：{exc}")
            self._building = False
            return
        if os.path.exists("config/web_config.json"):
            self._log("✔ web_config.json 已内嵌进 exe（PYZ），不随构建产物分发\n", LEVEL_OK)
        else:
            self._log("⚠ 未发现 config/web_config.json，云端功能将静默降级\n", LEVEL_WARN)
        self._step(6, "done")
        self._progress(62)

        # ---- 7. 复制资源（仅 7-zip + 战斗观测 DLL） ----
        self._step(7, "running")
        self._status("复制资源文件…")
        try:
            os.makedirs(f"build_{vi}/resources/7-zip", exist_ok=True)
            if os.path.isdir("resources/7-zip"):
                shutil.copytree("resources/7-zip", f"build_{vi}/resources/7-zip",
                                dirs_exist_ok=True)
            hook_dll = "functions/achievement/hook_dll"
            src_dll = os.path.join(hook_dll, "battle_watch.dll")
            src_c = os.path.join(hook_dll, "battle_watch.c")
            if os.path.isfile(src_dll):
                dst_dir = f"build_{vi}/_internal/hook_dll"
                os.makedirs(dst_dir, exist_ok=True)
                shutil.copy2(src_dll, os.path.join(dst_dir, "battle_watch.dll"))
                self._log("✔ battle_watch.dll 已随构建产物发布（{} 字节，{}）\n".format(
                    os.path.getsize(src_dll),
                    time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(os.path.getmtime(src_dll)))),
                    LEVEL_OK)
                if os.path.isfile(src_c) and os.path.getmtime(src_c) > os.path.getmtime(src_dll):
                    self._log("⚠ battle_watch.c 比 DLL 新：发布包里是旧构建，"
                              "请先跑 functions/achievement/hook_dll/build.ps1\n", LEVEL_WARN)
        except Exception as exc:  # noqa: BLE001
            self._fail(7, f"复制 resources 失败：{exc}")
            self._building = False
            return
        self._step(7, "done")
        self._progress(74)

        # ---- 8. 复制文档 ----
        self._step(8, "running")
        self._status("复制文档…")
        for name in ("LICENSE", "README.md"):
            try:
                shutil.copy(name, f"build_{vi}/{name}")
            except Exception:  # noqa: BLE001
                pass
        self._step(8, "done")
        self._progress(86)

        # ---- 9. 复制 exe ----
        self._step(9, "running")
        self._status("复制可执行文件…")
        src = "dist/FaustLauncher/FaustLauncher.exe"
        if not os.path.exists(src):
            self._fail(9, f"未找到 {src}")
            self._building = False
            return
        try:
            shutil.copy(src, f"build_{vi}/FaustLauncher.exe")
        except Exception as exc:  # noqa: BLE001
            self._fail(9, f"复制 exe 失败：{exc}")
            self._building = False
            return
        self._step(9, "done")
        self._progress(92)

        # ---- 10. 压缩打包 zip ----
        self._step(10, "running")
        self._status("压缩打包 zip…")
        try:
            import zipfile
            folder = f"build_{vi}"
            zip_path = "FaustLauncher-" + str(vi).lstrip("V") + ".zip"
            if os.path.exists(zip_path):
                os.remove(zip_path)
            files: list[str] = []
            dirs: list[str] = []
            for root, _dirs, fs in os.walk(folder):
                files.extend(os.path.join(root, f) for f in fs)
                dirs.extend(os.path.join(root, d) for d in _dirs)
            if not files and not dirs:
                raise FileNotFoundError(f"{folder} 为空，无法打包")
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for d in sorted(dirs):     # 目录条目（含空目录）保证解压后结构完整
                    arc = os.path.join("FaustLauncher",
                                       os.path.relpath(d, folder)).replace("\\", "/") + "/"
                    zf.writestr(arc, "")
                for i, full in enumerate(files):
                    arc = os.path.join("FaustLauncher",
                                       os.path.relpath(full, folder)).replace("\\", "/")
                    zf.write(full, arc)
                    if (i + 1) % 200 == 0:
                        self._progress(92 + int((i + 1) / len(files) * 8))
            size_mb = os.path.getsize(zip_path) / 1024.0 / 1024.0
            self._log(f"✔ 压缩完成：{zip_path}（{size_mb:.1f} MB）\n", LEVEL_OK)
            self._zip_path = zip_path
        except Exception as exc:  # noqa: BLE001
            self._fail(10, f"压缩打包失败：{exc}")
            self._building = False
            return
        self._step(10, "done")
        self._progress(100, "ok")
        self._status(f"构建完成！v{vi}", LEVEL_OK)
        self._log(f"\n✔ 构建完成：build_{vi}\n", LEVEL_OK)
        self._log(f"已生成压缩包：{self._zip_path}\n", LEVEL_OK)
        self._emit(type="done", ok=True)
        self._building = False

    # ---- 上传发布（**真实进度**来自蓝奏云 UploadFile 的 progress_callback） ----
    def _publish_release(self) -> None:
        zip_path = self._zip_path or ("FaustLauncher-" + str(self.version_info).lstrip("V") + ".zip")
        if not os.path.isfile(zip_path):
            self._upload(0, "未找到压缩包")
            self._log(f"✕ 未找到压缩包：{zip_path}\n", LEVEL_BAD)
            return
        try:
            from functions.tools.post_extension_tools import _lanzou_session, PARSER_BASE
            from functions.web_update.lanzou_utils import GetOrCreateFolder, UploadFile
            from functions.base.web_config import get_lanzou_config

            self._upload(0, "登录蓝奏云…")
            self._log(f"开始发布 {self.version_info} …\n")
            session = _lanzou_session(self._log)
            self._upload(2, "定位文件夹 FaustLauncher…")
            fid = GetOrCreateFolder(session, "FaustLauncher")
            if not fid:
                raise RuntimeError("无法创建/定位蓝奏云文件夹：FaustLauncher")

            max_mb = int(get_lanzou_config().get("max_size_mb") or 66)
            self._upload(4, "上传压缩包…")
            last = {"pct": -1}

            def _on_progress(progress: float) -> None:
                percent = min(100, max(0, int(progress * 100)))
                if percent != last["pct"]:
                    last["pct"] = percent
                    self._upload(4 + percent * 0.9, f"上传中 {percent}%")   # 留 6% 给版本信息

            ret = UploadFile(session, zip_path, folder_id=fid, max_size_mb=max_mb, # type: ignore
                             progress_callback=_on_progress) or {}
            if ret.get("status") != 1:
                raise RuntimeError(f"上传失败：{ret.get('msg')}")

            share = ret.get("share_url") or ""
            url = PARSER_BASE + share
            self._upload(94, "写入版本信息…")
            self._log(f"✔ 上传成功，直链：{url}\n", LEVEL_OK)
            upload_version_info(self.version_info, download_url=url, log=self._log)
            self._upload(100, "发布完成")
            self._log(f"\n✔ 发布完成！下载链接：{url}\n", LEVEL_OK)
        except Exception as exc:  # noqa: BLE001
            self._upload(0, f"发布失败：{exc}")
            self._log(f"\n✕ 发布失败：{exc}\n", LEVEL_BAD)
    _window = None


# 入口
def main() -> int:
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    try:
        from functions.base.settings_manager import get_settings_manager
        sm = get_settings_manager()
        sm.reset_all_settings()
        sm.save_settings()
        version = sm.get_setting("version_info")
    except Exception:  # noqa: BLE001
        version = "unknown"

    try:
        import webview
    except Exception as exc:  # noqa: BLE001
        print(f"[构建工具] 需要 pywebview：{exc}", file=sys.stderr)
        return 1

    api = BuildApi(version) # type: ignore
    index_html = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "web", "build_ui", "index.html")
    win = webview.create_window(
        f"FaustLauncher 构建工具 — v{version}",
        index_html, js_api=api, # type: ignore
        width=780, height=800, min_size=(680, 620),
        background_color="#14161c",
    )
    api._window = win # type: ignore
    webview.start()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
