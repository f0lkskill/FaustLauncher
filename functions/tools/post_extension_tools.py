#! 扩展工具: 生成插件模板 / 包装 Mod
#? 两种模式 (均需用户在 GUI 表单中填写信息):
#? - 生成插件模板: 填写 addon_info.json 字段后, 在 addons/ 下生成 插件名/ 目录 (scr.py + icon.png + addon_info.json)
#? - 包装 Mod: 选择原始文件夹(须含 Installer.bat / Assets 文件夹 / Uninstaller.bat),
#?   在表单中填写 mod_info.json 字段并勾选要载入的文件, 复制到 mods/ 下生成 Mod

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


def spawn_extension(name, info=None):
    """在 addons/ 下生成插件模板 (info 为表单填写的 addon_info 字段), 返回 (成功, 消息)"""
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
        # 图标: 用户选择的自定义图标或生成的默认图标
        if info and info.get('icon_path'):
            shutil.copy2(info['icon_path'], os.path.join(target, 'icon.png'))
        else:
            generate_icon(os.path.join(target, 'icon.png'), text=name)
        # addon_info.json (用户填写字段)
        info_json = dict(ADDON_INFO_TEMPLATE)
        info_json['name'] = name
        if info:
            info_json['desc'] = (info.get('desc') or '').strip()
            info_json['authors'] = info.get('authors') or {}
            info_json['version'] = (info.get('version') or '0.0.1').strip() or '0.0.1'
        with open(os.path.join(target, 'addon_info.json'), 'w', encoding='utf-8') as f:
            json.dump(info_json, f, ensure_ascii=False, indent=4)
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


def wrap_mod(source_folder, info=None, icon_path=None, extra_files=None):
    """包装 Mod: 校验必需文件, 复制到 mods/ 下, 按表单填写的信息生成图标与 mod_info.json

    info: {'name','desc','version','authors','file_names'} (file_names 为用户勾选)
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

    name = (info or {}).get('name') or os.path.basename(os.path.normpath(source))
    name = (name or '').strip()
    if not name:
        return False, '无法确定 Mod 名称'
    target = os.path.join(MODS_DIR, name)
    try:
        if not os.path.isdir(MODS_DIR):
            os.makedirs(MODS_DIR)
        # 源目录本身就是目标目录时跳过复制, 仅生成图标与信息
        if os.path.abspath(source) != os.path.abspath(target):
            if os.path.exists(target):
                return False, f'mods 下已存在同名 Mod: {target}'
            shutil.copytree(source, target)
        # 用户额外勾选的文件复制到 mod 根目录
        extra_names = []
        for f in extra_files or []:
            if not f or not os.path.isfile(f):
                continue
            shutil.copy2(f, os.path.join(target, os.path.basename(f)))
            extra_names.append(os.path.basename(f))
        # 图标: 用户选择的自定义图标, 否则生成默认
        target_icon = os.path.join(target, 'icon.png')
        if icon_path and os.path.isfile(icon_path):
            shutil.copy2(icon_path, target_icon)
        elif not os.path.exists(target_icon):
            generate_icon(target_icon, text=name)
        # mod_info.json (用户填写字段)
        file_names = sorted(set((info or {}).get('file_names') or []) | set(extra_names))
        info_json = dict(ADDON_INFO_TEMPLATE)
        info_json['name'] = name
        info_json['desc'] = ((info or {}).get('desc') or '').strip()
        info_json['authors'] = (info or {}).get('authors') or {}
        info_json['version'] = ((info or {}).get('version') or '0.0.1').strip() or '0.0.1'
        info_json['file_names'] = file_names
        with open(os.path.join(target, 'mod_info.json'), 'w', encoding='utf-8') as f:
            json.dump(info_json, f, ensure_ascii=False, indent=4)
        return True, f'Mod 包装完成: {target}'
    except Exception as e:
        return False, f'包装 Mod 失败: {e}'


# ============================================================
# 信息填写表单 (mod_info.json / addon_info.json)
# ============================================================

class InfoFormGUI:
    """表单窗口: 由用户填写名称/描述/版本/作者, Mod 模式额外勾选载入文件与自定义图标

    run() 返回填写结果 dict 或 None (取消):
    {'name','desc','version','authors','file_names','extra_files','icon_path'}
    """

    def __init__(self, parent, form_type, name_default='', files=()):
        self.parent = parent
        self.form_type = form_type  # 'mod' | 'plugin'
        self.result = None
        self.files = list(files)          # 显示名 (mod 根目录扫描 + 附加文件)
        self.extra_files = []             # 附加文件的绝对路径

        self.root = tk.Toplevel(parent.root)
        self.root.title('填写信息 - 包装 Mod' if form_type == 'mod' else '填写信息 - 生成插件')
        self.root.geometry('580x560')
        self.root.resizable(False, False)
        self.root.configure(bg=parent.lighten_bg_color)
        center_window(self.root)
        try:
            if os.path.exists('assets/images/icon/icon.ico'):
                self.root.iconbitmap('assets/images/icon/icon.ico')
        except Exception:
            pass
        self.root.protocol('WM_DELETE_WINDOW', self._on_cancel)
        self._create_widgets(name_default)

    def _create_widgets(self, name_default):
        bg = self.parent.bg_color
        lighten = self.parent.lighten_bg_color

        main = tk.Frame(self.root, bg=bg)
        main.pack(fill=tk.BOTH, expand=True, padx=20, pady=16)

        tip = ('以下信息将写入 mod_info.json' if self.form_type == 'mod'
               else '以下信息将写入 addon_info.json')
        tk.Label(main, text=tip, font=('Microsoft YaHei UI', 9), bg=bg,
                 fg='#94a3b8').pack(anchor='w', pady=(0, 8))

        # ---- 名称 ----
        tk.Label(main, text='名称:', font=('Microsoft YaHei UI', 10),
                 bg=bg, fg='#e2e8f0').pack(anchor='w')
        self.name_var = tk.StringVar(value=name_default)
        tk.Entry(main, textvariable=self.name_var, font=('Microsoft YaHei UI', 9),
                 bg=lighten, fg='#e2e8f0', relief='flat', insertbackground='#e2e8f0'
                 ).pack(fill=tk.X, pady=(2, 8), ipady=4)

        # ---- 描述 ----
        tk.Label(main, text='描述:', font=('Microsoft YaHei UI', 10),
                 bg=bg, fg='#e2e8f0').pack(anchor='w')
        self.desc_text = tk.Text(main, height=3, font=('Microsoft YaHei UI', 9),
                                 bg=lighten, fg='#e2e8f0', relief='flat',
                                 insertbackground='#e2e8f0', wrap='word')
        self.desc_text.pack(fill=tk.X, pady=(2, 8))

        # ---- 版本 ----
        tk.Label(main, text='版本:', font=('Microsoft YaHei UI', 10),
                 bg=bg, fg='#e2e8f0').pack(anchor='w')
        self.version_var = tk.StringVar(value='0.0.1')
        tk.Entry(main, textvariable=self.version_var, font=('Microsoft YaHei UI', 9),
                 bg=lighten, fg='#e2e8f0', relief='flat', insertbackground='#e2e8f0'
                 ).pack(fill=tk.X, pady=(2, 8), ipady=4)

        # ---- 作者 ----
        tk.Label(main, text='作者 (每行一个, 格式: 名字 或 名字|链接):',
                 font=('Microsoft YaHei UI', 10), bg=bg, fg='#e2e8f0').pack(anchor='w')
        self.authors_text = tk.Text(main, height=2, font=('Microsoft YaHei UI', 9),
                                    bg=lighten, fg='#e2e8f0', relief='flat',
                                    insertbackground='#e2e8f0', wrap='none')
        self.authors_text.pack(fill=tk.X, pady=(2, 8))

        # ---- 文件列表 (仅 Mod 模式) ----
        self.files_frame = None
        self.file_vars = {}
        if self.form_type == 'mod':
            files_lf = tk.LabelFrame(main, text=' 载入游戏的文件 (file_names) ',
                                     bg=bg, fg='#e2e8f0', font=('Microsoft YaHei UI', 9))
            files_lf.pack(fill=tk.X, pady=(4, 8))
            # 滚动区
            container = tk.Frame(files_lf, bg=bg)
            container.pack(fill=tk.X, padx=6, pady=4)
            canvas = tk.Canvas(container, bg=bg, highlightthickness=0, height=90)
            scrollbar = tk.Scrollbar(container, orient=tk.VERTICAL, command=canvas.yview,
                                     bg=bg, troughcolor=bg, activebackground='#475569')
            self.files_frame = tk.Frame(canvas, bg=bg)
            self.files_frame.bind('<Configure>',
                                  lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
            canvas.create_window((0, 0), window=self.files_frame, anchor='nw')
            canvas.configure(yscrollcommand=scrollbar.set)
            canvas.pack(side=tk.LEFT, fill=tk.X, expand=True)
            scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
            self._rebuild_file_list()
            # 添加额外文件按钮
            tk.Button(files_lf, text='➕ 添加其他文件...', command=self._pick_extra_files,
                      font=('Microsoft YaHei UI', 9), bg='#334155', fg='#f8fafc',
                      activebackground='#475569', activeforeground='#f8fafc',
                      relief='flat', padx=10, pady=2, cursor='hand2'
                      ).pack(anchor='w', padx=6, pady=(0, 6))

        # ---- 自定义图标 (可选) ----
        icon_row = tk.Frame(main, bg=bg)
        icon_row.pack(fill=tk.X, pady=(0, 8))
        self.icon_var = tk.StringVar(value='')
        tk.Button(icon_row, text='🎨 自定义图标 (可选)', command=self._pick_icon,
                  font=('Microsoft YaHei UI', 9), bg='#334155', fg='#f8fafc',
                  activebackground='#475569', activeforeground='#f8fafc',
                  relief='flat', padx=10, pady=2, cursor='hand2').pack(side=tk.LEFT)
        tk.Label(icon_row, textvariable=self.icon_var, font=('Microsoft YaHei UI', 8),
                 bg=bg, fg='#64748b').pack(side=tk.LEFT, padx=(8, 0))

        # ---- 按钮 ----
        btn_row = tk.Frame(main, bg=bg)
        btn_row.pack(fill=tk.X, pady=(4, 0))
        tk.Button(btn_row, text='✔ 确认生成', command=self._on_confirm,
                  font=('Microsoft YaHei UI', 10, 'bold'),
                  bg='#6366f1', fg='#ffffff', activebackground='#4f46e5',
                  activeforeground='#ffffff', relief='flat',
                  padx=20, pady=6, cursor='hand2').pack(side=tk.RIGHT)
        tk.Button(btn_row, text='取消', command=self._on_cancel,
                  font=('Microsoft YaHei UI', 10), bg='#334155', fg='#e2e8f0',
                  activebackground='#475569', activeforeground='#e2e8f0',
                  relief='flat', padx=16, pady=6, cursor='hand2').pack(side=tk.RIGHT,
                                                                       padx=(0, 8))

    def _rebuild_file_list(self):
        if not self.files_frame:
            return
        for child in self.files_frame.winfo_children():
            child.destroy()
        self.file_vars = {}
        extra_basenames = {os.path.basename(p) for p in self.extra_files}
        for f in self.files:
            var = tk.BooleanVar(value=True)
            self.file_vars[f] = var
            label = f'{f}  📎附加' if f in extra_basenames else f
            cb = tk.Checkbutton(self.files_frame, text=label, variable=var, bg='#0f172a',
                                fg='#e2e8f0', selectcolor='#1e293b', anchor='w',
                                activebackground='#0f172a', activeforeground='#e2e8f0',
                                font=('Microsoft YaHei UI', 8))
            cb.pack(fill=tk.X)
        if not self.files:
            tk.Label(self.files_frame,
                     text='未在文件夹根目录发现 .bank/.carra2 文件，可通过"添加其他文件"选择',
                     font=('Microsoft YaHei UI', 8), bg='#0f172a',
                     fg='#64748b').pack(anchor='w')

    def _pick_extra_files(self):
        paths = filedialog.askopenfilenames(
            title='选择要载入游戏的文件',
            parent=self.root,
            filetypes=[('Mod 文件', '*.bank *.carra2'), ('所有文件', '*.*')])
        for p in paths:
            base = os.path.basename(p)
            if base not in self.files:
                self.files.append(base)
                self.extra_files.append(p)
        self._rebuild_file_list()

    def _pick_icon(self):
        path = filedialog.askopenfilename(
            title='选择自定义图标',
            parent=self.root,
            filetypes=[('图片文件', '*.png *.jpg *.jpeg *.ico'), ('所有文件', '*.*')])
        if path:
            self.icon_var.set(path)

    def _parse_authors(self):
        authors = {}
        for line in self.authors_text.get('1.0', 'end').strip().splitlines():
            line = line.strip()
            if not line:
                continue
            if '|' in line:
                n, _, link = line.partition('|')
                authors[n.strip()] = link.strip()
            else:
                authors[line] = ''
        return authors

    def _collect(self):
        name = self.name_var.get().strip()
        if not name:
            messagebox.showwarning('提示', '请填写名称', parent=self.root)
            return None
        result = {
            'name': name,
            'desc': self.desc_text.get('1.0', 'end').strip(),
            'version': self.version_var.get().strip(),
            'authors': self._parse_authors(),
            'icon_path': self.icon_var.get() or None,
        }
        if self.form_type == 'mod':
            result['file_names'] = [f for f in self.files if self.file_vars.get(f, tk.BooleanVar()).get()]
            result['extra_files'] = list(self.extra_files)
        return result

    def _on_confirm(self):
        result = self._collect()
        if result is None:
            return
        self.result = result
        self.root.destroy()

    def _on_cancel(self):
        self.result = None
        self.root.destroy()

    def run(self):
        self.root.wait_window()
        return self.result


# ============================================================
# 主窗口
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
               '程序将复制到 mods/ 目录，并由你填写 mod_info.json 信息。',
            2: '填写插件信息后，在 addons/ 目录下生成插件模板（scr.py、图标、addon_info.json），\n'
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
        source = self.folder_var.get().strip()
        # 提前校验, 通过后进入信息填写表单
        if not source:
            self._show_result(False, '请先选择原始文件夹')
            return
        if not os.path.isdir(source):
            self._show_result(False, f'原始文件夹不存在: {source}')
            return
        required = ('installer.bat', 'uninstaller.bat', 'assets')
        entries = {e.lower(): e for e in os.listdir(source)}
        missing = [r for r in required if r not in entries]
        if missing:
            self._show_result(False, '原始文件夹缺少必需内容: ' + ', '.join(missing) +
                              '\n(需要 Installer.bat / Uninstaller.bat / Assets 文件夹)')
            return
        name_default = os.path.basename(os.path.normpath(source))
        form = InfoFormGUI(self, 'mod', name_default=name_default,
                           files=_scan_mod_files(source))
        data = form.run()
        if data is None:
            return
        self.wrap_btn.config(state=tk.DISABLED, text='包装中...')
        self.root.update_idletasks()
        try:
            ok, msg = wrap_mod(source, info=data, icon_path=data.get('icon_path'),
                               extra_files=data.get('extra_files'))
            self._show_result(ok, msg)
        finally:
            self.wrap_btn.config(state=tk.NORMAL, text='🚀 开始包装')

    def _do_spawn(self):
        name = self.name_var.get().strip()
        if not name:
            self._show_result(False, '请先填写插件名称')
            return
        form = InfoFormGUI(self, 'plugin', name_default=name)
        data = form.run()
        if data is None:
            return
        ok, msg = spawn_extension(data['name'], info=data)
        self._show_result(ok, msg)

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
dummy.root = root
dummy.lighten_bg_color = '#1e293b'
dummy.bg_color = '#0f172a'
try:
    if os.path.exists('assets/images/icon/icon.ico'):
        root.iconbitmap('assets/images/icon/icon.ico')
except Exception:
    pass
post_extension_tools_gui(dummy)
