#! 扩展工具: 生成插件模板 / 包装 Mod
#? 两种模式:
#? - 生成插件模板: 在软件目录 addons/ 下生成 插件名/ 目录, 含 空的 scr.py + 生成的 icon.png + 模板 addon_info.json
#? - 包装 Mod: 选择原始文件夹(须含 Installer.bat / Assets 文件夹 / Uninstaller.bat),
#?   复制到软件目录 mods/ 下, 自动生成 icon.png 与 mod_info.json (file_names 自动扫描 .bank/.carra2)

import json
import os
import shutil
import tkinter as tk
from tkinter import filedialog, messagebox

from PIL import Image, ImageDraw, ImageFont

from functions.base.window_utils import center_window

MODS_DIR = 'mods'
ADDONS_DIR = 'addons'
MOD_FILE_EXTS = ('.bank', '.carra2')
DEFAULT_ICON_BG = (30, 41, 59, 255)
DEFAULT_ICON_ACCENT = (99, 102, 241, 255)


# ============================================================
# 图标生成
# ============================================================

def generate_icon(path, text=''):
    """生成默认占位图标 (256x256 圆角边框 + 首字符)"""
    img = Image.new('RGBA', (256, 256), DEFAULT_ICON_BG)
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([8, 8, 247, 247], radius=24,
                           outline=DEFAULT_ICON_ACCENT, width=6)
    if text:
        try:
            font = ImageFont.truetype('msyh.ttc', 110)
        except Exception:
            font = ImageFont.load_default()
        draw.text((128, 128), text[0], font=font, fill=(226, 232, 240, 255),
                  anchor='mm')
    img.save(path)


# ============================================================
# 生成插件模板
# ============================================================

ADDON_INFO_TEMPLATE = {
    'name': '',
    'desc': '',
    'authors': {},
    'settings': {'enable': False},
    'version': '0.0.1',
}

SCR_TEMPLATE = """# 插件代码入口: 在此编写插件的加载逻辑
# 可用全局变量: ADDON_ARG (含 AddonManager / AddonName)
# 完整示例请参考 addons/example/scr.py
"""


def spawn_extension(name):
    """在 addons/ 下生成插件模板, 返回 (成功, 消息)"""
    name = (name or '').strip()
    if not name:
        return False, '插件名称不能为空'
    if not os.path.isdir(ADDONS_DIR):
        return False, f'未找到 addons 目录: {os.path.abspath(ADDONS_DIR)}'
    target = os.path.join(ADDONS_DIR, name)
    if os.path.exists(target):
        return False, f'插件 {name} 已存在: {target}'
    try:
        os.makedirs(target)
        # 空的 scr.py
        with open(os.path.join(target, 'scr.py'), 'w', encoding='utf-8') as f:
            f.write(SCR_TEMPLATE)
        # 生成的图标
        generate_icon(os.path.join(target, 'icon.png'), text=name)
        # 模板 addon_info.json
        info = dict(ADDON_INFO_TEMPLATE)
        info['name'] = name
        with open(os.path.join(target, 'addon_info.json'), 'w', encoding='utf-8') as f:
            json.dump(info, f, ensure_ascii=False, indent=4)
        return True, f'插件模板已生成: {target}'
    except Exception as e:
        shutil.rmtree(target, ignore_errors=True)
        return False, f'生成插件模板失败: {e}'


# ============================================================
# 包装 Mod
# ============================================================

def _scan_mod_files(mod_dir):
    """扫描 mod 根目录下的单文件 (.bank/.carra2), 用于 file_names"""
    result = []
    try:
        for f in os.listdir(mod_dir):
            full = os.path.join(mod_dir, f)
            if os.path.isfile(full) and os.path.splitext(f)[1].lower() in MOD_FILE_EXTS:
                result.append(f)
    except Exception:
        pass
    return sorted(result)


def wrap_mod(source_folder, target_name=None):
    """包装 Mod: 校验必需文件, 复制到 mods/ 下, 自动生成图标与 mod_info.json

    返回 (成功, 消息)
    """
    source = (source_folder or '').strip()
    if not source:
        return False, '未选择原始文件夹'
    if not os.path.isdir(source):
        return False, f'原始文件夹不存在: {source}'

    # 校验必需内容 (大小写不敏感)
    entries = {e.lower(): e for e in os.listdir(source)}
    required = ('installer.bat', 'uninstaller.bat', 'assets')
    missing = [r for r in required if r not in entries]
    if missing:
        return False, '原始文件夹缺少必需内容: ' + ', '.join(missing) + \
               '\n(需要 Installer.bat / Uninstaller.bat / Assets 文件夹)'

    if not os.path.isdir(os.path.join(source, entries['assets'])):
        return False, 'Assets 必须是文件夹'

    name = (target_name or os.path.basename(os.path.normpath(source))).strip()
    if not name:
        return False, '无法确定 Mod 名称'
    target = os.path.join(MODS_DIR, name)
    try:
        if not os.path.isdir(MODS_DIR):
            os.makedirs(MODS_DIR)
        # 源目录本身就是目标目录时跳过复制, 仅生成缺失的图标与信息
        if os.path.abspath(source) != os.path.abspath(target):
            if os.path.exists(target):
                return False, f'mods 下已存在同名 Mod: {target}'
            shutil.copytree(source, target)
        # 生成图标 (已存在则保留)
        icon_path = os.path.join(target, 'icon.png')
        if not os.path.exists(icon_path):
            generate_icon(icon_path, text=name)
        # 生成 mod_info.json (已存在则保留)
        info_path = os.path.join(target, 'mod_info.json')
        if not os.path.exists(info_path):
            info = dict(ADDON_INFO_TEMPLATE)
            info['name'] = name
            info['file_names'] = _scan_mod_files(target)
            with open(info_path, 'w', encoding='utf-8') as f:
                json.dump(info, f, ensure_ascii=False, indent=4)
        return True, f'Mod 包装完成: {target}'
    except Exception as e:
        return False, f'包装 Mod 失败: {e}'


# ============================================================
# GUI
# ============================================================

def post_extension_tools_gui(root):
    """显示扩展工具窗口 (模式选择: 插件模板 / 包装 Mod)"""
    try:
        app = PostExtensionToolsGUI(root)
        app.root.wait_window()
    except Exception as e:
        messagebox.showerror('启动错误', f'无法启动扩展工具:\n{str(e)}')


class PostExtensionToolsGUI:
    def __init__(self, parent):
        self.parent = parent
        self.root = tk.Toplevel(parent.root)
        self.root.title('扩展工具')
        self.root.geometry('560x420')
        self.root.resizable(False, False)
        self.root.configure(bg=parent.lighten_bg_color)
        center_window(self.root)
        try:
            if os.path.exists('assets/images/icon/icon.ico'):
                self.root.iconbitmap('assets/images/icon/icon.ico')
        except Exception:
            pass
        self.root.protocol('WM_DELETE_WINDOW', self.root.destroy)
        self.create_widgets()

    def create_widgets(self):
        bg = self.parent.bg_color
        lighten = self.parent.lighten_bg_color

        main = tk.Frame(self.root, bg=bg)
        main.pack(fill=tk.BOTH, expand=True, padx=20, pady=16)

        title = tk.Label(main, text='🧩 扩展工具', font=('Microsoft YaHei UI', 14, 'bold'),
                         bg=bg, fg='#f8fafc')
        title.pack(anchor='w')

        desc = tk.Label(main, text='生成插件模板 或 包装 Mod 为可分发格式',
                        font=('Microsoft YaHei UI', 9), bg=bg, fg='#94a3b8')
        desc.pack(anchor='w', pady=(2, 10))

        # ---- 模式选择 ----
        mode_frame = tk.LabelFrame(main, text=' 选择模式 ', bg=bg, fg='#e2e8f0',
                                   font=('Microsoft YaHei UI', 10))
        mode_frame.pack(fill=tk.X)
        self.mode_var = tk.IntVar(value=1)
        tk.Radiobutton(mode_frame, text='📦 包装 Mod', variable=self.mode_var, value=1,
                       font=('Microsoft YaHei UI', 10), bg=bg, fg='#e2e8f0',
                       activebackground=bg, activeforeground='#e2e8f0',
                       selectcolor=lighten, command=self._on_mode_change
                       ).pack(anchor='w', padx=14, pady=(8, 2))
        tk.Radiobutton(mode_frame, text='🧩 生成插件模板', variable=self.mode_var, value=2,
                       font=('Microsoft YaHei UI', 10), bg=bg, fg='#e2e8f0',
                       activebackground=bg, activeforeground='#e2e8f0',
                       selectcolor=lighten, command=self._on_mode_change
                       ).pack(anchor='w', padx=14, pady=(2, 8))
        # 模式说明
        self.mode_hint = tk.Label(mode_frame, text='', font=('Microsoft YaHei UI', 8),
                                  bg=bg, fg='#64748b', justify='left', anchor='w',
                                  wraplength=500)
        self.mode_hint.pack(fill=tk.X, padx=14, pady=(0, 8))

        # ---- 参数区 (两种模式共用容器, 切换显示) ----
        self.param_frame = tk.Frame(main, bg=bg)
        self.param_frame.pack(fill=tk.X, pady=(10, 0))

        # 包装 Mod: 原始文件夹
        self.wrap_frame = tk.Frame(self.param_frame, bg=bg)
        tk.Label(self.wrap_frame, text='原始文件夹:', font=('Microsoft YaHei UI', 10),
                 bg=bg, fg='#e2e8f0').pack(anchor='w')
        wrap_row = tk.Frame(self.wrap_frame, bg=bg)
        wrap_row.pack(fill=tk.X, pady=(4, 0))
        self.folder_var = tk.StringVar()
        folder_entry = tk.Entry(wrap_row, textvariable=self.folder_var,
                                font=('Microsoft YaHei UI', 9), bg=lighten, fg='#e2e8f0',
                                relief='flat', insertbackground='#e2e8f0')
        folder_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=4)
        tk.Button(wrap_row, text='浏览...', command=self._browse_folder,
                  font=('Microsoft YaHei UI', 9), bg='#334155', fg='#f8fafc',
                  activebackground='#475569', activeforeground='#f8fafc',
                  relief='flat', padx=12, cursor='hand2').pack(side=tk.LEFT, padx=(8, 0))
        self.wrap_btn = tk.Button(self.wrap_frame, text='🚀 开始包装',
                                  command=self._do_wrap, font=('Microsoft YaHei UI', 10, 'bold'),
                                  bg='#6366f1', fg='#ffffff', activebackground='#4f46e5',
                                  activeforeground='#ffffff', relief='flat',
                                  padx=20, pady=7, cursor='hand2')
        self.wrap_btn.pack(anchor='e', pady=(8, 0))

        # 插件模板: 名称
        self.spawn_frame = tk.Frame(self.param_frame, bg=bg)
        tk.Label(self.spawn_frame, text='插件名称:', font=('Microsoft YaHei UI', 10),
                 bg=bg, fg='#e2e8f0').pack(anchor='w')
        spawn_row = tk.Frame(self.spawn_frame, bg=bg)
        spawn_row.pack(fill=tk.X, pady=(4, 0))
        self.name_var = tk.StringVar()
        tk.Entry(spawn_row, textvariable=self.name_var, font=('Microsoft YaHei UI', 9),
                 bg=lighten, fg='#e2e8f0', relief='flat', insertbackground='#e2e8f0'
                 ).pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=4)
        self.spawn_btn = tk.Button(spawn_row, text='✨ 生成模板',
                                   command=self._do_spawn,
                                   font=('Microsoft YaHei UI', 10, 'bold'),
                                   bg='#10b981', fg='#ffffff', activebackground='#059669',
                                   activeforeground='#ffffff', relief='flat',
                                   padx=20, pady=7, cursor='hand2')
        self.spawn_btn.pack(side=tk.LEFT, padx=(8, 0))

        # ---- 结果消息 ----
        self.result_var = tk.StringVar()
        self.result_label = tk.Label(main, textvariable=self.result_var,
                                     font=('Microsoft YaHei UI', 9), bg=bg, fg='#34d399',
                                     justify='left', anchor='w', wraplength=520)
        self.result_label.pack(fill=tk.X, pady=(12, 0))

        self._on_mode_change()

    def _on_mode_change(self):
        mode = self.mode_var.get()
        hints = {
            1: '选择包含 Installer.bat、Assets 文件夹、Uninstaller.bat 的 Mod 原始文件夹，\n'
               '程序将复制到 mods/ 目录并自动生成 icon.png 与 mod_info.json。',
            2: '在 addons/ 目录下生成插件模板（空的 scr.py、图标、addon_info.json），\n'
               '可直接在此基础上开发插件。',
        }
        self.mode_hint.config(text=hints.get(mode, ''))
        self.wrap_frame.pack_forget()
        self.spawn_frame.pack_forget()
        if mode == 1:
            self.wrap_frame.pack(fill=tk.X)
        else:
            self.spawn_frame.pack(fill=tk.X)
        self.result_var.set('')

    def _browse_folder(self):
        folder = filedialog.askdirectory(title='选择 Mod 原始文件夹', parent=self.root)
        if folder:
            self.folder_var.set(folder)

    def _do_wrap(self):
        self.wrap_btn.config(state=tk.DISABLED, text='包装中...')
        self.root.update_idletasks()
        try:
            ok, msg = wrap_mod(self.folder_var.get())
            self._show_result(ok, msg)
        finally:
            self.wrap_btn.config(state=tk.NORMAL, text='🚀 开始包装')

    def _do_spawn(self):
        self.spawn_btn.config(state=tk.DISABLED, text='生成中...')
        self.root.update_idletasks()
        try:
            ok, msg = spawn_extension(self.name_var.get())
            self._show_result(ok, msg)
        finally:
            self.spawn_btn.config(state=tk.NORMAL, text='✨ 生成模板')

    def _show_result(self, ok, msg):
        self.result_var.set(msg)
        self.result_label.config(fg='#34d399' if ok else '#f87171')
        if not ok:
            messagebox.showerror('失败', msg, parent=self.root)


# 独立运行模式: 无父窗口时用普通 Tk
class _Dummy:
    root = None
    bg_color = '#0f172a'
    lighten_bg_color = '#1e293b'
root = tk.Tk()
dummy = _Dummy()
dummy.root = root # type: ignore
dummy.lighten_bg_color = '#1e293b'
dummy.bg_color = '#0f172a'
try:
    if os.path.exists('assets/images/icon/icon.ico'):
        root.iconbitmap('assets/images/icon/icon.ico')
except Exception:
    pass
post_extension_tools_gui(dummy)
