import tkinter as tk
from tkinter import ttk, font, messagebox
import os
import random
import sys
import json
from PIL import Image, ImageTk, ImageFilter
import pymysql
import threading
from subprocess import Popen
from functions.pages.settings_page import init_settings_page
from functions.base.settings_manager import get_settings_manager
from functions.pages.loading_info import create_simple_splash
from functions.base.window_ulits import center_window
from functions.dowloads.sql_manager import check_new_version, notify_new_version
from functions.base.sound_ulits import play_sound
from functions.addon.addon_ulit import AddonManager
import urllib3

# 禁用 urllib3 的警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 添加自定义汉化工具导入
try:
    sys.path.append('functions')
    from functions.pages.custom_translation import open_custom_translation_tool
except ImportError as e:
    print(f"导入自定义汉化工具失败: {e}")
    open_custom_translation_tool = None

dowloading = False
root: tk.Tk = None # type: ignore
debug = False
settings_manager = get_settings_manager()
bg_color:str = settings_manager.get_setting("bg_color") # type: ignore
VERSION_INFO:str = settings_manager.get_setting("version_info") # type: ignore

class TerminalRedirector:
    """重定向print输出到文本组件的类"""
    def __init__(self, text_widget):
        self.text_widget = text_widget
        self.original_stdout = sys.stdout
        self.original_stderr = sys.stderr
        self.buffer = ""  # 缓冲区用于处理部分消息
    
    def write(self, message):
        """重定向write方法"""
        if message:
            # 添加到缓冲区
            self.buffer += message
            
            # 如果缓冲区以换行符结尾，处理完整消息
            if self.buffer.endswith('\n'):
                # 移除结尾的换行符
                full_message = self.buffer.rstrip('\n')
                if full_message:  # 只处理非空消息
                    self._add_message_to_terminal(full_message)
                # 清空缓冲区
                self.buffer = ""
    
    def _add_message_to_terminal(self, message):
        """添加格式化消息到终端"""
        # if message[0] == '|':
        #     return
        # print('|'+message, file=self.original_stdout)
        message = self.process_message(message)

        try:
            if '\r' in message:
                return
            self.text_widget.config(state=tk.NORMAL)
            
            # 添加时间戳
            import datetime
            timestamp = datetime.datetime.now().strftime("%H:%M:%S")
            
            # 根据消息内容确定级别
            level = "info"
            if "❌" in message:
                level = "error"
            elif "✅" in message:
                level = "success"
            elif "⚠️" in message:
                level = "warning"
            elif ("🔄" in message) or ("📦" in message):
                level = "wait"
            
            # 插入带时间戳和颜色的消息
            timestamp_str = f'[{timestamp}]' if '[INFO]' not in message else ''
            self.text_widget.insert(tk.END, timestamp_str, "info")
            self.text_widget.insert(tk.END, message + "\n", level)
            
            # 自动滚动到底部
            self.text_widget.see(tk.END)
            
            # 禁用文本编辑
            self.text_widget.config(state=tk.DISABLED)
            
            # 立即更新显示
            self.text_widget.update_idletasks()
        
        except:
            pass

    @staticmethod
    def process_message(message:str) -> str: # type: ignore
        """根据消息内容添加表情符号"""
        emoji_dict = {
            "🚀": [
                "启动"
            ],
            "💡": [
                "提示",
                "提示信息",
            ],
            "⚠️": [
                "警告",
                "不存在",
                "warning",
            ],
            "❌": [
                "错误",
                "失败",
                "异常"
            ],
            "✅": [
                "成功",
                "完成",
                "已经"
            ],
            "🔄": [
                "正在",
                "加载中",
                "更新中"
            ],
            "📦": [
                "安装",
                "下载",
                "解压"
            ],
        }
        # 遍历字典，检查消息中是否包含关键字
        for emoji, keywords in emoji_dict.items():
            for keyword in keywords:
                if keyword in message:
                    return f"{emoji} {message}"
        return message
        
    def flush(self):
        """重定向flush方法"""
        # 处理缓冲区中剩余的消息
        if self.buffer:
            self._add_message_to_terminal(self.buffer)
            self.buffer = ""
    
    def start_redirect(self):
        """开始重定向"""
        if not debug:
            sys.stdout = self
            sys.stderr = self
    
    def stop_redirect(self):
        """停止重定向"""
        # 刷新缓冲区
        self.flush()
        sys.stdout = self.original_stdout
        sys.stderr = self.original_stderr

class FaustLauncherApp:
    def __init__(self, root: tk.Tk, on_initialized=None):
        global bg_color

        self.root = root
        self.root.title("Faust Launcher")
        self.root.geometry("800x700")
        self.root.resizable(False, False)

        self.addon_manager = None

        center_window(self.root, False)
        
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
        self.load_background_images()
        self.bg_color = bg_color
        self.lighten_bg_color = self.lighten_color(self.bg_color, 5)
        
        # 创建主容器框架
        self.container = tk.Frame(self.root, bg=self.darken_color(self.bg_color, 0.7))
        self.container.pack(fill=tk.BOTH, expand=True)
        
        # 创建背景 Canvas - 覆盖整个窗口
        self.bg_canvas = tk.Canvas(self.container, highlightthickness=0)
        self.bg_canvas.place(x=0, y=0, relwidth=1, relheight=1)
        
        # 创建内容容器
        self.content_frame = tk.Frame(self.container, bg=self.bg_color)
        self.content_frame.place(relx=0.5, rely=0.5, anchor=tk.CENTER, width=700, height=600)
        
        # 创建分页控件
        self.notebook = ttk.Notebook(self.content_frame)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # 创建页面 - 添加工具页、插件&mod管理页和下载中心
        self.home_frame = tk.Frame(self.notebook, bg=self.bg_color)
        self.features_frame = tk.Frame(self.notebook, bg=self.bg_color)
        self.tools_frame = tk.Frame(self.notebook, bg=self.bg_color)  # 工具页
        self.mod_addon_frame = tk.Frame(self.notebook, bg=self.bg_color)  # 插件&mod管理页
        self.download_center_frame = tk.Frame(self.notebook, bg=self.bg_color)  # 下载中心页面
        self.about_frame = tk.Frame(self.notebook, bg=self.bg_color)
        self.settings_frame = tk.Frame(self.notebook, bg=self.bg_color)
        
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

    def init_tray(self):
        """初始化托盘程序"""
        ico = Image.open("assets/images/icon/icon.ico")
        import pystray, threading

        menu_items = [
            pystray.MenuItem('显示窗口', self.root.deiconify, default=True),
            pystray.MenuItem('隐藏', self.root.withdraw),
        ]

        addon_items = []

        self.addon_manager = AddonManager(addon_items)
        self.addon_manager.run_all_addon()

        addon_menu = pystray.Menu(*addon_items)
        root_menu = pystray.MenuItem("插件", action=addon_menu)
        menu_items.append(root_menu)
        # menu_items.append(pystray.MenuItem('重载插件', self.addon_manager.run_all_addon))
        menu_items.append(pystray.MenuItem('退出', lambda:os._exit(0)))

        menu = pystray.Menu(*menu_items)
        self.tray = pystray.Icon(
            'FaustLauncher',
            ico,
            '浮士德启动器',
            menu
        )

        # 在单独线程中运行托盘图标
        threading.Thread(target=self.tray.run, daemon=True).start()

    def _notify_initialized(self):
        """通知应用程序初始化完成"""
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
            from functions.pages.mod_addon_info import init_mod_addon_manager
            self.mod_addon_page = init_mod_addon_manager(self.mod_addon_frame, self.bg_color, self.lighten_bg_color)
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
            from functions.pages.download_center import init_download_center
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
        from functions.pages.select_font import select_font_gui
        from functions.translate.auto_translate_gui import show_auto_translate_gui
        
        # 创建工具区域
        tools_container = tk.Frame(self.tools_frame, bg=self.bg_color)
        tools_container.pack(fill=tk.BOTH, expand=True, padx=80, pady=20)
        
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
            print("切换到插件&Mod管理页，正在刷新数据...")
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
                
                # 应用高斯模糊效果
                blurred_image = image.filter(ImageFilter.GaussianBlur(radius=5))
                
                # 转换为PhotoImage
                bg_image = ImageTk.PhotoImage(blurred_image)
                
                # 保存图片引用
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
        
        style.configure('TNotebook', background=bg_color)
        style.configure('TNotebook.Tab', background=bg_color, foreground='#ecf0f1',
                       padding=[15, 5], font=('Microsoft YaHei UI', 10))
        style.map('TNotebook.Tab', background=[('selected', self.lighten_bg_color)])
        
        # 配置标签样式 - 使用白色文字，在模糊背景上更清晰
        style.configure("Title.TLabel",
                       background=self.bg_color,
                       foreground='white',
                       font=('Microsoft YaHei UI', 18, 'bold'))
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
                       borderwidth=2)
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

        # 创建标题标签
        title_label = ttk.Label(self.home_frame, text="✨ Faust Launcher ✨", style="Title.TLabel")
        title_label.pack(pady=30)
        
        # 创建说明标签
        description = "欢迎使用 Faust Launcher - 您人生中绝无仅有的完美启动器！\n懒人化的一键操作，这就是浮士德大人的聪明才智口牙！"
        desc_label = ttk.Label(self.home_frame, text=description, style="Subtitle.TLabel", justify=tk.CENTER)
        desc_label.pack(pady=20)
        
        # 创建快速操作区域
        quick_actions_frame = ttk.LabelFrame(self.home_frame, text="  🚀 快速操作", style="Custom.TLabelframe")
        quick_actions_frame.pack(padx=30, pady=10)
        
        # 创建按钮容器 - 使用浅色背景
        button_container = tk.Frame(quick_actions_frame, bg=self.lighten_bg_color)
        button_container.pack(pady=15, padx=10)
        
        # 创建几个美化按钮 - 使用tkinter支持的十六进制颜色
        buttons_data = [
            {"text": "🚀 启动游戏", "command": lambda:Thread(target=handle_dowload, kwargs={"need_run_game": True, 'obj': self}).start(), "color": "#2980b9"},
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
        terminal_toolbar.pack(fill=tk.X, padx=10, pady=5)
        
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
        clear_button.pack(side=tk.LEFT, padx=5)
        
        copy_button = tk.Button(terminal_toolbar,
                              text="📋  复制内容",
                              command=self.copy_terminal_content,
                              bg='#3498db',
                              fg='white',
                              font=('微软雅黑', 8, 'bold'),
                              relief='flat',
                              padx=8,
                              pady=3)
        copy_button.pack(side=tk.LEFT, padx=5)
        
        # 创建终端显示区域
        terminal_container = tk.Frame(terminal_frame, bg='#1e1e1e')
        terminal_container.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
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
        self.terminal_redirector.start_redirect()
        
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
                                borderwidth=2)
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
        # 创建标题标签
        title_label = ttk.Label(self.about_frame, text="ℹ️ 关于 Faust Launcher", style="Title.TLabel")
        title_label.pack(pady=30)
        
        # 创建内容区域
        content_frame = tk.Frame(self.about_frame, bg=self.bg_color)
        content_frame.pack(fill=tk.BOTH, expand=True, padx=50, pady=20)
        
        # 添加应用程序信息
        about_info = [
            f"🌟 版本: {VERSION_INFO}",
            "👥 开发: FolkSkill"
            "",
            "Faust Launcher 是一个专为懒人但丁设计的现代化一键启动器。"
            "",
            "✨ 特色功能:",
            "零协会汉化自动更新，气泡mod自动更新下载，mod管理，载入，无需多余配置，全部内置"
            "",
            "🎯 我们的目标:",
            "让每一个但丁都解放自己的双手，专心坐牢。",
            "",
            "© 2025 Faust Launcher. 版权所有。"
        ]
        
        for info in about_info:
            color = 'white' if not info.startswith('✨') and not info.startswith('🎯') else '#e74c3c'
            weight = 'normal' if not info.startswith('✨') and not info.startswith('🎯') else 'bold'
            
            info_label = tk.Label(content_frame, 
                                text=info,
                                bg=self.bg_color,
                                fg=color,
                                font=('Microsoft YaHei UI', 10, weight),
                                justify=tk.LEFT if info.startswith('   •') else tk.CENTER)
            info_label.pack(anchor=tk.CENTER if not info.startswith('   •') else tk.W, pady=2)
        
        # 创建底部按钮区域 - 使用深蓝色背景
        buttons_frame = tk.Frame(self.about_frame, bg=self.bg_color)
        buttons_frame.pack(pady=30)
        
        # 添加按钮
        buttons_data = [
            {"text": "🌐 bilibili", "command": self.open_website, "color": "#22c9e6"},
            {"text": "💌 意见反馈", "command": self.send_feedback, "color": "#9b59b6"},
            {"text": "📦 开源地址", "command": lambda: self.open_feature({"name": "📦 Github"}), "color": "#777777"},
            {"text": "📄 检查更新", "command": lambda: notify_new_version(current_version_name=VERSION_INFO,info = '版本信息',root=self.root), "color": "#2ecc71"}
        ]
        
        for btn_data in buttons_data:
            button = tk.Button(buttons_frame,
                             text=btn_data["text"],
                             command=btn_data["command"],
                             bg=btn_data["color"],
                             fg='white',
                             font=('Microsoft YaHei UI', 10, 'bold'),
                             relief='flat',
                             padx=15,
                             pady=8,
                             cursor='hand2')
            button.pack(side=tk.LEFT, padx=10)
            # 添加悬停效果
            button.bind("<Enter>", lambda e, b=button: b.configure(bg=self.darken_color(b.cget('bg'))))
            button.bind("<Leave>", lambda e, b=button, c=btn_data["color"]: b.configure(bg=c))

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
        Thread(target=handle_dowload).start()
    
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
            from functions.pages.mod_manager import open_mod_manager
            open_mod_manager(self)
        except Exception as e:
            print(f"打开mod管理器失败: {e}")
            import tkinter.messagebox as messagebox
            messagebox.showerror("错误", f"打开mod管理器失败: {str(e)}")

    def check_settings(self):
        global settings_manager
        version_info = settings_manager.get_setting("version_info")

        if not settings_manager.get_setting("game_path"):
            print("错误: 未配置游戏路径")
            # 请求用户选择游戏文件 LimbusCompany.exe
            from tkinter.filedialog import askopenfilename
            file_path = askopenfilename(title="选择边狱巴士主程序", filetypes=[("边狱巴士主程序", "LimbusCompany.exe")])
            if file_path:
                settings_manager.set_setting("game_path", file_path.replace('LimbusCompany.exe', ''))
                settings_manager.save_settings()
                self.settings_page.refresh_all_displays()

                has_update, latest_info = check_new_version(version_info)
                notify_new_version(latest_info, '当前为最新版本', self.root)

                config_path = settings_manager.get_setting("game_path")

            else:
                print("错误: 未选择游戏文件")
                os._exit(-1)
        else:
            # 或者单独检测
            has_update, latest_info = check_new_version(version_info)
            if has_update:
                print(f"启动器的新版本已经发布: {latest_info['version_name']}") # type: ignore
                notify_new_version(latest_info, root = self.root)
            else:
                print("当前启动器已是最新版本")

        from threading import Thread

        # 检查是否有命令行参数
        if len(sys.argv) > 1 or not os.path.exists("lang/LLC_zh-CN"):
            # 有命令行参数，进入命令行模式
            Thread(target=handle_dowload).start()

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

def handle_dowload(obj = None, need_run_game=False):
    """命令行模式：执行下载翻译、下载气泡、载入mod并启动游戏"""
    
    global dowloading, root
    import threading
    from time import sleep

    if dowloading:
        return
    dowloading = True
    
    # 导入并执行各个功能模块
    try:
        # 检测 lang 下是否有 LLC_zh-CN 文件夹
        lang_path = 'lang/LLC_zh-CN'
        dowload_path = 'lang'

        from functions.dowloads.zeroasso_dow import main_gui as download_translation

        # 0. 检查必要的资源内容：
        from functions.dowloads.zeroasso_dow import DownloadGUI
        from functions.base.update_resource import check_resource_update
        gui_res = DownloadGUI(root, 'resources/', False)
        dt = threading.Thread(target=check_resource_update, args=(gui_res,)).start()

        while gui_res.is_downloading:
            sleep(1)
            
        del dt
        gui_res.root.destroy()

        # 1. 下载翻译
        print("开始下载零协会汉化包...")
        sys.path.append('functions')
        gui = download_translation(root, dowload_path) # type: ignore
        dt = threading.Thread(target=gui.root.mainloop)

        while gui.is_downloading:
            sleep(1)
        
        del dt
        print("零协会汉化包下载完成")
        
        # 2. 下载气泡
        print("开始下载气泡...")
        from functions.dowloads.bubble_dow import main as download_bubble
        download_bubble(dowload_path) # type: ignore
        print("气泡下载完成")

        # 检查是否需要更新汉化
        from functions.dowloads.dow_ulits import check_need_up_translate
        need_update = check_need_up_translate()

        # 把 'lang\LimbusCompany_Data\Lang\LLC_zh-CN' 复制到游戏目录下的 'lang' 文件夹 并删除 LimbusCompany_Data 文件夹
        import shutil

        if need_update:
            print("检测到新的汉化版本，准备更新汉化文件...")
            if os.path.exists(dowload_path + '/LimbusCompany_Data/Lang/LLC_zh-CN'): # type: ignore
                # 检查目标目录是否存在，如果存在就先删除
                if os.path.exists(lang_path):
                    shutil.rmtree(lang_path, ignore_errors=True)
                # 确保目标目录的父目录存在
                os.makedirs(os.path.dirname(lang_path), exist_ok=True)
                # 复制汉化文件
                shutil.copytree(dowload_path + '/LimbusCompany_Data/Lang/LLC_zh-CN', lang_path, dirs_exist_ok=True) # type: ignore
            else:
                print("错误: 未找到 lang 下的 LLC_zh-CN 文件夹")
        else:
            print("当前汉化已是最新版本，无需更新")

        if not os.path.exists('assets/Font/Context/ChineseFont.ttf'):
            shutil.copytree('lang/Font', 'assets/Font', dirs_exist_ok=True) # type: ignore
            shutil.rmtree('lang/Font', ignore_errors=True)

        # 删除 LimbusCompany_Data 文件夹
        if os.path.exists(os.path.join(dowload_path, 'LimbusCompany_Data')): # type: ignore
            shutil.rmtree(os.path.join(dowload_path, 'LimbusCompany_Data'), ignore_errors=True) # type: ignore

        print("汉化下载及处理全部完成！")

        if len(sys.argv) > 1 or need_run_game:
            # 关闭窗口
            # root.withdraw()
            pass
        else:
            dowloading = False
            return
        
        # 有参数,运行游戏
        run_game(obj)
        
    except Exception as e:
        print(f"下载过程中出错: {e}")
        return

    dowloading = False

def run_game(obj:None):
    global settings_manager
    # 复制 lang 下的 LLC_zh-CN 文件夹到游戏目录下的 LimbusCompany_Data/Lang 文件夹 下
    import shutil,json
    from functions.mod.mod_ulits import ModManager

    config_path = settings_manager.get_setting('game_path')

    # 尝试删除原有的 LimbusCompany_Data/Lang/LLC_zh-CN 文件夹
    if os.path.exists(os.path.join(config_path, 'LimbusCompany_Data/Lang/LLC_zh-CN')): # type: ignore
        print("删除原有的 LimbusCompany_Data/Lang/LLC_zh-CN 文件夹")
        shutil.rmtree(os.path.join(config_path, 'LimbusCompany_Data/Lang/LLC_zh-CN'), ignore_errors=True) # type: ignore

    print(f"开始复制 lang 下的 LLC_zh-CN 文件夹到游戏目录下的 {config_path}")
    try:
        shutil.copytree('lang/LLC_zh-CN', os.path.join(config_path, 'LimbusCompany_Data/Lang/LLC_zh-CN'), dirs_exist_ok=True) # type: ignore
        # print("汉化复制完成")
    except Exception as e:
        print(f"效用汉化复制文件夹时出错: {e}")
        return

    # 根据 lang/changes.json 更新 LimbusCompany_Data/Lang/LLC_zh-CN 里的数据
    print("开始应用自定义汉化修改...")

    dirs = []
    # 填充为mods文件夹下的所有子文件夹
    if settings_manager.get_setting('enable_mods'):
        for sub_dir in os.listdir('mods'):
            # 检测目录下 mod_info.json 里是否启用了这个mod
            mod_info_path = os.path.join('mods', sub_dir, 'mod_info.json')
            if not os.path.exists(mod_info_path):
                continue
            mod_info = json.load(open(mod_info_path, 'r', encoding='utf-8'))
            if not mod_info['settings']['enable']:
                continue
            dirs.append(os.path.join('mods', sub_dir))
    dirs.append('lang')
    ModManager.load_language('','lang/LLC_zh-CN')

    for dir in dirs:
        try:
            # 检查changes.json文件是否存在
            changes_file = os.path.join(dir, "changes.json")
            if os.path.exists(changes_file):
                # 加载changes.json
                with open(changes_file, 'r', encoding='utf-8') as f:
                    changes_data = json.load(f)
                
                if changes_data:
                    print(f"找到 {len(changes_data)} 个文件的修改记录")
                    
                    # 遍历changes.json中的每个文件修改记录
                    for relative_path, file_changes in changes_data.items():
                        # 构建完整的文件路径
                        lang_file_path = os.path.join("lang", relative_path)
                        game_file_path = os.path.join(config_path, "LimbusCompany_Data", "Lang", relative_path) # type: ignore
                        
                        # 检查游戏目录中的文件是否存在
                        if os.path.exists(game_file_path):
                            print(f"应用修改到: {relative_path}")
                            
                            # 读取游戏目录中的原始文件
                            with open(game_file_path, 'r', encoding='utf-8') as f:
                                original_data = json.load(f)
                            
                            # 应用修改
                            modified_data = apply_changes_to_data(original_data, file_changes)
                            
                            # 保存修改后的文件
                            with open(game_file_path, 'w', encoding='utf-8') as f:
                                json.dump(modified_data, f, ensure_ascii=False, indent=4)
                            
                            print(f"文件 {relative_path} 修改已应用")
                        else:
                            print(f"警告: 游戏目录中未找到文件 {relative_path}")
                else:
                    print("没有自定义汉化修改需要应用")
            else:
                print("没有找到changes.json文件，跳过自定义汉化修改")
        except Exception as e:
            print(f"应用自定义汉化修改时出错: {e}")
    
    # 气泡渐变色处理
    if settings_manager.get_setting('enable_text_gradient'):
        from functions.fancy.dialog_colorful import main as handle_colorful
        handle_colorful()
        print("气泡渐变色处理完成")

    # 复制字体文件夹到汉化目录下
    print("开始复制字体文件夹到汉化目录下...")
    try:
        if os.path.exists(config_path + 'LimbusCompany_Data/Lang/LLC_zh-CN/Font'): # type: ignore
            # 创建Font文件夹
            os.makedirs(config_path + 'LimbusCompany_Data/Lang/LLC_zh-CN/Font', exist_ok=True) # type: ignore

        shutil.copytree('assets/Font', config_path + 'LimbusCompany_Data/Lang/LLC_zh-CN/Font', dirs_exist_ok=True) # type: ignore
        print("字体文件夹复制完成")
    except Exception as e:
        print(f"复制字体文件夹时出错: {e}")
        return

    from functions.dowloads.zeroasso_dow import create_config_file
    create_config_file(settings_manager.get_setting('game_path'))

    try:
        # 是否设置用户名称
        if settings_manager.get_setting('enable_show_user_name'):
            print("设置用户名称中...")
            set_user_name()

        # 是否进行 EGO 样式美化
        if settings_manager.get_setting('enable_ego_style'):
            from functions.fancy.EGO_colorful import main as apply_ego_style
            print("处理EGO样式中...")
            apply_ego_style()

        # 技能描述美化
        if settings_manager.get_setting('enable_skill_style'):
            from functions.fancy.skill_info import handle_skill
            print("处理技能描述中...")
            handle_skill(config_path + 'LimbusCompany_Data/Lang/LLC_zh-CN/') # type: ignore

        if settings_manager.get_setting('enable_speical_tip'):
            from functions.fancy.hint_set import simple_replace
            simple_replace(config_path + 'LimbusCompany_Data/Lang/LLC_zh-CN/BattleHint.json') # type: ignore

        if settings_manager.get_setting('enable_skill_text_gradient'):
            from functions.fancy.skill_colorful import skill_color_process
            print("处理技能描述渐变色中...")
            skill_color_process(config_path + 'LimbusCompany_Data/Lang/') # type: ignore

    except Exception as e:
        print(f"应用美化功能时出错: {e}")
        from tkinter import messagebox
        messagebox.showerror("错误", f"应用美化功能时出错: {str(e)}\n可能是汉化包不完整导致的...\n请尝试使用汉化更新修复.")

    print("运行插件注册的启动事件...")
    threading.Thread(target=obj.addon_manager.run_game_start_event).start() # type: ignore

    # 载入mod并启动游戏
    from functions.base.load_mod import main as load_mod_and_launch
    load_mod_and_launch() # type: ignore

def set_user_name():
    """设置用户名称到 UserInfo_Friends.json 中"""
    global settings_manager
    user_name = settings_manager.get_setting('user_name')
    config_path = settings_manager.get_setting('game_path')
    from json import dump, load
    datalist = load(open(f'{config_path}LimbusCompany_Data/Lang/LLC_zh-CN/UserInfo_Friends.json','r',encoding='utf-8'))
    for data in datalist['dataList']:
        if data['id'] == 'Uid_Copy':
            data['content'] = f'{user_name}'
    dump(datalist, indent=4, fp=open(f'{config_path}LimbusCompany_Data/Lang/LLC_zh-CN/UserInfo_Friends.json','w',encoding='utf-8'))

def apply_changes_to_data(original_data, changes):
    """递归应用修改到数据 - 适配新的修改记录结构（包含id）"""

    print(f"应用用户自定义json修改: {type(original_data)}")

    # 处理包含dataList的修改记录结构
    if isinstance(changes, dict) and 'dataList' in changes:
        changes = changes['dataList']

    # 处理original_data是包含dataList键的字典，而changes是列表的情况
    if isinstance(original_data, dict) and 'dataList' in original_data and isinstance(changes, list):
        result = original_data.copy()
        result['dataList'] = apply_changes_to_data(original_data['dataList'], changes)
        return result

    if isinstance(original_data, dict) and isinstance(changes, dict):
        result = {}
        for key, value in original_data.items():
            if key in changes:
                # 如果changes中有对应的键，应用修改
                if isinstance(value, (dict, list)) and isinstance(changes[key], (dict, list)):
                    result[key] = apply_changes_to_data(value, changes[key])
                else:
                    result[key] = changes[key]
            else:
                result[key] = value
        return result
    
    elif isinstance(original_data, list) and isinstance(changes, list):
        result = []
        
        # 检查是否是包含id的字典列表的特殊修改记录
        if (len(original_data) > 0 and isinstance(original_data[0], dict) and 
            'id' in original_data[0] and len(changes) > 0 and 
            isinstance(changes[0], dict) and 'id' in changes[0]):
            
            # 对于包含id的字典列表，根据id进行匹配修改
            original_dict = {item['id']: item for item in original_data if 'id' in item}
            modified_ids = set()
            
            # 首先处理所有修改项
            for change_item in changes:
                if isinstance(change_item, dict) and 'id' in change_item:
                    change_id = change_item['id']
                    modified_ids.add(change_id)
                    
                    if change_id in original_dict:
                        # 找到对应的原始项
                        original_item = original_dict[change_id]
                        
                        # 普通修改，应用修改后添加
                        if 'changes' in change_item:
                            modified_item = apply_changes_to_data(original_item, change_item['changes'])
                            result.append(modified_item)
                        else:
                            # 如果没有changes字段，使用原始项
                            result.append(original_item)
                    else:
                        # 新增项（id不在原始数据中）
                        result.append(change_item.get('changes', change_item))
            
            # 处理未被修改的原始项
            for item in original_data:
                if isinstance(item, dict) and 'id' in item:
                    # 对于包含id的项，检查是否已被修改
                    if item['id'] not in modified_ids:
                        result.append(item)
                else:
                    # 对于不包含id的项，直接添加
                    result.append(item)
            
            return result
        else:
            # 对于普通的列表，使用原来的逻辑
            for i, item in enumerate(original_data):
                if i < len(changes):
                    if isinstance(item, (dict, list)) and isinstance(changes[i], (dict, list)):
                        result.append(apply_changes_to_data(item, changes[i]))
                    else:
                        result.append(changes[i])
                else:
                    result.append(item)
            return result
    else:
        return original_data

def main():
    """主函数"""
    global root

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
        root.after(3000, lambda: root.deiconify())

        ws_path = settings_manager.get_setting("welcome_sound")
        root.after(3000, lambda: play_sound(ws_path))

        # 检查设置
        root.after(3300, app.check_settings)

    # 创建应用程序实例，传入初始化完成回调
    app = FaustLauncherApp(root, on_initialized=on_app_initialized)
    
    # 启动主循环
    root.mainloop()

if __name__ == "__main__":
    main()