"""单个包的打包子进程：启动 mod_loader --package-only，并复用 mod_loader 页面显示进度。"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import core


def _loader_paths() -> tuple:
    base = core.PROJECT_ROOT / "resources" / "mod_loader" / "_internal"
    candidates = [
        base / "venv" / "Bins" / "python.exe",
        base / "venv" / "Scripts" / "python.exe",
    ]
    python_exe = next((p for p in candidates if p.is_file()), Path(sys.executable))
    return python_exe, base / "main.py"


def _read_progress(pkg: Path) -> str:
    try:
        return (pkg / core.PROGRESS_NAME).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _parse_progress(raw: str) -> tuple:
    if not raw:
        return "", 0, ""
    if raw == "LAUNCH":
        return "launch", core.STAGE_TOTAL, "打包完成"
    if raw.startswith("ERROR"):
        return "error", 0, (raw.split("|", 1)[1].strip() if "|" in raw else "打包失败")
    if "|" in raw:
        head, _sep, tail = raw.partition("|")
        if head.strip().isdigit():
            return "stage", int(head.strip()), tail.strip()
    return "unknown", 0, raw


def _log_level(line: str) -> str:
    low = line.lower()
    if "错误" in line or "失败" in line or "error" in low or "traceback" in low:
        return "error"
    if "警告" in line or "warn" in low:
        return "warning"
    for kw in ("完成", "成功", "已生成", "已删除", "已清理", "输出统计"):
        if kw in line:
            return "success"
    return "info"


def _read_log_tail(pkg: Path, max_lines: int = 240, max_bytes: int = 240000) -> list:
    path = pkg / core.LOG_NAME
    try:
        size = path.stat().st_size
        with open(path, "rb") as fh:
            fh.seek(max(0, size - max_bytes))
            data = fh.read()
        text = data.decode("utf-8", errors="replace")
        lines = [ln for ln in text.splitlines() if ln.strip()]
        return lines[-max_lines:]
    except OSError:
        return []


def _parse_iso(value: str):
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _icon_data_uri() -> str:
    try:
        from functions.base.window_chrome import icon_data_uri, titlebar_icon_path
        return icon_data_uri(titlebar_icon_path("yisang"))
    except Exception:
        pass
    try:
        path = core.PROJECT_ROOT / "resources" / "mod_loader" / "_internal" / "assets" / "icon.png"
        if path.is_file():
            return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode("ascii")
    except Exception:
        pass
    return ""


class PackageWorkerApi:
    """给 web/mod_loader 页面提供 package 模式的 state。"""

    def __init__(self, name: str):
        self.name = name
        self.pkg = core.package_dir(name)
        self._window = None
        self._t0 = time.time()
        self._icon = ""
        self._finished = False

    def attach(self, window) -> None:
        self._window = window
        self._icon = _icon_data_uri()

    def _win(self):
        if self._window is not None:
            return self._window
        try:
            import webview
            return webview.windows[0] if webview.windows else None
        except Exception:
            return None

    def close(self):
        if self._finished:
            return True
        self._finished = True
        window = self._win()
        try:
            if window is not None:
                from functions.base.window_chrome import fade_out_window
                fade_out_window(window, then_close=True)
            else:
                window.destroy()
        except Exception:
            pass
        return True

    # 兼容 WindowChromeBridge / chrome.js 的窗口按钮
    def minimize_window(self):
        try:
            from functions.base.window_chrome import minimize_window
            return minimize_window(self._win())
        except Exception:
            return False

    def close_window(self):
        return self.close()

    def begin_move_window(self, mouse_x, mouse_y):
        try:
            from functions.base.window_chrome import begin_move_window
            return begin_move_window(self._win(), mouse_x, mouse_y)
        except Exception:
            return False

    def move_window(self, mouse_x, mouse_y):
        try:
            from functions.base.window_chrome import move_window
            return move_window(self._win(), mouse_x, mouse_y)
        except Exception:
            return False

    def end_move_window(self):
        try:
            from functions.base.window_chrome import end_move_window
            return end_move_window(self._win())
        except Exception:
            return False

    def theme_revision(self) -> str:
        try:
            from functions.base.window_chrome import theme_revision
            return theme_revision()
        except Exception:
            return ""

    def get_full_theme_css(self) -> str:
        try:
            from functions.base.skin_theme import full_theme_css
            return full_theme_css()
        except Exception:
            return ""

    def get_state(self):
        job = core.read_job(self.name)
        raw = _read_progress(self.pkg)
        kind, stage_no, stage_text = _parse_progress(raw)

        status = job["status"]
        error = ""
        done = False

        if status == "failed":
            error = job["message"] or stage_text or "打包失败"
            done = True
        elif status == "interrupted":
            error = job["message"] or "打包进程意外退出"
        elif status == "done":
            done = True
        elif kind == "error":
            error = stage_text or "打包失败"
        elif kind == "launch" or stage_no >= core.STAGE_TOTAL:
            done = True

        if not stage_text:
            if error:
                stage_text = error
            elif status == "running":
                stage_text = "正在启动打包进程…"
            elif status == "idle":
                stage_text = "等待开始"
            elif done:
                stage_text = "打包完成"

        total = core.STAGE_TOTAL
        stages = []
        done_upto = 0
        if done and not error:
            done_upto = total
        elif kind == "stage":
            done_upto = max(0, stage_no - 1)
        for i in range(1, total + 1):
            if i <= done_upto:
                state = "done"
            elif kind == "stage" and i == stage_no and not error:
                state = "active"
            elif error and i == max(1, stage_no):
                state = "error"
            else:
                state = "pending"
            stages.append({
                "n": i,
                "title": core.STAGE_TITLES.get(i, "阶段 %d" % i),
                "state": state,
            })

        if done and not error:
            pct = 100.0
        elif kind == "stage":
            pct = max(0.0, (done_upto + 0.5) / total * 100.0)
        else:
            pct = 0.0

        start = _parse_iso(job["started_at"]) or datetime.fromtimestamp(self._t0)
        end = _parse_iso(job["finished_at"]) if (done or error) else None
        end = end or datetime.now()
        elapsed_ms = max(0, int((end - start).total_seconds() * 1000))

        return {
            "mode": "package",
            "title": self.name,
            "pid": job["worker_pid"],
            "alive": core.pid_alive(job["worker_pid"]),
            "kind": kind,
            "stage_no": stage_no,
            "stage_total": total,
            "stage_text": stage_text,
            "stages": stages,
            "pct": round(pct, 1),
            "threads": [],
            "log": [{"text": ln, "level": _log_level(ln)} for ln in _read_log_tail(self.pkg)],
            "elapsed_ms": elapsed_ms,
            "icon": self._icon,
            "done": done and not error,
            "error": error,
            "job_status": status,
        }


def _monitor_process(name: str, proc) -> None:
    code = proc.wait()
    job = core.read_job(name)
    if job["status"] in ("done", "failed"):
        return
    raw = _read_progress(core.package_dir(name))
    kind, _stage_no, stage_text = _parse_progress(raw)
    if code == 0:
        core.write_job(name, status="done", finished_at=core._now_iso(), message="")
    else:
        detail = stage_text if kind == "error" else "mod_loader 退出码 %d" % code
        core.write_job(name, status="failed", finished_at=core._now_iso(), message=detail)


def run_worker(package_dir, debug: bool = False) -> int:
    pkg = Path(package_dir).resolve()
    mods_dir = core.MODS_DIR.resolve()
    if pkg.parent != mods_dir or not pkg.is_dir():
        print("[workflow] 非法的包目录: %s" % pkg)
        return 1

    name = pkg.name
    core.append_worker_log(name, "worker 启动, pid=%d" % os.getpid())

    current = core._read_json(pkg / core.JOB_NAME)
    try:
        current_pid = int(current.get("worker_pid") or 0)
    except (TypeError, ValueError):
        current_pid = 0
    if current.get("status") == "running" and current_pid != os.getpid() and core.pid_alive(current_pid):
        core.append_worker_log(name, "已有 worker 在运行 (pid=%d), 退出" % current_pid)
        return 1

    try:
        (pkg / core.PROGRESS_NAME).unlink()
    except OSError:
        pass
    try:
        (pkg / core.THREADS_NAME).unlink()
    except OSError:
        pass

    core.write_job(
        name,
        status="running",
        worker_pid=os.getpid(),
        started_at=core._now_iso(),
        finished_at="",
        message="",
    )

    python_exe, loader_main = _loader_paths()
    if not loader_main.is_file():
        message = "找不到 mod_loader: %s" % loader_main
        core.write_job(name, status="failed", finished_at=core._now_iso(), message=message)
        core.append_worker_log(name, message)
        return 1

    cmd = [
        str(python_exe),
        str(loader_main),
        "--package-only",
        "--work-dir",
        str(pkg),
        "--threads",
        str(core.resolve_threads()),
    ]
    game_path = core.resolve_game_path()
    sound_dir = core.resolve_sound_dir()
    if game_path:
        cmd += ["--game-path", game_path]
    if sound_dir:
        cmd += ["--sound-dir", sound_dir]

    core.append_worker_log(name, "启动 mod_loader: %s" % " ".join(cmd))
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(core.PROJECT_ROOT),
            creationflags=creationflags,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError as exc:
        message = "无法启动 mod_loader: %s" % exc
        core.write_job(name, status="failed", finished_at=core._now_iso(), message=message)
        core.append_worker_log(name, message)
        return 1

    monitor = threading.Thread(target=_monitor_process, args=(name, proc), daemon=True)
    monitor.start()

    html = core.PROJECT_ROOT / "web" / "mod_loader" / "index.html"
    if not html.is_file():
        core.append_worker_log(name, "找不到页面 %s, 等待打包结束" % html)
        monitor.join()
        return 0

    try:
        import webview
    except Exception as exc:
        core.append_worker_log(name, "pywebview 不可用, 等待打包结束: %s" % exc)
        monitor.join()
        return 0

    api = PackageWorkerApi(name)
    try:
        from functions.base.skin_theme import window_background
        from functions.base.window_chrome import (
            apply_window_chrome, child_window_size, window_icon_path,
        )
    except Exception as exc:
        core.append_worker_log(name, "启动器 UI 模块不可用, 等待打包结束: %s" % exc)
        monitor.join()
        return 0

    win_w, win_h = child_window_size(440, 540)
    min_w, min_h = child_window_size(440, 480)
    try:
        window = webview.create_window(
            "打包 - " + name,
            str(html),
            js_api=api,
            width=win_w,
            height=win_h,
            min_size=(min_w, min_h),
            resizable=False,
            frameless=True,
            easy_drag=False,
            shadow=False,
            background_color=window_background("#0b0e14"),
            on_top=True,
            hidden=True,
        )
    except Exception as exc:
        core.append_worker_log(name, "创建窗口失败, 等待打包结束: %s" % exc)
        monitor.join()
        return 0

    api.attach(window)
    apply_window_chrome(window, title="打包 - " + name, kind="yisang",
                        show_when_ready=True, fallback_ms=1500,
                        resizable=False)
    try:
        webview.start(debug=debug, icon=window_icon_path("yisang"))
    except Exception as exc:
        core.append_worker_log(name, "pywebview 启动失败: %s" % exc)
    finally:
        monitor.join()

    code = proc.poll()
    core.append_worker_log(name, "worker 退出, mod_loader 返回码=%s" % code)
    return 0 if code == 0 else 1
