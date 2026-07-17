import tkinter as tk
from tkinter import ttk, font, messagebox
import os
import sys
import ctypes
from PIL import Image, ImageTk, ImageFilter
from threading import Thread
import pystray
import urllib3
from functions.base.window_ulits import center_window
from functions.pages.app.page_loader import PageLoader
from functions.extension.addon.addon_ulit import AddonManager
from functions.pages.app.app_core import FaustLauncherCore


urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class FaustLauncherUI:
    """应用程序UI类"""
    
    def __init__(self, root: tk.Tk, core: FaustLauncherCore, on_initialized=None):
        self.root = root
        self.core: FaustLauncherCore = core
        self.on_initialized = on_initialized
        
        self.lighten_bg_color = self.core.lighten_bg_color
        self.bg_color = self.core.bg_color
        
        self.tab_frost_canvases = []
        
        self.notebook: tk.Notebook = None # type: ignore
        self.container: tk.Frame = None # type: ignore
        self.bg_canvas:tk.Canvas = None # type: ignore
        self.content_canvas:tk.Canvas = None # type: ignore
        
        self._setup_window()
        self._setup_styles()
        self._create_ui_structure()
        self._setup_event_bindings()
        
        self.core.root = root
        self.core.page_loader = PageLoader(self)
        
    def _setup_window(self):
        """设置主窗口基础配置"""
        self.root.title("Faust Launcher")
        self.root.geometry("800x700")
        self.root.resizable(False, False)
        
        center_window(self.root, False)
        self.root.attributes('-topmost', True)
        
        try:
            if os.path.exists("assets/images/icon/icon.ico"):
                self.root.iconbitmap("assets/images/icon/icon.ico")
        except Exception:
            pass
        
    def _setup_styles(self):
        """设置应用程序样式"""
        style = ttk.Style()
        style.theme_use('clam')
        
        style.configure('TNotebook', background=self.core.lighten_bg_color, borderwidth=0)
        style.configure('TNotebook.Tab', background=self.core.lighten_bg_color, 
                        foreground='#ecf0f1', borderwidth=0,
                        padding=[15, 5], font=('Microsoft YaHei UI', 10))
        style.map('TNotebook.Tab', background=[('selected', self.core.bg_color)])
        
        style.configure("Title.TLabel",
                    background=self.core.bg_color,
                    foreground='white',
                    font=('Microsoft YaHei UI', 23, 'bold'))
        style.configure("Subtitle.TLabel",
                    background=self.core.bg_color,
                    foreground='white',
                    font=('Microsoft YaHei UI', 12))
        style.configure("Custom.TLabelframe",
                    background=self.core.lighten_bg_color,
                    foreground=self.core.darken_color(self.core.bg_color, 0.3),
                    bordercolor=self.core.lighten_color(self.core.lighten_bg_color, 40),
                    relief='raised',
                    borderwidth=1)
        style.configure("Custom.TLabelframe.Label",
                    background=self.core.lighten_bg_color,
                    foreground=self.core.lighten_color(self.core.lighten_bg_color, 40),
                    font=('微软雅黑', 11, 'bold'))
        
        self.title_font = font.Font(family='Microsoft YaHei UI', size=18, weight='bold')
        self.subtitle_font = font.Font(family='Microsoft YaHei UI', size=12)
        self.normal_font = font.Font(family='Microsoft YaHei UI', size=10)
        
    def _create_ui_structure(self):
        """创建UI结构框架"""
        self.container = tk.Frame(self.root, bg=self.core.darken_color(self.core.bg_color, 0.7))
        self.container.pack(fill=tk.BOTH, expand=True)
        
        self.bg_canvas = tk.Canvas(self.container, highlightthickness=0)
        self.bg_canvas.place(x=0, y=0, relwidth=1, relheight=1)
        
        self.content_canvas = tk.Canvas(self.container, highlightthickness=0, bg=self.core.bg_color)
        self.content_canvas.place(relx=0.5, rely=0.5, anchor=tk.CENTER, width=700, height=600)
        
        self.notebook = ttk.Notebook(self.content_canvas)
        self.content_canvas.create_window(350, 300, window=self.notebook,
                                        anchor=tk.CENTER, width=680, height=580)
        
        self.page_frames = {
            'home': tk.Frame(self.notebook, bg=self.core.bg_color),
            'features': tk.Frame(self.notebook, bg=self.core.bg_color),
            'tools': tk.Frame(self.notebook, bg=self.core.bg_color),
            'mod_addon': tk.Frame(self.notebook, bg=self.core.bg_color),
            'download_center': tk.Frame(self.notebook, bg=self.core.bg_color),
            'about': tk.Frame(self.notebook, bg=self.core.bg_color),
            'settings': tk.Frame(self.notebook, bg=self.core.bg_color),
        }
        
        for frame in self.page_frames.values():
            canvas = tk.Canvas(frame, highlightthickness=0)
            canvas.place(x=0, y=0, relwidth=1, relheight=1)
            canvas.lower(1)
            self.tab_frost_canvases.append(canvas)
        
        self.notebook.add(self.page_frames['home'], text="🏘 主页")
        self.notebook.add(self.page_frames['features'], text="✈ 快捷方式")
        self.notebook.add(self.page_frames['tools'], text="🔨 工具页")
        self.notebook.add(self.page_frames['mod_addon'], text="🧩 插件&Mod")
        self.notebook.add(self.page_frames['download_center'], text="📦 下载中心")
        self.notebook.add(self.page_frames['settings'], text="⚙️ 设置")
        self.notebook.add(self.page_frames['about'], text="💻 关于")
        
    def _setup_event_bindings(self):
        """设置事件绑定"""
        self.notebook.bind("<<NotebookTabChanged>>", self.on_tab_changed) # type: ignore
        self.root.bind_all("<ButtonPress-1>", self.core._on_global_click)
        
        def check_close():
            if self.core.settings_manager.get_setting("after_gui_exit") == 0:
                self.root.withdraw()
            else:
                self.root.destroy()
                os._exit(0)
            
            if not self.core.settings_manager.get_setting("mems")["tray_hint"]: # type: ignore
                self.core.settings_manager.set_setting("mems", {"tray_hint": True})
                messagebox.showinfo("提示", "程序将继续在托盘后台继续运行，右键托盘图标可退出程序\n您可以在设置中修改退出后操作")
        
        self.root.protocol("WM_DELETE_WINDOW", check_close)
        
    def initialize_pages(self):
        """初始化所有页面（异步方式）"""
        # 先创建 AddonManager，确保页面加载时可用
        self.addon_menu_items = []
        self.core.addon_manager = AddonManager([], app=self)
        self.core.addon_manager.run_all_addon()
        
        self.core.page_loader.load_all_pages()
        self.init_tray()
        self.start_background_rotation()
        self._notify_initialized()
        
    def _notify_initialized(self):
        """通知应用程序初始化完成"""
        self.root.attributes('-topmost', False)
        self.root.update_idletasks()
        self.root.update()
        
        if self.on_initialized:
            self.on_initialized()
        
    def on_tab_changed(self, event):
        """标签页切换时的处理"""
        current_tab = self.notebook.index(self.notebook.select()) # type: ignore
        
        if current_tab == 3:
            mod_addon_page = self.core.page_loader.get_page('mod_addon')
            if mod_addon_page:
                mod_addon_page.refresh_all_tabs()
    
    def init_tray(self):
        """初始化托盘程序"""
        ico = Image.open("assets/images/icon/icon.ico")
        
        menu_items = [
            pystray.MenuItem('显示窗口', self.root.deiconify, default=True),
            pystray.MenuItem('隐藏', self.root.withdraw),
        ]
        
        def build_addon_menu() -> pystray.Menu:
            self.addon_menu_items.clear()
            
            auto_items = []
            for addon in self.core.addon_manager.get_all_addons():
                name = addon['name']
                try:
                    enabled = bool(addon.get('info', {}).get('settings', {}).get('enable', True))
                except Exception:
                    enabled = True
                
                def _make_runner(n: str):
                    def _run(icon=None, item=None):
                        try:
                            self.core.addon_manager.run_addon(n)
                        except Exception as e:
                            from rich import print
                            print(f"手动运行插件 {n} 失败: {e}")
                    return _run
                
                label = f"🔧 {name}" if enabled else f"⚙️ {name} (已禁用)"
                auto_items.append(pystray.MenuItem(label, _make_runner(name)))
            
            custom_items = self.core.addon_manager.get_custom_tray_items()
            
            self.addon_menu_items.extend(auto_items)
            if custom_items:
                if auto_items:
                    self.addon_menu_items.append(pystray.MenuItem(
                        '─── 自定义项 ───', None, enabled=False))
                self.addon_menu_items.extend(custom_items)
            
            if not self.addon_menu_items:
                self.addon_menu_items.append(pystray.MenuItem('（暂无可用插件）', None, enabled=False))
            
            return pystray.Menu(*self.addon_menu_items)
        
        def addon_menu_lambda(icon=None, item=None):
            return build_addon_menu()
        
        root_menu = pystray.MenuItem('插件', lambda icon, item: build_addon_menu())
        menu_items.append(root_menu)
        menu_items.append(pystray.MenuItem('重载插件', lambda icon=None, item=None: self.core._on_reload_addons()))
        menu_items.append(pystray.MenuItem('退出', lambda: os._exit(0)))
        
        menu = pystray.Menu(*menu_items)
        self.tray = pystray.Icon(
            'FaustLauncher',
            ico,
            '浮士德启动器',
            menu
        )
        
        Thread(target=self.tray.run, daemon=True).start()
        
    def set_background_image(self):
        """设置背景图片"""
        if self.core.background_images:
            try:
                bg_path = random.choice(self.core.background_images)
                image = Image.open(bg_path)
                
                width = self.root.winfo_width() or 900
                height = self.root.winfo_height() or 700
                
                if width < 100:
                    width = 900
                if height < 100:
                    height = 700
                
                img_width, img_height = image.size
                width_ratio = width / img_width
                height_ratio = height / img_height
                scale_ratio = max(width_ratio, height_ratio)
                
                new_width = int(img_width * scale_ratio)
                new_height = int(img_height * scale_ratio)
                
                image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)
                
                gaussian_level: int = self.core.settings_manager.get_setting('bg_gaussian_blur') # type: ignore
                blurred_image = image.filter(ImageFilter.GaussianBlur(radius=gaussian_level))
                
                bg_image = ImageTk.PhotoImage(blurred_image)
                self.core.current_bg_image = bg_image # type: ignore
                
                self.bg_canvas.delete("all")
                
                x_position = (width - new_width) // 2
                y_position = (height - new_height) // 2
                
                self.bg_canvas.create_image(x_position, y_position,
                                        anchor=tk.NW,
                                        image=bg_image,
                                        tags="background")
                
                from PIL import ImageEnhance
                
                content_left = (width - 700) // 2
                content_top = (height - 600) // 2
                
                crop_x = int(content_left - x_position)
                crop_y = int(content_top - y_position)
                crop_w = 700
                crop_h = 600
                
                crop_x = max(0, min(crop_x, new_width - 1))
                crop_y = max(0, min(crop_y, new_height - 1))
                crop_w = min(crop_w, new_width - crop_x)
                crop_h = min(crop_h, new_height - crop_y)
                
                if crop_w > 0 and crop_h > 0:
                    glass_region = blurred_image.crop((crop_x, crop_y, crop_x + crop_w, crop_y + crop_h))
                    glass_region = glass_region.filter(ImageFilter.GaussianBlur(radius=10))
                    glass_region = ImageEnhance.Brightness(glass_region).enhance(0.55)
                    
                    dark_overlay = Image.new('RGB', glass_region.size, (30, 30, 30))
                    glass_region = Image.blend(glass_region, dark_overlay, 0.5)
                    
                    glass_photo = ImageTk.PhotoImage(glass_region)
                    self.core.current_content_bg = glass_photo # type: ignore
                    
                    self.content_canvas.delete("all")
                    self.content_canvas.create_image(350, 300, image=glass_photo)
                    self.content_canvas.create_window(350, 300, window=self.notebook,
                                                    anchor=tk.CENTER, width=680, height=580)
                    
                    for canvas in self.tab_frost_canvases:
                        canvas.delete("frost_bg")
                        canvas.create_image(350, 300, image=glass_photo, tags=("frost_bg",))
                        canvas.tag_lower("frost_bg")
                
                self.bg_canvas.create_image(x_position, y_position,
                                        anchor=tk.NW,
                                        image=bg_image,
                                        tags="background")
                
            except Exception as e:
                from rich import print
                print(f"加载背景图片失败: {e}")
                self.bg_canvas.configure(bg=self.core.bg_color)
        else:
            self.bg_canvas.configure(bg=self.core.bg_color)
        
    def start_background_rotation(self):
        """开始背景轮换"""
        self.root.after(100, self.rotate_background)
        
    def rotate_background(self):
        """轮换背景图片"""
        self.set_background_image()
        self.root.after(30000, self.rotate_background)
        
    def create_status_bar(self):
        """创建底部状态栏"""
        status_frame = tk.Frame(self.page_frames['home'], bg=self.core.lighten_bg_color, height=30)
        status_frame.pack(fill='x', side='bottom')
        status_frame.pack_propagate(False)
        
        status_label = tk.Label(status_frame,
                            text="🟢 就绪",
                            bg=self.core.lighten_bg_color,
                            fg='#bdc3c7',
                            font=('Microsoft YaHei UI', 9))
        status_label.pack(side='left', padx=10)
        
        version_label = tk.Label(status_frame,
                                text=f"版本 {self.core.version_info}",
                                bg=self.core.lighten_bg_color,
                                fg='#95a5a6',
                                font=('Microsoft YaHei UI', 9))
        version_label.pack(side='right', padx=10)


def check_single_instance():
    """检测是否已有实例在运行"""
    user32 = ctypes.windll.user32
    hwnd = user32.FindWindowA(None, "Faust Launcher".encode('utf-8'))
    
    if hwnd:
        from rich import print
        print(f"找到已运行的窗口，句柄: {hwnd}，准备恢复窗口")
        
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, 9)
        elif not user32.IsWindowVisible(hwnd):
            user32.ShowWindow(hwnd, 5)
        
        user32.SetForegroundWindow(hwnd)
        return True
    
    return False

import random