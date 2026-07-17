import tkinter as tk
from tkinter import messagebox
from tkinter import ttk
from typing import Dict, Callable, Optional, Any
import traceback
from rich import print


class PageLoader:
    """页面加载器 - 负责按需加载和初始化各个页面"""
    
    def __init__(self, app):
        self.app = app
        self.core = app.core
        self.pages: Dict[str, Any] = {}
        self.page_initializers: Dict[str, Callable] = {
            'home': self._init_home_page,
            'features': self._init_features_page,
            'tools': self._init_tools_page,
            'mod_addon': self._init_mod_addon_page,
            'download_center': self._init_download_center_page,
            'settings': self._init_settings_page,
            'about': self._init_about_page,
        }
        
    def load_page(self, page_name: str) -> Optional[Any]:
        """加载指定页面"""
        if page_name in self.pages:
            return self.pages[page_name]
            
        if page_name not in self.page_initializers:
            print(f"未知页面: {page_name}")
            return None
            
        try:
            page = self.page_initializers[page_name]()
            self.pages[page_name] = page
            print(f"页面 {page_name} 加载成功")
            return page
        except Exception as e:
            print(f"加载页面 {page_name} 失败: {e}")
            traceback.print_exc()
            return None
            
    def load_all_pages(self):
        """预加载所有页面"""
        for page_name in self.page_initializers.keys():
            self.load_page(page_name)
            
    def get_page(self, page_name: str) -> Optional[Any]:
        """获取已加载的页面"""
        return self.pages.get(page_name)
        
    def _init_settings_page(self):
        """初始化设置页面"""
        try:
            from functions.pages.setting.settings_page import init_settings_page
            return init_settings_page(
                self.app.page_frames['settings'], 
                self.core.bg_color, 
                self.core.lighten_bg_color
            )
        except Exception as e:
            self._show_page_error(self.app.page_frames['settings'], "设置页面", e)
            return None
            
    def _init_mod_addon_page(self):
        """初始化插件&mod管理页面"""
        try:
            from functions.pages.extension.mod_addon_info import init_mod_addon_manager
            return init_mod_addon_manager(
                self.app.page_frames['mod_addon'], 
                self.core.bg_color, 
                self.core.lighten_bg_color, 
                self.app
            )
        except Exception as e:
            self._show_page_error(self.app.page_frames['mod_addon'], "插件&Mod管理页面", e)
            return None
            
    def _init_download_center_page(self):
        """初始化下载中心页面"""
        try:
            from functions.pages.download.download_center import init_download_center
            return init_download_center(
                self.app.page_frames['download_center'], 
                self.app, 
                self.core.bg_color, 
                self.core.lighten_bg_color
            )
        except Exception as e:
            self._show_page_error(self.app.page_frames['download_center'], "下载中心页面", e)
            return None
            
    def _init_tools_page(self):
        """初始化工具页"""
        from functions.fancy.dialog_colorful import test_color_gradient_gui
        from functions.pages.tools.select_font import select_font_gui
        from functions.pages.tools.auto_translate_gui import show_auto_translate_gui
        from functions.base.settings_manager import get_settings_manager
        from functions.web_tool.launch_babel import launch_babel
        
        settings_manager = get_settings_manager()
        
        tools_container = tk.Frame(self.app.page_frames['tools'], bg=self.core.bg_color)
        tools_container.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
        
        tools_frost = tk.Canvas(tools_container, highlightthickness=0)
        tools_frost.place(x=0, y=0, relwidth=1, relheight=1)
        tools_frost.lower(1)
        self.app.tab_frost_canvases.append(tools_frost)
        
        def spawn_function_tr():
            source_path = f"{settings_manager.get_setting('game_path')}/LimbusCompany_Data/Assets/Resources_moved/Localize/en"
            target_path = "lang/LLC_zh-CN"
            return lambda: show_auto_translate_gui(self.app, source_path, target_path)
        
        tools = [
            {"name": "🔧 自定义汉化", "description": "编辑lang目录下的JSON文件\n实现自定义的汉化修改。",
             "color": "#3498db", "command": self.core.open_custom_translation_tool},
            
            {"name": "🚜 文件夹超链接", "description": "为文件夹制作超链接，\n达到转移空间的目的？",
             "color": "#34db34", "command": self.core.folder_link},
            
            {"name": "💻 渐变文本处理器", "description": "根据用户输入的文本生成渐变的 Untity 富文本。",
             "color": "#FFBD30", "command": lambda: test_color_gradient_gui(self.app)},
            
            {"name": "📝 字体修改", "description": "修改汉化包的字体，\n使用你自己喜欢的字体包代替",
             "color": "#FA3E3E", "command": lambda: select_font_gui(self.app)},
            
            {"name": "🔄 自动汉化", "description": "使用思知实现\n对游戏的补充汉化。",
             "color": "#9130FF", "command": spawn_function_tr()},
            
            {"name": "📦 Mod 管理器", "description": "管理边狱巴士的 Mod。\n",
             "color": "#FF8001", "command": self.core.open_mod_manager},
            
            {"name": "🚀 零协会CDN优选", "description": "自动选择最优质的CDN，优化游戏资源下载和服务器连接",
             "color": "#62fffa", "command": launch_babel},
            
            {"name": "🔧 正在制作的功能\n", "description": "此功能正在开发中...",
             "color": "#808080", "command": lambda: messagebox.showinfo("提示", "此功能正在开发中...")},
            
            {"name": "🔧 正在制作的功能\n", "description": "此功能正在开发中...",
             "color": "#808080", "command": lambda: messagebox.showinfo("提示", "此功能正在开发中...")},
        ]
        
        
        num_cols = 3
        num_rows = (len(tools) + num_cols - 1) // num_cols
        
        for i, tool in enumerate(tools):
            row = i // num_cols
            col = i % num_cols
            
            card_frame = tk.Frame(tools_container, 
                                bg=tool['color'],
                                relief='raised',
                                borderwidth=1)
            card_frame.grid(row=row, column=col, padx=5, pady=5, sticky="nsew")
            
            card_inner = tk.Frame(card_frame, bg=tool['color'])
            card_inner.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
            
            title_label = tk.Label(card_inner, 
                                text=tool['name'],
                                bg=tool['color'],
                                fg='white',
                                font=('Microsoft YaHei UI', 12, 'bold'))
            title_label.pack(pady=(5, 8))
            
            desc_label = tk.Label(card_inner, 
                                text=tool['description'],
                                bg=tool['color'],
                                fg='white',
                                font=('Microsoft YaHei UI', 9),
                                wraplength=160,
                                justify=tk.CENTER)
            desc_label.pack(pady=5)
            
            action_button = tk.Button(card_inner, 
                                    text="🚀 打开",
                                    command=tool['command'],
                                    bg='white',
                                    fg=tool['color'],
                                    font=('Microsoft YaHei UI', 8, 'bold'),
                                    relief='flat',
                                    padx=12,
                                    pady=4,
                                    cursor='hand2')
            action_button.pack(pady=(8, 5))
            
            action_button.bind("<Enter>", lambda e, b=action_button: b.configure(bg=self.core.darken_color(b.cget('bg'))))
            action_button.bind("<Leave>", lambda e, b=action_button: b.configure(bg='white'))
        
        for i in range(num_cols):
            tools_container.columnconfigure(i, weight=1, uniform="tool_col")
        
        for i in range(num_rows):
            tools_container.rowconfigure(i, weight=1, uniform="tool_row")
            
        return tools_container
        
    def _init_home_page(self):
        """初始化主页"""
        description = "欢迎使用 Faust Launcher - 您人生中绝无仅有的完美启动器！\n懒人化的一键操作，这就是浮士德大人的聪明才智口牙！"
        
        frost = self.app.tab_frost_canvases[0]
        frost.create_text(350, 50, text="✨ Faust Launcher ✨",
                        fill='white', font=('Microsoft YaHei UI', 25, 'bold'),
                        anchor=tk.CENTER, tags=("home_title",))
        frost.create_text(350, 110, text=description,
                        fill='white', font=('Microsoft YaHei UI', 13),
                        anchor=tk.CENTER, justify=tk.CENTER, width=600,
                        tags=("home_desc",))
        
        quick_actions_frame = ttk.LabelFrame(self.app.page_frames['home'], text="  🚀 快速操作", style="Custom.TLabelframe")
        quick_actions_frame.pack(padx=30, pady=(160, 10))
        
        button_container = tk.Frame(quick_actions_frame, bg=self.core.lighten_bg_color)
        button_container.pack(pady=15, padx=10)
        
        from threading import Thread
        
        buttons_data = [
            {"text": "🚀 启动游戏", "command": lambda: Thread(target=download_and_launch, kwargs={"need_run_game": True, 'obj': self.app}).start(), "color": "#2980b9"},
            {"text": "🎯 汉化更新", "command": self.core.update_translation, "color": "#27ae60"},
            {"text": "📚 使用帮助", "command": self.core.show_help, "color": "#9b59b6"}
        ]
        
        for i, btn_data in enumerate(buttons_data):
            button = tk.Button(button_container, 
                            text=btn_data["text"],
                            command=btn_data["command"],
                            bg=btn_data["color"],
                            fg='white',
                            font=('Microsoft YaHei UI', 10, 'bold'),
                            relief='flat',
                            padx=20,
                            pady=10,
                            cursor='hand2')
            button.pack(side=tk.LEFT, padx=10)
            button.bind("<Enter>", lambda e, b=button: b.configure(bg=self.core.darken_color(b.cget('bg'))))
            button.bind("<Leave>", lambda e, b=button, c=btn_data["color"]: b.configure(bg=c))
        
        self.app.create_status_bar()
        
        terminal_frame = ttk.LabelFrame(self.app.page_frames['home'], text="  💻 迷你终端", style="Custom.TLabelframe")
        terminal_frame.pack(fill=tk.BOTH, expand=True, padx=30, pady=15)
        
        terminal_toolbar = tk.Frame(terminal_frame, bg=self.core.lighten_bg_color)
        terminal_toolbar.pack(fill=tk.X, padx=5, pady=5)
        
        clear_button = tk.Button(terminal_toolbar, 
                                text="🗑️ 清空终端",
                                command=self.core.clear_terminal,
                                bg='#e74c3c',
                                fg='white',
                                font=('微软雅黑', 8, 'bold'),
                                relief='flat',
                                padx=8,
                                pady=3)
        clear_button.pack(side=tk.LEFT, padx=2)
        
        copy_button = tk.Button(terminal_toolbar,
                                text="📋  复制内容",
                                command=self.core.copy_terminal_content,
                                bg='#3498db',
                                fg='white',
                                font=('微软雅黑', 8, 'bold'),
                                relief='flat',
                                padx=8,
                                pady=3)
        copy_button.pack(side=tk.LEFT, padx=2)
        
        terminal_container = tk.Frame(terminal_frame, bg='#1e1e1e')
        terminal_container.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        scrollbar = ttk.Scrollbar(terminal_container)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.core.terminal_text = tk.Text(terminal_container,
                                        bg="#1e1e1e",
                                        fg="#ffffff",
                                        font=('微软雅黑', 10),
                                        yscrollcommand=scrollbar.set,
                                        wrap=tk.WORD,
                                        relief='flat',
                                        borderwidth=0)
        self.core.terminal_text.pack(fill=tk.BOTH, expand=True)
        
        scrollbar.config(command=self.core.terminal_text.yview)
        self.core.terminal_text.config(state=tk.DISABLED)
        
        self.core.terminal_text.tag_config("info", foreground="#ffffff")
        self.core.terminal_text.tag_config("error", foreground="#ff6b6b")
        self.core.terminal_text.tag_config("success", foreground="#4bff4e")
        self.core.terminal_text.tag_config("warning", foreground="#f9ca24")
        self.core.terminal_text.tag_config("wait", foreground="#4ecbff")
        
        self.core.setup_terminal_redirect()
        self.core.add_terminal_message("🚀 Faust Launcher 已启动")
        self.core.add_terminal_message("💻 终端重定向已启用")
        self.core.add_terminal_message("=" * 50)
        
        return quick_actions_frame
        
    def _init_features_page(self):
        """初始化功能页"""
        features_container = tk.Frame(self.app.page_frames['features'], bg=self.core.bg_color)
        features_container.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)
        
        features_frost = tk.Canvas(features_container, highlightthickness=0)
        features_frost.place(x=0, y=0, relwidth=1, relheight=1)
        features_frost.lower(1)
        self.app.tab_frost_canvases.append(features_frost)
        
        features = [
            {"name": "📁 游戏目录", "description": "边狱巴士的游戏目录。\n\n", "color": "#ff9c1b"},
            {"name": "🔄 零协会", "description": "一个伟大的社区。\n\n", "color": "#e74c3c"},
            {"name": "📒 气泡文本", "description": "气泡mod的汉化版本。\n提取码：fib6\n", "color": "#3498db"},
            {"name": "📝 维基", "description": "边狱巴士的灰机wiki。\n\n", "color": "#2ecc71"},
            {"name": "📖 N网", "description": "下载边狱巴士mod。\n\n", "color": "#9b59b6"},
            {"name": "📦 Github", "description": "查看本项目源码\n\n", "color": "#777777"}
        ]
        
        for i, feature in enumerate(features):
            row = i // 3
            col = i % 3
            
            card_frame = tk.Frame(features_container, 
                                bg=feature['color'],
                                relief='raised',
                                borderwidth=1)
            card_frame.grid(row=row, column=col, padx=10, pady=10, sticky="nsew")
            card_frame.grid_propagate(False)
            card_frame.configure(width=200, height=120)
            
            title_label = tk.Label(card_frame, 
                                text=feature['name'],
                                bg=feature['color'],
                                fg='white',
                                font=('Microsoft YaHei UI', 12, 'bold'))
            title_label.pack(pady=(15, 5))
            
            desc_label = tk.Label(card_frame, 
                                text=feature['description'],
                                bg=feature['color'],
                                fg='white',
                                font=('Microsoft YaHei UI', 9),
                                wraplength=180)
            desc_label.pack(pady=5)
            
            action_button = tk.Button(card_frame, 
                                    text="🚀 打开",
                                    command=lambda f=feature: self.core.open_feature(f),
                                    bg='white',
                                    fg=feature['color'],
                                    font=('Microsoft YaHei UI', 8, 'bold'),
                                    relief='flat',
                                    padx=10,
                                    pady=5,
                                    cursor='hand2')
            action_button.pack(pady=10)
        
        for i in range(3):
            features_container.columnconfigure(i, weight=1)
        for i in range(2):
            features_container.rowconfigure(i, weight=1)
            
        return features_container
        
    def _init_about_page(self):
        """初始化关于页面"""
        from functions.web_update.sql_manager import notify_new_version
        
        frost = self.app.tab_frost_canvases[5]
        
        frost.create_text(350, 40, text="ℹ️关于 Faust Launcher",
                        fill='white', font=('Microsoft YaHei UI', 23, 'bold'),
                        anchor=tk.CENTER, tags=("about_title",))
        
        ver_badge = tk.Frame(frost, bg='#e74c3c')
        frost.create_window(350, 78, window=ver_badge, anchor=tk.CENTER,
                            tags=("content_win",))
        tk.Label(ver_badge, text=f"{self.core.version_info}", bg='#e74c3c', fg='white',
                font=('Microsoft YaHei UI', 9, 'bold'), padx=14, pady=1).pack()
        
        card = tk.Frame(frost, bg='#1e1e1e', highlightbackground='#333333',
                        highlightthickness=1, highlightcolor='#333333')
        frost.create_window(340, 115, window=card, anchor=tk.N,
                            width=620, height=350, tags=("content_win",))
        
        tk.Label(card, text="📦 版本信息", bg='#1e1e1e', fg='#e74c3c',
                font=('Microsoft YaHei UI', 12, 'bold')).pack(anchor='w', padx=20, pady=(10, 5))
        
        tk.Label(card, text=f"  当前版本: {self.core.version_info}", bg='#1e1e1e', fg='#cccccc',
                font=('Microsoft YaHei UI', 10)).pack(anchor='w', padx=20, pady=2)
        tk.Label(card, text="  开发者: FolkSkill", bg='#1e1e1e', fg='#cccccc',
                font=('Microsoft YaHei UI', 10)).pack(anchor='w', padx=20, pady=2)
        
        tk.Frame(card, bg='#333333', height=1).pack(fill=tk.X, padx=20, pady=10)
            
        tk.Label(card, text="📖 应用介绍", bg='#1e1e1e', fg='#3498db',
                font=('Microsoft YaHei UI', 12, 'bold')).pack(anchor='w', padx=20, pady=(0, 5))
        
        desc_frame = tk.Frame(card, bg='#1e1e1e')
        desc_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=(0, 10))
        
        desc_text = tk.Text(desc_frame, bg='#1e1e1e', fg='#cccccc',
                            font=('Microsoft YaHei UI', 10), wrap=tk.WORD,
                            relief=tk.FLAT, bd=0, padx=5, pady=5,
                            highlightthickness=0)
        scrollbar = tk.Scrollbar(desc_frame, command=desc_text.yview, width=8,
                                troughcolor='#1e1e1e', activebackground='#555555')
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        desc_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        desc_text.config(yscrollcommand=scrollbar.set)
        
        desc_text.tag_configure("h2", font=('Microsoft YaHei UI', 11, 'bold'),
                            foreground='#f1c40f', spacing1=6, spacing3=3)
        desc_text.tag_configure("h3", font=('Microsoft YaHei UI', 10, 'bold'),
                            foreground='#2ecc71', spacing1=4, spacing3=2)
        desc_text.tag_configure("normal", foreground='#cccccc',
                            font=('Microsoft YaHei UI', 10))
        desc_text.tag_configure("highlight", foreground='#e2e8f0',
                            font=('Microsoft YaHei UI', 10, 'bold'))
        desc_text.tag_configure("muted", foreground='#666666',
                            font=('Microsoft YaHei UI', 9))
        
        desc_text.insert(tk.END, "一个专为懒人但丁设计的现代化启动器\n\n", "highlight")
        desc_text.insert(tk.END, "✨ 特色功能\n", "h2")
        desc_text.insert(tk.END, "  · 零协会汉化自动更新\n", "normal")
        desc_text.insert(tk.END, "  · 气泡mod自动更新下载\n", "normal")
        desc_text.insert(tk.END, "  · Mod 管理 & 一键载入\n", "normal")
        desc_text.insert(tk.END, "  · 无需多余配置，全部内置\n\n", "normal")
        desc_text.insert(tk.END, "🎯 我们的目标\n", "h3")
        desc_text.insert(tk.END, "让每一个但丁都解放自己的双手，专心坐牢。\n\n", "normal")
        desc_text.insert(tk.END, "© 2025 Faust Launcher. 版权所有。", "muted")
        desc_text.config(state=tk.DISABLED)
        
        btn_frame = tk.Frame(frost, bg=self.core.bg_color)
        frost.create_window(340, 480, window=btn_frame, anchor=tk.N,
                            width=350, height=45, tags=("content_win",))
        
        buttons_data = [
            ("🌐 bilibili", self.core.open_website, "#22c9e6", "#1a9bbf"),
            ("💌 意见反馈", self.core.send_feedback, "#9b59b6", "#7d3c98"),
            ("📦 开源地址", lambda: self.core.open_feature({"name": "📦 Github"}), "#777777", "#555555"),
            ("📄 检查更新", lambda: notify_new_version(
                current_version_name=self.core.version_info, info='版本信息', root=self.app.root), "#2ecc71", "#27ae60"),
        ]
        
        for text, cmd, color, hover_color in buttons_data:
            btn = tk.Button(btn_frame, text=text, command=cmd,
                        bg=color, fg='white', bd=0, cursor='hand2',
                        font=('Microsoft YaHei UI', 9, 'bold'),
                        padx=3, pady=6)
            btn.pack(side=tk.LEFT, expand=True)
            
            btn.bind("<Enter>", lambda e, b=btn, hc=hover_color: b.config(bg=hc))
            btn.bind("<Leave>", lambda e, b=btn, oc=color: b.config(bg=oc))
            
        return card
        
    def _show_page_error(self, frame, page_name: str, error: Exception):
        """显示页面加载错误"""
        error_label = tk.Label(frame, 
                            text=f"❌ {page_name}加载失败",
                            font=('Microsoft YaHei UI', 16),
                            bg=self.core.bg_color, fg='white')
        error_label.pack(expand=True)
        
        detail_label = tk.Label(frame, 
                                text=str(error),
                                font=('Microsoft YaHei UI', 10),
                                bg=self.core.bg_color, fg='#bdc3c7')
        detail_label.pack()


def download_and_launch(obj=None, need_run_game=False):
    """下载翻译资源，然后可选地启动游戏"""
    from functions.base.game_launcher import GameLauncher
    from functions.web_update.zeroasso_dow import main_gui as download_translation, check_need_up_translate, DownloadGUI, download_and_extract_gui
    from functions.web_update.update_resource import check_resource_update
    from functions.fancy.bubble_transfer import main as download_bubble
    import os
    import sys
    import shutil
    import traceback
    from threading import Thread
    from time import sleep
    
    global downloading
    if downloading:
        return
    downloading = True
    
    try:
        lang_path = 'lang/LLC_zh-CN'
        download_path = 'lang'
        
        print("开始下载零协会汉化包...")
        sys.path.append('functions')
        
        main_root = obj.root if obj else None
        
        gui = download_translation(main_root, download_path)
        dt = Thread(target=gui.root.mainloop)

        while gui.is_downloading:
            sleep(1)
        
        del dt
        print("零协会汉化包下载完成")

        gui_res = DownloadGUI(main_root, 'resources/', False, download_func=download_and_extract_gui)
        dt = Thread(target=check_resource_update, args=(gui_res,)).start()

        while gui_res.is_downloading:
            sleep(1)
            
        del dt
        gui_res.root.destroy()
        
        print("开始下载气泡...")
        download_bubble(download_path)
        print("气泡下载完成")

        need_update = check_need_up_translate()

        if need_update:
            print("检测到新的汉化版本，准备更新汉化文件...")
            if os.path.exists(download_path + '/LimbusCompany_Data/Lang/LLC_zh-CN'):
                if os.path.isdir(lang_path):
                    try:
                        shutil.rmtree(lang_path, ignore_errors=True)
                    except Exception as e:
                        print(f"删除目录 {lang_path} 时出错: {e}")
                        traceback.print_exc()
                elif os.path.exists(lang_path):
                    os.remove(lang_path)
                try:
                    from functions.base.game_launcher import safe_merge_dirs
                    safe_merge_dirs(
                        os.path.join(download_path, 'LimbusCompany_Data', 'Lang', 'LLC_zh-CN'),
                        lang_path
                    )
                except Exception as e:
                    print(f"复制汉化文件时出错: {e}")
                    traceback.print_exc()
            else:
                print("错误: 未找到 lang 下的 LLC_zh-CN 文件夹")
        else:
            print("当前汉化已是最新版本，无需更新")

        if not os.path.exists('assets/Font/Context/ChineseFont.ttf'):
            shutil.copytree('lang/Font', 'assets/Font', dirs_exist_ok=True)
            shutil.rmtree('lang/Font', ignore_errors=True)

        if os.path.exists(os.path.join(download_path, 'LimbusCompany_Data')):
            shutil.rmtree(os.path.join(download_path, 'LimbusCompany_Data'), ignore_errors=True)

        print("汉化下载及处理全部完成！")

        if len(sys.argv) > 1 or need_run_game:
            pass
        else:
            downloading = False
            return
        
        if obj is not None:
            print('正在进行启动游戏前进行重载插件事件中...')
            obj.core._on_reload_addons()
            launcher = GameLauncher(obj.core.addon_manager)
        else:
            launcher = GameLauncher()
        launcher.launch()
        
    except Exception as e:
        print(f"下载过程中出错: {e}")
        traceback.print_exception(*sys.exc_info())
        return
    finally:
        downloading = False


downloading = False