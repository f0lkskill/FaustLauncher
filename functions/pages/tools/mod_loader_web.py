"""Mod 加载器进度窗口 —— Web 版 (pywebview)

替代原 tkinter 版 (functions/pages/tools/mod_loader_progress.py):

* 界面在 ``web/mod_loader/`` (HTML/CSS/JS), 与其它子窗口共用
  ``web/shared/theme.css`` 设计令牌, 皮肤 (web/app_skins/<id>) 通过
  ``functions.base.skin_theme`` 注入, 所以加载窗口和主界面是同一套外观。
* 数据源不变: mod 目录下的 ``loader_progress.txt`` / ``loader_threads.txt`` / ``log.txt``
* 流畅性的关键: 前端每 200ms 拉一次 ``get_state()``, **只更新变化的 DOM 节点**
  (tkinter 版是每 300ms 把日志 Text 整块 delete + 重新 insert, 那是卡顿的根源),
  进度条 / 阶段 / 线程行都有 CSS 过渡, 不会跳变。

窗口生命周期 (与原 tkinter 版语义一致):
    阶段推进  -> 显示窗口, 渲染阶段 / 线程 / 日志
    LAUNCH    -> 短暂展示"游戏已启动", 随后隐藏窗口 (不打扰游戏), 后台继续轮询
    RESTORE   -> 游戏退出后重新显示, 提示"正在恢复原版文件"
    ERROR     -> 显示错误并提供关闭
    loader 进程结束 -> 窗口自动销毁, 本进程退出
"""
from __future__ import annotations

import json
import os
import time

from functions.base.common.path_utils import get_mod_root_dir, get_web_root
from functions.base.skin_theme import SkinBridge, apply_theme_to_window, window_background

# ---- 文件 ----
PROGRESS_FILE = os.path.join(get_mod_root_dir(create=False), "loader_progress.txt")
THREADS_FILE = os.path.join(get_mod_root_dir(create=False), "loader_threads.txt")
LOG_FILE = os.path.join(get_mod_root_dir(create=False), "log.txt")

ICON_FILE = get_web_root("app", "assets", "icon", "icon.png")

TOTAL_STAGES = 6
# 阶段标题: 与 resources/mod_loader/_internal 里的 progress.stage(n, ...) 对应。
# 阶段 3 目前加载器侧没有显式调用, 保留占位以免序号错位。
STAGE_TITLES = {
    1: "恢复原版音效",
    2: "检测模组",
    3: "准备资源",
    4: "备份并修补游戏资源",
    5: "处理音效差分",
    6: "启动游戏",
}

LOG_MAX_LINES = 200
# loader 进程 pid 拿不到时 (解析失败/传 0) 的兜底: 超过这个时长没有进度更新就收工
NO_PID_IDLE_TIMEOUT = 90.0


# ============================================================
# 数据读取 (纯文件, 不依赖 tkinter)
# ============================================================
def _pid_alive(pid):
    """loader 进程是否存活 (OpenProcess + GetExitCodeProcess)"""
    if not pid:
        return True
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        h = k32.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        try:
            code = ctypes.c_ulong()
            if k32.GetExitCodeProcess(h, ctypes.byref(code)) and code.value == 259:  # STILL_ACTIVE
                return True
            return False
        finally:
            k32.CloseHandle(h)
    except Exception:
        # 非 Windows / ctypes 不可用时保守认为存活 (由兜底超时收尾)
        return True


def _read_progress_raw():
    """进度文件只有一行 (加载器每次覆盖写), 返回原始文本"""
    try:
        with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def _parse_progress(raw: str):
    """解析进度标记 -> (kind, stage_no, stage_text)"""
    if not raw:
        return "", 0, ""
    if raw == "LAUNCH":
        return "launch", TOTAL_STAGES, "游戏已启动"
    if raw.startswith("RESTORE"):
        return "restore", TOTAL_STAGES, (raw.split("|", 1)[1].strip() if "|" in raw else "正在恢复原版文件…")
    if raw.startswith("ERROR"):
        return "error", 0, (raw.split("|", 1)[1].strip() if "|" in raw else "加载失败")
    if "|" in raw:
        head, _sep, tail = raw.partition("|")
        if head.strip().isdigit():
            return "stage", int(head.strip()), tail.strip()
    return "unknown", 0, raw


def _read_threads():
    """线程状态 JSON (OrderedDict 顺序保留) -> list"""
    try:
        with open(THREADS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return []
    if not isinstance(data, dict):
        return []
    out = []
    for name, info in data.items():
        info = info if isinstance(info, dict) else {}
        out.append({
            "name": str(name),
            "status": str(info.get("status") or "running"),
            "stage": str(info.get("stage") or ""),
            "description": str(info.get("description") or ""),
        })
    return out


def _log_level(line: str) -> str:
    low = line.lower()
    if "错误" in line or "失败" in line or "error" in low or "traceback" in low:
        return "error"
    if "警告" in line or "warn" in low:
        return "warning"
    for kw in ("* 修补完成", "* 完成", "* 备份", "已恢复", "已完成", "已应用", "已生成", "已删除", "已清理", "成功"):
        if kw in line:
            return "success"
    return "info"


def _read_log_tail(max_lines=LOG_MAX_LINES, max_bytes=200000):
    try:
        size = os.path.getsize(LOG_FILE)
        with open(LOG_FILE, "rb") as f:
            f.seek(max(0, size - max_bytes))
            data = f.read()
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            text = data.decode("gbk", errors="replace")
        lines = [ln for ln in text.splitlines() if ln.strip()]
        return lines[-max_lines:]
    except OSError:
        return []


def _icon_data_uri():
    """标题图标 (base64 data URI, 失败返回空)"""
    try:
        import base64
        if os.path.isfile(ICON_FILE):
            with open(ICON_FILE, "rb") as f:
                return "data:image/png;base64," + base64.b64encode(f.read()).decode("ascii")
    except Exception:
        pass
    return ""


# ============================================================
# js_api
# ============================================================
class ModLoaderApi(SkinBridge):
    """前端唯一的后端接口: 轮询 get_state() 拿全部状态"""

    def __init__(self, loader_pid=0):
        self._pid = int(loader_pid or 0)
        self._window = None
        self._t0 = time.time()
        self._last_change = time.time()
        self._last_raw = None
        self._hidden = False
        self._finished = False
        self._icon = ""
        self._eval_ok = True

    # ---- 内部 ----
    def attach(self, window):
        self._window = window
        try:
            self._icon = _icon_data_uri()
        except Exception:
            self._icon = ""

    def _call_window(self, fn, *args):
        if not self._window or not self._eval_ok:
            return False
        try:
            getattr(self._window, fn)(*args)
            return True
        except Exception as e:
            self._eval_ok = False
            print(f"[Mod加载器] 窗口操作 {fn} 失败: {e}")
            return False

    def _finish(self):
        """loader 结束: 标记完成并关闭窗口 (由前端渲染最后一帧后调用 close)"""
        if self._finished:
            return
        self._finished = True
        if not self._hidden:
            self._call_window("show")
        self._call_window("destroy")

    # ---- 前端调用 ----
    def get_state(self):
        raw = _read_progress_raw()
        if raw != self._last_raw:
            self._last_raw = raw
            self._last_change = time.time()
        kind, stage_no, stage_text = _parse_progress(raw)
        alive = _pid_alive(self._pid)

        # 阶段状态
        done_upto = 0
        if kind in ("launch", "restore"):
            done_upto = TOTAL_STAGES
        elif kind == "stage":
            done_upto = max(0, stage_no - 1)

        stages = []
        for i in range(1, TOTAL_STAGES + 1):
            if i <= done_upto:
                st = "done"
            elif kind == "stage" and i == stage_no:
                st = "active"
            elif kind == "error" and i == max(1, stage_no):
                st = "error"
            else:
                st = "pending"
            stages.append({"n": i, "title": STAGE_TITLES.get(i, "阶段 %d" % i), "state": st})

        pct = 100.0 if kind in ("launch", "restore") else (max(0.0, (done_upto + (0.5 if kind == "stage" else 0)) / TOTAL_STAGES * 100.0))

        # ---- 窗口生命周期 ----
        if not alive:
            self._finish()
        elif kind == "launch" and not self._hidden:
            self._hidden = True
            self._call_window("hide")   # 游戏已起来, 窗口退到后台不打扰
        elif kind == "restore" and self._hidden:
            self._hidden = False
            self._call_window("show")
        elif self._pid <= 0:
            # pid 未知: 没有进度变化太久就自动收工, 避免窗口永远留在桌面上
            if time.time() - self._last_change > NO_PID_IDLE_TIMEOUT and kind in ("", "launch", "unknown"):
                self._finish()

        return {
            "pid": self._pid,
            "alive": alive,
            "kind": kind,
            "stage_no": stage_no,
            "stage_text": stage_text,
            "stages": stages,
            "pct": round(pct, 1),
            "threads": _read_threads(),
            "log": [{"text": ln, "level": _log_level(ln)} for ln in _read_log_tail()],
            "elapsed_ms": int((time.time() - self._t0) * 1000),
            "icon": self._icon,
            "done": kind in ("launch", "restore"),
            "error": stage_text if kind == "error" else "",
        }

    def close(self):
        """用户点击关闭按钮"""
        self._call_window("destroy")
        return True


# ============================================================
# 子进程入口
# ============================================================
def run_mod_loader_web(loader_pid=0, debug=False):
    """运行 Web 版进度窗口

    Returns:
        True: 正常跑完 (窗口被关闭); False: 环境不支持 (调用方回退 tkinter 版)
    """
    try:
        import webview
    except Exception as e:
        print(f"[Mod加载器] 未安装 pywebview, 回退 tkinter 版: {e}")
        return False

    html = get_web_root("mod_loader", "index.html")
    if not os.path.isfile(html):
        print(f"[Mod加载器] 找不到加载页 {html}, 回退 tkinter 版")
        return False

    api = ModLoaderApi(loader_pid)
    try:
        window = webview.create_window(
            "Mod 加载器",
            html,
            js_api=api,
            width=660,
            height=540,
            min_size=(560, 440),
            background_color=window_background("#0b0e14"),
            on_top=True,
            hidden=True,
        )
    except Exception as e:
        print(f"[Mod加载器] 创建窗口失败, 回退 tkinter 版: {e}")
        return False

    api.attach(window)
    apply_theme_to_window(window, show_when_ready=True, fallback_ms=1500)
    try:
        webview.start(debug=debug)
    except Exception as e:
        print(f"[Mod加载器] pywebview 启动失败: {e}")
        return False
    return True


if __name__ == "__main__":
    import sys
    pid = 0
    if "--pid" in sys.argv:
        idx = sys.argv.index("--pid")
        if idx + 1 < len(sys.argv):
            try:
                pid = int(sys.argv[idx + 1])
            except ValueError:
                pid = 0
    if not run_mod_loader_web(pid, debug="--debug" in sys.argv):
        from functions.pages.tools.mod_loader_progress import run_mod_loader_progress
        run_mod_loader_progress(pid, debug="--debug" in sys.argv)
