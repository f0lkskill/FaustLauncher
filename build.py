"""FaustLauncher 可视化构建工具"""
import subprocess, shutil, os, sys, threading, time, queue
import requests
import json
from datetime import datetime
from functions.base.web_config import get_webnote

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
    ('build_temp', '复制运行环境'),
    ('assets',     '复制资产文件'),
    ('font',       '重置字体目录'),
    ('config',     '复制配置文件'),
    ('resources',  '复制资源文件'),
    ('docs',       '复制文档文件'),
    ('exe',        '复制可执行文件'),
    ('compress',   '压缩打包 zip'),
]


def upload_version_info(address, version, download_url='', log=None): # type: ignore
    """上传版本信息到 webnote。

    规则:
    - 版本号已存在 → 跳过上传
    - 只登记版本号与上传时间; 描述预置空值键, 由开发者到服务器(textdb)上填写
    - download_url 传入时一并登记 (蓝奏云直链解析 URL)
    - 不切换 latest_release_version 标签 (缺失时预置空值键, 由服务器侧填写)

    address: webnote 笔记完整地址(如 FaustLauncher.version_info)
    version: 要登记的版本号(如 V0.6.0-pre.7.fix.2)
    download_url: 下载直链 (可为空)
    log: 可选日志回调(text), 默认 print
    """
    if log is None:
        def log(msg):
            try:
                print(msg, end='')
            except UnicodeEncodeError:
                print(msg.encode(sys.stdout.encoding or 'utf-8', 'replace')
                          .decode(sys.stdout.encoding or 'utf-8'), end='')
    try:
        note_url = f'https://textdb.online/{address}'
        print(f'获取云端版本信息: {note_url}')
        r = requests.get(note_url, verify=False, timeout=20)
        r.raise_for_status()
        if not r.text.strip():
            data = {'versions': {}}
        else:
            data = json.loads(r.text)
        versions = data.get('versions', {})

        if version in versions:
            log(f'⏭ 版本 {version} 已存在于云端版本信息, 跳过上传\n')
            return

        # 新版本插入 dict 最前 (dict 顺序即 JSON 顺序, 保证最新版本在列表顶部)
        new_versions = {version: {
            'data': datetime.now().strftime('%Y-%m-%d-%H:%M:%S'),
            'description': '',
            'url': download_url or '',
        }}
        new_versions.update(versions)
        data['versions'] = new_versions
        # 最新版本标记: 不自动切换, 仅预置空值键供服务器侧填写
        if not data.get('latest_release_version'):
            data['latest_release_version'] = '' # type: ignore
        new_content = json.dumps(data, ensure_ascii=False, indent=4)

        print(f'上传版本信息: {version}')
        ur = requests.post(f'https://textdb.online/update/?key={address}',
                           data={'value': new_content},
                           verify=False, timeout=30)
        result = ur.json()
        if result.get('status') == 1:
            log(f'✔ 版本信息上传成功: {version}\n')
        else:
            log(f'✕ 版本信息上传失败: {result}\n')
    except Exception as e:
        log(f'⚠ 上传版本信息失败(不影响构建结果): {e}\n')


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
        w, h = 600, 740
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

        # 版本信息地址输入框: 填了就用, 留空则回退到 config/web_config.json
        default_addr = get_webnote('version_info')[0]
        addr_row = tk.Frame(self.root, bg=BG)
        addr_row.pack(fill=tk.X, padx=20, pady=(8, 0))
        tk.Label(addr_row, text='版本信息地址:', bg=BG, fg=TEXT,
                font=('Microsoft YaHei UI', 9)).pack(side=tk.LEFT)
        self._version_addr_var = tk.StringVar()
        tk.Entry(addr_row, textvariable=self._version_addr_var, bg=LOG_BG, fg=TEXT,
                insertbackground=TEXT, relief='flat', highlightthickness=1,
                highlightbackground=self._lighter(CARD_BG, 12),
                font=('Consolas', 9)).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(10, 0))
        if default_addr:
            tk.Label(self.root, text=f'留空则使用配置文件地址: {default_addr}',
                    bg=BG, fg=MUTED, font=('Microsoft YaHei UI', 8)).pack(anchor='w', padx=22)
        else:
            tk.Label(self.root, text='未配置版本信息地址, 留空则跳过上传',
                    bg=BG, fg=MUTED, font=('Microsoft YaHei UI', 8)).pack(anchor='w', padx=22)

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
        self._publish_btn = tk.Button(btn_frame, text='上传发布', state=tk.DISABLED,
                                     bg=SUCCESS, fg='#04110b', relief='flat',
                                     font=('Microsoft YaHei UI', 10),
                                     padx=20, pady=6, cursor='hand2',
                                     activebackground='#0d9668', activeforeground='#04110b')
        self._publish_btn.pack(side=tk.LEFT, padx=(0, 8))
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
        # 优先用项目 venv 运行 PyInstaller: 系统 python 可能缺 pystray 等依赖,
        # 导致产物 _internal 缺模块 (旧 build_temp 模板掩盖了该问题, 现已废弃模板)
        py = sys.executable
        venv_py = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               'venv', 'Scripts', 'python.exe')
        if os.path.isfile(venv_py):
            py = venv_py
            self._log(f'· 使用项目 venv 解释器打包: {venv_py}\n')
        else:
            self._log(f'· 未找到项目 venv, 使用当前解释器: {sys.executable}\n')
        p = subprocess.Popen(
            [py, '-m', 'PyInstaller', '--noconfirm', 'FaustLauncher.spec'],
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

        # ---- 复制运行环境 (直接取自 PyInstaller 产物, build_temp 模板机制已废弃) ----
        self._set_step(3, 'running')
        self._set_status('复制运行环境 (来自 dist)...')
        try:
            if not os.path.isdir('dist/FaustLauncher/_internal'):
                raise FileNotFoundError('未找到 dist/FaustLauncher/_internal')
            # 1) PyInstaller 产物 _internal: 与本次 exe 同源的全新环境
            shutil.copytree('dist/FaustLauncher/_internal', f'build_{vi}/_internal',
                            dirs_exist_ok=True)
            # 2) addons/mods 必须为空目录 (插件/模组由用户自行添加, 不随构建分发)
            for d in ('addons', 'mods'):
                os.makedirs(f'build_{vi}/{d}', exist_ok=True)
            # 3) lang: 只创建空汉化目录 (默认零协会 LLC_zh-CN; 翻译数据由云端下载,
            #    changes.json/nav_config.json 等由工具在运行时生成, 均不随构建分发)
            from functions.web_update.translation_source import get_translation_dir
            os.makedirs(f'build_{vi}/{get_translation_dir()}', exist_ok=True)
            # 4) updater.vbs: 版本更新器必备 (由 wscript 运行, 把新版本文件覆盖到安装目录),
            #    仅存于 build_temp 目录, 缺失则构建失败
            if not os.path.isfile('build_temp/updater.vbs'):
                raise FileNotFoundError('未找到 build_temp/updater.vbs (版本更新器必备)')
            shutil.copy('build_temp/updater.vbs', f'build_{vi}/updater.vbs')
            # 5) webFunc: 运行时代码以裸导入 (from webFunc import ...) 使用,
            #    PyInstaller 不会收集为顶层模块, 必须放进 _internal 供 sys.path 解析
            if os.path.isdir('functions/webFunc'):
                shutil.copytree('functions/webFunc', f'build_{vi}/_internal/webFunc',
                                dirs_exist_ok=True)
            # 6) pystray: app_ui 顶层导入, 缺失会导致启动崩溃。纯 Python 模块编入 PYZ,
            #    通过 PYZ-00.toc 校验是否被收集 (旧 build_temp 模板曾掩盖此问题)
            _pyz_toc = os.path.join('build', 'FaustLauncher', 'PYZ-00.toc')
            _pyz_txt = ''
            try:
                with open(_pyz_toc, 'r', encoding='utf-8', errors='replace') as _f:
                    _pyz_txt = _f.read()
            except Exception:
                pass
            if "'pystray'" not in _pyz_txt:
                raise FileNotFoundError('PyInstaller 未收集 pystray (系统托盘不可用), 请用项目 venv 运行本构建工具')
            # 7) webui: pywebview 及平台后端必须被收集 (默认新版 Web 界面启动)
            if "'webview'" not in _pyz_txt:
                raise FileNotFoundError('PyInstaller 未收集 webview (新版 Web 界面无法启动), 请用项目 venv 运行本构建工具')
            if "'cffi'" not in _pyz_txt:
                raise FileNotFoundError('PyInstaller 未收集 cffi (pywebview 依赖缺失), 请用项目 venv 运行本构建工具')
        except Exception as e:
            self._set_step(3, 'failed')
            self._set_status(f'复制运行环境失败: {e}', DANGER)
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
            # 排除 web_config.json: 云端配置由 spec 构建时内嵌进 exe (PYZ), 不以独立文件分发
            shutil.copytree('config', f'build_{vi}/config', dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns('web_config.json'))
        except Exception as e:
            self._set_step(6, 'failed')
            self._set_status(f'复制 config 失败: {e}', DANGER)
            self._on_done(False)
            return
        # webnote 云端配置: 由 FaustLauncher.spec 内嵌进 exe (PYZ), 不随构建产物分发独立文件
        if os.path.exists('config/web_config.json'):
            self._log('✔ web_config.json 已内嵌进 exe (PYZ)，不随构建产物分发\n', SUCCESS)
        else:
            self._log('⚠ 未发现 config/web_config.json, 云端功能将静默降级\n', DANGER)
        self._set_step(6, 'done')
        self._set_progress(62)

        # ---- 复制资源 (仅 7-zip; mod_loader/bubble_speech/llc_babel 等由云端按需下载) ----
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
        self._set_step(9, 'done')
        self._set_progress(92)

        # ---- 压缩打包 zip (顶层 FaustLauncher/, 文件名 FaustLauncher-<版本>.zip) ----
        self._set_step(10, 'running')
        self._set_status('压缩打包 zip...')
        try:
            import zipfile
            folder = f'build_{self.version_info}'
            zip_name = 'FaustLauncher-' + str(self.version_info).lstrip('V')
            zip_path = f'{zip_name}.zip'
            if os.path.exists(zip_path):
                os.remove(zip_path)
            files = []
            dirs = []
            for root, _dirs, fs in os.walk(folder):
                for f in fs:
                    files.append(os.path.join(root, f))
                for d in _dirs:
                    dirs.append(os.path.join(root, d))
            if not files and not dirs:
                raise FileNotFoundError(f'{folder} 为空, 无法打包')
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                # 先写目录条目 (含空目录 addons/mods/lang 等, 解压后结构完整)
                for d in sorted(dirs):
                    arc = os.path.join('FaustLauncher', os.path.relpath(d, folder)).replace('\\', '/') + '/'
                    zf.writestr(arc, '')
                for i, full in enumerate(files):
                    arc = os.path.join('FaustLauncher', os.path.relpath(full, folder)).replace('\\', '/')
                    zf.write(full, arc)
                    if (i + 1) % 200 == 0:
                        self._set_progress(92 + int((i + 1) / len(files) * 8))
            size_mb = os.path.getsize(zip_path) / 1024.0 / 1024.0
            self._log(f'✔ 压缩完成: {zip_path} ({size_mb:.1f} MB)\n', SUCCESS)
            self._zip_path = zip_path
        except Exception as e:
            self._set_step(10, 'failed')
            self._set_status(f'压缩打包失败: {e}', DANGER)
            self._on_done(False)
            return
        self._set_step(10, 'done')
        self._set_progress(100)
        self._on_done(True)

    def _open_build_dir(self):
        """打开压缩为 zip 的原始目录, 供用户自行测试 (窗口与进程不退出)"""
        try:
            os.startfile(f'build_{self.version_info}')
        except Exception as e:
            self._log(f'打开目录失败: {e}\n', DANGER)

    def _publish_release(self):
        """蓝奏云上传 zip 到 FaustLauncher 文件夹 → 直链 → 上传版本信息(附下载链接)"""
        def _run():
            zip_path = getattr(self, '_zip_path', '') or ('FaustLauncher-' + str(self.version_info).lstrip('V') + '.zip')
            if not os.path.isfile(zip_path):
                self._log(f'✕ 未找到压缩包: {zip_path}\n', DANGER)
                return
            try:
                from functions.tools.post_extension_tools import _lanzou_session, PARSER_BASE
                from functions.web_update.lanzou_utils import GetOrCreateFolder, UploadFile
                from functions.base.web_config import get_lanzou_config
                self._log(f'开始发布 {self.version_info} ...\n')
                session = _lanzou_session(self._log)
                self._log('定位蓝奏云文件夹: FaustLauncher\n')
                fid = GetOrCreateFolder(session, 'FaustLauncher')
                if not fid:
                    raise RuntimeError('无法创建/定位蓝奏云文件夹: FaustLauncher')
                max_mb = int(get_lanzou_config().get('max_size_mb') or 66)
                self._log('上传压缩包到蓝奏云...\n')
                ret = UploadFile(session, zip_path, folder_id=fid, max_size_mb=max_mb, # type: ignore
                                 progress_callback=lambda p: self._log(f'  上传 {p * 100:.0f}%\n'))
                if ret.get('status') != 1:
                    raise RuntimeError(f'上传失败: {ret.get("msg")}')
                share = ret.get('share_url') or ''
                url = PARSER_BASE + share
                self._log(f'✔ 上传成功, 直链: {url}\n', SUCCESS)
                # 上传版本信息 (附下载链接)
                address = self._read_version_addr() or get_webnote('version_info')[0]
                if not address:
                    self._log('· 未填写版本信息地址, 跳过版本信息上传\n', MUTED)
                else:
                    upload_version_info(address, self.version_info, download_url=url, log=self._log)
                self._log(f'\n✔ 发布完成! 下载链接: {url}\n', SUCCESS)
            except Exception as e:
                self._log(f'\n✕ 发布失败: {e}\n', DANGER)
        threading.Thread(target=_run, daemon=True).start()

    def _read_version_addr(self):
        """从主线程安全读取版本信息地址输入框的值"""
        event = threading.Event()
        result = {}

        def _get():
            try:
                result['v'] = self._version_addr_var.get().strip()
            except Exception:
                result['v'] = ''
            event.set()

        self.root.after(0, _get)
        event.wait(timeout=2)
        return result.get('v', '')

    def _upload_version_info(self):
        """上传当前版本信息到 webnote, 详见 upload_version_info()。"""
        address = self._read_version_addr() or get_webnote('version_info')[0]
        if not address:
            self._log('· 未填写版本信息地址, 跳过上传\n', MUTED)
            return
        upload_version_info(address, self.version_info, log=self._log)

    def _on_done(self, success):
        if success:
            self._set_status(f'构建完成! v{self.version_info}', SUCCESS)
            self._set_progress(100)
            self._log(f'\n✔ 构建完成: build_{self.version_info}\n', SUCCESS)
            self._log(f'已生成压缩包: {getattr(self, "_zip_path", "")}\n', SUCCESS)
            # 窗口与进程不退出: 打开原始目录供用户自行测试, 并提供"上传发布"按钮
            self._close_btn.configure(text='打开测试目录', state=tk.NORMAL,
                                      command=self._open_build_dir,
                                      bg=ACCENT, activebackground='#4f46e5')
            self._publish_btn.configure(state=tk.NORMAL, command=self._publish_release)
            try:
                os.startfile(f'build_{self.version_info}')
            except Exception:
                pass
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
