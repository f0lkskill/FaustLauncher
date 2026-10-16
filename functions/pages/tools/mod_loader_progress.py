#! Mod 加载器进度提示窗口 (tkinter)

import os
import subprocess
import sys
import json
import tkinter as tk

try:
    from PIL import Image, ImageTk
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

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
THREADS_FILE = os.path.join(get_mod_root_dir(create=False), "loader_threads.txt")
LOG_FILE = os.path.join(get_mod_root_dir(create=False), "log.txt")

ICON_FILE = os.path.join(_PROJECT_ROOT, "resources", "mod_loader", "_internal", "assets", "icon.png")
if not os.path.isfile(ICON_FILE):
    ICON_FILE = os.path.join(_PROJECT_ROOT, "assets", "images", "icon", "icon.png")

BG = "#2a2a2a"
BG_PANEL = "#1B1B1B"
BG_LOGS = "#1B1B1B"
BORDER = "#444444"

FG_TITLE = '#89b4fa'
FG_STAGE = '#cdd6f4'
FG_DETAIL = '#a6adc8'
FG_FOOTER = '#7f849c'

LOG_FG = '#cdd6f4'
LOG_WARN_FG = '#f9e2af'
LOG_ERR_FG = '#f38ba8'
LOG_SUCCESS_FG = '#a6e3a1'

THREAD_NAME_FG = '#cdd6f4'
THREAD_STAGE_FG = '#89b4fa'
THREAD_DESC_FG = '#a6adc8'
THREAD_BG = '#2a2a3c'
THREAD_BG_ALT = '#313244'

TOTAL_STAGES = 6
LOG_MAX_LINES = 14
POLL_MS = 300

def _pick_font(candidates):
    try:
        import tkinter.font as tkfont
        available = set(tkfont.families())
        for fam in candidates:
            if fam in available:
                return fam
    except Exception:
        pass
    return candidates[0]

MONO_FONT = _pick_font(["Cascadia Mono", "Cascadia Code", "Consolas", "Courier New"])
UI_FONT = _pick_font(["Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI", "PingFang SC"])

FONT_HEADER = (UI_FONT, 8, "bold")
FONT_STAGE = (UI_FONT, 12, "bold")
FONT_DETAIL = (UI_FONT, 8)
FONT_FOOTER = (UI_FONT, 8)
FONT_LOG = (MONO_FONT, 8)
FONT_THREAD = (MONO_FONT, 8)
FONT_THREAD_NAME = (UI_FONT, 8, "bold")

def _pid_alive(pid):
    if not pid:
        return True
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        h = k32.OpenProcess(0x1000, False, pid)
        if not h:
            return False
        try:
            code = ctypes.c_ulong()
            if k32.GetExitCodeProcess(h, ctypes.byref(code)) and code.value == 259:
                return True
            return False
        finally:
            k32.CloseHandle(h)
    except Exception:
        return True

def _read_progress():
    try:
        with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
            lines = [line.strip() for line in f if line.strip()]
        return lines[-1] if lines else ""
    except OSError:
        return ""

def _read_threads():
    try:
        with open(THREADS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data
    except (OSError, ValueError):
        return {}

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

def _is_success_log(line: str) -> bool:
    lower = line.lower()
    success_keywords = [
        "* 修补完成", "* 完成", "* 备份", "已恢复",
        "已完成", "已应用", "已生成", "已删除", "已清理",
    ]
    for kw in success_keywords:
        if kw in line:
            return True
    return False

def _load_header_icon(size=24):
    if not HAS_PIL or not os.path.isfile(ICON_FILE):
        return None
    try:
        img = Image.open(ICON_FILE)
        img = img.convert("RGBA")
        img.thumbnail((size, size), Image.LANCZOS) # type: ignore
        return ImageTk.PhotoImage(img)
    except Exception:
        return None

class LoaderProgressWindow:

    def __init__(self, root, loader_pid):
        self.root = root
        self.pid = loader_pid
        self.state = "loading"
        self._closing = False
        self._last_log_lines = []
        self._last_threads_state = None
        self._header_icon = None
        self._build_ui()
        self._poll()

    def _build_ui(self):
        import random

        root = self.root
        root.title("Mod 加载器")
        root.configure(bg=BG)
        root.resizable(False, False)
        root.geometry("440x540")
        root.attributes("-topmost", True)

        yisang_sayings = [
            "将鸟字抹去一点，乌鸦俯瞰大地。",
            "斗争者是过去未曾斗争过的人，同时斗争者也是不斗争之人。",
            "我就像失去了魂魄一般随波逐流，并静悄悄地流下了泪水。",
            "我就像被水流摆弄的毒蛇一样被固定在地平，再也无法动弹。"
        ]

        header_bar = tk.Frame(root, bg=BG)
        header_bar.pack(fill="x", padx=16, pady=(10, 0))
        tk.Label(header_bar, text="李箱正在努力加载 MOD...", font=FONT_STAGE,
                 bg=BG, fg=FG_TITLE).pack(side="left")
        right_side = tk.Frame(header_bar, bg=BG)
        right_side.pack(side="right")
        tk.Label(right_side, text=random.choice(yisang_sayings)[:15]+'...', font=FONT_FOOTER,
                 bg=BG, fg=FG_FOOTER).pack(side="left")
        self._header_icon = _load_header_icon(20)
        if self._header_icon is not None:
            tk.Label(right_side, image=self._header_icon,
                     bg=BG).pack(side="left", padx=(3, 0))

        tk.Frame(root, bg=BORDER, height=1).pack(fill="x", padx=16, pady=(8, 0))

        self.stage_lbl = tk.Label(root, text="正在启动加载器…", font=FONT_STAGE,
                                  bg=BG, fg=FG_STAGE, anchor="w")
        self.stage_lbl.pack(fill="x", padx=16, pady=(8, 0))
        self.detail_lbl = tk.Label(root, text="", font=FONT_DETAIL,
                                   bg=BG, fg=FG_DETAIL, anchor="w")
        self.detail_lbl.pack(fill="x", padx=16, pady=(0, 0))

        threads_frame = tk.Frame(root, bg=BG)
        threads_frame.pack(fill="x", padx=16, pady=(8, 0))
        self._threads_header = tk.Label(threads_frame, text="活跃任务 (0)", font=FONT_FOOTER,
                                        bg=BG, fg=FG_FOOTER, anchor="w")
        self._threads_header.pack(fill="x")

        list_wrap = tk.Frame(threads_frame, bg=BG_PANEL,
                             highlightbackground=BORDER, highlightthickness=1)
        list_wrap.pack(fill="x", pady=(4, 0))
        self._threads_canvas = tk.Canvas(list_wrap, bg=BG_PANEL,
                                         highlightthickness=0, height=120)
        self._threads_scrollbar = tk.Scrollbar(list_wrap, orient="vertical",
                                               command=self._threads_canvas.yview,
                                               bg=BG_PANEL, troughcolor=BG_PANEL,
                                               bd=0, highlightthickness=0, width=6)
        self._threads_canvas.configure(yscrollcommand=self._threads_scrollbar.set)
        self._threads_scrollbar.pack(side="right", fill="y")
        self._threads_canvas.pack(side="left", fill="both", expand=True)

        self._threads_inner = tk.Frame(self._threads_canvas, bg=BG_PANEL)
        self._threads_window = self._threads_canvas.create_window(
            (0, 0), window=self._threads_inner, anchor="nw")
        self._threads_inner.bind("<Configure>", self._on_threads_configure)
        self._threads_canvas.bind(
            "<Configure>",
            lambda e: self._threads_canvas.itemconfig(self._threads_window, width=e.width))
        self._thread_widgets = {}

        log_frame = tk.Frame(root, bg=BG)
        log_frame.pack(fill="both", expand=True, padx=16, pady=(8, 12))
        tk.Label(log_frame, text="处理日志", font=FONT_FOOTER,
                 bg=BG, fg=FG_FOOTER).pack(anchor="w")
        self.log_text = tk.Text(log_frame, height=8, bg=BG_LOGS, fg=LOG_FG,
                                font=FONT_LOG, relief="flat", borderwidth=0,
                                padx=8, pady=6, state="disabled",
                                wrap="char", cursor="arrow", highlightthickness=0)
        self.log_text.pack(fill="both", expand=True, pady=(4, 0))
        self.log_text.tag_config("warn", foreground=LOG_WARN_FG)
        self.log_text.tag_config("err", foreground=LOG_ERR_FG)
        self.log_text.tag_config("ok", foreground=LOG_SUCCESS_FG)

    def _on_threads_configure(self, event):
        self._threads_canvas.configure(scrollregion=self._threads_canvas.bbox("all"))

    def _set_error(self, message):
        self.stage_lbl.config(text="加载出错", fg=LOG_ERR_FG)
        self.detail_lbl.config(text=message, fg=FG_DETAIL)

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
            elif _is_success_log(ln):
                tag = "ok"
            else:
                tag = "info"
            t.insert("end", ln + "\n", tag)
        t.config(state="disabled")
        t.see("end")

    def _update_threads(self):
        threads = _read_threads()
        stable = json.dumps(threads, sort_keys=True, ensure_ascii=False)
        if stable == self._last_threads_state:
            return
        self._last_threads_state = stable

        current_names = set(threads.keys())
        existing_names = set(self._thread_widgets.keys())

        for name in list(existing_names - current_names):
            widgets = self._thread_widgets.pop(name, None)
            if widgets:
                widgets["frame"].destroy()

        idx = 0
        for name, info in threads.items():
            stage = info.get("stage", "")
            desc = info.get("description", "")
            status = info.get("status", "running")
            if status == "running":
                spinner = "●" if idx % 2 == 0 else "○"
            else:
                spinner = "✓"
            display_name = f"{spinner} {name}"
            if name in self._thread_widgets:
                widgets = self._thread_widgets[name]
                widgets["name_lbl"].config(text=display_name, fg=THREAD_NAME_FG)
                widgets["stage_lbl"].config(text=stage, fg=THREAD_STAGE_FG)
                widgets["desc_lbl"].config(text=desc, fg=THREAD_DESC_FG)
            else:
                bg = THREAD_BG if idx % 2 == 0 else THREAD_BG_ALT
                frame = tk.Frame(self._threads_inner, bg=bg)
                frame.pack(fill="x", padx=1, pady=0)
                name_lbl = tk.Label(frame, text=display_name, font=FONT_THREAD_NAME,
                                    bg=bg, fg=THREAD_NAME_FG, anchor="w", width=22)
                name_lbl.pack(side="left", padx=(6, 2), pady=1)
                stage_lbl = tk.Label(frame, text=stage, font=FONT_THREAD,
                                     bg=bg, fg=THREAD_STAGE_FG, anchor="w", width=11)
                stage_lbl.pack(side="left", padx=2, pady=1)
                desc_lbl = tk.Label(frame, text=desc, font=FONT_THREAD,
                                    bg=bg, fg=THREAD_DESC_FG, anchor="w")
                desc_lbl.pack(side="left", fill="x", expand=True, padx=(2, 6), pady=1)
                self._thread_widgets[name] = {
                    "frame": frame,
                    "name_lbl": name_lbl,
                    "stage_lbl": stage_lbl,
                    "desc_lbl": desc_lbl,
                }
            idx += 1

        active_count = sum(
            1 for v in threads.values()
            if v.get("status") in ("running", "waiting")
        )
        count = len(current_names)
        if active_count:
            header_text = f"活跃任务 ({active_count})"
        else:
            header_text = f"活跃任务 ({count})" + (f" · 等待" if count == 0 else "")
        self._threads_header.config(text=header_text)

    def _finish(self, text, delay_ms):
        if self._closing:
            return
        self._closing = True
        self.root.deiconify()
        self.root.attributes("-topmost", True)
        self.root.lift()
        self.stage_lbl.config(text=text, fg=FG_STAGE)
        self.detail_lbl.config(text="", fg=FG_DETAIL)
        self.root.after(delay_ms, self.root.destroy)

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

        if content == "LAUNCH":
            if not self._closing and self.state != "launched":
                self.state = "launched"
                self.stage_lbl.config(text="启动游戏", fg=FG_STAGE)
                self.detail_lbl.config(text="游戏运行中，游戏退出后将自动恢复原版文件", fg=FG_DETAIL)
                self.root.withdraw()
            self._update_log()
            self._update_threads()
            if not pid_alive:
                self._finish("加载器已退出，原版文件已恢复", 2500)
            return

        if content.startswith("RESTORE"):
            if self.state != "loading" and self.state != "restoring" and not self._closing:
                self.state = "restoring"
                self.root.deiconify()
                self.root.attributes("-topmost", True)
                self.root.lift()
                self.stage_lbl.config(text="正在恢复文件…", fg=FG_STAGE)
                self.detail_lbl.config(text="游戏已退出，正在把原版文件写回游戏目录", fg=FG_DETAIL)
            self._update_log()
            self._update_threads()
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
            parts = content.split("|")
            try:
                stage_no = max(1, min(int(parts[0]), TOTAL_STAGES))
            except ValueError:
                stage_no = 1
            text = "|".join(parts[1:])
            self.stage_lbl.config(text=text or "加载中…", fg=FG_STAGE)
            self._update_log()
            self._update_threads()
            return

        if self.state == "launched":
            self._update_log()
            self._update_threads()
            if not pid_alive:
                self._finish("加载器已退出，原版文件可能未恢复", 2500)
            return

        if not pid_alive:
            if not self._closing:
                self._finish("加载器已退出", 1200)
            return

        self._update_log()
        self._update_threads()

def _set_window_icon(root):
    try:
        path = os.path.join(os.getcwd(), "assets", "images", "icon", "icon.png")
        if not os.path.isfile(path):
            path = os.path.join(_PROJECT_ROOT, "assets", "images", "icon", "icon.png")
        if os.path.isfile(path):
            img = tk.PhotoImage(file=path)
            root.iconphoto(True, img)
            root._icon_img = img
    except Exception:
        pass

def run_mod_loader_progress(loader_pid=0, debug=False):
    try:
        from functions.pages.tools.mod_loader_web import run_mod_loader_web
        if run_mod_loader_web(loader_pid, debug=debug):
            return
    except Exception as e:
        print(f"[Mod加载器] Web 版加载页不可用, 回退 tkinter 版: {e}")
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
