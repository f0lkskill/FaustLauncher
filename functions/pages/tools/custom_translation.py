import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
import os
import json
from threading import Thread
from functions.base.window_utils import center_window
from functions.base.color_scheme import C, darken_color, lighten_color


def _make_default_nav_items():
    """默认导航项 (汉化目录名跟随当前平台)"""
    from functions.web_update.translation_source import get_translation_dir_name
    d = get_translation_dir_name()
    return [
        {"name": "剧情对话", "path": f"{d}/StoryData"},
        {"name": "战斗提示", "path": f"{d}/BattleHint.json"},
        {"name": "战斗关键词", "path": f"{d}/BattleKeywords.json"},
        {"name": "单位关键词", "path": f"{d}/UnitKeyword.json"},
        {"name": "剧本事件", "path": f"{d}/AbEvents.json"},
        {"name": "人格对话", "path": f"{d}/BattleAnnouncerDlg"},
        {"name": "阿勃拉对话", "path": f"{d}/AbDlg_Faust.json"},
        {"name": "故事剧场主", "path": f"{d}/StoryTheaterMain.json"},
        {"name": "UI文本", "path": f"{d}/StoryUIText.json"},
        {"name": "镜牢地牢", "path": f"{d}/TutorialMirrorDungeon.json"},
    ]


DEFAULT_NAV_ITEMS = _make_default_nav_items()

NAV_CONFIG_FILE = "lang/nav_config.json"

# ========== 功能开关 / 黑名单 ==========
_NAV_ENABLED = False
HIDDEN_KEYS = {"id", "usage", "personalityid", "voicefile"}


class CollapsiblePane(tk.Frame):
    """可折叠的层级面板 - 替代原生 Treeview"""

    def __init__(self, master, title, root_app, bg_color=None,
                 is_container=False, is_root=False, meta=None):
        super().__init__(master, bd=0, highlightthickness=0,
                         bg=bg_color or root_app.bg_color)
        self.root_app = root_app
        self.is_container = is_container
        self.is_expanded = True
        self.meta = meta or {}

        header_bg = bg_color or root_app.lighten_bg_color
        body_bg = darken_color(header_bg, 0.88)
        self.body_bg = body_bg
        self.configure(bg=header_bg if is_container else body_bg)

        # -------- 头部（可点击折叠/展开）--------
        self.header = tk.Frame(self, bg=header_bg, bd=0, highlightthickness=0)
        self.header.pack(fill=tk.X, side=tk.TOP)

        self.toggle_lbl = tk.Label(self.header, text="▼" if is_container else "",
                                   bg=header_bg,
                                   fg='#7be2f7',
                                   font=('Microsoft YaHei UI', 9, 'bold'),
                                   cursor='hand2' if is_container else 'arrow',
                                   padx=6)
        self.toggle_lbl.pack(side=tk.LEFT)
        if is_container:
            self.toggle_lbl.bind("<Button-1>", lambda e: self.toggle())

        self.title_lbl = tk.Label(self.header, text=title, bg=header_bg,
                                  fg='#ecf0f1',
                                  font=('Microsoft YaHei UI', 9, 'bold'),
                                  anchor='w', cursor='hand2' if is_container else 'arrow')
        self.title_lbl.pack(side=tk.LEFT, padx=(0, 6))
        if is_container:
            self.title_lbl.bind("<Button-1>", lambda e: self.toggle())

        self.info_lbl = tk.Label(self.header, text="", bg=header_bg,
                                 fg='#95a5a6', font=('Microsoft YaHei UI', 8))
        self.info_lbl.pack(side=tk.RIGHT, padx=10)

        # -------- 内容容器 --------
        self.body = tk.Frame(self, bg=body_bg, bd=0, highlightthickness=0)
        self.body.pack(fill=tk.X, side=tk.TOP, padx=6, pady=(2, 4))

        # 折叠线（装饰性左侧竖线）
        self._left_line = tk.Frame(self.body, bg='#3498db', width=2, bd=0, highlightthickness=0)
        self._left_line.pack(side=tk.LEFT, fill=tk.Y)
        self.body_inner = tk.Frame(self.body, bg=body_bg, bd=0, highlightthickness=0)
        self.body_inner.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(6, 0))

        if is_root:
            self.configure(bg=root_app.bg_color)
            self.header.configure(bg=root_app.lighten_bg_color)

    def set_info(self, text, color='#95a5a6'):
        self.info_lbl.config(text=text, fg=color)

    def set_title(self, text):
        self.title_lbl.config(text=text)

    def toggle(self):
        if self.is_expanded:
            self.collapse()
        else:
            self.expand()

    def collapse(self):
        if not self.is_expanded:
            return
        self.body.pack_forget()
        self.toggle_lbl.config(text="▶")
        self.is_expanded = False

    def expand(self):
        if self.is_expanded:
            return
        self.body.pack(fill=tk.X, side=tk.TOP, padx=6, pady=(2, 4))
        self.toggle_lbl.config(text="▼")
        self.is_expanded = True


class CustomTranslationTool:
    """自定义汉化工具 - 全 GUI 版"""

    def __init__(self, root, parent_window):
        self.root = root
        self.parent_window = tk.Toplevel(parent_window)
        self.parent_window.geometry("1300x800")
        self.parent_window.minsize(900, 600)
        self.parent_window.withdraw()
        center_window(self.parent_window, False)
        self.parent_window.title("自定义汉化工具 - 加载中...")
        self.parent_window.configure(bg=root.bg_color)
        try:
            if os.path.exists("assets/images/icon/icon.ico"):
                self.parent_window.iconbitmap("assets/images/icon/icon.ico")
        except Exception:
            pass

        # 先隐藏窗口，等文件树异步加载完成后再显示
        self._tree_loading_done = False

        self.current_file = None
        self.original_data = {}
        self.modified_data = {}
        self.changes = {}
        self.changes_file = "lang/changes.json"
        self.lang_dir = "lang"
        self.nav_items = []
        self._all_panes = []
        self._search_keyword = ""
        self._only_modified = False
        self._loading_overlay = None
        self._current_original_data = None  # 多线程加载保存临时数据
        self._current_modified_data = None
        self._current_file_path = None
        
        # 常用颜色
        self.bg = root.bg_color
        self.bg_light = root.lighten_bg_color
        self.bg_dark = darken_color(root.bg_color, 0.78)
        self.bg_darker = darken_color(root.bg_color, 0.6)

        # 显示隐藏键的开关（默认不显示黑名单中的键）
        self._show_hidden_keys_var = tk.BooleanVar(value=False)

        os.makedirs(self.lang_dir, exist_ok=True)
        self._ensure_changes_file()
        self._load_existing_changes()
        if _NAV_ENABLED:
            self._load_nav_config()
        self._init_ui()
        # 异步加载文件树，加载完成后再显示窗口
        self._refresh_file_tree_and_show()

    def _refresh_file_tree_and_show(self):
        """异步构建文件树，构建完成后显示窗口"""
        for item in self.file_tree.get_children():
            self.file_tree.delete(item)
        root_node = self.file_tree.insert('', 'end', text=" lang",
                                          values=("", "dir"))
        self.file_tree.item(root_node, open=True)
        # 使用线程构建，构建完成后通过 after(0, ...) 回到主线程显示窗口
        def build_and_notify():
            try:
                self._build_tree(root_node, self.lang_dir)
            except Exception as e:
                print(f"[CustomTranslationTool] 构建文件树失败: {e}")
            finally:
                # 回到主线程，显示窗口
                self.parent_window.after(0, self._on_tree_loaded)

        Thread(target=build_and_notify, daemon=True).start()

    def _on_tree_loaded(self):
        """文件树加载完成：显示窗口"""
        self._tree_loading_done = True
        try:
            self.parent_window.title("自定义汉化工具")
            self.parent_window.deiconify()
            self.parent_window.lift()
            self.parent_window.focus_force()
            self.status_label.config(text="文件树加载完成")
        except Exception:
            pass

    # ======================= 文件系统辅助 =======================
    def _ensure_changes_file(self):
        os.makedirs(os.path.dirname(self.changes_file), exist_ok=True)
        if not os.path.exists(self.changes_file):
            with open(self.changes_file, 'w', encoding='utf-8') as f:
                json.dump({}, f, ensure_ascii=False, indent=4)

    def _load_existing_changes(self):
        try:
            with open(self.changes_file, 'r', encoding='utf-8') as f:
                self.changes = json.load(f)
            self._normalize_changes_keys()
        except Exception as e:
            print(f"加载修改记录失败: {e}")
            self.changes = {}

    def _save_changes_to_file(self):
        try:
            with open(self.changes_file, 'w', encoding='utf-8') as f:
                json.dump(self.changes, f, ensure_ascii=False, indent=4)
        except Exception as e:
            print(f"保存修改记录失败: {e}")

    def _normalize_change_path(self, path):
        """统一 changes.json 里的相对路径，兼容 Windows 旧反斜杠键。"""
        return os.path.normpath(path).replace("\\", "/")

    def _relative_to_lang(self, path):
        return self._normalize_change_path(os.path.relpath(path, self.lang_dir))

    def _change_key_aliases(self, relative):
        normalized = self._normalize_change_path(relative)
        aliases = [normalized, normalized.replace("/", "\\")]
        if relative not in aliases:
            aliases.append(relative)
        return aliases

    def _normalize_changes_keys(self):
        if not isinstance(self.changes, dict):
            self.changes = {}
            return
        normalized_changes = {}
        for key, value in self.changes.items():
            normalized_changes[self._normalize_change_path(key)] = value
        self.changes = normalized_changes

    def _get_changes_for_relative(self, relative):
        for key in self._change_key_aliases(relative):
            if key in self.changes:
                return self.changes[key]
        return None

    def _has_changes_for_relative(self, relative):
        return self._get_changes_for_relative(relative) is not None

    def _set_changes_for_relative(self, relative, diff):
        for key in self._change_key_aliases(relative):
            self.changes.pop(key, None)
        self.changes[self._normalize_change_path(relative)] = diff

    def _delete_changes_for_relative(self, relative):
        for key in self._change_key_aliases(relative):
            self.changes.pop(key, None)

    def _load_nav_config(self):
        try:
            if os.path.exists(NAV_CONFIG_FILE):
                with open(NAV_CONFIG_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.nav_items = data.get("items", list(DEFAULT_NAV_ITEMS))
                    return
        except Exception as e:
            print(f"加载导航配置失败: {e}")
        self.nav_items = list(DEFAULT_NAV_ITEMS)

    def _save_nav_config(self):
        try:
            with open(NAV_CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump({"items": self.nav_items}, f, ensure_ascii=False, indent=4)
        except Exception as e:
            print(f"保存导航配置失败: {e}")

    # ======================= "加载中" 遮罩 =======================
    def _show_loading(self, text="加载中..."):
        if self._loading_overlay is not None:
            try:
                self._loading_overlay.destroy()
            except Exception:
                pass
        overlay = tk.Frame(self.data_canvas.master if hasattr(self, 'data_canvas') else self.parent_window,
                           bg='black', bd=0, highlightthickness=0)
        overlay.place(x=0, y=0, relwidth=1, relheight=1)
        overlay.tkraise()
        overlay.configure(bg=self.bg)

        label = tk.Label(overlay, text=f"⏳ {text}",
                         bg=self.bg, fg='#7be2f7',
                         font=('Microsoft YaHei UI', 14, 'bold'))
        label.place(relx=0.5, rely=0.5, anchor='center')
        self._loading_overlay = overlay
        self.parent_window.update_idletasks()

    def _hide_loading(self):
        if self._loading_overlay is not None:
            try:
                self._loading_overlay.destroy()
            except Exception:
                pass
            self._loading_overlay = None

    # ======================= UI 构建 =======================
    def _init_ui(self):
        main_container = tk.Frame(self.parent_window, bg=self.bg, bd=0, highlightthickness=0)
        main_container.pack(fill=tk.BOTH, expand=True)

        # 顶部导航栏（仅当 _NAV_ENABLED=True 时启用，作为测试功能）
        if _NAV_ENABLED:
            top_bar = tk.Frame(main_container, bg=self.bg_dark, height=54,
                               bd=0, highlightthickness=0)
            top_bar.pack(fill=tk.X, side=tk.TOP)
            top_bar.pack_propagate(False)

            tk.Label(top_bar, text="⚡ 快速导航:", bg=self.bg_dark, fg='#ecf0f1',
                     font=('Microsoft YaHei UI', 10, 'bold')).pack(side=tk.LEFT, padx=12)

            nav_canvas = tk.Canvas(top_bar, bg=self.bg_dark, highlightthickness=0,
                                   height=52)
            nav_canvas.pack(side=tk.LEFT, fill=tk.X, expand=True)

            nav_scrollbar = ttk.Scrollbar(top_bar, orient=tk.HORIZONTAL,
                                          command=nav_canvas.xview)
            nav_scrollbar.pack(side=tk.BOTTOM, fill=tk.X)
            nav_canvas.configure(xscrollcommand=nav_scrollbar.set)

            self.nav_inner = tk.Frame(nav_canvas, bg=self.bg_dark, bd=0,
                                      highlightthickness=0)
            nav_canvas.create_window((0, 0), window=self.nav_inner, anchor='nw')
            self.nav_inner.bind("<Configure>",
                                lambda e: nav_canvas.configure(
                                    scrollregion=nav_canvas.bbox("all")))

            tk.Button(top_bar, text="+添加当前",
                      command=self._add_current_to_nav,
                      bg='#27ae60', fg='white',
                      font=('Microsoft YaHei UI', 9, 'bold'),
                      relief='flat', padx=12, pady=6,
                      cursor='hand2',
                      activebackground='#1e8449',
                      activeforeground='white').pack(side=tk.RIGHT, padx=4)

            tk.Button(top_bar, text="管理导航",
                      command=self._manage_nav_dialog,
                      bg='#3498db', fg='white',
                      font=('Microsoft YaHei UI', 9, 'bold'),
                      relief='flat', padx=12, pady=6,
                      cursor='hand2',
                      activebackground='#2874a6',
                      activeforeground='white').pack(side=tk.RIGHT, padx=4)

            self._refresh_nav_bar()

        # 主体双栏
        split_frame = tk.Frame(main_container, bg=self.bg, bd=0, highlightthickness=0)
        split_frame.pack(fill=tk.BOTH, expand=True)

        self._build_left_panel(split_frame)
        self._build_right_panel(split_frame)

    def _build_left_panel(self, parent):
        left_frame = tk.Frame(parent, bg=self.bg_light, width=310, bd=0, highlightthickness=0)
        left_frame.pack(side=tk.LEFT, fill=tk.Y)
        left_frame.pack_propagate(False)

        # 标题
        title_bar = tk.Frame(left_frame, bg=self.bg_dark, height=42, bd=0, highlightthickness=0)
        title_bar.pack(fill=tk.X, side=tk.TOP)
        title_bar.pack_propagate(False)
        tk.Label(title_bar, text="📁 文件目录",
                 bg=self.bg_dark, fg='#ecf0f1',
                 font=('Microsoft YaHei UI', 10, 'bold')).pack(side=tk.LEFT, padx=12)

        # 搜索框
        search_wrap = tk.Frame(left_frame, bg=self.bg_light, bd=0, highlightthickness=0)
        search_wrap.pack(fill=tk.X, padx=10, pady=8)

        tk.Label(search_wrap, text="🔍", bg=self.bg_light,
                 fg='#7be2f7', font=('Microsoft YaHei UI', 10)).pack(side=tk.LEFT)

        self.search_var = tk.StringVar()
        entry = tk.Entry(search_wrap, textvariable=self.search_var,
                         bg=self.bg_darker, fg='white', insertbackground='white',
                         relief='flat',
                         font=('Microsoft YaHei UI', 10))
        entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=6, ipady=3)
        entry.bind('<KeyRelease>', self._on_search_changed)

        # 刷新按钮
        tk.Button(left_frame, text="↻ 刷新文件树",
                  command=self._refresh_file_tree,
                  bg='#3498db', fg='white',
                  font=('Microsoft YaHei UI', 9, 'bold'),
                  relief='flat', cursor='hand2',
                  activebackground='#2874a6',
                  activeforeground='white').pack(fill=tk.X, padx=10, pady=(0, 6),
                                                  ipady=3)

        # 文件树
        tree_frame = tk.Frame(left_frame, bg=self.bg_light, bd=0, highlightthickness=0)
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

        # 文件树样式 - 独立样式，不修改全局主题
        tree_style = ttk.Style(self.parent_window)
        tree_style.configure("Custom.Treeview",
                             background=self.bg_darker, foreground='#ecf0f1',
                             fieldbackground=self.bg_darker, rowheight=26,
                             borderwidth=0, bd=0)
        tree_style.map('Custom.Treeview',
                       background=[('selected', '#3498db')],
                       foreground=[('selected', 'white')])
        tree_style.configure("Custom.Treeview.Heading",
                             background=self.bg_light,
                             foreground="white")
        tree_style.configure("Custom.Treeview.Item",
                             padding=(2, 2))

        self.file_tree = ttk.Treeview(tree_frame, style="Custom.Treeview",
                                      selectmode='browse', show='tree')
        self.file_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.file_tree.bind('<<TreeviewSelect>>', self._on_tree_selected)

        tree_scroll = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL,
                                    command=self.file_tree.yview)
        tree_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.file_tree.configure(yscrollcommand=tree_scroll.set)

    def _build_right_panel(self, parent):
        right_frame = tk.Frame(parent, bg=self.bg, bd=0, highlightthickness=0)
        right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        # 顶部信息栏
        info_bar = tk.Frame(right_frame, bg=self.bg_dark, height=42, bd=0, highlightthickness=0)
        info_bar.pack(fill=tk.X, side=tk.TOP)
        info_bar.pack_propagate(False)

        self.current_file_label = tk.Label(info_bar,
                                            text="📄 未选择文件",
                                            bg=self.bg_dark, fg='#f1c40f',
                                            font=('Microsoft YaHei UI', 10, 'bold'),
                                            anchor='w', justify=tk.LEFT)
        self.current_file_label.pack(side=tk.LEFT, padx=12)

        self.changes_count_label = tk.Label(info_bar, text="",
                                            bg=self.bg_dark, fg='#2ecc71',
                                            font=('Microsoft YaHei UI', 9, 'bold'))
        self.changes_count_label.pack(side=tk.RIGHT, padx=12)

        # 工具栏
        tool_bar = tk.Frame(right_frame, bg=self.bg_light, height=46, bd=0, highlightthickness=0)
        tool_bar.pack(fill=tk.X, side=tk.TOP)
        tool_bar.pack_propagate(False)

        tk.Label(tool_bar, text="🔎 搜索键/值:",
                 bg=self.bg_light, fg='#ecf0f1',
                 font=('Microsoft YaHei UI', 9, 'bold')).pack(side=tk.LEFT,
                                                              padx=(12, 0), pady=10)

        self.data_search_var = tk.StringVar()
        data_search_entry = tk.Entry(tool_bar, textvariable=self.data_search_var,
                                     bg=self.bg_darker, fg='white',
                                     insertbackground='white',
                                     relief='flat', width=28,
                                     font=('Microsoft YaHei UI', 10))
        data_search_entry.pack(side=tk.LEFT, padx=6, pady=10, ipady=3)
        # 支持回车触发搜索（不再用 KeyRelease 事件循环）
        data_search_entry.bind('<Return>',
                               lambda e: self._on_data_search_changed())

        search_btn = tk.Button(tool_bar, text="搜索",
                              command=self._on_data_search_changed,
                              bg='#2e86de', fg='white',
                              relief='flat', padx=10, pady=2,
                              cursor='hand2',
                              activebackground='#1b4f72',
                              activeforeground='white',
                              font=('Microsoft YaHei UI', 9, 'bold'))
        search_btn.pack(side=tk.LEFT, pady=10, padx=(0, 6))

        tk.Button(tool_bar, text="✖ 清除",
                   command=self._clear_data_search,
                   bg='#6c7a7d', fg='white',
                   relief='flat', padx=8, pady=2,
                   cursor='hand2',
                   activebackground='#4e5b5d',
                   activeforeground='white',
                   font=('Microsoft YaHei UI', 9)).pack(side=tk.LEFT, pady=10,
                                                          padx=(0, 4))

        self.only_modified_var = tk.BooleanVar(value=False)
        tk.Checkbutton(tool_bar, text="仅显示已修改",
                       variable=self.only_modified_var,
                       bg=self.bg_light, fg='#ecf0f1',
                       selectcolor=self.bg_darker, activebackground=self.bg_light,
                       activeforeground='#ecf0f1',
                       command=self._on_data_search_changed,
                       font=('Microsoft YaHei UI', 9)).pack(side=tk.LEFT,
                                                           padx=8, pady=10)

        tk.Checkbutton(tool_bar, text="显示隐藏键",
                       variable=self._show_hidden_keys_var,
                       bg=self.bg_light, fg='#ecf0f1',
                       selectcolor=self.bg_darker, activebackground=self.bg_light,
                       activeforeground='#ecf0f1',
                       command=self._on_data_search_changed,
                       font=('Microsoft YaHei UI', 9)).pack(side=tk.LEFT,
                                                           padx=8, pady=10)

        # 右侧操作按钮
        tk.Button(tool_bar, text="⊞ 全部展开",
                  command=self._expand_all,
                  bg='#9b59b6', fg='white',
                  font=('Microsoft YaHei UI', 9, 'bold'),
                  relief='flat', cursor='hand2',
                  activebackground='#7d3c98',
                  activeforeground='white').pack(side=tk.RIGHT, padx=(4, 12), pady=10,
                                                ipady=2)

        tk.Button(tool_bar, text="⊟ 全部折叠",
                  command=self._collapse_all,
                  bg='#7f8c8d', fg='white',
                  font=('Microsoft YaHei UI', 9, 'bold'),
                  relief='flat', cursor='hand2',
                  activebackground='#6c7a7d',
                  activeforeground='white').pack(side=tk.RIGHT, padx=4, pady=10,
                                                ipady=2)

        # 数据编辑区 - 虚拟滚动 (Virtual Scroll) 模式：
        # 1) 先将整个 JSON 扁平化为轻量 entries 列表（仅存元数据，不创建控件）
        # 2) Canvas 只在可视范围内动态创建/销毁控件，支持数十万级条目
        data_container = tk.Frame(right_frame, bg=self.bg, bd=0, highlightthickness=0)
        data_container.pack(fill=tk.BOTH, expand=True)
        self._init_virtual_scroll(data_container)

        # 底部操作按钮
        bottom_bar = tk.Frame(right_frame, bg=self.bg_dark, height=72, bd=0, highlightthickness=0)
        bottom_bar.pack(fill=tk.X, side=tk.BOTTOM)
        bottom_bar.pack_propagate(False)

        btn_row = tk.Frame(bottom_bar, bg=self.bg_dark, bd=0, highlightthickness=0)
        btn_row.pack(pady=14)

        tk.Button(btn_row, text="💾 保存当前文件",
                  command=self._save_json_changes,
                  bg='#27ae60', fg='white',
                  font=('Microsoft YaHei UI', 10, 'bold'),
                  relief='flat', padx=22, pady=7,
                  cursor='hand2',
                  activebackground='#1e8449',
                  activeforeground='white').pack(side=tk.LEFT, padx=5)

        tk.Button(btn_row, text="💾 保存所有已修改文件",
                  command=self._save_all_changes,
                  bg='#2980b9', fg='white',
                  font=('Microsoft YaHei UI', 10, 'bold'),
                  relief='flat', padx=22, pady=7,
                  cursor='hand2',
                  activebackground='#1f618d',
                  activeforeground='white').pack(side=tk.LEFT, padx=5)

        tk.Button(btn_row, text="🔄 重置当前文件",
                  command=self._reset_current_file,
                  bg='#e67e22', fg='white',
                  font=('Microsoft YaHei UI', 10, 'bold'),
                  relief='flat', padx=22, pady=7,
                  cursor='hand2',
                  activebackground='#ba4a00',
                  activeforeground='white').pack(side=tk.LEFT, padx=5)

        tk.Button(btn_row, text="🗑 清空全部修改记录",
                  command=self._reset_all_changes,
                  bg='#e74c3c', fg='white',
                  font=('Microsoft YaHei UI', 10, 'bold'),
                  relief='flat', padx=22, pady=7,
                  cursor='hand2',
                  activebackground='#b03a2e',
                  activeforeground='white').pack(side=tk.LEFT, padx=5)

        tk.Button(btn_row, text="📂 打开修改记录目录",
                  command=self._open_changes_dir,
                  bg='#8e44ad', fg='white',
                  font=('Microsoft YaHei UI', 10, 'bold'),
                  relief='flat', padx=22, pady=7,
                  cursor='hand2',
                  activebackground='#6c3483',
                  activeforeground='white').pack(side=tk.LEFT, padx=5)

        self.status_label = tk.Label(right_frame,
                                     text="就绪 - 双击编辑按钮可编辑字段，键名不可修改",
                                     bg=self.bg, fg='#95a5a6',
                                     font=('Microsoft YaHei UI', 9))
        self.status_label.pack(pady=3)

    # ======================= 导航栏 =======================
    def _refresh_nav_bar(self):
        for w in self.nav_inner.winfo_children():
            w.destroy()
        if not self.nav_items:
            tk.Label(self.nav_inner,
                     text="(暂无导航项)",
                     bg=self.bg_dark, fg='#95a5a6',
                     font=('Microsoft YaHei UI', 9)).pack(side=tk.LEFT, padx=10,
                                                         pady=10)
            return
        for item in self.nav_items:
            tk.Button(self.nav_inner, text=item["name"],
                      command=lambda p=item["path"]: self._jump_to_nav_path(p),
                      bg='#3498db', fg='white',
                      font=('Microsoft YaHei UI', 9, 'bold'),
                      relief='flat', padx=14, pady=7,
                      cursor='hand2',
                      activebackground='#2874a6',
                      activeforeground='white').pack(side=tk.LEFT, padx=3, pady=5)

    def _jump_to_nav_path(self, relative_path):
        full_path = os.path.join(self.lang_dir, relative_path)
        if os.path.isdir(full_path):
            messagebox.showinfo("提示",
                                f"请展开文件树中的目录选择文件:\n{relative_path}")
        elif os.path.isfile(full_path):
            self._load_json_file(full_path)
        else:
            messagebox.showwarning("警告", f"未找到文件: {full_path}")

    def _add_current_to_nav(self):
        if not self.current_file:
            messagebox.showwarning("警告", "请先选择一个文件")
            return
        relative = self._relative_to_lang(self.current_file)
        default_name = os.path.basename(self.current_file).replace('.json', '')
        name = simpledialog.askstring("添加导航项", "输入导航项名称:",
                                      initialvalue=default_name,
                                      parent=self.parent_window)
        if not name:
            return
        self.nav_items.append({"name": name, "path": relative})
        self._save_nav_config()
        self._refresh_nav_bar()
        self.status_label.config(text=f"已添加导航项: {name}")

    def _manage_nav_dialog(self):
        dialog = tk.Toplevel(self.parent_window)
        dialog.title("管理导航项")
        dialog.geometry("640x540")
        dialog.configure(bg=self.bg)
        dialog.transient(self.parent_window)
        dialog.grab_set()
        center_window(dialog, False)

        tk.Label(dialog, text="导航项列表 (可上下移动 / 删除):",
                 bg=self.bg, fg='white',
                 font=('Microsoft YaHei UI', 10, 'bold')).pack(pady=10)

        list_frame = tk.Frame(dialog, bg=self.bg, bd=0, highlightthickness=0)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=12)

        listbox = tk.Listbox(list_frame, bg=self.bg_darker, fg='white',
                             font=('Microsoft YaHei UI', 10),
                             selectbackground='#3498db', relief='flat',
                             height=14, bd=0, highlightthickness=0)
        listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar = ttk.Scrollbar(list_frame, command=listbox.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        listbox.configure(yscrollcommand=scrollbar.set)

        def _refresh():
            listbox.delete(0, tk.END)
            for item in self.nav_items:
                listbox.insert(tk.END, f"  {item['name']:20s}  →  {item['path']}")

        _refresh()

        btn_frame = tk.Frame(dialog, bg=self.bg, bd=0, highlightthickness=0)
        btn_frame.pack(fill=tk.X, padx=12, pady=10)

        def move_up():
            sel = listbox.curselection()
            if not sel or sel[0] == 0:
                return
            i = sel[0]
            self.nav_items[i], self.nav_items[i - 1] = self.nav_items[i - 1], self.nav_items[i]
            _refresh()
            listbox.selection_set(i - 1)

        def move_down():
            sel = listbox.curselection()
            if not sel or sel[0] >= len(self.nav_items) - 1:
                return
            i = sel[0]
            self.nav_items[i], self.nav_items[i + 1] = self.nav_items[i + 1], self.nav_items[i]
            _refresh()
            listbox.selection_set(i + 1)

        def delete_item():
            sel = listbox.curselection()
            if not sel:
                return
            del self.nav_items[sel[0]]
            _refresh()

        def add_new():
            from functions.web_update.translation_source import get_translation_dir_name
            name = simpledialog.askstring("新增导航", "名称:", parent=dialog)
            if not name:
                return
            path = simpledialog.askstring("新增导航",
                                          f"相对路径 (如 {get_translation_dir_name()}/UnitKeyword.json):",
                                          parent=dialog)
            if not path:
                return
            self.nav_items.append({"name": name, "path": path})
            _refresh()

        def reset_default():
            if messagebox.askyesno("确认", "恢复默认导航项列表？"):
                self.nav_items = list(DEFAULT_NAV_ITEMS)
                _refresh()

        for label, cmd, color in [
            ("↑上移", move_up, '#3498db'),
            ("↓下移", move_down, '#3498db'),
            ("🗑 删除", delete_item, '#e74c3c'),
            ("➕新增", add_new, '#27ae60'),
            ("↺恢复默认", reset_default, '#9b59b6'),
        ]:
            tk.Button(btn_frame, text=label, command=cmd,
                      bg=color, fg='white', relief='flat',
                      cursor='hand2',
                      activebackground='#1e2a38',
                      activeforeground='white').pack(side=tk.LEFT, padx=4, ipady=3)

        def on_ok():
            self._save_nav_config()
            self._refresh_nav_bar()
            dialog.destroy()

        def on_cancel():
            self._load_nav_config()
            dialog.destroy()

        bottom_frame = tk.Frame(dialog, bg=self.bg, bd=0, highlightthickness=0)
        bottom_frame.pack(fill=tk.X, pady=12)
        tk.Button(bottom_frame, text="确定", command=on_ok,
                  bg='#27ae60', fg='white', relief='flat',
                  cursor='hand2', width=12).pack(side=tk.LEFT, padx=60, ipady=4)
        tk.Button(bottom_frame, text="取消", command=on_cancel,
                  bg='#7f8c8d', fg='white', relief='flat',
                  cursor='hand2', width=12).pack(side=tk.RIGHT, padx=60, ipady=4)

    # ======================= 文件树 =======================
    def _refresh_file_tree(self):
        for item in self.file_tree.get_children():
            self.file_tree.delete(item)
        root_node = self.file_tree.insert('', 'end', text=" lang",
                                          values=("", "dir"))
        Thread(target=self._build_tree, args=(root_node, self.lang_dir),
               daemon=True).start()
        self.file_tree.item(root_node, open=True)
        self.status_label.config(text="文件树已刷新")

    def _refresh_file_tree_async(self):
        """异步刷新文件树（带遮罩），避免大目录时 UI 卡顿"""
        self._show_loading("刷新文件树中...")

        def _worker():
            try:
                # 在主线程清空 Treeview（Treeview 操作必须在主线程）
                def _clear_and_build():
                    for item in self.file_tree.get_children():
                        self.file_tree.delete(item)
                    root_node = self.file_tree.insert('', 'end', text=" lang",
                                                      values=("", "dir"))
                    self.file_tree.item(root_node, open=True)
                    # _build_tree 本身已是线程化的
                    Thread(target=lambda: (self._build_tree(root_node, self.lang_dir),
                                           self.parent_window.after(0, self._on_tree_refresh_done)),
                           daemon=True).start()

                self.parent_window.after(0, _clear_and_build)
            except Exception as e:
                print(f"[refresh_file_tree_async] 错误: {e}")
                self.parent_window.after(0, self._on_tree_refresh_done)

        Thread(target=_worker, daemon=True).start()

    def _on_tree_refresh_done(self):
        """文件树刷新完成回调"""
        self._hide_loading()
        self.status_label.config(text="文件树刷新完成")

    def _build_tree(self, parent, path):
        try:
            items = sorted(os.listdir(path), key=lambda x: x.lower())
            dirs = []
            files = []
            for item in items:
                if item.startswith('_'):
                    continue
                item_path = os.path.join(path, item)
                if os.path.isdir(item_path):
                    dirs.append(item)
                elif item.lower().endswith('.json') and item != 'changes.json':
                    files.append(item)

            for dir_name in dirs:
                dir_path = os.path.join(path, dir_name)
                relative = self._relative_to_lang(dir_path)
                node = self.file_tree.insert(parent, 'end',
                                             text=f"  📂  {dir_name}",
                                             values=(relative, "dir"))
                self._build_tree(node, dir_path)

            for file_name in files:
                file_path = os.path.join(path, file_name)
                relative = self._relative_to_lang(file_path)
                has_changes = self._has_changes_for_relative(relative)
                prefix = "✏  " if has_changes else "    "
                self.file_tree.insert(parent, 'end',
                                      text=f"  {prefix}{file_name}",
                                      values=(relative, "file"))
        except Exception as e:
            print(f"构建文件树错误: {e}")

    def _on_tree_selected(self, event):
        selection = self.file_tree.selection()
        if selection:
            item = selection[0]
            values = self.file_tree.item(item, 'values')
            if values and len(values) >= 2 and values[1] == "file":
                file_path = os.path.join(self.lang_dir, values[0])
                self._load_json_file(file_path)

    def _on_search_changed(self, event):
        keyword = self.search_var.get().lower().strip()
        for item in self.file_tree.get_children():
            self._filter_tree_items(item, keyword)
        if keyword:
            for item in self.file_tree.get_children():
                self._expand_matching_parents(item, keyword)

    def _filter_tree_items(self, item, keyword):
        text = self.file_tree.item(item, 'text').lower()
        has_matching = False
        for child in self.file_tree.get_children(item):
            if self._filter_tree_items(child, keyword):
                has_matching = True
        if not keyword or keyword in text or has_matching:
            self.file_tree.reattach(item, self.file_tree.parent(item),
                                    self.file_tree.index(item))
            return True
        else:
            self.file_tree.detach(item)
            return False

    def _expand_matching_parents(self, item, keyword):
        text = self.file_tree.item(item, 'text').lower()
        for child in self.file_tree.get_children(item):
            if self._expand_matching_parents(child, keyword):
                self.file_tree.item(item, open=True)
                return True
        if keyword in text:
            self.file_tree.item(self.file_tree.parent(item), open=True)
            return True
        return False

    # ======================= 加载 JSON (多线程) =======================
    def _load_json_file(self, file_path):
        """后台线程读取 JSON 并构建视图，避免大文件阻塞 UI。
        关键：切换文件前先把当前文件的修改同步到 changes（内存），
        这样切回来时不会丢失用户已做的编辑。"""

        # 切换之前：如果当前文件有未保存的修改，先同步到 self.changes（内存层）
        if self.current_file and self.original_data is not None and self.modified_data is not None:
            try:
                relative = self._relative_to_lang(self.current_file)
                diff = self._compute_diff(self.original_data, self.modified_data)
                if diff is not None:
                    self._set_changes_for_relative(relative, diff)  # 只改内存，不写磁盘
                else:
                    self._delete_changes_for_relative(relative)
            except Exception:
                pass

        def _worker():
            try:
                # 1. 读取文件
                with open(file_path, 'r', encoding='utf-8') as f:
                    loaded_data = json.load(f)

                # 2. 深拷贝
                modified = self._deep_copy(loaded_data)
                # 3. 应用已有的 changes
                self._apply_changes_to_data_standalone(modified, file_path)

                # 保存到主线程
                self._current_original_data = loaded_data
                self._current_modified_data = modified # type: ignore
                self._current_file_path = file_path # type: ignore

                # 回到主线程更新 UI
                self.parent_window.after(0, self._finish_loading_file)
            except Exception as e:
                err = str(e)
                self.parent_window.after(0, lambda: self._fail_loading_file(err))

        self._show_loading(f"加载 {os.path.basename(file_path)} 中...")
        Thread(target=_worker, daemon=True).start()

    def _finish_loading_file(self):
        self.original_data = self._current_original_data
        self.modified_data = self._current_modified_data # type: ignore
        self.current_file = self._current_file_path # type: ignore

        relative = self._relative_to_lang(self.current_file) # type: ignore
        self.current_file_label.config(text=f"📄 当前文件: {relative}")

        self.data_search_var.set("")
        self.only_modified_var.set(False)
        self._search_keyword = ""
        self._only_modified = False

        # 构建数据视图（若文件很大，也放到线程 + 分批，但这里直接构建）
        self._refresh_data_view(preserve_scroll=False)  # 新文件 → 滚到顶部
        self._hide_loading()
        self.status_label.config(text=f"加载成功: {relative}")

    def _fail_loading_file(self, err):
        self._hide_loading()
        messagebox.showerror("错误", f"加载文件失败: {err}")

    def _apply_changes_to_data_standalone(self, data, file_path):
        relative = self._relative_to_lang(file_path)
        changes = self._get_changes_for_relative(relative)
        if changes is not None:
            self._recursive_apply(data, changes)

    def _deep_copy(self, data):
        if isinstance(data, dict):
            return {k: self._deep_copy(v) for k, v in data.items()}
        elif isinstance(data, list):
            return [self._deep_copy(v) for v in data]
        else:
            return data

    def _recursive_apply(self, original, changes):
        if isinstance(original, dict) and isinstance(changes, dict):
            for k, v in changes.items():
                if k in original:
                    if isinstance(original[k], (dict, list)) and isinstance(v, (dict, list)):
                        self._recursive_apply(original[k], v)
                    else:
                        original[k] = v
        elif isinstance(original, list) and isinstance(changes, list):
            id_map = {}
            for idx, item in enumerate(original):
                if isinstance(item, dict) and 'id' in item:
                    id_map[item['id']] = idx  # 保留原始 id 类型
            for key, value in list(id_map.items()):
                id_map[str(key)] = value
            for idx, change in enumerate(changes):
                if isinstance(change, dict) and 'id' in change and 'changes' in change:
                    target_id = change['id']  # 保留原始 id 类型
                    change_data = change.get('changes', {})
                    target_idx = id_map.get(target_id, id_map.get(str(target_id)))
                    if target_idx is not None:
                        orig_item = original[target_idx]
                        if isinstance(orig_item, (dict, list)) and isinstance(change_data, (dict, list)):
                            self._recursive_apply(orig_item, change_data)
                        else:
                            original[target_idx] = change_data
                elif idx < len(original):
                    if isinstance(original[idx], (dict, list)) and isinstance(change, (dict, list)):
                        self._recursive_apply(original[idx], change)
                    else:
                        original[idx] = change

    # ======================= 数据视图 (虚拟滚动 Virtual Scroll) =======================

    # 每个条目的高度（像素），由虚拟滚动统一使用
    _ROW_HEIGHT = 36
    # 可视区域外额外渲染的条目数（缓冲，避免滚动时立刻看到空白）
    # 与可视区域行数成正比，不盲目用大数字
    _BUFFER_ROWS = 50

    def _init_virtual_scroll(self, parent):
        """初始化虚拟滚动的 Canvas + Scrollbar + 事件绑定"""
        self.data_canvas = tk.Canvas(parent, bg=self.bg,
                                     highlightthickness=0, bd=0)
        self.data_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        data_scroll = ttk.Scrollbar(parent, orient=tk.VERTICAL,
                                    command=self.data_canvas.yview)
        data_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # 渲染缓存：{entry_index: (canvas_item_id, frame_widget)}
        # 关键：必须同时保存 canvas item ID（整数）和 widget，否则
        # canvas.delete(widget) 不可靠——Tk canvas 需要 item ID 才能正确删除
        self._rendered_widgets = {}
        # 扁平化条目
        self._flat_entries = []
        # 防止递归重渲染
        self._in_render = False
        # 记录 entries 总数（变化时才更新 scrollregion）
        self._entries_count = 0
        # 延迟渲染调度 id，用于合并多次滚动/resize 事件
        self._pending_render_id = None

        def _tracked_yscroll(*args):
            """yview 回调：更新滚动条 + 延迟重渲染
            直接在这里调用 _render_visible 会导致 scrollregion→yview 链死循环
            """
            data_scroll.set(*args)
            if hasattr(self, '_flat_entries') and self._flat_entries:
                self._schedule_render()

        self.data_canvas.configure(yscrollcommand=_tracked_yscroll)

        # Canvas 配置事件（大小变化）
        self.data_canvas.bind("<Configure>", self._on_virtual_canvas_configure)
        # 滚动时重渲染
        self.data_canvas.bind("<Enter>",
                              lambda e: self.data_canvas.bind_all("<MouseWheel>",
                                                                  self._on_virtual_mousewheel))
        self.data_canvas.bind("<Leave>",
                              lambda e: self.data_canvas.unbind_all("<MouseWheel>"))

    def _on_virtual_mousewheel(self, event):
        """鼠标滚轮事件 - 只在编辑区聚焦时触发"""
        try:
            x, y = event.x_root, event.y_root
            wx = self.data_canvas.winfo_rootx()
            wy = self.data_canvas.winfo_rooty()
            ww = self.data_canvas.winfo_width()
            wh = self.data_canvas.winfo_height()
            if wx <= x <= wx + ww and wy <= y <= wy + wh:
                self.data_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
                self._schedule_render()
        except Exception:
            pass

    def _on_virtual_canvas_configure(self, event):
        """Canvas 大小改变时：更新渲染窗口宽度 + 延迟重渲染"""
        try:
            for item_id, widget in list(self._rendered_widgets.values()):
                try:
                    self.data_canvas.itemconfigure(item_id, width=event.width)
                except Exception:
                    pass
            self._schedule_render()
        except Exception:
            pass

    def _schedule_render(self):
        """合并多次滚动/resize 事件，延迟统一渲染，避免 UI 抖动"""
        if self._in_render:
            return
        if self._pending_render_id is not None:
            try:
                self.parent_window.after_cancel(self._pending_render_id)
            except Exception:
                pass
        self._pending_render_id = self.parent_window.after(
            15, self._render_visible)

    def _flatten_data(self):
        """核心：把整个 JSON 树扁平化为一维条目列表（纯数据，不创建控件）。
        每个 entry 是一个 dict，包含渲染时所需的全部元数据。
        通过 self._collapsed_paths 集合来跳过已折叠容器的子项。"""
        entries = []
        if not hasattr(self, '_collapsed_paths'):
            self._collapsed_paths = set()

        def walk(current, original, title, depth, dict_key=None,
                 list_index=None, id_value=None, is_root=False,
                 parent_path=""):
            is_container = isinstance(current, (dict, list))
            # 键黑名单过滤（只对有 dict_key 的叶子生效；容器的键如 "id" 不是常见情形
            # 这里为保守起见只过滤叶子节点的键）
            if not is_container and dict_key is not None:
                if not self._show_hidden_keys_var.get() and dict_key in HIDDEN_KEYS:
                    return  # 跳过隐藏的叶子

            # 对叶子节点做"仅显示已修改"和"搜索"过滤
            if not is_container:
                is_modified = (original != current)
                if self._only_modified and not is_modified:
                    return
                value_str = str(current)
                # 搜索范围：键名 + 值 + 所在记录的 id（如果有）
                search_parts = [str(dict_key) if dict_key is not None else "",
                                value_str]
                if id_value is not None:
                    search_parts.append(str(id_value))
                text_to_search = " ".join(search_parts).lower()
                if self._search_keyword and self._search_keyword not in text_to_search:
                    return

            # 计算此容器的唯一 path（用于折叠/展开记忆）
            path = parent_path + "/" + (str(dict_key) if dict_key is not None else
                                         (f"[{list_index}]" if list_index is not None else "root"))

            entry = {
                'title': title,
                'current': current,
                'original': original,
                'depth': depth,
                'is_container': is_container,
                'is_root': is_root,
                'dict_key': dict_key,
                'list_index': list_index,
                'id_value': str(id_value) if id_value is not None else None,
                'expanded': (path not in self._collapsed_paths),
                'is_container_header': is_container,
                'path': path,
            }

            # 对容器内部内容做同样的过滤；若容器过滤后内容为空则跳过
            if is_container:
                entries.append(entry)  # 先放入容器头
                # 如果容器被折叠（且不是搜索/仅修改模式），直接跳过子项遍历
                # —— 搜索/过滤模式下强制展开，否则匹配项可能被隐藏
                force_expand = bool(self._search_keyword) or self._only_modified
                if not force_expand and path in self._collapsed_paths and not is_root:
                    return
                has_visible_child = False
                if isinstance(current, dict):
                    show_hidden = self._show_hidden_keys_var.get()
                    for k, v in current.items():
                        if not show_hidden and k in HIDDEN_KEYS and not isinstance(v, (dict, list)):
                            continue
                        orig_v = original.get(k) if isinstance(original, dict) else None
                        child_id = v if k == 'id' else None
                        before = len(entries)
                        walk(v, orig_v, k, depth + 1,
                             dict_key=k, id_value=child_id, parent_path=path)
                        if len(entries) > before:
                            has_visible_child = True
                else:  # list
                    has_ids = all(isinstance(it, dict) and 'id' in it for it in current)
                    for i, item in enumerate(current):
                        orig_item = original[i] if (
                            isinstance(original, list) and i < len(original)) else None
                        sub_id = None
                        if isinstance(item, dict) and 'id' in item:
                            sub_id = str(item['id'])
                        if has_ids and sub_id is not None:
                            sub_title = f"[{i + 1}] id = {sub_id}"
                        elif isinstance(item, dict):
                            keys = ", ".join(list(item.keys())[:4])
                            if len(item) > 4:
                                keys += "..."
                            sub_title = f"[{i + 1}] {{ {keys} }}"
                        elif isinstance(item, list):
                            sub_title = f"[{i + 1}] [ ... {len(item)} 项 ]"
                        else:
                            sub_title = f"[{i + 1}] {str(item)[:50]}"
                        before = len(entries)
                        walk(item, orig_item, sub_title, depth + 1,
                             list_index=i, id_value=sub_id, parent_path=path)
                        if len(entries) > before:
                            has_visible_child = True
                # 如果容器过滤后没有可见子项，把它自己也移除（除非是根）
                if not has_visible_child and not is_root:
                    entries.pop()
            else:
                entries.append(entry)

        if self.current_file and (isinstance(self.modified_data, (dict, list))):
            walk(self.modified_data, self.original_data,
                 "📄 JSON 内容", 0, is_root=True)

        return entries

    def _render_visible(self):
        """虚拟滚动核心：根据 yview 位置，只渲染可见 + 缓冲范围内的条目
        关键修复：
        1. _rendered_widgets 存储 (canvas_item_id:int, widget) 元组
        2. 销毁时必须 canvas.delete(item_id) + widget.destroy()，缺一不可
        3. scrollregion 仅在条目数变化时更新，避免触发 yview 回调死循环
        """
        if not hasattr(self, '_flat_entries') or self._in_render:
            return
        self._in_render = True
        self._pending_render_id = None
        try:
            canvas = self.data_canvas
            total = len(self._flat_entries)
            if total == 0:
                # 清空所有已渲染控件
                for item_id, widget in list(self._rendered_widgets.values()):
                    try:
                        canvas.delete(item_id)
                    except Exception:
                        pass
                    try:
                        widget.destroy()
                    except Exception:
                        pass
                self._rendered_widgets.clear()
                canvas.configure(scrollregion=(0, 0, 0, 0))
                return

            # 仅在总数变化时更新 scrollregion（减少 yview 回调链）
            if self._entries_count != total:
                self._entries_count = total
                canvas.configure(scrollregion=(0, 0, 0, total * self._ROW_HEIGHT))

            # 可视范围 [first_index, last_index)
            canvas_h = canvas.winfo_height()
            if canvas_h <= 1:
                canvas_h = 600  # canvas 尚未布局，给一个默认值
            view_top = canvas.canvasy(0)
            view_bottom = canvas.canvasy(canvas_h)
            first_idx = max(0, int(view_top // self._ROW_HEIGHT) - self._BUFFER_ROWS)
            last_idx = min(total, int((view_bottom + self._ROW_HEIGHT - 1)
                                      // self._ROW_HEIGHT) + self._BUFFER_ROWS)

            # 销毁不再在可视范围内的控件
            for idx in list(self._rendered_widgets.keys()):
                if idx < first_idx or idx >= last_idx:
                    item_id, widget = self._rendered_widgets[idx]
                    try:
                        canvas.delete(item_id)
                    except Exception:
                        pass
                    try:
                        widget.destroy()
                    except Exception:
                        pass
                    del self._rendered_widgets[idx]

            # 渲染新进入可视范围的条目
            canvas_width = max(100, canvas.winfo_width())
            for idx in range(first_idx, last_idx):
                if idx in self._rendered_widgets:
                    continue
                if idx >= len(self._flat_entries):
                    break
                entry = self._flat_entries[idx]
                y = idx * self._ROW_HEIGHT
                widget = self._create_row_widget(entry, idx, canvas_width)
                if widget is not None:
                    # 关键：canvas.create_window 返回 item ID（整数），必须保存
                    item_id = canvas.create_window(0, y, window=widget,
                                                   anchor='nw', width=canvas_width)
                    self._rendered_widgets[idx] = (item_id, widget)
        finally:
            self._in_render = False

    def _create_row_widget(self, entry, index, canvas_width):
        """为单个 entry 创建一行控件"""
        depth = entry['depth']
        is_container = entry['is_container']
        is_root = entry['is_root']
        bg_color = self._get_depth_color(depth)
        row_bg = darken_color(bg_color, 0.92) if is_container else bg_color

        frame = tk.Frame(self.data_canvas, bg=row_bg, bd=0,
                         highlightthickness=0, height=self._ROW_HEIGHT)
        frame.pack_propagate(False)

        # 缩进
        indent_px = depth * 14
        if indent_px > 0:
            tk.Frame(frame, bg=row_bg, width=indent_px,
                     bd=0, highlightthickness=0).pack(side=tk.LEFT)

        # 左侧蓝色竖线（装饰）
        if depth > 0 or is_container:
            line = tk.Frame(frame, bg='#3498db', width=2,
                            bd=0, highlightthickness=0)
            line.pack(side=tk.LEFT, fill=tk.Y)
            line.pack_propagate(False)

        if is_container:
            # 容器头部：▼/▶ + 标题 + 信息
            toggle_text = "▼" if entry['expanded'] else "▶"
            toggle = tk.Label(frame, text=toggle_text,
                              bg=row_bg, fg='#7be2f7',
                              font=('Microsoft YaHei UI', 9, 'bold'),
                              cursor='hand2', padx=6)
            toggle.pack(side=tk.LEFT)
            toggle.bind("<Button-1>",
                        lambda e, i=index: self._toggle_container(i))

            title_label = tk.Label(frame, text=entry['title'],
                                   bg=row_bg, fg='#ecf0f1',
                                   font=('Microsoft YaHei UI', 9, 'bold'),
                                   anchor='w', cursor='hand2')
            title_label.pack(side=tk.LEFT, padx=(2, 8))
            title_label.bind("<Button-1>",
                             lambda e, i=index: self._toggle_container(i))

            # 统计容器信息（延迟计算，只看当前层级）
            info_text = ""
            current = entry['current']
            if isinstance(current, dict):
                info_text = f"{len(current)} 项"
            elif isinstance(current, list):
                info_text = f"{len(current)} 项"
            if info_text:
                tk.Label(frame, text=info_text,
                         bg=row_bg, fg='#95a5a6',
                         font=('Microsoft YaHei UI', 8)).pack(side=tk.RIGHT, padx=12)

        else:
            # 叶子节点：键名 + 值 + 编辑按钮
            dict_key = entry['dict_key']
            is_modified = (entry['original'] != entry['current'])
            key_text = str(dict_key) if dict_key is not None else "(值)"
            key_color = '#f1c40f' if is_modified else '#ecf0f1'

            key_label = tk.Label(frame, text=f"🔑 {key_text}",
                                 bg=row_bg, fg=key_color,
                                 font=('Microsoft YaHei UI', 9, 'bold'),
                                 anchor='w')
            key_label.pack(side=tk.LEFT, padx=(4, 10))

            if is_modified:
                tk.Label(frame, text="●", bg=row_bg,
                         fg='#e67e22', font=('Microsoft YaHei UI', 12)).pack(
                    side=tk.RIGHT, padx=(4, 4))

            # 编辑按钮（放在右侧，确保不被挤掉）
            if dict_key == 'id':
                tk.Label(frame, text="[只读·id]",
                         bg=row_bg, fg='#bdc3c7',
                         font=('Microsoft YaHei UI', 8)).pack(side=tk.RIGHT, padx=8)
            else:
                btn_text = "✏ 已修改" if is_modified else "✏ 编辑"
                btn_color = '#e67e22' if is_modified else '#27ae60'
                btn_hover = '#ba4a00' if is_modified else '#1e8449'
                btn = tk.Button(frame, text=btn_text,
                                bg=btn_color, fg='white',
                                relief='flat', padx=10, pady=0,
                                cursor='hand2',
                                activebackground=btn_hover,
                                activeforeground='white',
                                font=('Microsoft YaHei UI', 8, 'bold'))
                btn.configure(command=lambda k=dict_key,
                                       cv=entry['current'],
                                       ov=entry['original'],
                                       iv=entry['id_value'],
                                       li=entry['list_index'],
                                       d=depth,
                                       p=entry['path']:
                    self._open_edit_dialog(k, cv, ov, iv, li, d, p))
                btn.pack(side=tk.RIGHT, padx=(6, 8))

            # 值文本（填充中间空间，不挤按钮）
            value_str = str(entry['current'])
            short_text = value_str if len(value_str) < 80 else value_str[:77] + "..."
            val_color = '#f1c40f' if is_modified else '#ecf0f1'
            value_label = tk.Label(frame, text=short_text,
                                   bg=row_bg, fg=val_color,
                                   font=('Microsoft YaHei UI', 9),
                                   anchor='w', justify=tk.LEFT)
            value_label.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)

        # 绑定鼠标滚轮（让行内控件也能滚动编辑区）
        def _row_mousewheel(event):
            self._on_virtual_mousewheel(event)

        self._bind_to_hierarchy(frame, _row_mousewheel)
        return frame

    def _bind_to_hierarchy(self, widget, handler):
        """递归绑定鼠标滚轮事件到 widget 及其子控件"""
        try:
            widget.bind("<MouseWheel>", handler)
        except Exception:
            pass
        try:
            for child in widget.winfo_children():
                self._bind_to_hierarchy(child, handler)
        except Exception:
            pass

    def _toggle_container(self, index):
        """点击容器头部切换展开/折叠。
        用 yview 比例保留滚动位置，不做 target_path 定位，避免视觉上跳到顶部。"""
        if not hasattr(self, '_collapsed_paths'):
            self._collapsed_paths = set()
        if index < 0 or index >= len(self._flat_entries):
            return
        entry = self._flat_entries[index]
        if not entry['is_container']:
            return
        target_path = entry['path']
        if target_path in self._collapsed_paths:
            self._collapsed_paths.remove(target_path)
        else:
            self._collapsed_paths.add(target_path)

        # 用 yview 比例保留滚动（折叠/展开时总数变化，像素值会变）
        try:
            saved_fraction = self.data_canvas.yview()[0]
        except Exception:
            saved_fraction = 0.0

        self._refresh_data_view(preserve_scroll_fraction=saved_fraction)

    def _refresh_data_view(self, preserve_scroll=True, target_index=None,
                            target_path=None, preserve_scroll_pixel=None,
                            preserve_scroll_fraction=None):
        """虚拟滚动版：刷新数据视图。
        参数优先级（从高到低）：
        1. target_path / target_index → 定位到特定条目（编辑后用）
        2. preserve_scroll_fraction → 按比例保留（折叠/展开时用，最可靠）
        3. preserve_scroll_pixel → 按像素保留（结构不变时用）
        4. preserve_scroll=True → 按 yview()[0] 比例保留（默认）
        5. preserve_scroll=False → 滚到顶部
        """
        canvas = self.data_canvas

        # 保存当前滚动位置（多种方式）
        saved_fraction = 0.0
        try:
            if preserve_scroll:
                saved_fraction = canvas.yview()[0]
        except Exception:
            saved_fraction = 0.0

        saved_pixel = None
        if preserve_scroll_pixel is not None:
            saved_pixel = float(preserve_scroll_pixel)

        # 2) 只销毁我们自己追踪的已渲染控件，减少撕裂
        try:
            for idx in list(self._rendered_widgets.keys()):
                item_id, widget = self._rendered_widgets[idx]
                try:
                    canvas.delete(item_id)
                except Exception:
                    pass
                try:
                    widget.destroy()
                except Exception:
                    pass
            self._rendered_widgets.clear()
        except Exception:
            pass

        if not self.current_file:
            self._flat_entries = []
            self._entries_count = 0
            canvas.configure(scrollregion=(0, 0, 0, 300))
            hint = tk.Label(canvas,
                            text="\n  请从左侧文件树选择一个 JSON 文件开始编辑\n",
                            bg=self.bg, fg='#95a5a6',
                            font=('Microsoft YaHei UI', 13, 'bold'))
            cw = canvas.winfo_width()
            hint_x = cw // 2 if cw > 0 else 400
            item_id = canvas.create_window(hint_x, 60, window=hint, anchor='n')
            self._rendered_widgets[-1] = (item_id, hint)
            self.status_label.config(text="就绪 - 虚拟滚动模式已启用")
            return

        self._search_keyword = self.data_search_var.get().lower().strip()
        self._only_modified = self.only_modified_var.get()

        # 3) 扁平化（纯数据，不生成控件 - 这是最快的一步）
        self._flat_entries = self._flatten_data()

        # 4) 计数修改
        total_modified = 0
        for e in self._flat_entries:
            if not e['is_container'] and e['original'] != e['current']:
                total_modified += 1
        if total_modified > 0:
            self.changes_count_label.config(
                text=f"✏ 已修改 {total_modified} 项 (需点击 [保存到 changes.json] 确认)")
        else:
            self.changes_count_label.config(text="")

        total = len(self._flat_entries)
        self._entries_count = 0  # 让 _render_visible 重新计算 scrollregion

        # 先设置 yview 位置，再渲染 —— 让 render 从正确的可视范围开始
        # 优先级：target_path/target_index (定位) > preserve_scroll_fraction > saved_pixel > preserve_scroll
        if total > 0:
            if target_path is not None:
                # 定位到指定 path：让它出现在可视区域 1/3 处，不贴顶
                target_idx = None
                for i, e in enumerate(self._flat_entries):
                    if e.get('path') == target_path:
                        target_idx = i
                        break
                if target_idx is not None:
                    total_height = total * self._ROW_HEIGHT
                    if total_height > 0:
                        top_y = max(0, target_idx * self._ROW_HEIGHT - self._ROW_HEIGHT * 2)
                        canvas.yview_moveto(max(0.0, top_y / total_height))
                elif preserve_scroll:
                    canvas.yview_moveto(saved_fraction)
                else:
                    canvas.yview_moveto(0)
            elif target_index is not None:
                idx = max(0, min(int(target_index), total - 1))
                top_y = max(0, idx * self._ROW_HEIGHT - self._ROW_HEIGHT * 2)
                total_height = total * self._ROW_HEIGHT
                if total_height > 0:
                    canvas.yview_moveto(top_y / total_height)
            elif preserve_scroll_fraction is not None:
                # **关键修复：** 折叠/展开时条目总数变化，像素值会变，
                # 但 yview 比例不变，直接用比例保留最准确
                canvas.yview_moveto(max(0.0, min(1.0, float(preserve_scroll_fraction))))
            elif saved_pixel is not None:
                # 按像素保留（结构不变时用）
                total_height = total * self._ROW_HEIGHT
                if total_height > 0:
                    ratio = max(0.0, min(1.0, saved_pixel / total_height))
                    canvas.yview_moveto(ratio)
            elif preserve_scroll:
                canvas.yview_moveto(saved_fraction)
            else:
                canvas.yview_moveto(0)
        else:
            canvas.yview_moveto(0)

        # 6) 渲染可视范围内的控件
        self._in_render = False
        self._render_visible()

        self.status_label.config(
            text=f"虚拟滚动模式：共 {total} 个条目，"
                 f"仅渲染可视范围内控件")

    # ======================= 颜色/样式 =======================

    def _get_depth_color(self, depth):
        """根据深度在 lighten_bg_color 基础上渐暗"""
        base = self.bg_light
        factor = max(0.55, 0.92 - depth * 0.05)
        return darken_color(base, factor)

    def _build_pane(self, parent, current_data, original_data,
                    title, depth, changes_count,
                    is_root=False, dict_key=None, list_index=None,
                    id_value=None):
        """递归构建可折叠面板"""
        bg_color = self._get_depth_color(depth)
        is_container = isinstance(current_data, (dict, list))

        pane = CollapsiblePane(parent, title, self.root,
                               bg_color=bg_color, is_container=is_container,
                               is_root=is_root,
                               meta={'dict_key': dict_key,
                                     'list_index': list_index,
                                     'id_value': id_value,
                                     'depth': depth})
        pane.pack(fill=tk.X, padx=8, pady=3)
        self._all_panes.append(pane)

        if isinstance(current_data, dict):
            total = len(current_data)
            modified_count = 0
            visible_count = 0
            show_hidden = self._show_hidden_keys_var.get()
            for k, v in current_data.items():
                # 键黑名单过滤：除非勾选"显示隐藏键"，否则跳过 HIDDEN_KEYS 中的键
                if not show_hidden and k in HIDDEN_KEYS:
                    continue
                orig_v = original_data.get(k) if isinstance(original_data, dict) else None
                is_id = (k == 'id')
                if self._build_pane(pane.body_inner, v, orig_v,
                                    k, depth + 1, changes_count,
                                    dict_key=k,
                                    id_value=(v if is_id else None)):
                    visible_count += 1
                if orig_v != v:
                    modified_count += 1

            info_parts = []
            if total > 0:
                info_parts.append(f"{total} 项")
            if modified_count > 0:
                info_parts.append(f"{modified_count} 已修改")
            if info_parts:
                pane.set_info(" / ".join(info_parts),
                              '#e67e22' if modified_count > 0 else '#95a5a6')

            if visible_count == 0 and not is_root:
                pane.destroy()
                return False
            return True

        elif isinstance(current_data, list):
            total = len(current_data)
            modified_count = 0
            visible_count = 0
            has_ids = all(isinstance(it, dict) and 'id' in it for it in current_data)

            for i, item in enumerate(current_data):
                orig_item = original_data[i] if (
                        isinstance(original_data, list) and i < len(original_data)) else None
                item_id = None
                if isinstance(item, dict) and 'id' in item:
                    item_id = str(item['id'])

                if has_ids and item_id is not None:
                    sub_title = f"[{i + 1}] id = {item_id}"
                elif isinstance(item, dict):
                    keys = ", ".join(list(item.keys())[:4])
                    if len(item) > 4:
                        keys += "..."
                    sub_title = f"[{i + 1}] {{ {keys} }}"
                elif isinstance(item, list):
                    sub_title = f"[{i + 1}] [ ... {len(item)} 项 ]"
                else:
                    sub_title = f"[{i + 1}] {str(item)[:50]}"

                if self._build_pane(pane.body_inner, item, orig_item,
                                    sub_title, depth + 1, changes_count,
                                    list_index=i, id_value=item_id):
                    visible_count += 1
                if orig_item != item:
                    modified_count += 1

            info_parts = []
            if total > 0:
                info_parts.append(f"{total} 项")
            if modified_count > 0:
                info_parts.append(f"{modified_count} 已修改")
            if info_parts:
                pane.set_info(" / ".join(info_parts),
                              '#e67e22' if modified_count > 0 else '#95a5a6')

            if visible_count == 0 and not is_root:
                pane.destroy()
                return False
            return True

        else:
            # 叶子节点：渲染为一行
            is_id_field = (dict_key == 'id')
            is_modified = (original_data != current_data)
            if is_modified:
                changes_count[0] += 1

            # 键黑名单过滤（叶子节点）
            if not self._show_hidden_keys_var.get() and dict_key in HIDDEN_KEYS:
                return False

            # 搜索过滤
            value_str = str(current_data)
            text_to_search = f"{str(dict_key)} {value_str}".lower()
            if self._only_modified and not is_modified:
                return False
            if self._search_keyword and self._search_keyword not in text_to_search:
                return False

            # 构建一行
            row_bg = pane.body_bg
            row = tk.Frame(pane.body_inner, bg=row_bg, bd=0, highlightthickness=0)
            row.pack(fill=tk.X, padx=2, pady=1)

            # 键名：不使用固定 width，改用 pad 限制
            key_text = str(dict_key) if dict_key is not None else "(值)"
            key_color = '#f1c40f' if is_modified else '#ecf0f1'

            # 左侧：键名
            key_label = tk.Label(row, text=f"🔑 {key_text}",
                                 bg=row_bg, fg=key_color,
                                 font=('Microsoft YaHei UI', 9, 'bold'),
                                 anchor='w', justify=tk.LEFT)
            key_label.pack(side=tk.LEFT, padx=(4, 10), pady=4)

            # 修改标记（放在右侧）
            if is_modified:
                tk.Label(row, text="●", bg=row_bg, fg='#e67e22',
                         font=('Microsoft YaHei UI', 12)).pack(side=tk.RIGHT, padx=(4, 8), pady=4)

            # 值显示
            if is_id_field or not isinstance(current_data, str):
                # 只读字段：显示截断文字 + 类型标注
                short_text = value_str if len(value_str) < 60 else value_str[:57] + "..."
                val_color = '#bdc3c7'
                # 中间使用可扩展的 Label，让按钮固定在右侧
                value_label = tk.Label(row, text=short_text, bg=row_bg, fg=val_color,
                                       font=('Microsoft YaHei UI', 9),
                                       anchor='w', justify=tk.LEFT)
                value_label.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4, pady=4)

                type_label = tk.Label(row,
                                      text=f"[只读·{type(current_data).__name__}]",
                                      bg=row_bg, fg='#7f8c8d',
                                      font=('Microsoft YaHei UI', 8))
                type_label.pack(side=tk.RIGHT, padx=(4, 8), pady=4)
            else:
                # 可编辑：先放按钮（RIGHT），然后用 expand 文本填充中间
                btn_text = "✏ 已修改" if is_modified else "✏ 编辑"
                btn_color = '#e67e22' if is_modified else '#27ae60'
                btn_hover = '#ba4a00' if is_modified else '#1e8449'

                # 先放按钮到最右边，保证不被挤掉
                edit_btn = tk.Button(row, text=btn_text,
                                     command=lambda k=dict_key, cv=current_data,
                                                    ov=original_data, lv=id_value,
                                                    li=list_index, d=depth:
                                     self._open_edit_dialog(k, cv, ov, lv, li, d),
                                     bg=btn_color, fg='white',
                                     font=('Microsoft YaHei UI', 8, 'bold'),
                                     relief='flat', padx=12, pady=2,
                                     cursor='hand2',
                                     activebackground=btn_hover,
                                     activeforeground='white')
                edit_btn.pack(side=tk.RIGHT, padx=(4, 8), pady=3)

                # 再用扩展 Label 显示文字截断（不会挤掉按钮）
                short_text = value_str if len(value_str) < 80 else value_str[:77] + "..."
                val_color = '#f1c40f' if is_modified else '#ecf0f1'
                value_label = tk.Label(row, text=short_text, bg=row_bg, fg=val_color,
                                       font=('Microsoft YaHei UI', 9),
                                       anchor='w', justify=tk.LEFT)
                value_label.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4, pady=4)

            self._all_panes.append(row)
            return True

    # ======================= 编辑对话框 =======================
    def _open_edit_dialog(self, dict_key, current_value, original_value,
                          id_value, list_index, depth, entry_path=None):
        if dict_key == 'id':
            messagebox.showinfo("提示", "'id' 字段用于定位记录，不可修改")
            return

        dialog = tk.Toplevel(self.parent_window)
        dialog.title(f"编辑字段: {dict_key}")
        dialog.geometry("720x500")
        dialog.minsize(600, 400)
        dialog.configure(bg=self.bg)
        dialog.transient(self.parent_window)
        dialog.grab_set()
        center_window(dialog, False)

        # 顶部栏
        header = tk.Frame(dialog, bg=self.bg_dark, height=48, bd=0, highlightthickness=0)
        header.pack(fill=tk.X, side=tk.TOP)
        header.pack_propagate(False)
        tk.Label(header,
                 text=f"  字段: {dict_key}  |  类型: {type(current_value).__name__}",
                 bg=self.bg_dark, fg='#f1c40f',
                 font=('Microsoft YaHei UI', 10, 'bold')).pack(side=tk.LEFT, padx=12)
        if id_value is not None:
            tk.Label(header, text=f"所在记录 id: {id_value}  ",
                     bg=self.bg_dark, fg='#7be2f7',
                     font=('Microsoft YaHei UI', 9)).pack(side=tk.RIGHT, padx=12)

        # 主内容区 - 限制高度，避免挤出按钮
        body = tk.Frame(dialog, bg=self.bg, bd=0, highlightthickness=0)
        body.pack(fill=tk.BOTH, expand=True, padx=14, pady=10)

        # 原始值
        tk.Label(body, text="📖 原始值 (作为参考，只读):",
                 bg=self.bg, fg='#95a5a6',
                 font=('Microsoft YaHei UI', 9, 'bold')).pack(anchor='w')

        orig_frame = tk.Frame(body, bg=self.bg_darker, bd=0, highlightthickness=0)
        orig_frame.pack(fill=tk.X, pady=(4, 10))
        orig_text = tk.Text(orig_frame, height=5, bg=self.bg_darker, fg='#ecf0f1',
                            font=('Microsoft YaHei UI', 10), wrap=tk.WORD,
                            relief='flat', padx=10, pady=8)
        orig_text.pack(fill=tk.BOTH, expand=True)
        orig_text.insert("1.0", str(original_value) if original_value is not None else "")
        orig_text.config(state='disabled')

        # 新值
        tk.Label(body, text="✏ 新值 (可编辑，点击保存后会写入修改记录):",
                 bg=self.bg, fg='#7be2f7',
                 font=('Microsoft YaHei UI', 9, 'bold')).pack(anchor='w')

        new_frame = tk.Frame(body, bg=self.bg_darker, bd=0, highlightthickness=0)
        new_frame.pack(fill=tk.BOTH, expand=True, pady=(4, 0))
        new_text = tk.Text(new_frame, height=8, bg=self.bg_darker, fg='white',
                           insertbackground='white',
                           font=('Microsoft YaHei UI', 10), wrap=tk.WORD,
                           relief='flat', padx=10, pady=8,
                           highlightthickness=1,
                           highlightbackground='#3498db',
                           highlightcolor='#3498db')
        new_text.pack(fill=tk.BOTH, expand=True)
        new_text.insert("1.0", str(current_value))
        new_text.focus_set()

        # 底部按钮栏 - 固定在底部
        btn_row = tk.Frame(dialog, bg=self.bg_dark, bd=0, highlightthickness=0, height=62)
        btn_row.pack(fill=tk.X, side=tk.BOTTOM)
        btn_row.pack_propagate(False)

        btn_inner = tk.Frame(btn_row, bg=self.bg_dark, bd=0, highlightthickness=0)
        btn_inner.pack(pady=14)

        def on_save():
            new_value = new_text.get("1.0", tk.END).rstrip('\n')
            if isinstance(current_value, bool):
                try:
                    lower = new_value.lower()
                    if lower not in ('true', 'false'):
                        raise ValueError
                    new_value = (lower == 'true')
                except Exception:
                    messagebox.showerror("错误", "布尔值必须为 true 或 false")
                    return
            elif isinstance(current_value, int):
                try:
                    new_value = int(new_value)
                except Exception:
                    messagebox.showerror("错误", f"请输入有效的整数 (int)")
                    return
            elif isinstance(current_value, float):
                try:
                    new_value = float(new_value)
                except Exception:
                    messagebox.showerror("错误", f"请输入有效的数字 (float)")
                    return

            self._apply_edit(dict_key, new_value, depth, list_index, id_value,
                             entry_path=entry_path)
            # 保存修改后立刻刷新视图，让"已修改"标记正确
            self._refresh_data_view(preserve_scroll=False, target_path=entry_path)
            dialog.destroy()

        def on_reset():
            new_text.delete("1.0", tk.END)
            new_text.insert("1.0", str(original_value) if original_value is not None else "")

        tk.Button(btn_inner, text="💾 保存修改", command=on_save,
                  bg='#27ae60', fg='white', relief='flat',
                  cursor='hand2', padx=22, pady=6,
                  font=('Microsoft YaHei UI', 10, 'bold'),
                  activebackground='#1e8449',
                  activeforeground='white').pack(side=tk.LEFT, padx=8)

        tk.Button(btn_inner, text="↺ 恢复原始值", command=on_reset,
                  bg='#e67e22', fg='white', relief='flat',
                  cursor='hand2', padx=22, pady=6,
                  font=('Microsoft YaHei UI', 10, 'bold'),
                  activebackground='#ba4a00',
                  activeforeground='white').pack(side=tk.LEFT, padx=8)

        tk.Button(btn_inner, text="取消", command=dialog.destroy,
                  bg='#7f8c8d', fg='white', relief='flat',
                  cursor='hand2', padx=22, pady=6,
                  font=('Microsoft YaHei UI', 10, 'bold'),
                  activebackground='#6c7a7d',
                  activeforeground='white').pack(side=tk.LEFT, padx=8)

    def _apply_edit(self, dict_key, new_value, depth, list_index, id_value,
                     entry_path=None):
        """精准定位并更新 JSON 中某一个字段。
        用 entry_path（来自被点击的 entry）逐层导航，避免全局 id 搜索的误匹配。"""
        def _navigate_and_set(data, path_parts, value):
            """path_parts: 解析后的路径（已过滤 root 前缀）
            例：修改 items 列表中第 0 个 dict 的 name 字段 → ["items", "[0]", "name"]
            例：修改顶层 key "version" → ["version"]
            """
            if not path_parts:
                return False
            # 先导航到父对象
            parent = data
            for part in path_parts[:-1]:
                if part.startswith("[") and part.endswith("]"):
                    # list 索引/按 id 查找
                    idx_str = part[1:-1]
                    try:
                        idx = int(idx_str)
                        if isinstance(parent, list) and 0 <= idx < len(parent):
                            parent = parent[idx]
                        else:
                            return False
                    except ValueError:
                        # 非纯数字 → 在 list 中按 id 字段查找
                        if isinstance(parent, list):
                            found = None
                            for item in parent:
                                if isinstance(item, dict) and str(item.get('id')) == idx_str:
                                    found = item
                                    break
                            if found is not None:
                                parent = found
                            else:
                                return False
                        else:
                            return False
                else:
                    # dict key
                    if isinstance(parent, dict) and part in parent:
                        parent = parent[part]
                    else:
                        return False
            # 在父对象上写入最后一段
            last = path_parts[-1]
            if last.startswith("[") and last.endswith("]"):
                idx_str = last[1:-1]
                try:
                    idx = int(idx_str)
                    if isinstance(parent, list) and 0 <= idx < len(parent):
                        parent[idx] = value
                        return True
                except ValueError:
                    return False
            elif isinstance(parent, dict):
                parent[last] = value
                return True
            return False

        success = False
        try:
            if entry_path:
                parts = [p for p in entry_path.split("/") if p]
                # **关键修复：** "root" 是 walk 虚拟出来的根节点名，真实数据
                # 在 self.modified_data 顶层就直接是数据，没有 "root" 这一层。
                # 如果 path 以 "root" 开头，必须把它去掉，否则会尝试去找
                # self.modified_data["root"]，这会失败。
                if parts and parts[0] == "root":
                    parts = parts[1:]
                success = _navigate_and_set(self.modified_data, parts, new_value)
            elif id_value is not None:
                def find_by_id(data):
                    if isinstance(data, list):
                        for item in data:
                            if isinstance(item, dict) and str(item.get('id')) == str(id_value):
                                if dict_key in item:
                                    item[dict_key] = new_value
                                    return True
                            if isinstance(item, (dict, list)):
                                if find_by_id(item):
                                    return True
                    elif isinstance(data, dict):
                        if str(data.get('id')) == str(id_value):
                            if dict_key in data:
                                data[dict_key] = new_value
                                return True
                        for v in data.values():
                            if isinstance(v, (dict, list)):
                                if find_by_id(v):
                                    return True
                    return False
                success = find_by_id(self.modified_data)
            elif list_index is not None:
                def find_by_index(data, remaining):
                    if isinstance(data, list):
                        if remaining == 0 and list_index < len(data):
                            item = data[list_index]
                            if isinstance(item, dict) and dict_key in item:
                                item[dict_key] = new_value
                                return True
                        for it in data:
                            if isinstance(it, (dict, list)):
                                if find_by_index(it, remaining - 1):
                                    return True
                    elif isinstance(data, dict):
                        for v in data.values():
                            if isinstance(v, (dict, list)):
                                if find_by_index(v, remaining):
                                    return True
                    return False
                success = find_by_index(self.modified_data, max(0, depth - 1))
            else:
                if isinstance(self.modified_data, dict) and dict_key in self.modified_data:
                    self.modified_data[dict_key] = new_value
                    success = True
        except Exception as e:
            print(f"[_apply_edit] 错误: {e}")

        if success:
            self.status_label.config(
                text=f"已更新字段 '{dict_key}'，请点击 [保存修改记录] 按钮确认保存")
        else:
            messagebox.showerror("错误", "无法定位到要修改的字段，请尝试重新加载文件")

    # ======================= 搜索/展开/折叠 =======================
    def _on_data_search_changed(self, event=None):
        if self.current_file:
            self._refresh_data_view(preserve_scroll=False)  # 搜索 → 滚到顶部

    def _clear_data_search(self):
        self.data_search_var.set("")
        self._search_keyword = ""
        if self.current_file:
            try:
                pixel_top = self.data_canvas.canvasy(0)
            except Exception:
                pixel_top = 0
            self._refresh_data_view(preserve_scroll_pixel=pixel_top)

    def _expand_all(self):
        """虚拟滚动版：清空 _collapsed_paths，完全刷新"""
        if not hasattr(self, '_collapsed_paths'):
            self._collapsed_paths = set()
        self._collapsed_paths.clear()
        self._refresh_data_view()

    def _collapse_all(self):
        """虚拟滚动版：把所有非根容器 path 加入集合，完全刷新"""
        if not hasattr(self, '_collapsed_paths'):
            self._collapsed_paths = set()
        if hasattr(self, '_flat_entries') and self._flat_entries:
            for e in self._flat_entries:
                if e['is_container'] and not e['is_root']:
                    self._collapsed_paths.add(e['path'])
        self._refresh_data_view()

    # ======================= 保存 / 重置 =======================

    def _refresh_tree_markers(self):
        """轻量级刷新文件树的 ✏ 标记（不重建树）。"""
        try:
            def _walk(node):
                values = self.file_tree.item(node, 'values')
                if values and len(values) >= 2 and values[1] == "file":
                    # 文件节点：根据是否在 self.changes 中决定前缀
                    relative = self._normalize_change_path(values[0])
                    # 从当前文本中提取文件名（去除前缀修饰）
                    current_text = self.file_tree.item(node, 'text')
                    # 找文件名起始位置：简单策略是找 ".json" 前后的内容
                    # 更可靠：直接用 relative 的 basename
                    file_name = os.path.basename(relative) or relative
                    has_changes = self._has_changes_for_relative(relative)
                    prefix = "✏  " if has_changes else "    "
                    self.file_tree.item(node, text=f"  {prefix}{file_name}")
                # 递归处理子节点
                for child in self.file_tree.get_children(node):
                    _walk(child)

            for root_node in self.file_tree.get_children(''):
                _walk(root_node)
        except Exception as e:
            print(f"[_refresh_tree_markers] 错误: {e}")

    def _save_all_changes(self):
        """保存所有文件的修改（把内存中 modified_data 和 original_data 的 diff 写到 changes.json）。
        只处理用户当前打开过的文件。对于 self.changes 中已有但用户未打开的文件，保持原样。"""
        if not self.changes and not (self.current_file and self.original_data is not None):
            messagebox.showinfo("信息", "当前没有检测到任何修改")
            return

        # 当前文件的修改也要同步（如果用户没点"保存当前文件"就直接点这个按钮）
        saved_any = False
        file_list = []

        # 1) 同步当前文件到 changes 内存
        if self.current_file and self.original_data is not None and self.modified_data is not None:
            try:
                relative = self._relative_to_lang(self.current_file)
                diff = self._compute_diff(self.original_data, self.modified_data)
                if diff is not None:
                    self._set_changes_for_relative(relative, diff)
                else:
                    self._delete_changes_for_relative(relative)
            except Exception:
                pass

        # 2) 遍历 self.changes，逐个检查对应文件是否真的有修改
        #    这里策略：直接把 self.changes 里所有文件写盘（最安全）
        if self.changes:
            try:
                self._save_changes_to_file()
                saved_any = True
                file_list = list(self.changes.keys())
            except Exception as e:
                messagebox.showerror("错误", f"保存失败: {e}")
                return

        if saved_any and file_list:
            names = "\n".join(f"  • {n}" for n in file_list[:10])
            extra = f"\n  ... 还有 {len(file_list) - 10} 个" if len(file_list) > 10 else ""
            messagebox.showinfo("成功",
                                f"✏ 已保存 {len(file_list)} 个文件的修改:\n\n{names}{extra}")
            self.status_label.config(text=f"已保存 {len(file_list)} 个文件的修改")
        else:
            messagebox.showinfo("信息", "当前没有检测到任何修改")

        # 刷新标记 + 编辑区（不重建文件树）
        self._refresh_tree_markers()
        try:
            pixel_top = self.data_canvas.canvasy(0)
        except Exception:
            pixel_top = 0
        self._refresh_data_view(preserve_scroll_pixel=pixel_top)

    def _save_json_changes(self):
        if not self.current_file:
            messagebox.showwarning("警告", "请先选择一个文件")
            return
        try:
            relative = self._relative_to_lang(self.current_file)
            diff = self._compute_diff(self.original_data, self.modified_data)
            if diff is None:
                self._delete_changes_for_relative(relative)
                self._save_changes_to_file()
                messagebox.showinfo("信息", "当前文件无修改 (未与原始数据产生差异)")
                self.status_label.config(text="没有修改需要保存")
            else:
                self._set_changes_for_relative(relative, diff)
                self._save_changes_to_file()
                self.status_label.config(text=f"修改内容已保存，文件: {relative}")
                messagebox.showinfo("成功",
                                    f"✏ 修改内容已保存\n\n文件: {relative}")
            # 保存后不要刷新文件树 —— 目录结构没变，不需要重建
            # 只需要刷新 ✏ 标记 + 编辑区
            self._refresh_tree_markers()
            try:
                pixel_top = self.data_canvas.canvasy(0)
            except Exception:
                pixel_top = 0
            self._refresh_data_view(preserve_scroll_pixel=pixel_top)
        except Exception as e:
            messagebox.showerror("错误", f"保存失败: {e}")

    def _compute_diff(self, original, modified):
        if isinstance(original, dict) and isinstance(modified, dict):
            changes = {}
            for k, v in modified.items():
                if k in original:
                    sub = self._compute_diff(original[k], v)
                    if sub is not None:
                        changes[k] = sub
                else:
                    changes[k] = v
            return changes if changes else None
        elif isinstance(original, list) and isinstance(modified, list):
            has_ids = all(isinstance(it, dict) and 'id' in it for it in original)
            if has_ids:
                id_to_orig = {item['id']: item for item in original}  # 保留原始 id 类型
                changes_list = []
                for item in modified:
                    if not isinstance(item, dict) or 'id' not in item:
                        continue
                    item_id = item['id']  # 保留原始 id 类型 (int/str)
                    if item_id in id_to_orig:
                        sub = self._compute_diff(id_to_orig[item_id], item)
                        if sub is not None:
                            changes_list.append({
                                'id': item_id,  # 保留原始 id 类型
                                'changes': sub,
                                'action': 'modified'
                            })
                return changes_list if changes_list else None
            else:
                changes_list = []
                min_len = min(len(original), len(modified))
                for i in range(min_len):
                    sub = self._compute_diff(original[i], modified[i])
                    if sub is not None:
                        changes_list.append(sub)
                return changes_list if changes_list else None
        else:
            return modified if original != modified else None

    def _reset_current_file(self):
        if not self.current_file:
            messagebox.showwarning("警告", "请先选择一个文件")
            return
        if not messagebox.askyesno("确认", "确定要撤销当前文件的所有修改吗？"):
            return
        relative = self._relative_to_lang(self.current_file)
        self._delete_changes_for_relative(relative)
        self._save_changes_to_file()
        self.modified_data = self._deep_copy(self.original_data)
        self._refresh_tree_markers()
        try:
            pixel_top = self.data_canvas.canvasy(0)
        except Exception:
            pixel_top = 0
        self._refresh_data_view(preserve_scroll_pixel=pixel_top)
        self.status_label.config(text="当前文件的修改已撤销")

    def _reset_all_changes(self):
        if not messagebox.askyesno("确认",
                                   "确定要清空整个修改记录吗？此操作不可恢复！"):
            return
        self.changes = {}
        self._save_changes_to_file()
        if self.current_file:
            self.modified_data = self._deep_copy(self.original_data)
            self._refresh_tree_markers()
            try:
                pixel_top = self.data_canvas.canvasy(0)
            except Exception:
                pixel_top = 0
            self._refresh_data_view(preserve_scroll_pixel=pixel_top)
        self.status_label.config(text="所有修改记录已清空")

    def _open_changes_dir(self):
        """打开修改记录文件所在目录"""
        try:
            abs_path = os.path.abspath(self.changes_file)
            dir_path = os.path.dirname(abs_path)
            if os.path.exists(dir_path):
                os.startfile(dir_path)
            else:
                messagebox.showerror("错误", f"目录不存在: {dir_path}")
        except Exception as e:
            messagebox.showerror("错误", f"打开目录失败: {e}")

def open_custom_translation_tool(root):
    """
    main.py 调用入口。
    root 需提供: bg_color, lighten_bg_color 等界面属性。
    """
    CustomTranslationTool(root, root.root if hasattr(root, 'root') else root)
