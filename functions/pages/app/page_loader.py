import tkinter as tk
from tkinter import messagebox
from tkinter import ttk
from typing import Dict, Callable, Optional, Any
import traceback
from rich import print
import os
import webbrowser


downloading = False

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
        
        # 现代化配色方案
        accent_indigo = '#6366f1'
        accent_purple = '#8b5cf6'
        accent_blue = '#3b82f6'
        accent_green = '#10b981'
        accent_orange = '#f59e0b'
        accent_red = '#ef4444'
        accent_cyan = '#06b6d4'
        accent_pink = '#ec4899'
        accent_gray = '#6b7280'
        
        tools = [
            {"name": "🔧 自定义汉化", "description": "编辑lang目录下的JSON文件\n实现自定义的汉化修改。",
             "color": accent_blue, "command": self.core.open_custom_translation_tool},
            
            {"name": "🚜 文件夹超链接", "description": "为文件夹制作超链接，\n达到转移空间的目的？",
             "color": accent_green, "command": self.core.folder_link},
            
            {"name": "💻 渐变文本处理器", "description": "根据用户输入的文本生成渐变的 Untity 富文本。",
             "color": accent_orange, "command": lambda: test_color_gradient_gui(self.app)},
            
            {"name": "📝 字体修改", "description": "修改汉化包的字体，\n使用你自己喜欢的字体包代替",
             "color": accent_red, "command": lambda: select_font_gui(self.app)},
            
            {"name": "🔄 自动汉化", "description": "使用思知实现\n对游戏的补充汉化。",
             "color": accent_purple, "command": spawn_function_tr()},
            
            {"name": "📦 Mod 管理器", "description": "管理边狱巴士的 Mod。\n",
             "color": accent_indigo, "command": self.core.open_mod_manager},
            
            {"name": "🚀 零协会CDN优选", "description": "自动选择最优质的CDN，优化游戏资源下载和服务器连接",
             "color": accent_cyan, "command": launch_babel},
            
            {"name": "🔧 正在制作的功能\n", "description": "此功能正在开发中...",
             "color": accent_gray, "command": lambda: messagebox.showinfo("提示", "此功能正在开发中...")},
            
            {"name": "🔧 正在制作的功能\n", "description": "此功能正在开发中...",
             "color": accent_gray, "command": lambda: messagebox.showinfo("提示", "此功能正在开发中...")},
        ]
        
        
        num_cols = 3
        num_rows = (len(tools) + num_cols - 1) // num_cols
        
        for i, tool in enumerate(tools):
            row = i // num_cols
            col = i % num_cols
            
            # 现代化卡片 - 使用深色背景配合渐变效果
            card_bg = self.core.darken_color(tool['color'], 0.15)
            card_frame = tk.Frame(tools_container, 
                                bg=card_bg,
                                relief='flat',
                                borderwidth=0,
                                highlightthickness=1,
                                highlightbackground=self.core.lighten_color(card_bg, 20))
            card_frame.grid(row=row, column=col, padx=8, pady=8, sticky="nsew")
            
            card_inner = tk.Frame(card_frame, bg=card_bg)
            card_inner.pack(fill=tk.BOTH, expand=True, padx=12, pady=12)
            
            title_label = tk.Label(card_inner, 
                                text=tool['name'],
                                bg=card_bg,
                                fg='#f8fafc',
                                font=('Microsoft YaHei UI', 11, 'bold'))
            title_label.pack(pady=(4, 6))
            
            desc_label = tk.Label(card_inner, 
                                text=tool['description'],
                                bg=card_bg,
                                fg='#cbd5e1',
                                font=('Microsoft YaHei UI', 9),
                                wraplength=160,
                                justify=tk.CENTER)
            desc_label.pack(pady=4)
            
            # 现代化按钮 - 扁平设计
            action_button = tk.Button(card_inner, 
                                    text="打开",
                                    command=tool['command'],
                                    bg=tool['color'],
                                    fg='#ffffff',
                                    font=('Microsoft YaHei UI', 9, 'bold'),
                                    relief='flat',
                                    padx=16,
                                    pady=5,
                                    cursor='hand2',
                                    activebackground=self.core.lighten_color(tool['color'], 15),
                                    activeforeground='#ffffff',
                                    borderwidth=0)
            action_button.pack(pady=(8, 4))
            
            action_button.bind("<Enter>", lambda e, b=action_button, c=tool['color']: b.configure(bg=self.core.lighten_color(c, 10)))
            action_button.bind("<Leave>", lambda e, b=action_button, c=tool['color']: b.configure(bg=c))
        
        for i in range(num_cols):
            tools_container.columnconfigure(i, weight=1, uniform="tool_col")
        
        for i in range(num_rows):
            tools_container.rowconfigure(i, weight=1, uniform="tool_row")
            
        return tools_container
        
    def _init_home_page(self):
        """初始化主页"""
        description = "欢迎使用 Faust Launcher - 您人生中绝无仅有的完美启动器！\n懒人化的一键操作，这就是浮士德大人的聪明才智口牙！"
        
        frost = self.app.tab_frost_canvases[0]
        frost.create_text(340, 35, text="✨ Faust Launcher ✨",
                        fill='white', font=('Microsoft YaHei UI', 22, 'bold'),
                        anchor=tk.CENTER, tags=("home_title",))
        frost.create_text(340, 80, text=description,
                        fill='white', font=('Microsoft YaHei UI', 11),
                        anchor=tk.CENTER, justify=tk.CENTER, width=600,
                        tags=("home_desc",))
        
        quick_actions_frame = ttk.LabelFrame(self.app.page_frames['home'], text="  🚀 快速操作", style="Custom.TLabelframe")
        quick_actions_frame.pack(padx=30, pady=(115, 10))
        
        button_container = tk.Frame(quick_actions_frame, bg=self.core.lighten_bg_color)
        button_container.pack(pady=15, padx=10)
        
        from threading import Thread
        
        # 现代化主按钮配色
        buttons_data = [
            {"text": "🚀 启动游戏", "command": lambda: Thread(target=download_and_launch, kwargs={"need_run_game": True, 'obj': self.app}).start(), "color": "#3b82f6", "hover": "#2563eb"},
            {"text": "🎯 汉化更新", "command": self.core.update_translation, "color": "#10b981", "hover": "#059669"},
            {"text": "📚 使用帮助", "command": self.core.show_help, "color": "#8b5cf6", "hover": "#7c3aed"}
        ]
        
        for i, btn_data in enumerate(buttons_data):
            button = tk.Button(button_container, 
                            text=btn_data["text"],
                            command=btn_data["command"],
                            bg=btn_data["color"],
                            fg='#ffffff',
                            font=('Microsoft YaHei UI', 10, 'bold'),
                            relief='flat',
                            padx=24,
                            pady=12,
                            cursor='hand2',
                            borderwidth=0,
                            activebackground=btn_data["hover"],
                            activeforeground='#ffffff')
            button.pack(side=tk.LEFT, padx=12)
            button.bind("<Enter>", lambda e, b=button, h=btn_data["hover"]: b.configure(bg=h))
            button.bind("<Leave>", lambda e, b=button, c=btn_data["color"]: b.configure(bg=c))
        
        self.app.create_status_bar()
        
        terminal_frame = ttk.LabelFrame(self.app.page_frames['home'], text="  💻 迷你终端", style="Custom.TLabelframe")
        terminal_frame.pack(fill=tk.BOTH, expand=True, padx=30, pady=15)
        
        terminal_toolbar = tk.Frame(terminal_frame, bg=self.core.lighten_bg_color)
        terminal_toolbar.pack(fill=tk.X, padx=5, pady=5)
        
        # 现代化终端工具栏按钮
        clear_button = tk.Button(terminal_toolbar, 
                                text="🗑️ 清空",
                                command=self.core.clear_terminal,
                                bg='#ef4444',
                                fg='#ffffff',
                                font=('Microsoft YaHei UI', 9, 'bold'),
                                relief='flat',
                                padx=12,
                                pady=5,
                                borderwidth=0,
                                cursor='hand2',
                                activebackground='#dc2626')
        clear_button.pack(side=tk.LEFT, padx=4)
        clear_button.bind("<Enter>", lambda e, b=clear_button: b.configure(bg='#dc2626'))
        clear_button.bind("<Leave>", lambda e, b=clear_button: b.configure(bg='#ef4444'))
        
        copy_button = tk.Button(terminal_toolbar,
                                text="📋 复制",
                                command=self.core.copy_terminal_content,
                                bg='#3b82f6',
                                fg='#ffffff',
                                font=('Microsoft YaHei UI', 9, 'bold'),
                                relief='flat',
                                padx=12,
                                pady=5,
                                borderwidth=0,
                                cursor='hand2',
                                activebackground='#2563eb')
        copy_button.pack(side=tk.LEFT, padx=4)
        copy_button.bind("<Enter>", lambda e, b=copy_button: b.configure(bg='#2563eb'))
        copy_button.bind("<Leave>", lambda e, b=copy_button: b.configure(bg='#3b82f6'))
        
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
        
        # 现代化功能卡片配色
        features = [
            {"name": "📁 游戏目录", "description": "边狱巴士的游戏目录", "color": "#f59e0b"},
            {"name": "🔄 零协会", "description": "一个伟大的社区", "color": "#ef4444"},
            {"name": "📒 气泡文本", "description": "气泡mod的汉化版本\n提取码：fib6", "color": "#3b82f6"},
            {"name": "📝 维基", "description": "边狱巴士的灰机wiki", "color": "#10b981"},
            {"name": "📖 N网", "description": "下载边狱巴士mod", "color": "#8b5cf6"},
            {"name": "📦 Github", "description": "查看本项目源码", "color": "#6b7280"}
        ]
        
        for i, feature in enumerate(features):
            row = i // 3
            col = i % 3
            
            # 现代化卡片设计
            card_bg = self.core.darken_color(feature['color'], 0.12)
            card_frame = tk.Frame(features_container, 
                                bg=card_bg,
                                relief='flat',
                                borderwidth=0,
                                highlightthickness=1,
                                highlightbackground=self.core.lighten_color(card_bg, 20))
            card_frame.grid(row=row, column=col, padx=12, pady=12, sticky="nsew")
            card_frame.grid_propagate(False)
            card_frame.configure(width=195, height=130)
            
            title_label = tk.Label(card_frame, 
                                text=feature['name'],
                                bg=card_bg,
                                fg='#f8fafc',
                                font=('Microsoft YaHei UI', 11, 'bold'))
            title_label.pack(pady=(18, 6))
            
            desc_label = tk.Label(card_frame, 
                                text=feature['description'],
                                bg=card_bg,
                                fg='#cbd5e1',
                                font=('Microsoft YaHei UI', 9),
                                wraplength=170,
                                justify=tk.CENTER)
            desc_label.pack(pady=4)
            
            # 现代化按钮
            action_button = tk.Button(card_frame, 
                                    text="打开",
                                    command=lambda f=feature: self.core.open_feature(f),
                                    bg=feature['color'],
                                    fg='#ffffff',
                                    font=('Microsoft YaHei UI', 9, 'bold'),
                                    relief='flat',
                                    padx=16,
                                    pady=5,
                                    borderwidth=0,
                                    cursor='hand2',
                                    activebackground=self.core.lighten_color(feature['color'], 15))
            action_button.pack(pady=(8, 12))
            action_button.bind("<Enter>", lambda e, b=action_button, c=feature['color']: b.configure(bg=self.core.lighten_color(c, 10)))
            action_button.bind("<Leave>", lambda e, b=action_button, c=feature['color']: b.configure(bg=c))
        
        for i in range(3):
            features_container.columnconfigure(i, weight=1)
        for i in range(2):
            features_container.rowconfigure(i, weight=1)
            
        return features_container
        
    def _init_about_page(self):
        """初始化关于页面 - 使用程序主题色"""
        from functions.web_update.sql_manager import notify_new_version
        
        frost = self.app.tab_frost_canvases[5]
        
        # 使用程序主题色
        bg_color = self.core.bg_color
        lighten_bg = self.core.lighten_bg_color
        text_primary = '#f8fafc'
        text_secondary = '#cbd5e1'
        text_muted = '#94a3b8'
        accent_blue = '#3b82f6'
        accent_green = '#10b981'
        accent_cyan = '#06b6d4'
        
        # 贡献者数据
        contributors = [
            {
                "name": "FolkSkill",
                "role": "项目创始人 & 主开发者",
                "description": "Faust Launcher 的创始人和主要开发者，负责整体架构设计和核心功能开发。\n项目于 2025年11月25日 开始开发。\n已经过了这么久了，这还是我第一次这样长久的去投入到一个项目上，还做得这么的完善！\n感谢所有支持过我的朋友们，让我不至于放弃这个项目。同时，也让我学会了很多东西！",
                "icon": "assets/images/contributor/folkskill.png",
                "links": {
                    "github": "https://github.com/f0lkskill",
                    "blbl": "https://space.bilibili.com/599331034"
                }
            },
            {
                "name": "HZBHZB1234",
                "role": "项目程序贡献者",
                "description": "在本程序开发早期，提供了部分的代码贡献，以及非常有用的流程指导，感激不尽！\n大佬也在为社区编写自己的项目（LCTA），感兴趣的各位可以去体验下！",
                "icon": "assets/images/contributor/HZB.png",
                "links": {
                    "blbl": "https://space.bilibili.com/3493119444126599",
                    "github": "https://github.com/HZBHZB1234/",
                    "LCTA": "https://github.com/HZBHZB1234/LCTA-Limbus-company-transfer-auto"
                }
            },
            {
                "name": "里诺Ariko",
                "role": "民间有色战斗气泡文本作者",
                "description": "里诺Ariko是社区的活跃成员之一，在b站发布了很多游戏内容的提前个人汉化版本。\n同时也在不断完善和更新自己的民间气泡汉化内容，感谢ta持续的为启动器提供的有色战斗气泡文本。",
                "icon": "assets/images/contributor/Ariko.png",
                "links": {
                    "blbl": "https://space.bilibili.com/321808552"
                }
            },
            {
                "name": "零协会",
                "role": "汉化支持",
                "description": "关于都市零协会汉化组\n都市零协会汉化组是围绕《Limbus Company》建立的中文社区本地化项目。\n我们致力于为中文玩家提供稳定、清晰、易于使用的游戏文本翻译与相关工具，\n让更多玩家能够更顺畅地理解剧情、系统与角色内容，并在相同的基础和共识之间参与社区讨论。\n本启动器采用自动更新获取零协会的汉化，在此特别感谢其为社区做出的重大贡献。",
                "icon": "assets/images/contributor/zeroasso.jpg",
                "links": {
                    "官网": "https://www.zeroasso.top/",
                    "blbl": "https://space.bilibili.com/3632319835409017",
                    "github": "https://github.com/LocalizeLimbusCompany/LocalizeLimbusCompany"
                }
            },
            {
                "name": "社区贡献者",
                "role": "测试 & 反馈",
                "description": "感谢所有参与测试、提供反馈和建议的社区成员，你们的支持让这个项目变得更好。\n包括但不限以下人员（排名顺序不分前后）：\n· 使徒\n· HZB\n· 尘\n· 海螺\n· 庭渡久歌(是我!)\n· 里诺Ariko\n· 终末之影\n· 四季交融\n· 快乐咸鱼君\n· 盘",
                "icon": "assets/images/contributor/community.png"
            }
        ]
        
        # 主容器
        main_container = tk.Frame(frost, bg=bg_color)
        frost.create_window(340, 20, window=main_container, anchor=tk.N,
                            width=640, height=500, tags=("content_win",))
        
        # 顶部标签栏
        tab_frame = tk.Frame(main_container, bg=lighten_bg, height=42)
        tab_frame.pack(fill=tk.X, side=tk.TOP)
        tab_frame.pack_propagate(False)
        
        # 内容区域
        content_frame = tk.Frame(main_container, bg=bg_color)
        content_frame.pack(fill=tk.BOTH, expand=True)
        
        # 当前选中的标签
        self._current_about_tab = tk.StringVar(value="program")
        
        def switch_tab(tab_name):
            self._current_about_tab.set(tab_name)
            # 更新标签样式
            for tab_id, btn in tab_buttons.items():
                if tab_id == tab_name:
                    btn.configure(bg=bg_color, fg=accent_blue)
                else:
                    btn.configure(bg=lighten_bg, fg=text_secondary)
            # 切换内容
            self._show_about_content(content_frame, tab_name, contributors, 
                                     bg_color, lighten_bg, text_primary, text_secondary, text_muted,
                                     accent_blue, accent_cyan, accent_green)
        
        # 创建标签按钮
        tab_buttons = {}
        tabs = [
            ("program", "程序介绍"),
            ("contributors", "贡献者")
        ]
        
        for tab_id, tab_text in tabs:
            is_active = tab_id == "program"
            btn = tk.Button(tab_frame, text=tab_text,
                          bg=bg_color if is_active else lighten_bg,
                          fg=accent_blue if is_active else text_secondary,
                          font=('Microsoft YaHei UI', 10, 'bold'),
                          relief='flat', borderwidth=0,
                          cursor='hand2',
                          command=lambda t=tab_id: switch_tab(t))
            btn.pack(side=tk.LEFT, padx=(15, 5), pady=8)
            tab_buttons[tab_id] = btn
            
            # 悬停效果
            def on_enter(e, b=btn, tid=tab_id):
                if self._current_about_tab.get() != tid:
                    b.configure(bg=self.core.darken_color(bg_color, 0.9))
            def on_leave(e, b=btn, tid=tab_id):
                is_current = self._current_about_tab.get() == tid
                b.configure(bg=bg_color if is_current else lighten_bg)
            
            btn.bind("<Enter>", on_enter)
            btn.bind("<Leave>", on_leave)
        
        # 初始显示程序介绍
        self._show_about_content(content_frame, "program", contributors,
                                bg_color, lighten_bg, text_primary, text_secondary, text_muted,
                                accent_blue, accent_cyan, accent_green)
    
    def _show_about_content(self, parent, tab_name, contributors, bg_color, lighten_bg,
                           text_primary, text_secondary, text_muted,
                           accent_blue, accent_cyan, accent_green):
        """显示关于页面的内容"""
        # 清除现有内容
        for widget in parent.winfo_children():
            widget.destroy()
        
        if tab_name == "program":
            self._show_program_info(parent, bg_color, lighten_bg, text_primary, text_secondary, 
                                   text_muted, accent_blue, accent_cyan, accent_green)
        else:
            self._show_contributors(parent, contributors, bg_color, lighten_bg, text_primary, 
                                   text_secondary, text_muted, accent_blue)
    
    def _show_program_info(self, parent, bg_color, lighten_bg, text_primary, text_secondary, 
                          text_muted, accent_blue, accent_cyan, accent_green):
        """显示程序介绍 - 包含标题、版本、介绍和按钮"""
        from functions.web_update.sql_manager import notify_new_version
        
        # 创建滚动区域
        canvas = tk.Canvas(parent, bg=bg_color, highlightthickness=0)
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        scrollable_frame = tk.Frame(canvas, bg=bg_color)
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw", width=600)
        canvas.configure(yscrollcommand=scrollbar.set)
        
        # 绑定鼠标滚轮事件到所有子控件
        def on_mousewheel(event):
            canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        
        def bind_mousewheel(widget):
            widget.bind("<MouseWheel>", on_mousewheel)
            for child in widget.winfo_children():
                bind_mousewheel(child)
        
        bind_mousewheel(scrollable_frame)
        
        canvas.pack(side="left", fill="both", expand=True, padx=10, pady=10)
        scrollbar.pack(side="right", fill="y")
        
        # 标题 - 居中
        title_frame = tk.Frame(scrollable_frame, bg=bg_color)
        title_frame.pack(fill=tk.X, pady=(10, 5))
        tk.Label(title_frame, text="关于 Faust Launcher", bg=bg_color, fg=text_primary,
                font=('Microsoft YaHei UI', 20, 'bold')).pack()
        
        # 版本标签 - 居中
        ver_frame = tk.Frame(scrollable_frame, bg=accent_blue, padx=12, pady=3)
        ver_frame.pack(pady=(0, 15))
        tk.Label(ver_frame, text=f"v{self.core.version_info}", bg=accent_blue, fg=text_primary,
                font=('Microsoft YaHei UI', 9, 'bold')).pack()
        
        # 版本信息区域
        info_frame = tk.Frame(scrollable_frame, bg=lighten_bg, padx=15, pady=12)
        info_frame.pack(fill=tk.X, pady=(0, 15))
        
        tk.Label(info_frame, text="📦 版本信息", bg=lighten_bg, fg=accent_blue,
                font=('Microsoft YaHei UI', 12, 'bold')).pack(anchor='w')
        
        tk.Label(info_frame, text=f"  当前版本: {self.core.version_info}", bg=lighten_bg, fg=text_secondary,
                font=('Microsoft YaHei UI', 10)).pack(anchor='w', pady=(8, 3))
        tk.Label(info_frame, text="  开发者: FolkSkill", bg=lighten_bg, fg=text_secondary,
                font=('Microsoft YaHei UI', 10)).pack(anchor='w', pady=3)
        
        # 应用介绍区域
        desc_frame = tk.Frame(scrollable_frame, bg=lighten_bg, padx=15, pady=12)
        desc_frame.pack(fill=tk.X, pady=(0, 15))
        
        tk.Label(desc_frame, text="📖 应用介绍", bg=lighten_bg, fg=accent_cyan,
                font=('Microsoft YaHei UI', 12, 'bold')).pack(anchor='w', pady=(0, 8))
        
        desc_text = tk.Text(desc_frame, bg=lighten_bg, fg=text_secondary,
                            font=('Microsoft YaHei UI', 10), wrap=tk.WORD,
                            relief=tk.FLAT, bd=0, padx=0, pady=0,
                            highlightthickness=0, height=8)
        desc_text.pack(fill=tk.X)
        
        # 文本标签样式
        desc_text.tag_configure("h2", font=('Microsoft YaHei UI', 11, 'bold'),
                            foreground='#fbbf24', spacing1=6, spacing3=3)
        desc_text.tag_configure("h3", font=('Microsoft YaHei UI', 10, 'bold'),
                            foreground=accent_green, spacing1=4, spacing3=2)
        desc_text.tag_configure("normal", foreground=text_secondary,
                            font=('Microsoft YaHei UI', 10))
        desc_text.tag_configure("highlight", foreground=text_primary,
                            font=('Microsoft YaHei UI', 10, 'bold'))
        desc_text.tag_configure("muted", foreground=text_muted,
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
        
        # 按钮区域 - 居中对齐，减小间距
        btn_frame = tk.Frame(scrollable_frame, bg=bg_color)
        btn_frame.pack(fill=tk.X, pady=(0, 15))
        
        # 内部容器用于居中
        btn_inner_frame = tk.Frame(btn_frame, bg=bg_color)
        btn_inner_frame.pack(expand=True)
        
        buttons_data = [
            ("🌐 B站", self.core.open_website, "#06b6d4", "#0891b2"),
            ("💌 反馈", self.core.send_feedback, accent_blue, "#2563eb"),
            ("📦 GitHub", lambda: self.core.open_feature({"name": "📦 Github"}), "#475569", "#334155"),
            ("📄 更新", lambda: notify_new_version(
                current_version_name=self.core.version_info, info='版本信息', root=self.app.root), accent_green, "#059669"),
        ]
        
        for text, cmd, color, hover_color in buttons_data:
            btn = tk.Button(btn_inner_frame, text=text, command=cmd,
                        bg=color, fg=text_primary, bd=0, cursor='hand2',
                        font=('Microsoft YaHei UI', 9, 'bold'),
                        padx=12, pady=6, borderwidth=0,
                        activebackground=hover_color)
            btn.pack(side=tk.LEFT, padx=3)
            
            btn.bind("<Enter>", lambda e, b=btn, hc=hover_color: b.config(bg=hc))
            btn.bind("<Leave>", lambda e, b=btn, oc=color: b.config(bg=oc))
    
    def _show_contributors(self, parent, contributors, bg_color, lighten_bg, text_primary, 
                          text_secondary, text_muted, accent_blue):
        """显示贡献者列表"""
        # 左侧列表
        list_frame = tk.Frame(parent, bg=bg_color, width=200)
        list_frame.pack(side=tk.LEFT, fill=tk.Y, padx=(15, 0), pady=15)
        list_frame.pack_propagate(False)
        
        tk.Label(list_frame, text="贡献者列表", bg=bg_color, fg=text_primary,
                font=('Microsoft YaHei UI', 11, 'bold')).pack(anchor='w', pady=(0, 10))
        
        # 贡献者列表
        self._selected_contributor = tk.IntVar(value=0)
        self._contributor_list_buttons = []  # 保存按钮引用
        
        for i, contributor in enumerate(contributors):
            # 创建贡献者项容器
            item_frame = tk.Frame(list_frame, bg=self.core.darken_color(bg_color, 0.9) if i == 0 else bg_color,
                                  cursor='hand2')
            item_frame.pack(fill=tk.X, pady=2)
            item_frame.bind("<Button-1>", lambda e, idx=i: self._select_contributor(idx, contributors, 
                                                                        list_frame, detail_frame,
                                                                        bg_color, lighten_bg, text_primary, 
                                                                        text_secondary, text_muted,
                                                                        accent_blue))
            
            # 左侧缩略图
            thumb_frame = tk.Frame(item_frame, bg=item_frame.cget('bg'), width=36, height=36)
            thumb_frame.pack(side=tk.LEFT, padx=8, pady=6)
            thumb_frame.pack_propagate(False)
            
            try:
                if os.path.exists(contributor["icon"]):
                    from PIL import Image, ImageTk
                    img = Image.open(contributor["icon"])
                    img = img.resize((32, 32), Image.Resampling.LANCZOS)
                    photo = ImageTk.PhotoImage(img)
                    thumb_label = tk.Label(thumb_frame, image=photo, bg=item_frame.cget('bg'))
                    thumb_label.image = photo  # type: ignore # 保持引用
                    thumb_label.pack(expand=True)
                else:
                    # 默认缩略图 - 显示首字母
                    thumb_label = tk.Label(thumb_frame, text=contributor["name"][0], 
                                          bg=lighten_bg, fg=text_primary,
                                          font=('Microsoft YaHei UI', 14, 'bold'))
                    thumb_label.place(relx=0.5, rely=0.5, anchor='center')
            except Exception:
                # 默认缩略图
                thumb_label = tk.Label(thumb_frame, text=contributor["name"][0], 
                                      bg=lighten_bg, fg=text_primary,
                                      font=('Microsoft YaHei UI', 14, 'bold'))
                thumb_label.place(relx=0.5, rely=0.5, anchor='center')
            
            # 右侧姓名
            name_label = tk.Label(item_frame, text=contributor["name"],
                                bg=item_frame.cget('bg'),
                                fg=accent_blue if i == 0 else text_secondary,
                                font=('Microsoft YaHei UI', 10, 'bold' if i == 0 else 'normal'),
                                cursor='hand2')
            name_label.pack(side=tk.LEFT, fill=tk.Y, expand=True, padx=(0, 8))
            name_label.bind("<Button-1>", lambda e, idx=i: self._select_contributor(idx, contributors, 
                                                                        list_frame, detail_frame,
                                                                        bg_color, lighten_bg, text_primary, 
                                                                        text_secondary, text_muted,
                                                                        accent_blue))
            
            self._contributor_list_buttons.append({
                'frame': item_frame,
                'thumb': thumb_frame,
                'name': name_label,
                'thumb_label': thumb_label if 'thumb_label' in dir() else None
            })
        
        # 分隔线
        tk.Frame(parent, bg=self.core.lighten_color(bg_color, 20), width=1).pack(side=tk.LEFT, fill=tk.Y, padx=10, pady=15)
        
        # 右侧详情
        detail_frame = tk.Frame(parent, bg=bg_color)
        detail_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 15), pady=15)
        
        self._update_contributor_detail(detail_frame, contributors[0], bg_color, lighten_bg,
                                       text_primary, text_secondary, text_muted, accent_blue)
    
    def _select_contributor(self, index, contributors, list_frame, detail_frame,
                           bg_color, lighten_bg, text_primary, text_secondary, text_muted, accent_blue):
        """选择贡献者"""
        self._selected_contributor.set(index)
        
        # 更新列表样式
        for i, item in enumerate(self._contributor_list_buttons):
            is_selected = (i == index)
            new_bg = self.core.darken_color(bg_color, 0.9) if is_selected else bg_color
            item['frame'].configure(bg=new_bg)
            item['thumb'].configure(bg=new_bg)
            item['name'].configure(
                bg=new_bg,
                fg=accent_blue if is_selected else text_secondary,
                font=('Microsoft YaHei UI', 10, 'bold' if is_selected else 'normal')
            )
            # 更新缩略图背景
            if item['thumb_label'] and isinstance(item['thumb_label'], tk.Label):
                if not hasattr(item['thumb_label'], 'image') or item['thumb_label'].image is None:
                    item['thumb_label'].configure(bg=lighten_bg)
        
        # 更新详情
        for widget in detail_frame.winfo_children():
            widget.destroy()
        self._update_contributor_detail(detail_frame, contributors[index], bg_color, lighten_bg,
                                       text_primary, text_secondary, text_muted, accent_blue)
    
    def _update_contributor_detail(self, parent, contributor, bg_color, lighten_bg,
                                   text_primary, text_secondary, text_muted, accent_blue):
        """更新贡献者详情"""
        # 头像区域
        avatar_frame = tk.Frame(parent, bg=bg_color)
        avatar_frame.pack(fill=tk.X, pady=(10, 15))
        
        # 尝试加载头像
        try:
            if os.path.exists(contributor["icon"]):
                from PIL import Image, ImageTk
                img = Image.open(contributor["icon"])
                img = img.resize((80, 80), Image.Resampling.LANCZOS)
                photo = ImageTk.PhotoImage(img)
                avatar_label = tk.Label(avatar_frame, image=photo, bg=bg_color)
                avatar_label.image = photo  # type: ignore # 保持引用
                avatar_label.pack()
            else:
                # 默认头像占位
                default_avatar = tk.Frame(avatar_frame, bg=lighten_bg,
                                         width=80, height=80)
                default_avatar.pack()
                tk.Label(default_avatar, text=contributor["name"][0], 
                        bg=lighten_bg,
                        fg=text_primary, font=('Microsoft YaHei UI', 24, 'bold')).place(relx=0.5, rely=0.5, anchor='center')
        except Exception:
            # 默认头像占位
            default_avatar = tk.Frame(avatar_frame, bg=lighten_bg,
                                     width=80, height=80)
            default_avatar.pack()
            tk.Label(default_avatar, text=contributor["name"][0], 
                    bg=lighten_bg,
                    fg=text_primary, font=('Microsoft YaHei UI', 24, 'bold')).place(relx=0.5, rely=0.5, anchor='center')
        
        # 姓名
        tk.Label(parent, text=contributor["name"], bg=bg_color, fg=text_primary,
                font=('Microsoft YaHei UI', 16, 'bold')).pack(anchor='w')
        
        # 职位标签
        role_label = tk.Label(parent, text=contributor["role"], bg=accent_blue, fg=text_primary,
                             font=('Microsoft YaHei UI', 9, 'bold'), padx=10, pady=2)
        role_label.pack(anchor='w', pady=(8, 15))
        
        # 分隔线
        tk.Frame(parent, bg=self.core.lighten_color(bg_color, 20), height=1).pack(fill=tk.X, pady=(0, 15))
        
        # 介绍
        tk.Label(parent, text="简介", bg=bg_color, fg=text_secondary,
                font=('Microsoft YaHei UI', 10, 'bold')).pack(anchor='w', pady=(0, 8))
        
        desc_text = tk.Text(parent, bg=bg_color, fg=text_secondary,
                           font=('Microsoft YaHei UI', 10), wrap=tk.WORD,
                           relief=tk.FLAT, bd=0, padx=0, pady=0,
                           highlightthickness=0, height=6)
        desc_text.pack(fill=tk.BOTH, expand=True)
        desc_text.insert(tk.END, contributor["description"])
        desc_text.config(state=tk.DISABLED)
        
        # 链接按钮
        if "links" in contributor and contributor["links"]:
            tk.Frame(parent, bg=self.core.lighten_color(bg_color, 20), height=1).pack(fill=tk.X, pady=(15, 10))
            
            links_frame = tk.Frame(parent, bg=bg_color)
            links_frame.pack(fill=tk.X, pady=(0, 5))
            
            link_icons = {
                "github": "🐙 GitHub",
                "blbl": "📺 B站",
                "website": "🌐 网站",
                "twitter": "🐦 Twitter",
                "email": "📧 邮箱"
            }
            link_colors = {
                "github": ("#24292e", "#1a1e22"),
                "blbl": ("#00a1d6", "#008cc7"),
                "website": ("#10b981", "#059669"),
                "twitter": ("#1da1f2", "#0d8ecf"),
                "email": ("#ea4335", "#d33b28")
            }
            
            for link_type, url in contributor["links"].items():
                color, hover = link_colors.get(link_type, (accent_blue, "#2563eb"))
                text = link_icons.get(link_type, f"🔗 {link_type.capitalize()}")
                
                btn = tk.Button(links_frame, text=text,
                              bg=color, fg=text_primary,
                              font=('Microsoft YaHei UI', 9, 'bold'),
                              relief=tk.FLAT, bd=0, cursor='hand2',
                              padx=12, pady=5,
                              command=lambda u=url: webbrowser.open(u))
                btn.pack(side=tk.LEFT, padx=(0, 8))
                btn.bind("<Enter>", lambda e, b=btn, h=hover: b.config(bg=h))
                btn.bind("<Leave>", lambda e, b=btn, c=color: b.config(bg=c))
        
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

        while gui.is_downloading:
            sleep(1)
        
        print("零协会汉化包下载完成")

        sleep(1.5)

        gui_res = DownloadGUI(main_root, 'resources/', False, download_func=download_and_extract_gui)
        dt = Thread(target=check_resource_update, args=(gui_res,)).start()

        while gui_res.is_downloading:
            sleep(1)
            
        del dt
        gui_res.root.destroy()
        
        print("开始下载气泡文本...")
        download_bubble(download_path)
        print("气泡文本载入完成")

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