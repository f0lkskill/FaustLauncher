"""FaustLauncher 可视化构建工具"""
import subprocess, shutil, os, sys, threading, time, queue

ACCENT = '#6366f1'
SUCCESS = '#10b981'
DANGER = '#ef4444'
BG = '#181818'
CARD_BG = '#1f1f23'
TEXT = '#f8fafc'
MUTED = '#94a3b8'
LOG_BG = '#0d0d11'

import tkinter as tk
from tkinter import ttk

_BUILD_STEPS = [
    ('pyinstaller', 'PyInstaller 打包'),
    ('cleanup',    '清理旧构建'),
    ('mkdir',      '创建版本目录'),
    ('build_temp', '复制前置环境'),
    ('assets',     '复制资产文件'),
    ('font',       '重置字体目录'),
    ('config',     '复制配置文件'),
    ('resources',  '复制资源文件'),
    ('docs',       '复制文档文件'),
    ('exe',        '复制可执行文件'),
]


class BuildGUI:
    def __init__(self, version_info):
        self.version_info = version_info
        self.root = tk.Tk()
        self.root.title(f'FaustLauncher 构建工具 — v{version_info}')
        self.root.geometry('600x680')
        self.root.resizable(False, False)
        self.root.configure(bg=BG)
        try:
            self.root.iconbitmap('assets/images/icon/icon.ico')
        except Exception:
            pass
        self._log_queue = queue.Queue()
        self._pyi_ok = False
        self._setup_ui()
        self._center_window()
        self.root.after(100, self._poll_log)
        self.root.after(300, self._start_build)

    def _center_window(self):
        self.root.update_idletasks()
        w, h = 600, 680
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        self.root.geometry(f'{w}x{h}+{(sw-w)//2}+{(sh-h)//2}')

    def _setup_ui(self):
        header = tk.Frame(self.root, bg=BG, height=56)
        header.pack(fill=tk.X, padx=20, pady=(14, 0))
        header.pack_propagate(False)
        tk.Label(header, text='构建 FaustLauncher',
                bg=BG, fg=TEXT, font=('Microsoft YaHei UI', 16, 'bold')).pack(anchor='w')
        tk.Label(header, text=f'目标版本: v{self.version_info}',
                bg=BG, fg=MUTED, font=('Microsoft YaHei UI', 9)).pack(anchor='w')

        card = tk.Frame(self.root, bg=CARD_BG, highlightthickness=1,
                       highlightbackground=self._lighter(CARD_BG, 12))
        card.pack(fill=tk.BOTH, expand=True, padx=20, pady=(10, 2))

        self._step_icons: list[tk.Label] = []
        self._step_labels: list[tk.Label] = []
        for i, (_, name) in enumerate(_BUILD_STEPS):
            row = tk.Frame(card, bg=CARD_BG)
            row.pack(fill=tk.X, padx=14, pady=1)
            icon = tk.Label(row, text='○', bg=CARD_BG, fg=MUTED, font=('Microsoft YaHei UI', 10))
            icon.pack(side=tk.LEFT, padx=(0, 8))
            self._step_icons.append(icon)
            label = tk.Label(row, text=name, bg=CARD_BG, fg=MUTED,
                           font=('Microsoft YaHei UI', 10))
            label.pack(side=tk.LEFT)
            self._step_labels.append(label)

        self._progress = ttk.Progressbar(self.root, mode='determinate', length=560)
        self._progress.pack(padx=20, pady=(4, 0))

        self._status = tk.Label(self.root, text='准备中...', bg=BG, fg=MUTED,
                               font=('Microsoft YaHei UI', 9))
        self._status.pack(pady=(2, 4))

        log_frame = tk.Frame(self.root, bg=BG, height=160)
        log_frame.pack(fill=tk.X, padx=20, pady=(0, 6))
        log_frame.pack_propagate(False)

        log_header = tk.Frame(log_frame, bg=LOG_BG)
        log_header.pack(fill=tk.X)
        tk.Label(log_header, text='构建日志', bg=LOG_BG, fg=MUTED,
                font=('Microsoft YaHei UI', 8)).pack(anchor='w', padx=8, pady=2)

        text_frame = tk.Frame(log_frame, bg=LOG_BG)
        text_frame.pack(fill=tk.BOTH, expand=True)

        self._log_text = tk.Text(text_frame, bg=LOG_BG, fg='#cbd5e1',
                                font=('Consolas', 9), wrap=tk.WORD,
                                relief='flat', bd=0)
        self._log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(6, 0), pady=(0, 4))

        log_scroll = ttk.Scrollbar(text_frame, orient='vertical', command=self._log_text.yview)
        log_scroll.pack(side=tk.RIGHT, fill=tk.Y, pady=(0, 4))
        self._log_text.configure(yscrollcommand=log_scroll.set)

        btn_frame = tk.Frame(self.root, bg=BG)
        btn_frame.pack(pady=(0, 12))
        self._close_btn = tk.Button(btn_frame, text='关闭', command=self.root.destroy,
                                   bg='#334155', fg=TEXT, relief='flat',
                                   font=('Microsoft YaHei UI', 10),
                                   padx=20, pady=6, cursor='hand2',
                                   activebackground='#475569', activeforeground=TEXT)
        self._close_btn.pack()

    def _log(self, text, color=None):
        self._log_queue.put((text, color))

    def _poll_log(self):
        while not self._log_queue.empty():
            text, color = self._log_queue.get_nowait()
            self._log_text.insert(tk.END, text)
            if color:
                start = f'{self._log_text.index(tk.END)}-{len(text)}c'
                end = tk.END
                self._log_text.tag_add(str(id(text)), f'{start} linestart', end)
                self._log_text.tag_config(str(id(text)), foreground=color)
            self._log_text.see(tk.END)
        self.root.after(50, self._poll_log)

    def _start_build(self):
        self._close_btn.configure(text='构建中...', state=tk.DISABLED)
        threading.Thread(target=self._run_all_steps, daemon=True).start()

    def _set_step(self, idx, state):
        m = {'pending': ('○', MUTED), 'running': ('◉', ACCENT),
             'done': ('●', SUCCESS), 'failed': ('✕', DANGER)}
        icon_text, color = m.get(state, ('○', MUTED))
        self.root.after(0, lambda: self._step_icons[idx].configure(text=icon_text, fg=color))
        self.root.after(0, lambda: self._step_labels[idx].configure(
            fg=TEXT if state in ('running', 'done') else
            DANGER if state == 'failed' else MUTED))

    def _set_status(self, text, color=MUTED):
        self.root.after(0, lambda: self._status.configure(text=text, fg=color))

    def _set_progress(self, val):
        self.root.after(0, lambda: self._progress.configure(value=val))

    def _run_pyinstaller(self):
        # 用当前解释器(venv)的 PyInstaller 构建, 避免裸 pyinstaller 命令解析到
        # 其他环境的安装导致 cffi 等扩展模块漏收集(如缺 _cffi_backend)
        p = subprocess.Popen(
            [sys.executable, '-m', 'PyInstaller', '--noconfirm', 'FaustLauncher.spec'],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding='utf-8', errors='replace'
        )
        for line in p.stdout: # type: ignore
            self._log(line)
        p.wait()
        return p.returncode

    def _run_all_steps(self):
        vi = self.version_info

        self._set_step(0, 'running')
        self._set_status('正在运行 PyInstaller...')
        self._set_progress(3)
        try:
            rc = self._run_pyinstaller()
        except Exception as e:
            self._log(f'[PYINSTALLER ERROR] {e}\n', DANGER)
            self._set_step(0, 'failed')
            self._set_status(f'PyInstaller 异常: {e}', DANGER)
            self._on_done(False)
            return
        if rc != 0:
            self._set_step(0, 'failed')
            self._set_status(f'PyInstaller 失败 (code {rc})', DANGER)
            self._on_done(False)
            return
        self._set_step(0, 'done')
        self._set_progress(12)

        # ---- 清理旧构建 ----
        self._set_step(1, 'running')
        self._set_status('清理旧版本文件夹...')
        try:
            shutil.rmtree(f'build_{vi}', ignore_errors=True)
        except Exception:
            pass
        self._set_step(1, 'done')
        self._set_progress(20)

        # ---- 创建版本目录 ----
        self._set_step(2, 'running')
        self._set_status('创建版本目录...')
        os.makedirs(f'build_{vi}', exist_ok=True)
        self._set_step(2, 'done')
        self._set_progress(30)

        # ---- 复制前置环境 ----
        self._set_step(3, 'running')
        self._set_status('复制前置环境...')
        try:
            shutil.copytree('build_temp', f'build_{vi}', dirs_exist_ok=True)
        except Exception as e:
            self._set_step(3, 'failed')
            self._set_status(f'复制 build_temp 失败: {e}', DANGER)
            self._on_done(False)
            return
        self._set_step(3, 'done')
        self._set_progress(38)

        # ---- 复制资产 ----
        self._set_step(4, 'running')
        self._set_status('复制资产文件...')
        try:
            shutil.copytree('assets', f'build_{vi}/assets', dirs_exist_ok=True)
            shutil.copytree('html', f'build_{vi}/html', dirs_exist_ok=True)
        except Exception as e:
            self._set_step(4, 'failed')
            self._set_status(f'复制 assets 失败: {e}', DANGER)
            self._on_done(False)
            return
        self._set_step(4, 'done')
        self._set_progress(46)

        # ---- 重置字体 ----
        self._set_step(5, 'running')
        self._set_status('重置字体目录...')
        try:
            shutil.rmtree(f'build_{vi}/assets/Font', ignore_errors=True)
            os.makedirs(f'build_{vi}/assets/Font', exist_ok=True)
        except Exception:
            pass
        self._set_step(5, 'done')
        self._set_progress(54)

        # ---- 复制配置 ----
        self._set_step(6, 'running')
        self._set_status('复制配置文件...')
        try:
            sys.path.insert(0, '.')
            from functions.base.settings_manager import get_settings_manager
            sm = get_settings_manager()
            sm.reset_all_settings()
        except Exception:
            pass
        try:
            shutil.copytree('config', f'build_{vi}/config', dirs_exist_ok=True)
        except Exception as e:
            self._set_step(6, 'failed')
            self._set_status(f'复制 config 失败: {e}', DANGER)
            self._on_done(False)
            return
        self._set_step(6, 'done')
        self._set_progress(62)

        # ---- 复制资源 ----
        self._set_step(7, 'running')
        self._set_status('复制资源文件...')
        try:
            os.makedirs(f'build_{vi}/resources/7-zip', exist_ok=True)
            if os.path.isdir('resources/7-zip'):
                shutil.copytree('resources/7-zip', f'build_{vi}/resources/7-zip', dirs_exist_ok=True)
        except Exception as e:
            self._set_step(7, 'failed')
            self._set_status(f'复制 resources 失败: {e}', DANGER)
            self._on_done(False)
            return
        self._set_step(7, 'done')
        self._set_progress(74)

        # ---- 复制文档 ----
        self._set_step(8, 'running')
        self._set_status('复制文档...')
        for f in ('LICENSE', 'README.md'):
            try:
                shutil.copy(f, f'build_{vi}/{f}')
            except Exception:
                pass
        self._set_step(8, 'done')
        self._set_progress(86)

        # ---- 复制 exe ----
        self._set_step(9, 'running')
        self._set_status('复制可执行文件...')
        src = 'dist/FaustLauncher/FaustLauncher.exe'
        dst = f'build_{vi}/FaustLauncher.exe'
        if not os.path.exists(src):
            self._set_step(9, 'failed')
            self._set_status(f'未找到 {src}', DANGER)
            self._on_done(False)
            return
        try:
            shutil.copy(src, dst)
        except Exception as e:
            self._set_step(9, 'failed')
            self._set_status(f'复制 exe 失败: {e}', DANGER)
            self._on_done(False)
            return
        # 同步本次构建的 _internal (exe 与内部模块须同源), 覆盖 build_temp 里的旧模板,
        # 避免模板长期未更新导致扩展模块缺失(如 _cffi_backend)
        try:
            shutil.copytree('dist/FaustLauncher/_internal', f'build_{vi}/_internal',
                            dirs_exist_ok=True)
        except Exception as e:
            self._set_step(9, 'failed')
            self._set_status(f'同步 _internal 失败: {e}', DANGER)
            self._on_done(False)
            return
        self._set_step(9, 'done')
        self._set_progress(100)
        self._on_done(True)

    def _on_done(self, success):
        if success:
            self._set_status(f'构建完成! v{self.version_info}', SUCCESS)
            self._set_progress(100)
            self._log(f'\n✔ 构建完成: build_{self.version_info}\n', SUCCESS)
            self._close_btn.configure(text='打开文件夹', state=tk.NORMAL,
               command=lambda: [os.startfile(f'build_{self.version_info}'),
                                self.root.destroy()],
               bg=ACCENT, activebackground='#4f46e5')
        else:
            self._log('\n✕ 构建失败\n', DANGER)
            self._close_btn.configure(text='关闭', state=tk.NORMAL,
                                     command=self.root.destroy,
                                     bg=DANGER, activebackground='#dc2626')
        self.root.after(200, lambda: self.root.attributes('-topmost', True))

    def _lighter(self, hex_color, percent):
        rgb = tuple(int(hex_color[i:i+2], 16) for i in (1, 3, 5))
        l = [min(255, c + int((255 - c) * percent / 100)) for c in rgb]
        return f'#{l[0]:02x}{l[1]:02x}{l[2]:02x}'

    def run(self):
        self.root.mainloop()


if __name__ == '__main__':
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    try:
        from functions.base.settings_manager import get_settings_manager
        st = get_settings_manager()
        st.reset_all_settings()
        st.save_settings()
        vi = st.get_setting('version_info')
    except Exception:
        vi = 'unknown'
    BuildGUI(vi).run()
