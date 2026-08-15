#! Mod 加载器进度提示窗口 (tkinter)
#? 打包 (rebank 差分生成/应用) 期间以阶段式提示 + 实时日志展示加载进度, 美观地替代裸 cmd 窗口
#? 轮询 %APPDATA%/LimbusCompanyMods/loader_progress.txt (loader 侧 progress.py 写入):
#?   - "n|文本"   -> 更新阶段进度
#?   - "LAUNCH"   -> 游戏已启动, 窗口隐藏 (进程常驻, 等待恢复阶段)
#?   - "RESTORE|.."-> 游戏退出、正在恢复原版文件: 窗口重新弹出提示
#?   - "ERROR|.." -> 红色错误提示, 加载器进程退出后自动关闭
#? 同时滚动展示加载器 log.txt 末尾日志 (按 [WARNING]/[ERROR] 着色)
#? 加载器进程 (--pid) 退出后自动关闭, 避免窗口残留
#? 与 Mod管理器同一子进程模式:
#? - 源码模式: 用 pythonw 运行本脚本子进程
#? - 打包模式 (sys.frozen): 用自身 exe 以 --mod-loader-progress 参数二次启动

import os
import subprocess
import sys
import tkinter as tk

if getattr(sys, "frozen", False):
    _PROJECT_ROOT = os.path.dirname(os.path.abspath(sys.executable))
else:
    _PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from functions.base.color_scheme import SemanticColors as C
from functions.base.window_utils import center_window
from functions.base.common.path_utils import get_mod_root_dir

PROGRESS_FILE = os.path.join(get_mod_root_dir(create=False), "loader_progress.txt")
LOG_FILE = os.path.join(get_mod_root_dir(create=False), "log.txt")

BG = '#2b2b2b'
TRACK = '#3f3f3f'
LOG_BG = '#1f1f1f'
FILL = C.ACCENT
FILL_ERROR = '#ff6b6b'
FILL_SUCCESS = C.SUCCESS

HEADER_FG = '#8a8a8a'
STAGE_FG = '#ffffff'
DETAIL_FG = '#a9a9a9'
FOOTER_FG = '#777777'
LOG_FG = '#b8b8b8'
LOG_WARN_FG = '#e8a33d'
LOG_ERR_FG = '#ff6b6b'

FONT_HEADER = ("Microsoft YaHei UI", 8)
FONT_STAGE = ("Microsoft YaHei UI", 12, "bold")
FONT_DETAIL = ("Microsoft YaHei UI", 9)
FONT_FOOTER = ("Microsoft YaHei UI", 8)
FONT_LOG = ("Consolas", 8)

TOTAL_STAGES = 6
LOG_MAX_LINES = 10
POLL_MS = 300
BAR_W = 470


def _pid_alive(pid):
    """进程是否存活 (OpenProcess + GetExitCodeProcess, 避免刚终止进程句柄误判)"""
    if not pid:
        return True
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        h = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
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
        return True


def _read_progress():
    """读取进度文件最后一行"""
    try:
        with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
            lines = [line.strip() for line in f if line.strip()]
        return lines[-1] if lines else ""
    except OSError:
        return ""


def _read_log_tail(max_lines=LOG_MAX_LINES, max_bytes=200000):
    """读取加载器 log.txt 末尾若干行 (utf-8, 失败回退 gbk)"""
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


def _round_rect(canvas, x1, y1, x2, y2, r, fill):
    """圆角矩形 (smooth polygon)"""
    canvas.create_polygon(
        x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
        x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
        x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
        smooth=True, fill=fill, outline=""
    )


class LoaderProgressWindow:
    """状态: loading(加载中) -> launched(游戏运行, 窗口隐藏) -> restoring(恢复文件) -> 关闭"""

    def __init__(self, root, loader_pid):
        self.root = root
        self.pid = loader_pid
        self.state = "loading"
        self._closing = False
        self._last_log_lines = []
        self._pulse_step = 0
        self._build_ui()
        self._poll()

    # ---------- UI ----------

    def _build_ui(self):
        root = self.root
        root.title("Mod 加载器")
        root.configure(bg=BG)
        root.resizable(False, False)
        root.attributes("-topmost", True)

        tk.Label(root, text="FAUST LAUNCHER · MOD 加载", font=FONT_HEADER,
                 bg=BG, fg=HEADER_FG).pack(anchor="w", padx=18, pady=(12, 0))
        self.stage_lbl = tk.Label(root, text="正在启动加载器…", font=FONT_STAGE,
                                  bg=BG, fg=STAGE_FG, anchor="w")
        self.stage_lbl.pack(fill="x", padx=18, pady=(4, 0))
        self.detail_lbl = tk.Label(root, text="", font=FONT_DETAIL,
                                   bg=BG, fg=DETAIL_FG, anchor="w")
        self.detail_lbl.pack(fill="x", padx=18, pady=(2, 0))

        self.canvas = tk.Canvas(root, width=BAR_W, height=14, bg=BG, highlightthickness=0)
        self.canvas.pack(padx=18, pady=(6, 14))

        log_frame = tk.Frame(root, bg=BG)
        log_frame.pack(fill="both", expand=True, padx=18, pady=(0, 10))
        tk.Label(log_frame, text="处理日志", font=FONT_FOOTER,
                 bg=BG, fg=FOOTER_FG).pack(anchor="w")
        self.log_text = tk.Text(log_frame, height=6, bg=LOG_BG, fg=LOG_FG,
                                font=FONT_LOG, relief="flat", borderwidth=0,
                                padx=8, pady=6, state="disabled",
                                wrap="char", cursor="arrow", highlightthickness=0)
        self.log_text.pack(fill="both", expand=True, pady=(3, 0))
        self.log_text.tag_config("warn", foreground=LOG_WARN_FG)
        self.log_text.tag_config("err", foreground=LOG_ERR_FG)

    def _draw_bar(self, fraction, color):
        c = self.canvas
        c.delete("all")
        _round_rect(c, 0, 0, BAR_W, 14, 7, TRACK)
        w = int((BAR_W - 4) * max(0.0, min(1.0, fraction)))
        if w > 2:
            _round_rect(c, 2, 2, 2 + w, 12, 5, color)

    def _set_error(self, message):
        self.stage_lbl.config(text="加载出错", fg=FILL_ERROR)
        self.detail_lbl.config(text=message, fg=DETAIL_FG)
        self._draw_bar(1.0, FILL_ERROR)

    def _update_log(self):
        lines = _read_log_tail()
        if lines == self._last_log_lines:
            return
        self._last_log_lines = lines
        t = self.log_text
        t.config(state="normal")
        t.delete("1.0", "end")
        for ln in lines:
            if "[WARNING]" in ln:
                tag = "warn"
            elif "[ERROR]" in ln:
                tag = "err"
            else:
                tag = "info"
            t.insert("end", ln + "\n", tag)
        t.config(state="disabled")
        t.see("end")

    def _finish(self, text, delay_ms):
        """显示结束语并延迟关闭 (只触发一次)"""
        if self._closing:
            return
        self._closing = True
        self.root.deiconify()
        self.root.attributes("-topmost", True)
        self.root.lift()
        self.stage_lbl.config(text=text, fg=STAGE_FG)
        self.detail_lbl.config(text="", fg=DETAIL_FG)
        self._draw_bar(1.0, FILL_SUCCESS)
        self.root.after(delay_ms, self.root.destroy)

    def _pulse(self):
        """恢复阶段不定进度动画"""
        if self.state != "restoring":
            return
        t = (self._pulse_step % 40) / 40.0
        frac = 0.15 + 0.7 * abs(t * 2 - 1)
        self._draw_bar(frac, FILL)
        self._pulse_step += 1
        self.root.after(80, self._pulse)

    # ---------- 轮询 ----------

    def _poll(self):
        try:
            self._tick()
        except Exception:
            import traceback
            try:
                with open(os.path.join(_PROJECT_ROOT, "mod_loader_progress_error.log"), "a", encoding="utf-8") as f:
                    f.write("poll tick error:\n" + traceback.format_exc())
            except Exception:
                pass
        if not self._closing:
            self.root.after(POLL_MS, self._poll)

    def _tick(self):
        content = _read_progress()
        pid_alive = _pid_alive(self.pid)

        # 游戏启动 -> 窗口隐藏, 常驻等待恢复阶段
        if content == "LAUNCH":
            if self.state == "loading":
                self.state = "launched"
                self.stage_lbl.config(text="启动游戏", fg=STAGE_FG)
                self.detail_lbl.config(text="游戏运行中，游戏退出后将自动恢复原版文件", fg=DETAIL_FG)
                self._draw_bar(1.0, FILL_SUCCESS)
                self.root.withdraw()
            self._update_log()
            if not pid_alive:
                self._finish("加载器已退出，原版文件已恢复", 2500)
            return

        # 游戏退出、恢复原版文件 -> 重新弹出提示
        if content.startswith("RESTORE"):
            if self.state != "restoring":
                self.state = "restoring"
                self.root.deiconify()
                self.root.attributes("-topmost", True)
                self.root.lift()
                self.stage_lbl.config(text="正在恢复文件…", fg=STAGE_FG)
                self.detail_lbl.config(text="游戏已退出，正在把原版文件写回游戏目录", fg=DETAIL_FG)
                self._pulse()
            self._update_log()
            if not pid_alive:
                self._finish("恢复完成", 900)
            return

        if content.startswith("ERROR|"):
            if not self._closing:
                self._set_error(content[6:])
                if self.state == "launched":
                    self.root.deiconify()
                    self.root.lift()
                if not pid_alive:
                    self._finish("加载器已退出", 2500)
            return

        if "|" in content and self.state == "loading":
            n, text = content.split("|", 1)
            try:
                stage_no = max(1, min(int(n), TOTAL_STAGES))
            except ValueError:
                stage_no = 1
            self.stage_lbl.config(text=text or "加载中…", fg=STAGE_FG)
            self._draw_bar(stage_no / TOTAL_STAGES, FILL)
            self._update_log()
            return

        # 游戏运行中 (窗口隐藏): 加载器异常退出时提示
        if self.state == "launched":
            self._update_log()
            if not pid_alive:
                self._finish("加载器已退出，原版文件可能未恢复", 2500)
            return

        if not pid_alive:
            if not self._closing:
                self._finish("加载器已退出", 1200)
            return

        # 初始状态: 进度文件尚未写入
        self._draw_bar(0.05, FILL)
        self._update_log()


def _set_window_icon(root):
    """设置窗口图标: 启动器以 cwd=项目根目录 拉起本窗口, 优先按 cwd 找 icon.png"""
    try:
        path = os.path.join(os.getcwd(), "assets", "images", "icon", "icon.png")
        if not os.path.isfile(path):
            path = os.path.join(_PROJECT_ROOT, "assets", "images", "icon", "icon.png")
        if os.path.isfile(path):
            img = tk.PhotoImage(file=path)
            root.iconphoto(True, img)
            root._icon_img = img  # 防止被垃圾回收
    except Exception:
        pass


def run_mod_loader_progress(loader_pid=0, debug=False):
    """子进程入口: 运行进度提示窗口"""
    try:
        root = tk.Tk()
        _set_window_icon(root)
        root.withdraw()
        LoaderProgressWindow(root, loader_pid)
        center_window(root)
        root.mainloop()
    except BaseException as e:
        import traceback
        try:
            with open(os.path.join(_PROJECT_ROOT, "mod_loader_progress_error.log"), "a", encoding="utf-8") as f:
                f.write(traceback.format_exc())
        except Exception:
            pass
        import ctypes
        try:
            ctypes.windll.user32.MessageBoxW(
                None, f"进度窗口启动失败:\n{type(e).__name__}: {e}", "Mod 加载器", 0x10)
        except Exception:
            pass
        raise SystemExit(1)


def open_mod_loader_progress(loader_pid):
    """非阻塞拉起进度提示窗口 (与 Mod管理器同一模式, 立即返回)

    Returns:
        True: 窗口成功拉起; None: 拉起失败
    """
    if getattr(sys, "frozen", False):
        cmd = [os.path.abspath(sys.executable), "--mod-loader-progress", "--pid", str(loader_pid)]
    else:
        script = os.path.join(_PROJECT_ROOT, "functions", "pages", "tools", "mod_loader_progress.py")
        if not os.path.exists(script):
            print("[Mod加载器] 找不到进度窗口脚本, 已跳过")
            return None
        pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
        if not os.path.exists(pythonw):
            pythonw = sys.executable
        cmd = [pythonw, script, "--pid", str(loader_pid)]

    try:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.Popen(cmd, cwd=_PROJECT_ROOT, creationflags=flags)
    except Exception as e:
        print(f"[Mod加载器] 无法启动进度窗口进程: {e}")
        return None
    return True


if __name__ == "__main__":
    pid = 0
    if "--pid" in sys.argv:
        idx = sys.argv.index("--pid")
        if idx + 1 < len(sys.argv):
            try:
                pid = int(sys.argv[idx + 1])
            except ValueError:
                pid = 0
    run_mod_loader_progress(pid, debug="--debug" in sys.argv)