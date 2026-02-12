import tkinter as tk
import time
import threading
from functions.base.window_ulits import center_window
from functions.base.settings_manager import get_settings_manager

VERSION_INFO = get_settings_manager().get_setting("version_info")  # type: ignore

class ModernSplashScreen:
    def __init__(self, root):
        self.root = root
        self.splash = tk.Toplevel(root)
        self.splash.title("Faust Launcher")
        self.splash.geometry("500x350")
        self.splash.overrideredirect(True)  # 移除窗口边框
        
        # 设置窗口透明度和圆角效果
        self.splash.attributes('-alpha', 0.0)  # 初始完全透明
        self.splash.attributes('-topmost', True)  # 置顶显示
        
        # 创建圆角背景（使用Canvas实现）
        self.canvas = tk.Canvas(self.splash, 
                               bg='#1a1a1a', 
                               highlightthickness=0,
                               width=500, 
                               height=350)
        self.canvas.pack(fill='both', expand=True)
        
        # 绘制圆角矩形背景（深色半透明）
        self.bg_rect = self.canvas.create_rectangle(10, 10, 490, 340,
                                                   fill='#1a1a1a',
                                                   outline="#2f2f2f",
                                                   width=2,
                                                   stipple='gray50')
        
        # 添加发光效果边框
        self.glow_rect = self.canvas.create_rectangle(8, 8, 492, 342,
                                                     outline='#2f2f2f',
                                                     width=1,
                                                     stipple='gray25')
        
        # 居中显示
        center_window(self.splash)
        
        # 加载图标和创建UI元素
        self.create_ui_elements()
        
        # 动画参数
        self.animation_running = True
        self.fade_in_complete = False

    def center_window(self):
        """居中显示窗口"""
        self.splash.update_idletasks()
        screen_width = self.splash.winfo_screenwidth()
        screen_height = self.splash.winfo_screenheight()
        x = (screen_width - 500) // 2
        y = (screen_height - 350) // 2
        self.splash.geometry(f"+{x}+{y}")

    def create_ui_elements(self):
        """创建UI元素"""
        # 添加图标
        try:
            from PIL import Image, ImageTk
            img = Image.open("assets/images/icon/icon.png")
            img = img.resize((100, 100), Image.Resampling.LANCZOS)
            self.icon_img = img
            self.icon_photo = ImageTk.PhotoImage(img)
            
            # 在Canvas上创建图标
            self.icon_item = self.canvas.create_image(250, 100, 
                                                     image=self.icon_photo)

        except Exception as e:
            print(f"加载图标失败: {e}")
            # 创建备用图标
            self.icon_item = self.canvas.create_text(250, 100,
                                                    text="🎭",
                                                    font=('Microsoft YaHei UI', 48),
                                                    fill='#3498db')

        # 添加标题（带渐入效果）
        self.title_item = self.canvas.create_text(250, 170,
                                                 text="Faust Launcher",
                                                 font=('Microsoft YaHei UI', 24, 'bold'),
                                                 fill='#ffffff',
                                                 state='hidden')

        # 添加副标题
        self.subtitle_item = self.canvas.create_text(250, 200,
                                                    text="正在启动...",
                                                    font=('Microsoft YaHei UI', 12),
                                                    fill='#bdc3c7',
                                                    state='hidden')

        # 创建现代化进度条（Canvas实现）
        self.progress_bg = self.canvas.create_rectangle(100, 240, 400, 250,
                                                       fill='#2c3e50',
                                                       outline='')
        
        self.progress_fg = self.canvas.create_rectangle(100, 240, 100, 250,
                                                       fill="#decf00",
                                                       outline='')
        
        # 添加进度文本
        self.progress_text = self.canvas.create_text(250, 265,
                                                    text="0%",
                                                    font=('Microsoft YaHei UI', 10),
                                                    fill='#95a5a6',
                                                    state='hidden')

        # 添加版本信息
        self.version_item = self.canvas.create_text(250, 320,
                                                   text=f"版本 {VERSION_INFO}",
                                                   font=('Microsoft YaHei UI', 9),
                                                   fill='#7f8c8d',
                                                   state='hidden')

    def fade_in(self):
        """渐入动画"""
        def animate_fade_in(alpha=0.0):
            if alpha < 1.0 and self.animation_running:
                self.splash.attributes('-alpha', alpha)
                self.splash.after(30, lambda: animate_fade_in(alpha + 0.05))
            else:
                self.splash.attributes('-alpha', 1.0)
                self.fade_in_complete = True

        self.show_content_animation()
        
        animate_fade_in()

    def show_content_animation(self):
        """显示内容动画"""
        # 显示标题
        self.canvas.itemconfig(self.title_item, state='normal')
        
        # 显示副标题（延迟显示）
        self.splash.after(0, lambda: self.canvas.itemconfig(self.subtitle_item, state='normal'))
        
        # 显示进度文本
        self.splash.after(0, lambda: self.canvas.itemconfig(self.progress_text, state='normal'))
        
        # 显示版本信息
        self.splash.after(0, lambda: self.canvas.itemconfig(self.version_item, state='normal'))
        
        # 开始进度条动画
        self.splash.after(500, self.start_progress_animation)

    def start_progress_animation(self):
        """开始进度条动画"""
        def animate_progress(progress=0):
            if progress <= 100 and self.animation_running:
                # 更新进度条宽度
                progress_width = 100 + (progress / 100) * 300
                self.canvas.coords(self.progress_fg, 100, 240, progress_width, 250)
                
                # 更新进度文本
                self.canvas.itemconfig(self.progress_text, text=f"{progress}%")
                
                # 更新副标题文本
                status_texts = [
                    "浮士德正在检查梅菲斯特的动向...",
                    "加载巴士系统的配置文件...", 
                    "准备经理面板界面组件...",
                    "即将完成...",
                    "欢迎您, 但丁。"
                ]
                status_index = min(len(status_texts) - 1, progress // 25)
                self.canvas.itemconfig(self.subtitle_item, text=status_texts[status_index])
                
                # 继续动画
                delay = 10 if progress < 80 else 30  # 最后阶段慢一点
                self.splash.after(delay, lambda: animate_progress(progress + 1))
            elif progress > 100:
                # 进度完成，准备淡出
                self.splash.after(500, self.fade_out)
        
        animate_progress()

    def fade_out(self):
        """淡出动画"""
        def animate_fade_out(alpha=1.0):
            if alpha > 0.0 and self.animation_running:
                self.splash.attributes('-alpha', alpha)
                self.splash.after(20, lambda: animate_fade_out(alpha - 0.05))
            else:
                self.splash.attributes('-alpha', 0.0)
                self.close()
        
        animate_fade_out()

    def show(self):
        """显示启动画面"""
        self.splash.update()
        # 开始渐入动画
        self.splash.after(0, self.fade_in)
        # 开始图标旋转（可选）
        # self.splash.after(200, self.rotate_icon)
        return self.splash

    def close(self):
        """关闭启动画面"""
        self.animation_running = False
        self.splash.destroy()

    def update_status(self, text, progress=None):
        """更新状态文本和进度"""
        if hasattr(self, 'subtitle_item'):
            self.canvas.itemconfig(self.subtitle_item, text=text)
        
        if progress is not None and hasattr(self, 'progress_fg'):
            progress_width = 100 + (progress / 100) * 300
            self.canvas.coords(self.progress_fg, 100, 240, progress_width, 250)
            self.canvas.itemconfig(self.progress_text, text=f"{progress}%")
        
        self.splash.update()

# 使用方式示例
def show_loading_page(root):
    # 显示启动画面
    splash = ModernSplashScreen(root)
    splash_root = splash.show()
    
    # 模拟初始化过程（在实际使用中替换为真实初始化）
    def init_app():
        # 模拟不同的初始化阶段
        stages = [
            ("正在检查系统环境...", 10),
            ("加载用户配置...", 25),
            ("初始化界面组件...", 45),
            ("准备游戏资源...", 65),
            ("完成启动准备...", 85),
            ("启动完成!", 100)
        ]
        
        for text, progress in stages:
            time.sleep(0.8)  # 模拟每个阶段耗时
            splash_root.after(0, lambda t=text, p=progress: splash.update_status(t, p))
        
        # 所有阶段完成后淡出
        time.sleep(0.5)
        splash_root.after(0, splash.fade_out)
    
    # 在新线程中初始化
    init_thread = threading.Thread(target=init_app)
    init_thread.daemon = True
    init_thread.start()
    
    splash_root.mainloop()

# 简化版本，适合集成到主程序
def create_simple_splash(root):
    """创建简化的启动画面（适合集成到主程序）"""
    splash = ModernSplashScreen(root)
    splash_root = splash.show()
    return splash, splash_root