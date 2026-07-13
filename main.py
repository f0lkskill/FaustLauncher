import tkinter as tk
from tkinter import ttk, font, messagebox
import os
import random
import sys
from PIL import Image, ImageTk, ImageFilter
from subprocess import Popen
from functions.pages.setting.settings_page import init_settings_page
from functions.base.settings_manager import get_settings_manager
from functions.pages.notice.loading_info import create_simple_splash
from functions.web_update.sql_manager import notify_new_version
from functions.update.version_ulits import check_version_update
from functions.base.window_ulits import center_window
from functions.base.sound_ulits import play_sound
from rich import print
from functions.extension.addon.addon_ulit import AddonManager
from functions.pages.terminal.terminal_redirect import TerminalRedirector
from threading import Thread
import traceback
import urllib3

# 禁用 urllib3 的警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 添加自定义汉化工具导入
try:
    sys.path.append('functions')
    from functions.pages.tools.custom_translation import open_custom_translation_tool
except ImportError as e:
    print(f"导入自定义汉化工具失败: {e}")
    open_custom_translation_tool = None

downloading = False
root: tk.Tk = None # type: ignore
debug = False
settings_manager = get_settings_manager()
bg_color:str = settings_manager.get_setting("bg_color") # type: ignore
VERSION_INFO:str = settings_manager.get_setting("version_info") # type: ignore

if os.path.exists("updater.vbs"):
    # 删除旧的更新脚本
    os.remove("updater.vbs")
    
# 检测是否有已经正在运行的程序系统线程
import ctypes
# 创建单实例检测函数
def check_single_instance():
    """通过窗口标题检测是否已有实例在运行，如果有则恢复窗口并返回True"""
    user32 = ctypes.windll.user32

    hwnd = user32.FindWindowA(None, "Faust Launcher".encode('utf-8'))

    if hwnd:
        print(f"找到已运行的窗口，句柄: {hwnd}，准备恢复窗口")

        # 根据窗口状态选择不同的恢复方式
        if user32.IsIconic(hwnd):
            # 窗口被最小化到任务栏 -> SW_RESTORE
            user32.ShowWindow(hwnd, 9)
        elif not user32.IsWindowVisible(hwnd):
            # 窗口被隐藏（withdraw） -> SW_SHOW，不改变尺寸位置
            user32.ShowWindow(hwnd, 5)

        user32.SetForegroundWindow(hwnd)
        return True

    return False

class FaustLauncherApp:
    def __init__(self, root: tk.Tk, on_initialized=None):
        global bg_color

        self.root = root
        self.root.title("Faust Launcher")
        self.root.geometry("800x700")
        self.root.resizable(False, False)

        self.addon_manager = None

        center_window(self.root, False)
        
        self.root.attributes('-topmost', True)
        
        # 设置应用程序图标
        try:
            if os.path.exists("assets/images/icon/icon.ico"):
                self.root.iconbitmap("assets/images/icon/icon.ico")
        except:
            pass
        
        # 背景图片相关
        self.background_images = []
        self.current_bg_index = 0
        self.current_bg_image = None
        self.current_blurred_bg = None
        self._last_sound_ms = 0
        self.load_background_images()
        self.bg_color = bg_color
        self.lighten_bg_color = self.lighten_color(self.bg_color, 5)
        
        # 创建主容器框架
        self.container = tk.Frame(self.root, bg=self.darken_color(self.bg_color, 0.7))
        self.container.pack(fill=tk.BOTH, expand=True)
        
        # 创建背景 Canvas - 覆盖整个窗口
        self.bg_canvas = tk.Canvas(self.container, highlightthickness=0)
        self.bg_canvas.place(x=0, y=0, relwidth=1, relheight=1)
        
        # 创建内容 Canvas（显示毛玻璃背景图片 - 参考 loading_info.py 模糊+暗化方案）
        self.content_canvas = tk.Canvas(self.container, highlightthickness=0, bg=self.bg_color)
        self.content_canvas.place(relx=0.5, rely=0.5, anchor=tk.CENTER, width=700, height=600)
        
        # 保存当前内容区毛玻璃图片引用（防止GC）
        self.current_content_bg = None
        self.tab_frost_canvases = []
        
        # 创建分页控件 - 嵌入内容 Canvas
        self.notebook = ttk.Notebook(self.content_canvas)
        self.content_canvas.create_window(350, 300, window=self.notebook,
                                          anchor=tk.CENTER, width=680, height=580)
        
        # 创建页面 - 添加工具页、插件&mod管理页和下载中心
        self.home_frame = tk.Frame(self.notebook, bg=self.bg_color)
        self.features_frame = tk.Frame(self.notebook, bg=self.bg_color)
        self.tools_frame = tk.Frame(self.notebook, bg=self.bg_color)  # 工具页
        self.mod_addon_frame = tk.Frame(self.notebook, bg=self.bg_color)  # 插件&mod管理页
        self.download_center_frame = tk.Frame(self.notebook, bg=self.bg_color)  # 下载中心页面
        self.about_frame = tk.Frame(self.notebook, bg=self.bg_color)
        self.settings_frame = tk.Frame(self.notebook, bg=self.bg_color)

        # 为每个标签页创建毛玻璃背景 Canvas（置于最底层，让内部 frame 透出毛玻璃效果）
        self.tab_frost_canvases = []
        for frame in [self.home_frame, self.features_frame, self.tools_frame,
                      self.mod_addon_frame, self.download_center_frame,
                      self.about_frame, self.settings_frame]:
            canvas = tk.Canvas(frame, highlightthickness=0)
            canvas.place(x=0, y=0, relwidth=1, relheight=1)
            canvas.lower(1)
            self.tab_frost_canvases.append(canvas)

        # 添加页面到分页控件
        self.notebook.add(self.home_frame, text="🏘 主页")
        self.notebook.add(self.features_frame, text="✈ 快捷方式")
        self.notebook.add(self.tools_frame, text="🔨 工具页")
        self.notebook.add(self.mod_addon_frame, text="🧩 插件&Mod")
        self.notebook.add(self.download_center_frame, text="📦 下载中心")  # 新增下载中心标签页
        self.notebook.add(self.settings_frame, text="⚙️ 设置")
        self.notebook.add(self.about_frame, text="💻 关于")
        
        # 绑定分页切换事件
        self.notebook.bind("<<NotebookTabChanged>>", self.on_tab_changed)
        self.root.bind_all("<ButtonPress-1>", self._on_global_click)   # 左键按下

        # 绑定关闭按钮事件
        def check_close():
            if settings_manager.get_setting("after_gui_exit") == 0:
                self.root.withdraw()
            else:
                self.root.destroy()
                os._exit(0)
            
            if not settings_manager.get_setting("mems")["tray_hint"]: # type: ignore
                settings_manager.set_setting("mems", {"tray_hint": True}) # type: ignore
                messagebox.showinfo("提示", "程序将继续在托盘后台继续运行，右键托盘图标可退出程序\n您可以在设置中修改退出后操作")
        root.protocol("WM_DELETE_WINDOW", check_close)

        # 设置样式
        self.set_styles()

        # 初始化各页面
        self.init_home_page()
        self.init_features_page()
        self.init_tools_page()  # 工具页初始化
        self.init_mod_addon_page()  # 插件&mod管理页初始化
        self.init_download_center_page()  # 下载中心页面初始化
        self.init_settings_page()
        self.init_about_page()
        self.init_tray()
        
        # 启动背景轮换
        self.start_background_rotation()
        
        # 设置终端重定向
        self.setup_terminal_redirect()
        
        # 保存初始化完成回调
        self.on_initialized = on_initialized
        
        # 延迟调用初始化完成回调，确保界面完全渲染
        self.root.after(500, self._notify_initialized)
    
    def _on_global_click(self, event):
        """全局点击事件处理：播放音效。"""

        # 1) 节流：30ms 以内的连续点击忽略，防止拖拽/高频事件疯狂播放
        import time
        now_ms = int(time.time() * 1000)
        if now_ms - self._last_sound_ms < 30:
            return
        self._last_sound_ms = now_ms

        # 2) 排除某些不想播放的情况（可选，按需保留）
        # event.widget 是被点到的控件，你可以按类型/名称过滤
        widget_name = getattr(event.widget, 'winfo_class', lambda: '')()
        # 例如：Toplevel / Frame 等空白容器被点到时不播放，只在"可交互控件"上播
        container_classes = {'Frame', 'TFrame', 'Canvas', 'Toplevel',
                             'Labelframe', 'TLabelframe', 'Panedwindow',
                             'TPanedwindow'}
        if widget_name not in container_classes:
            play_sound("assets/voices/click.wav")

    def init_tray(self):
        """初始化托盘程序"""
        ico = Image.open("assets/images/icon/icon.ico")
        import pystray, threading

        menu_items = [
            pystray.MenuItem('显示窗口', self.root.deiconify, default=True),
            pystray.MenuItem('隐藏', self.root.withdraw),
        ]

        # 插件子菜单项列表，仅用于当前次构建菜单
        self.addon_menu_items: list = []

        # 注意：**不**把 main.py 的 addon_menu_items 传给 AddonManager，
        # AddonManager 内部使用独立的 custom_tray_items 列表来保存插件注册的项，
        # build_addon_menu() 在每次构建菜单时通过 get_custom_tray_items() 读取它们，
        # 然后合并到 addon_menu_items 中。这样 build_addon_menu 可以随意 clear 自己的列表，
        # 而不会意外清空插件注册的项。
        self.addon_manager = AddonManager([], app=self)
        self.addon_manager.run_all_addon()

        def build_addon_menu() -> pystray.Menu:
            """动态构造插件子菜单内容"""
            # 先清空旧项目，再根据当前扫描到的插件生成
            self.addon_menu_items.clear()

            # --- 第一部分：自动扫描的插件（点击运行该插件）---
            auto_items: list = []
            for addon in self.addon_manager.get_all_addons(): # type: ignore
                name = addon['name']
                try:
                    enabled = bool(addon.get('info', {}).get('settings', {}).get('enable', True))
                except Exception:
                    enabled = True

                def _make_runner(n: str):
                    def _run(icon=None, item=None):
                        try:
                            self.addon_manager.run_addon(n) # type: ignore
                        except Exception as e:
                            print(f"手动运行插件 {n} 失败: {e}")
                    return _run

                label = f"🔧 {name}" if enabled else f"⚙️ {name} (已禁用)"
                auto_items.append(pystray.MenuItem(label, _make_runner(name)))

            # --- 第二部分：插件主动注册的自定义项 ---
            custom_items = self.addon_manager.get_custom_tray_items() # type: ignore

            # 合并两部分
            self.addon_menu_items.extend(auto_items)
            if custom_items:
                # 添加分隔线（使用一个不可点击的项作为分隔）
                if auto_items:
                    self.addon_menu_items.append(pystray.MenuItem(
                        '─── 自定义项 ───', None, enabled=False))
                self.addon_menu_items.extend(custom_items)

            if not self.addon_menu_items:
                self.addon_menu_items.append(pystray.MenuItem('（暂无可用插件）', None, enabled=False))

            return pystray.Menu(*self.addon_menu_items)

        # 使用 lambda 让插件子菜单支持动态生成
        def addon_menu_lambda(icon=None, item=None):
            return build_addon_menu()

        # 使用 pystray.Menu 的回调式构造，让菜单在每次打开时重建
        root_menu = pystray.MenuItem('插件', lambda icon, item: build_addon_menu())
        menu_items.append(root_menu)
        menu_items.append(pystray.MenuItem('重载插件', lambda icon=None, item=None: self._on_reload_addons()))
        menu_items.append(pystray.MenuItem('退出', lambda: os._exit(0)))

        menu = pystray.Menu(*menu_items)
        self.tray = pystray.Icon(
            'FaustLauncher',
            ico,
            '浮士德启动器',
            menu
        )

        # 在单独线程中运行托盘图标
        threading.Thread(target=self.tray.run, daemon=True).start()

    def _on_reload_addons(self):
        """重载插件的统一入口：先清理旧实例、重新扫描、重新加载"""
        try:
            self.addon_manager.reload_all_addons() # type: ignore
            # 手动触发一次托盘菜单刷新（若支持）
            if hasattr(self, 'tray') and self.tray is not None:
                try:
                    self.tray.update_menu()
                except Exception:
                    pass
        except Exception as e:
            print(f"重载插件时发生错误: {e}")

    def _notify_initialized(self):
        """通知应用程序初始化完成"""
        self.root.attributes('-topmost', False)
        
        # 确保界面已经完全渲染
        self.root.update_idletasks()
        self.root.update()
        
        # 调用初始化完成回调
        if self.on_initialized:
            self.on_initialized()
    
    def init_settings_page(self):
        """初始化设置页面"""
        try:
            self.settings_page = init_settings_page(self.settings_frame, self.bg_color, self.lighten_bg_color)
        except Exception as e:
            print(f"初始化设置页面失败: {e}")
            # 创建错误提示
            error_label = tk.Label(self.settings_frame, 
                                 text="❌ 设置页面加载失败",
                                 font=('Microsoft YaHei UI', 16),
                                 bg=self.bg_color, fg='white')
            error_label.pack(expand=True)
            
            detail_label = tk.Label(self.settings_frame, 
                                  text=str(e),
                                  font=('Microsoft YaHei UI', 10),
                                  bg=self.bg_color, fg='#bdc3c7')
            detail_label.pack()
    
    def init_mod_addon_page(self):
        """初始化插件&mod管理页面"""
        try:
            from functions.pages.extension.mod_addon_info import init_mod_addon_manager
            self.mod_addon_page = init_mod_addon_manager(self.mod_addon_frame, self.bg_color, self.lighten_bg_color, self)
        except Exception as e:
            print(f"初始化插件&mod管理页面失败: {e}")
            # 创建错误提示
            error_label = tk.Label(self.mod_addon_frame, 
                                 text="❌ 插件&Mod管理页面加载失败",
                                 font=('Microsoft YaHei UI', 16),
                                 bg=self.bg_color, fg='white')
            error_label.pack(expand=True)
            
            detail_label = tk.Label(self.mod_addon_frame, 
                                  text=str(e),
                                  font=('Microsoft YaHei UI', 10),
                                  bg=self.bg_color, fg='#bdc3c7')
            detail_label.pack()
    
    def init_download_center_page(self):
        """初始化下载中心页面"""
        try:
            from functions.pages.download.download_center import init_download_center
            self.download_center_page = init_download_center(self.download_center_frame, self, self.bg_color, self.lighten_bg_color)
        except Exception as e:
            print(f"初始化下载中心页面失败: {e}")
            # 创建错误提示
            error_label = tk.Label(self.download_center_frame, 
                                 text="❌ 下载中心页面加载失败",
                                 font=('Microsoft YaHei UI', 16),
                                 bg=self.bg_color, fg='white')
            error_label.pack(expand=True)
            
            detail_label = tk.Label(self.download_center_frame, 
                                  text=str(e),
                                  font=('Microsoft YaHei UI', 10),
                                  bg=self.bg_color, fg='#bdc3c7')
            detail_label.pack()

    def init_tools_page(self):
        """初始化工具页内容"""
        global settings_manager
        from functions.fancy.dialog_colorful import test_color_gradient_gui
        from functions.pages.tools.select_font import select_font_gui
        from functions.pages.tools.auto_translate_gui import show_auto_translate_gui
        
        # 创建工具区域
        tools_container = tk.Frame(self.tools_frame, bg=self.bg_color)
        tools_container.pack(fill=tk.BOTH, expand=True, padx=80, pady=20)
        
        tools_frost = tk.Canvas(tools_container, highlightthickness=0)
        tools_frost.place(x=0, y=0, relwidth=1, relheight=1)
        tools_frost.lower(1)
        self.tab_frost_canvases.append(tools_frost)
        
        def spawn_function_tr():
            source_path = f"{settings_manager.get_setting('game_path')}/LimbusCompany_Data/Assets/Resources_moved/Localize/en"
            target_path = "lang/LLC_zh-CN"

            return lambda: show_auto_translate_gui(self, source_path, target_path)
        
        # 创建工具列表
        tools = [
            {"name": "🔧 自定义汉化", "description": "编辑lang目录下的JSON文件\n实现自定义的汉化修改。", "color": "#3498db", "command": self.open_custom_translation_tool},
            {"name": "🚜 文件夹超链接", "description": "为文件夹制作超链接，达到转移空间的目的？", "color": "#34db34", "command": self.folder_link},
            {"name": "💻 渐变文本处理器", "description": "根据用户输入的文本生成渐变的 Untity 富文本。", "color": "#FFBD30", "command": lambda: test_color_gradient_gui(self)},
            {"name": "📝 字体修改", "description": "修改汉化包的字体，使用你自己喜欢的字体包代替。", "color": "#FA3E3E", "command": lambda: select_font_gui(self)},
            {"name": "🔄 自动汉化", "description": "使用思知实现对游戏的补充汉化。", "color": "#9130FF", "command": spawn_function_tr()},
            {"name": "📦 Mod 管理器", "description": "管理边狱巴士的 Mod。", "color": "#808080", "command": self.open_mod_manager}
        ]
        
        # 使用网格布局创建工具卡片
        for i, tool in enumerate(tools):
            row = i // 2
            col = i % 2
            
            # 创建工具卡片
            card_frame = tk.Frame(tools_container, 
                                bg=tool['color'],
                                relief='raised',
                                borderwidth=1)
            card_frame.grid(row=row, column=col, padx=5, pady=5, sticky="nsew")
            card_frame.grid_propagate(False)
            card_frame.configure(width=150, height=150)
            
            # 添加工具标题
            title_label = tk.Label(card_frame, 
                                 text=tool['name'],
                                 bg=tool['color'],
                                 fg='white',
                                 font=('Microsoft YaHei UI', 14, 'bold'))
            title_label.pack(pady=(10, 10))
            
            # 添加工具描述
            desc_label = tk.Label(card_frame, 
                                text=tool['description'],
                                bg=tool['color'],
                                fg='white',
                                font=('Microsoft YaHei UI', 10),
                                wraplength=220)
            desc_label.pack(pady=2)
            
            # 添加操作按钮
            action_button = tk.Button(card_frame, 
                                    text="🚀 打开",
                                    command=tool['command'],
                                    bg='white',
                                    fg=tool['color'],
                                    font=('Microsoft YaHei UI', 9, 'bold'),
                                    relief='flat',
                                    padx=15,
                                    pady=3,
                                    cursor='hand2')
            action_button.pack(pady=15)
            
            # 添加悬停效果
            action_button.bind("<Enter>", lambda e, b=action_button: b.configure(bg=self.darken_color(b.cget('bg'))))
            action_button.bind("<Leave>", lambda e, b=action_button: b.configure(bg='white'))
        
        # 配置网格权重
        for i in range(2):
            tools_container.columnconfigure(i, weight=1)
        for i in range(2):
            tools_container.rowconfigure(i, weight=1)

    def open_custom_translation_tool(self):
        """打开自定义汉化工具"""
        if open_custom_translation_tool:
            try:
                open_custom_translation_tool(self)
                print("🔧 自定义汉化工具已打开")
            except Exception as e:
                print(f"打开自定义汉化工具失败: {e}")
                import tkinter.messagebox as messagebox
                messagebox.showerror("错误", f"打开自定义汉化工具失败: {str(e)}")
        else:
            print("自定义汉化工具未正确导入")
            import tkinter.messagebox as messagebox
            messagebox.showerror("错误", "自定义汉化工具未正确导入，请检查functions目录")
    
    def add_fade_animation(self, widget):
        """为控件添加淡入动画"""
        def fade_in(alpha=0):
            if alpha < 1:
                # 设置透明度（需要支持透明度的系统）
                try:
                    widget.configure(alpha=alpha)
                except:
                    pass
                self.root.after(10, lambda: fade_in(alpha + 0.05)) # type: ignore
        
        fade_in()

    def on_tab_changed(self, event):
        """标签页切换时的动画效果"""
        # play_sound("assets/voices/click.wav")
        
        # 获取当前选中的标签页
        current_tab = self.notebook.index(self.notebook.select())

        if current_tab == 3:
            # print("切换到插件&Mod管理页，正在刷新数据...")
            self.mod_addon_page.refresh_all_tabs()

    def load_background_images(self):
        """加载背景图片"""
        background_dir = "assets/images/background"
        if os.path.exists(background_dir):
            for file in os.listdir(background_dir):
                if file.lower().endswith(('.png', '.jpg', '.jpeg')):
                    # 处理文件名中的空格
                    file_path = os.path.join(background_dir, file)
                    self.background_images.append(file_path)
        
        if not self.background_images:
            print("未找到背景图片，将使用默认背景")
        else:
            print(f"找到 {len(self.background_images)} 张背景图片")
    
    def set_background_image(self):
        """设置背景图片 - 居中显示，并添加模糊效果"""
        if self.background_images:
            try:
                # 随机选择一张图片
                bg_path = random.choice(self.background_images)
                # print(f"加载背景图片: {bg_path}")
                
                # 打开图片
                image = Image.open(bg_path)
                
                # 获取窗口大小
                width = self.root.winfo_width() or 900
                height = self.root.winfo_height() or 700
                
                # 确保图片大小合理
                if width < 100: width = 900
                if height < 100: height = 700
                
                # 计算缩放比例，保持图片比例
                img_width, img_height = image.size
                width_ratio = width / img_width
                height_ratio = height / img_height
                scale_ratio = max(width_ratio, height_ratio)  # 确保图片覆盖整个窗口
                
                # 计算缩放后的尺寸
                new_width = int(img_width * scale_ratio)
                new_height = int(img_height * scale_ratio)
                
                # 缩放图片
                image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)
                
                # 应用高斯模糊效果（用户设置的模糊程度）
                gaussian_level: float = settings_manager.get_setting('bg_gaussian_blur') # type: ignore
                blurred_image = image.filter(ImageFilter.GaussianBlur(radius=gaussian_level))
                
                # ===== 1. 主背景：bg_canvas 显示模糊图片（无暗化） =====
                bg_image = ImageTk.PhotoImage(blurred_image)
                self.current_bg_image = bg_image
                
                # 清除Canvas上的旧图片
                self.bg_canvas.delete("all")
                
                # 计算居中位置
                x_position = (width - new_width) // 2
                y_position = (height - new_height) // 2
                
                # 在Canvas上居中显示模糊背景图片
                self.bg_canvas.create_image(x_position, y_position, 
                                          anchor=tk.NW, 
                                          image=bg_image,
                                          tags="background")
                
                # ===== 2. 内容区毛玻璃背景：裁剪背景 + 额外模糊 + 暗化（参考 loading_info.py） =====
                from PIL import ImageEnhance  # 确保导入
                
                # 内容区域位置（与 content_canvas 位置一致）
                content_left = (width - 700) // 2
                content_top = (height - 600) // 2
                
                # 将内容区域坐标映射到背景图片坐标
                crop_x = int(content_left - x_position)
                crop_y = int(content_top - y_position)
                crop_w = 700
                crop_h = 600
                
                # 确保裁剪区域在图片范围内
                crop_x = max(0, min(crop_x, new_width - 1))
                crop_y = max(0, min(crop_y, new_height - 1))
                crop_w = min(crop_w, new_width - crop_x)
                crop_h = min(crop_h, new_height - crop_y)
                
                if crop_w > 0 and crop_h > 0:
                    # 从模糊背景上裁剪内容区域
                    glass_region = blurred_image.crop((crop_x, crop_y, crop_x + crop_w, crop_y + crop_h))
                    
                    # 额外模糊：让内容区比背景更模糊，呈现毛玻璃质感
                    glass_region = glass_region.filter(ImageFilter.GaussianBlur(radius=10))
                    
                    # 降低亮度（参考 loading_info.py: ImageEnhance.Brightness(img).enhance(0.65)）
                    glass_region = ImageEnhance.Brightness(glass_region).enhance(0.55)

                    # 叠加暗色调蒙版（~#1e1e1e），与 container frame 的 bg_color(#181818) 视觉融合
                    dark_overlay = Image.new('RGB', glass_region.size, (30, 30, 30))
                    glass_region = Image.blend(glass_region, dark_overlay, 0.5)

                    # 转换并保存
                    glass_photo = ImageTk.PhotoImage(glass_region)
                    self.current_content_bg = glass_photo
                    
                    # 在 content_canvas 上显示毛玻璃背景（完全覆盖内容区域）
                    self.content_canvas.delete("all")
                    self.content_canvas.create_image(350, 300, image=glass_photo)
                    # 重新创建 notebook 嵌入窗口（确保在毛玻璃图片之上）
                    self.content_canvas.create_window(350, 300, window=self.notebook,
                                                      anchor=tk.CENTER, width=680, height=580)

                    # 更新所有标签页内部的毛玻璃背景（仅删除frost图片，保留create_text文字）
                    # 同时更新所有标签页内部的毛玻璃背景
                    if hasattr(self, 'tab_frost_canvases'):
                        for canvas in self.tab_frost_canvases:
                            canvas.delete("frost_bg")
                            canvas.create_image(350, 300, image=glass_photo, tags=("frost_bg",))
                            canvas.tag_lower("frost_bg")

                # 在Canvas上居中显示模糊背景图片
                self.bg_canvas.create_image(x_position, y_position, 
                                          anchor=tk.NW, 
                                          image=bg_image,
                                          tags="background")
                
            except Exception as e:
                print(f"加载背景图片失败: {e}")
                # 使用默认背景颜色
                self.bg_canvas.configure(bg=bg_color)
        else:
            # 使用默认背景颜色
            self.bg_canvas.configure(bg=bg_color)
    
    def start_background_rotation(self):
        """开始背景轮换"""
        # 延迟启动，确保窗口已显示
        self.root.after(100, self.rotate_background)
    
    def rotate_background(self):
        """轮换背景图片"""
        self.set_background_image()
        # 每30秒更换一次背景
        self.root.after(30000, self.rotate_background)

    def set_styles(self):
        """设置应用程序的样式"""
        style = ttk.Style()
        
        # 配置自定义主题
        style.theme_use('clam')
        
        # 配置 TNotebook 样式外描边为相似颜色
        style.configure('TNotebook', background=self.lighten_bg_color, borderwidth=0)
        style.configure('TNotebook.Tab', background=self.lighten_bg_color, foreground='#ecf0f1',borderwidth=0,
                       padding=[15, 5], font=('Microsoft YaHei UI', 10))
        style.map('TNotebook.Tab', background=[('selected', self.bg_color)])
        
        # 配置标签样式 - 使用白色文字，在模糊背景上更清晰
        style.configure("Title.TLabel",
                       background=self.bg_color,
                       foreground='white',
                       font=('Microsoft YaHei UI', 23, 'bold'))
        style.configure("Subtitle.TLabel",
                       background=self.bg_color,
                       foreground='white',
                       font=('Microsoft YaHei UI', 12))
        # 配置标签框架样式 - 使用浅色背景
        style.configure("Custom.TLabelframe",
                       background=self.lighten_bg_color,
                       foreground=self.darken_color(self.bg_color, 0.3),
                       bordercolor=self.lighten_color(self.lighten_bg_color, 40),
                       relief='raised',
                       borderwidth=1)
        style.configure("Custom.TLabelframe.Label",
                       background=self.lighten_bg_color,
                       foreground=self.lighten_color(self.lighten_bg_color, 40),
                       font=('微软雅黑', 11, 'bold'))
        
        # 字体配置
        self.title_font = font.Font(family='Microsoft YaHei UI', size=18, weight='bold')
        self.subtitle_font = font.Font(family='Microsoft YaHei UI', size=12)
        self.normal_font = font.Font(family='Microsoft YaHei UI', size=10)
    
    def init_home_page(self):
        """初始化主页内容"""
        from threading import Thread

        # 使用 ttk Label 作为标题（保持布局，深色背景融合毛玻璃）
        description = "欢迎使用 Faust Launcher - 您人生中绝无仅有的完美启动器！\n懒人化的一键操作，这就是浮士德大人的聪明才智口牙！"
        
        frost = self.tab_frost_canvases[0]
        frost.create_text(350, 50, text="✨ Faust Launcher ✨",
                          fill='white', font=('Microsoft YaHei UI', 25, 'bold'),
                          anchor=tk.CENTER, tags=("home_title",))
        frost.create_text(350, 110, text=description,
                          fill='white', font=('Microsoft YaHei UI', 13),
                          anchor=tk.CENTER, justify=tk.CENTER, width=600,
                          tags=("home_desc",))
        
        # 创建快速操作区域
        quick_actions_frame = ttk.LabelFrame(self.home_frame, text="  🚀 快速操作", style="Custom.TLabelframe")
        quick_actions_frame.pack(padx=30, pady=(160, 10))
        
        # 创建按钮容器 - 使用浅色背景
        button_container = tk.Frame(quick_actions_frame, bg=self.lighten_bg_color)
        button_container.pack(pady=15, padx=10)
        
        # 创建几个美化按钮 - 使用tkinter支持的十六进制颜色
        buttons_data = [
            {"text": "🚀 启动游戏", "command": lambda:Thread(target=download_and_launch, kwargs={"need_run_game": True, 'obj': self}).start(), "color": "#2980b9"},
            {"text": "🎯 汉化更新", "command": self.update_translation, "color": "#27ae60"},
            {"text": "📚 使用帮助", "command": self.show_help, "color": "#9b59b6"}
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
            # 添加悬停效果
            button.bind("<Enter>", lambda e, b=button: b.configure(bg=self.darken_color(b.cget('bg'))))
            button.bind("<Leave>", lambda e, b=button, c=btn_data["color"]: b.configure(bg=c))

        self.create_status_bar()
        
        # 创建迷你终端区域 - 替换原来的系统状态面板
        terminal_frame = ttk.LabelFrame(self.home_frame, text="  💻 迷你终端", style="Custom.TLabelframe")
        terminal_frame.pack(fill=tk.BOTH, expand=True, padx=30, pady=15)
        
        # 创建终端工具栏
        terminal_toolbar = tk.Frame(terminal_frame, bg=self.lighten_bg_color)
        terminal_toolbar.pack(fill=tk.X, padx=5, pady=5)
        
        # 添加终端控制按钮
        clear_button = tk.Button(terminal_toolbar, 
                               text="🗑️ 清空终端",
                               command=self.clear_terminal,
                               bg='#e74c3c',
                               fg='white',
                               font=('微软雅黑', 8, 'bold'),
                               relief='flat',
                               padx=8,
                               pady=3)
        clear_button.pack(side=tk.LEFT, padx=2)
        
        copy_button = tk.Button(terminal_toolbar,
                              text="📋  复制内容",
                              command=self.copy_terminal_content,
                              bg='#3498db',
                              fg='white',
                              font=('微软雅黑', 8, 'bold'),
                              relief='flat',
                              padx=8,
                              pady=3)
        copy_button.pack(side=tk.LEFT, padx=2)
        
        # 创建终端显示区域
        terminal_container = tk.Frame(terminal_frame, bg='#1e1e1e')
        terminal_container.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        # 创建滚动条
        scrollbar = ttk.Scrollbar(terminal_container)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # 创建终端文本组件
        self.terminal_text = tk.Text(terminal_container,
                                   bg="#1e1e1e",
                                   fg="#ffffff",
                                   font=('微软雅黑', 10),
                                   yscrollcommand=scrollbar.set,
                                   wrap=tk.WORD,
                                   relief='flat',
                                   borderwidth=0)
        self.terminal_text.pack(fill=tk.BOTH, expand=True)
        
        # 配置滚动条
        scrollbar.config(command=self.terminal_text.yview)
        
        # 设置文本组件为只读
        self.terminal_text.config(state=tk.DISABLED)

        # 配置终端文本标签颜色
        self.terminal_text.tag_config("info", foreground="#ffffff")
        self.terminal_text.tag_config("error", foreground="#ff6b6b")
        self.terminal_text.tag_config("success", foreground="#4bff4e")
        self.terminal_text.tag_config("warning", foreground="#f9ca24")
        self.terminal_text.tag_config("wait", foreground="#4ecbff")
        
        # 设置终端重定向
        self.setup_terminal_redirect()
        
        # 添加欢迎信息
        self.add_terminal_message("🚀 Faust Launcher 已启动")
        self.add_terminal_message("💻 终端重定向已启用")
        self.add_terminal_message("=" * 50)

    def create_status_bar(self):
        """创建底部状态栏"""
        status_frame = tk.Frame(self.home_frame, bg=self.lighten_bg_color, height=30)
        status_frame.pack(fill='x', side='bottom')
        status_frame.pack_propagate(False)
        
        # 状态信息
        status_label = tk.Label(status_frame,
                            text="🟢 就绪",
                            bg=self.lighten_bg_color,
                            fg='#bdc3c7',
                            font=('Microsoft YaHei UI', 9))
        status_label.pack(side='left', padx=10)
        
        # 版本信息
        version_label = tk.Label(status_frame,
                                text=f"版本 {VERSION_INFO}",
                                bg=self.lighten_bg_color, 
                                fg='#95a5a6',
                                font=('Microsoft YaHei UI', 9))
        version_label.pack(side='right', padx=10)
    
    def setup_terminal_redirect(self):
        """设置终端重定向"""
        # 启用文本组件编辑以添加内容
        self.terminal_text.config(state=tk.NORMAL)
        
        # 创建重定向器
        self.terminal_redirector = TerminalRedirector(self.terminal_text)
        self.terminal_redirector.start_redirect(debug)
        
        # 禁用文本组件编辑
        self.terminal_text.config(state=tk.DISABLED)
        
        print("终端重定向已启用")

    def add_terminal_message(self, message:str):
        """添加消息到终端"""
        self.terminal_text.config(state=tk.NORMAL)
        self.terminal_text.insert(tk.END, message + "\n")
        self.terminal_text.see(tk.END)
        self.terminal_text.config(state=tk.DISABLED)
        self.terminal_text.update_idletasks()
    
    def clear_terminal(self):
        """清空终端内容"""
        self.terminal_text.config(state=tk.NORMAL)
        self.terminal_text.delete(1.0, tk.END)
        self.terminal_text.config(state=tk.DISABLED)
        print("🗑️ 终端内容已清空")
    
    def copy_terminal_content(self):
        """复制终端内容到剪贴板"""
        try:
            content = self.terminal_text.get(1.0, tk.END)
            self.root.clipboard_clear()
            self.root.clipboard_append(content)
            print("📋 终端内容已复制到剪贴板")
        except Exception as e:
            print(f"复制失败: {e}")
    
    def init_features_page(self):
        """初始化功能页内容"""
        
        # 创建功能区域
        features_container = tk.Frame(self.features_frame, bg=self.bg_color)
        features_container.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)

        # 在 features_container 内部添加毛玻璃 Canvas（卡片间隙透出毛玻璃效果）
        features_frost = tk.Canvas(features_container, highlightthickness=0)
        features_frost.place(x=0, y=0, relwidth=1, relheight=1)
        features_frost.lower(1)
        self.tab_frost_canvases.append(features_frost)

        # 创建功能列表 - 使用tkinter支持的十六进制颜色
        
        # 创建功能列表 - 使用tkinter支持的十六进制颜色
        features = [
            {"name": "📁 游戏目录", "description": "边狱巴士的游戏目录。\n\n", "color": "#ff9c1b"},
            {"name": "🔄 零协会", "description": "一个伟大的社区。\n\n", "color": "#e74c3c"},
            {"name": "📒 气泡文本", "description": "气泡mod的汉化版本。\n提取码：fib6\n", "color": "#3498db"},
            {"name": "📝 维基", "description": "边狱巴士的灰机wiki。\n\n", "color": "#2ecc71"},
            {"name": "📖 N网", "description": "下载边狱巴士mod。\n\n", "color": "#9b59b6"},
            {"name": "📦 Github", "description": "查看本项目源码\n\n", "color": "#777777"}
        ]
        
        # 使用网格布局创建功能卡片
        for i, feature in enumerate(features):
            row = i // 3
            col = i % 3
            
            # 创建功能卡片 - 使用tkinter支持的十六进制颜色
            card_frame = tk.Frame(features_container, 
                                bg=feature['color'],
                                relief='raised',
                                borderwidth=1)
            card_frame.grid(row=row, column=col, padx=10, pady=10, sticky="nsew")
            card_frame.grid_propagate(False)
            card_frame.configure(width=200, height=120)
            
            # 添加功能标题
            title_label = tk.Label(card_frame, 
                                 text=feature['name'],
                                 bg=feature['color'],
                                 fg='white',
                                 font=('Microsoft YaHei UI', 12, 'bold'))
            title_label.pack(pady=(15, 5))
            
            # 添加功能描述
            desc_label = tk.Label(card_frame, 
                                text=feature['description'],
                                bg=feature['color'],
                                fg='white',
                                font=('Microsoft YaHei UI', 9),
                                wraplength=180)
            desc_label.pack(pady=5)
            
            # 添加操作按钮
            action_button = tk.Button(card_frame, 
                                    text="🚀 打开",
                                    command=lambda f=feature: self.open_feature(f),
                                    bg='white',
                                    fg=feature['color'],
                                    font=('Microsoft YaHei UI', 8, 'bold'),
                                    relief='flat',
                                    padx=10,
                                    pady=5,
                                    cursor='hand2')
            action_button.pack(pady=10)
        
        # 配置网格权重
        for i in range(3):
            features_container.columnconfigure(i, weight=1)
        for i in range(2):
            features_container.rowconfigure(i, weight=1)
            
    def init_about_page(self):
        """初始化关于页面内容"""
        frost = self.tab_frost_canvases[5]  # about_frame 的毛玻璃 Canvas
        
        # ========== 1. 标题（在毛玻璃上 = 透明背景） ==========
        frost.create_text(350, 40, text="ℹ️关于 Faust Launcher",
                          fill='white', font=('Microsoft YaHei UI', 23, 'bold'),
                          anchor=tk.CENTER, tags=("about_title",))
        
        # ========== 2. 版本徽标 ==========
        ver_badge = tk.Frame(frost, bg='#e74c3c')
        frost.create_window(350, 78, window=ver_badge, anchor=tk.CENTER,
                            tags=("content_win",))
        tk.Label(ver_badge, text=f"{VERSION_INFO}", bg='#e74c3c', fg='white',
                 font=('Microsoft YaHei UI', 9, 'bold'), padx=14, pady=1).pack()
        
        # ========== 3. 内容卡片 ==========
        card = tk.Frame(frost, bg='#1e1e1e', highlightbackground='#333333',
                        highlightthickness=1, highlightcolor='#333333')
        frost.create_window(340, 115, window=card, anchor=tk.N,
                            width=620, height=350, tags=("content_win",))
        
        # 标题栏
        tk.Label(card, text="📦 版本信息", bg='#1e1e1e', fg='#e74c3c',
                font=('Microsoft YaHei UI', 12, 'bold')).pack(anchor='w', padx=20, pady=(10, 5))
        
        tk.Label(card, text=f"  当前版本: {VERSION_INFO}", bg='#1e1e1e', fg='#cccccc',
                font=('Microsoft YaHei UI', 10)).pack(anchor='w', padx=20, pady=2)
        tk.Label(card, text="  开发者: FolkSkill", bg='#1e1e1e', fg='#cccccc',
                font=('Microsoft YaHei UI', 10)).pack(anchor='w', padx=20, pady=2)
        
        # 分隔线
        tk.Frame(card, bg='#333333', height=1).pack(fill=tk.X, padx=20, pady=10)
            
        # 介绍标题
        tk.Label(card, text="📖 应用介绍", bg='#1e1e1e', fg='#3498db',
                font=('Microsoft YaHei UI', 12, 'bold')).pack(anchor='w', padx=20, pady=(0, 5))
        
        # 带滚动条的文本区域
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
        
        # 配置文本标签
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
        
        # 插入内容
        desc_text.insert(tk.END, "一个专为懒人但丁设计的现代化启动器\n\n", "highlight")
        desc_text.insert(tk.END, "✨ 特色功能\n", "h2")
        desc_text.insert(tk.END, "  · 零协会汉化自动更新\n", "normal")
        desc_text.insert(tk.END, "  · 气泡mod自动更新下载\n", "normal")
        desc_text.insert(tk.END, "  · Mod 管理 & 一键载入\n", "normal")
        desc_text.insert(tk.END, "  · 无需多余配置，全部内置\n\n", "normal")
        desc_text.insert(tk.END, "🎯 我们的目标\n", "h3")
        desc_text.insert(tk.END, "让每一个但丁都解放自己的双手，专心坐牢。\n\n", "normal")
        desc_text.insert(tk.END, "© 2025 Faust Launcher. 版权所有。", "muted")
        desc_text.config(state=tk.DISABLED)  # 只读
        
        # ========== 4. 底部操作按钮（居中 + 悬停反馈） ==========
        btn_frame = tk.Frame(frost, bg=self.bg_color)
        frost.create_window(340, 480, window=btn_frame, anchor=tk.N,
                            width=350, height=45, tags=("content_win",))
        
        buttons_data = [
            ("🌐 bilibili", self.open_website, "#22c9e6", "#1a9bbf"),
            ("💌 意见反馈", self.send_feedback, "#9b59b6", "#7d3c98"),
            ("📦 开源地址", lambda: self.open_feature({"name": "📦 Github"}), "#777777", "#555555"),
            ("📄 检查更新", lambda: notify_new_version(
                current_version_name=VERSION_INFO, info='版本信息', root=self.root), "#2ecc71", "#27ae60"),
        ]
        
        for text, cmd, color, hover_color in buttons_data:
            btn = tk.Button(btn_frame, text=text, command=cmd,
                           bg=color, fg='white', bd=0, cursor='hand2',
                           font=('Microsoft YaHei UI', 9, 'bold'),
                           padx=3, pady=6)
            btn.pack(side=tk.LEFT, expand=True)
            
            # ── 悬停效果（参考 version_info.py: on_enter / on_leave） ──
            btn.bind("<Enter>", lambda e, b=btn, hc=hover_color: b.config(bg=hc))
            btn.bind("<Leave>", lambda e, b=btn, oc=color: b.config(bg=oc))

    def lighten_color(self, color, percent):
        """颜色变亮"""
        import colorsys
        # 将十六进制颜色转换为RGB
        rgb = tuple(int(color[i:i+2], 16) for i in (1, 3, 5))
        # 转换为HSL
        h, l, s = colorsys.rgb_to_hls(rgb[0]/255, rgb[1]/255, rgb[2]/255)
        # 增加亮度
        l = min(1.0, l + percent/100)
        # 转换回RGB
        r, g, b = colorsys.hls_to_rgb(h, l, s)
        # 返回十六进制
        return f"#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}"
    
    def darken_color(self, color, factor=0.8):
        """加深颜色"""
        if color.startswith('#'):
            r = int(color[1:3], 16)
            g = int(color[3:5], 16)
            b = int(color[5:7], 16)
            r = max(0, min(255, int(r * factor)))
            g = max(0, min(255, int(g * factor)))
            b = max(0, min(255, int(b * factor)))
            return f'#{r:02x}{g:02x}{b:02x}'
        return color
    
    def update_translation(self):
        """更新汉化"""
        from threading import Thread
        Thread(target=download_and_launch).start()

    def show_help(self):
        """显示帮助信息"""
        Popen(["notepad", "README.md"], shell=True)
    
    def open_feature(self, feature):
        """打开指定功能"""
        import webbrowser
        global settings_manager

        if feature['name'] == "📁 游戏目录":
            # 打开settings.json的指定游戏路径
            path = settings_manager.get_setting("game_path")
            if path and os.path.exists(path):
                os.startfile(path)
        elif feature['name'] == "🔄 零协会":
            # 打开零协会的官方网站
            webbrowser.open("https://zeroasso.top")
        elif feature['name'] == "📒 气泡文本":
            # 打开气泡文本的网盘
            webbrowser.open("https://wwyi.lanzoub.com/b014wpn02j")
        elif feature['name'] == "📝 维基":
            # 打开边狱巴士的官方wiki
            webbrowser.open("https://limbuscompany.huijiwiki.com/wiki/%E9%A6%96%E9%A1%B5")
        elif feature['name'] == "📖 N网":
            # 打开N网
            webbrowser.open("https://www.nexusmods.com/limbuscompany/mods")
        elif feature['name'] == "📦 Github":
            # 打开Github
            webbrowser.open("https://github.com/f0lkskill/FaustLauncher")
    
    def open_website(self):
        """打开作者网站"""
        import webbrowser
        webbrowser.open("https://space.bilibili.com/599331034")
    
    def send_feedback(self):
        """发送反馈"""
        import webbrowser
        webbrowser.open("https://space.bilibili.com/599331034")
    
    def open_mod_manager(self):
        """打开mod管理器"""
        try:
            # 导入mod管理器模块
            sys.path.append('functions')
            from functions.pages.extension.mod_manager import open_mod_manager
            open_mod_manager(self)
        except Exception as e:
            print(f"打开mod管理器失败: {e}")
            import tkinter.messagebox as messagebox
            messagebox.showerror("错误", f"打开mod管理器失败: {str(e)}")

    def check_settings(self):
        global settings_manager
        # version_info = settings_manager.get_setting("version_info")

        if not settings_manager.get_setting("game_path"):
            print("错误: 未配置游戏路径")
            # 请求用户选择游戏文件 LimbusCompany.exe
            from tkinter.filedialog import askopenfilename
            file_path = askopenfilename(title="选择边狱巴士主程序", filetypes=[("边狱巴士主程序", "LimbusCompany.exe")])
            if file_path:
                settings_manager.set_setting("game_path", file_path.replace('LimbusCompany.exe', ''))
                settings_manager.save_settings()
                self.settings_page.refresh_all_displays()
            else:
                print("错误: 未选择游戏文件")
                os._exit(-1)
                
        mems:dict = settings_manager.get_setting('mems') # type: ignore
        has_notify = mems.get('version_notify_flag') # type: ignore
        has_update, latest_info, name = check_version_update(self.root) # type: ignore
        if has_update:
            print(f"启动器的新版本已经发布: {name}")
        latest_info['version_name'] = name # type: ignore
        if not has_notify:
            notify_new_version(name, root = self.root, has_new_version = True, latest_info = latest_info, info = '发现新版本' if has_update else '已是最新版本')
            mems['version_notify_flag'] = True
            settings_manager.set_setting('mems', mems)

        # 检查是否有命令行参数
        if len(sys.argv) > 1 or not os.path.exists("lang/LLC_zh-CN"):
            # 有命令行参数，进入命令行模式
            Thread(target=download_and_launch).start()

        if not os.path.exists("assets/Font/Context/ChineseFont.ttf"):
            print("错误: 未找到字体文件 Font/Context/ChineseFont.ttf\n请尝试手动添加或者使用汉化更新修复")

        self.root.after(1000, self.start_background_rotation)
        
    def folder_link(self):
        # 先要求用户分别选择两个路径，然后根据其生成文件夹超链接指令，然后以管理员身份执行
        import tkinter.messagebox as messagebox
        from tkinter.filedialog import askdirectory
        
        try:
            # 第一步：选择源文件夹（要创建链接的文件夹）
            messagebox.showinfo("选择源文件夹", "请选择要创建链接的源文件夹")
            source_path = askdirectory(title="选择源文件夹")
            if not source_path:
                messagebox.showwarning("取消", "操作已取消")
                return
            
            # 第二步：选择目标文件夹（链接要放置的位置）
            messagebox.showinfo("选择目标位置", "请选择链接要放置的目标文件夹")
            target_path = askdirectory(title="选择目标文件夹")
            if not target_path:
                messagebox.showwarning("取消", "操作已取消")
                return
            
            # 获取目标文件夹的名称（从源路径中提取）
            source_name = os.path.basename(source_path)
            link_path = os.path.join(target_path, source_name)
            
            # 检查目标位置是否已存在同名文件夹
            if os.path.exists(link_path):
                response = messagebox.askyesno("确认覆盖", 
                    f"目标位置已存在同名文件夹 '{source_name}'，是否覆盖？")
                if not response:
                    messagebox.showinfo("取消", "操作已取消")
                    return
            
            # 第三步：生成mklink命令
            # 使用 /J 参数创建目录联接（类似于符号链接）
            mklink_command = f'mklink /J "{link_path}" "{source_path}"'
            
            # 第四步：以管理员身份执行命令
            # 创建批处理文件来执行命令
            batch_content = f'''@echo off
echo 正在创建文件夹链接...
{mklink_command}
if %errorlevel% equ 0 (
    echo 文件夹链接创建成功！
    echo 源文件夹: {source_path}
    echo 链接位置: {link_path}
    pause
) else (
    echo 创建文件夹链接失败，请检查权限或路径是否正确
)
'''
            
            # 保存批处理文件
            batch_file = "create_link.bat"
            with open(batch_file, 'w', encoding='gbk') as f:
                f.write(batch_content)
            
            Popen(f'powershell Start-Process "{batch_file}" -Verb runAs', shell=True)

        except Exception as e:
            messagebox.showerror("错误", f"创建文件夹链接时出错: {str(e)}")

from functions.base.game_launcher import safe_merge_dirs, GameLauncher

def download_and_launch(obj = None, need_run_game=False):
    """下载翻译资源，然后可选地启动游戏"""
    
    global downloading, root
    import threading
    from time import sleep

    if downloading:
        return
    downloading = True
    
    # 导入并执行各个功能模块
    try:

        # 检测 lang 下是否有 LLC_zh-CN 文件夹
        lang_path = 'lang/LLC_zh-CN'
        download_path = 'lang'
        print(f"[调试] 当前工作目录: {os.getcwd()}")
        print(f"[调试] lang_path 相对路径: {lang_path!r} -> 绝对路径: {os.path.abspath(lang_path)!r}")
        print(f"[调试] download_path 相对路径: {download_path!r} -> 绝对路径: {os.path.abspath(download_path)!r}")
        print(f"[调试] lang_path 存在: {os.path.exists(lang_path)}, 是目录: {os.path.isdir(lang_path)}, 是文件: {os.path.isfile(lang_path)}")
        src_full = os.path.join(download_path, 'LimbusCompany_Data', 'Lang', 'LLC_zh-CN')
        print(f"[调试] 下载源路径: {src_full!r} 存在: {os.path.exists(src_full)}")


        # 0. 下载翻译
        from functions.web_update.zeroasso_dow import main_gui as download_translation
        print("开始下载零协会汉化包...")
        sys.path.append('functions')
        gui = download_translation(root, download_path) # type: ignore
        dt = threading.Thread(target=gui.root.mainloop)

        while gui.is_downloading:
            sleep(1)
        
        del dt
        print("零协会汉化包下载完成")

        # 1. 检查必要的资源内容：
        from functions.web_update.zeroasso_dow import DownloadGUI, download_and_extract_gui
        from functions.web_update.update_resource import check_resource_update
        gui_res = DownloadGUI(root, 'resources/', False, download_func=download_and_extract_gui)
        dt = threading.Thread(target=check_resource_update, args=(gui_res,)).start()

        while gui_res.is_downloading:
            sleep(1)
            
        del dt
        gui_res.root.destroy()
        
        # 2. 下载气泡
        print("开始下载气泡...")
        from functions.fancy.bubble_transfer import main as download_bubble
        download_bubble(download_path) # type: ignore
        print("气泡下载完成")

        # 检查是否需要更新汉化
        from functions.web_update.zeroasso_dow import check_need_up_translate
        need_update = check_need_up_translate()

        # 把 'lang\LimbusCompany_Data\Lang\LLC_zh-CN' 复制到游戏目录下的 'lang' 文件夹 并删除 LimbusCompany_Data 文件夹
        import shutil

        if need_update:
            print("检测到新的汉化版本，准备更新汉化文件...")
            if os.path.exists(download_path + '/LimbusCompany_Data/Lang/LLC_zh-CN'):

                if os.path.isdir(lang_path):
                    try:
                        print(f"检测到目标目录 {lang_path}，准备删除...")
                        shutil.rmtree(lang_path, ignore_errors=True)
                    except Exception as e:
                        print(f"删除目录 {lang_path} 时出错: {e}")
                        traceback.print_exc()
                elif os.path.exists(lang_path):
                    print(f"[调试] lang_path 是文件而非目录，直接删除: {lang_path!r}")
                    os.remove(lang_path)
                try:
                    # 复制汉化文件
                    print(f"[调试] 开始 safe_merge_dirs: 源={os.path.join(download_path, 'LimbusCompany_Data', 'Lang', 'LLC_zh-CN')!r} -> 目标={lang_path!r}")
                    safe_merge_dirs(
                        os.path.join(download_path, 'LimbusCompany_Data', 'Lang', 'LLC_zh-CN'),
                        lang_path
                    )
                    print(f"[调试] safe_merge_dirs 完成")
                except Exception as e:
                    print(f"复制汉化文件时出错: {e}")
                    traceback.print_exc()
            else:
                print("错误: 未找到 lang 下的 LLC_zh-CN 文件夹")
        else:
            print("当前汉化已是最新版本，无需更新")

        # 复制字体文件
        if not os.path.exists('assets/Font/Context/ChineseFont.ttf'):
            shutil.copytree('lang/Font', 'assets/Font', dirs_exist_ok=True) # type: ignore
            shutil.rmtree('lang/Font', ignore_errors=True)

        # 删除 LimbusCompany_Data 文件夹
        if os.path.exists(os.path.join(download_path, 'LimbusCompany_Data')): # type: ignore
            shutil.rmtree(os.path.join(download_path, 'LimbusCompany_Data'), ignore_errors=True) # type: ignore

        print("汉化下载及处理全部完成！")

        if len(sys.argv) > 1 or need_run_game:
            # 关闭窗口
            # root.withdraw()
            pass
        else:
            downloading = False
            return
        
        # 有参数或需要运行游戏
        if obj is not None:
            launcher = GameLauncher(obj.addon_manager)
        else:
            launcher = GameLauncher()
        launcher.launch()
        
    except Exception as e:
        print(f"下载过程中出错: {e}")
        traceback.print_exception(*sys.exc_info())
        return
    
    finally:
        downloading = False

def main():
    """主函数"""
    global root

    # 检测是否已有实例在运行
    if check_single_instance():
        # 已有实例，退出当前进程
        os._exit(0)

    # 创建主窗口
    root = tk.Tk()
    root.withdraw()  # 先隐藏主窗口

    # 创建启动画面
    splash, splash_root = create_simple_splash(root)

    
    # 定义应用程序初始化完成回调
    def on_app_initialized():
        """应用程序初始化完成后的回调"""
        # 确保主窗口已经完全显示
        root.update_idletasks()
        root.update()
        
        # 等待一小段时间确保界面完全渲染
        root.after(4000, lambda: root.deiconify())

        ws_path = settings_manager.get_setting("welcome_sound")
        root.after(4000, lambda: play_sound(ws_path))
        app.terminal_redirector.enable_type = True

        # 检查设置
        root.after(4500, app.check_settings)

    # 创建应用程序实例，传入初始化完成回调
    app = FaustLauncherApp(root, on_initialized=on_app_initialized)
    
    # 启动主循环
    root.mainloop()

if __name__ == "__main__":
    main()