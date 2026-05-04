import tkinter as tk
from functions.base.window_ulits import center_window
from tkinter import ttk
import threading
import os,time

class DownloadGUI:
    """简化版下载GUI界面"""
    
    def __init__(self, parent, config_path: str = "", auto_start: bool = True, dowload_func=None):
        self.root = tk.Toplevel(parent)
        self.root.withdraw()  # 先隐藏，防止闪烁
        # 居中显示窗口
        self.root.title("下载中...")
        self.root.geometry("500x160")
        self.root.resizable(False, False)
        self.root.attributes("-topmost", True)
        center_window(self.root)
        # self.root.attributes("-transparentcolor","#ffffff")

        # 设置应用程序图标
        try:
            if os.path.exists("assets/images/icon/icon.ico"):
                self.root.iconbitmap("assets/images/icon/icon.ico")
        except:
            pass

        self.config_path = config_path
        self.is_dowloading = True
        
        # 创建界面
        self.create_widgets()

        # threading.Thread(target=self.cycle_animation).start()
        
        # 初始化后立即开始下载
        if auto_start:
            self.start_download(dowload_func)

    def cycle_animation(self):
        """循环动画效果（可选）"""
        # 创建循环动画效果的代码，上下跳动窗口位置
        while self.is_dowloading:
            # 窗口跳动，模拟物理效果，g = 9.8 m/s²
            # 动画需要平滑过渡
            for offset in range(0, 7, 1):
                if not self.is_dowloading:
                    break
                self.root.geometry(f"+{self.root.winfo_x()}+{self.root.winfo_y() - offset}")
                self.root.update()
                time.sleep(0.01)
            for offset in range(6, -1, -1):
                if not self.is_dowloading:
                    break
                self.root.geometry(f"+{self.root.winfo_x()}+{self.root.winfo_y() + offset}")
                self.root.update()
                time.sleep(0.05)

        self.root.after(1000, self.cycle_animation)  # 还原位置
        
    def create_widgets(self):
        """创建现代化美观下载界面组件"""
        # 设置窗口背景色 - 使用渐变背景
        self.root.configure(bg='#f8fafc')
        
        # 主框架 - 添加圆角和阴影效果
        main_frame = tk.Frame(self.root, bg='#ffffff', relief='flat', bd=0, 
                             highlightbackground='#e2e8f0', highlightthickness=1)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # 标题区域 - 添加渐变背景
        title_frame = tk.Frame(main_frame, bg='#ffffff', height=60)
        title_frame.pack(fill=tk.X, pady=(0, 5))
        title_frame.pack_propagate(False)  # 固定高度
        
        # 下载图标区域 - 圆形背景
        icon_frame = tk.Frame(title_frame, bg='#3b82f6', width=40, height=40)
        icon_frame.pack(side=tk.LEFT, padx=(20, 15), pady=10)
        icon_frame.pack_propagate(False)
        
        download_icon = tk.Label(icon_frame, text="⬇️", font=('Microsoft YaHei', 14), 
                                bg='#3b82f6', fg='white')
        download_icon.place(relx=0.5, rely=0.5, anchor='center')
        
        # 当前文件信息 - 更优雅的排版
        file_info_frame = tk.Frame(title_frame, bg='#ffffff')
        file_info_frame.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 20))
        
        # 标题文字
        title_label = tk.Label(file_info_frame, text="正在下载", 
                              font=('Microsoft YaHei', 12, 'bold'), bg='#ffffff', 
                              fg='#1e293b', anchor='w')
        title_label.pack(anchor='w', pady=(5, 0))
        
        # 当前文件 - 使用更精致的样式
        self.current_file_var = tk.StringVar(value="初始化下载组件...")
        current_file_label = tk.Label(file_info_frame, textvariable=self.current_file_var, 
                                     font=('Microsoft YaHei', 10), bg='#ffffff', 
                                     fg='#64748b', anchor='w')
        current_file_label.pack(anchor='w', pady=(2, 5))
        
        # 进度条区域 - 增加垂直间距
        progress_frame = tk.Frame(main_frame, bg='#ffffff')
        progress_frame.pack(fill=tk.X, padx=20, pady=(10, 0))
        
        # 进度条 - 现代化设计
        self.progress_var = tk.DoubleVar()
        style = ttk.Style()
        style.configure("Modern.Horizontal.TProgressbar", 
                       troughcolor='#f1f5f9', 
                       background='#10b981', 
                       bordercolor='#e2e8f0',
                       lightcolor='#10b981',
                       darkcolor='#059669',
                       thickness=8)
        
        self.progress_bar = ttk.Progressbar(progress_frame, variable=self.progress_var, 
                                           maximum=100, style="Modern.Horizontal.TProgressbar")
        self.progress_bar.pack(fill=tk.X, pady=(0, 12))
        
        # 进度信息框架 - 更紧凑的布局
        info_frame = tk.Frame(main_frame, bg='#ffffff')
        info_frame.pack(fill=tk.X, padx=20, pady=(0, 15))
        
        # 左侧：进度百分比和文件大小
        left_info_frame = tk.Frame(info_frame, bg='#ffffff')
        left_info_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        self.progress_text_var = tk.StringVar(value="0%")
        progress_label = tk.Label(left_info_frame, textvariable=self.progress_text_var, 
                                 font=('Microsoft YaHei', 11, 'bold'), bg='#ffffff', 
                                 fg='#10b981')
        progress_label.pack(anchor='w')
        
        # 右侧：下载速度和状态
        right_info_frame = tk.Frame(info_frame, bg='#ffffff')
        right_info_frame.pack(side=tk.RIGHT)
        
        self.speed_var = tk.StringVar(value="0 KB/s")
        speed_label = tk.Label(right_info_frame, textvariable=self.speed_var, 
                              font=('Microsoft YaHei', 9), bg='#ffffff', 
                              fg='#64748b')
        speed_label.pack(anchor='e')
        
        # 状态指示器 - 使用更现代的颜色
        status_frame = tk.Frame(main_frame, bg='#ffffff')
        status_frame.pack(fill=tk.X, padx=20, pady=(0, 10))
        
        self.status_var = tk.StringVar(value="🔄 准备开始下载...")
        status_label = tk.Label(status_frame, textvariable=self.status_var, 
                               font=('Microsoft YaHei', 9), bg='#ffffff', 
                               fg='#f59e0b')
        status_label.pack(side=tk.LEFT)
        
        # 底部装饰 - 更细的分隔线
        separator = ttk.Separator(main_frame, orient='horizontal')
        separator.pack(fill=tk.X, padx=20, pady=(8, 0))
        
        # 添加版权信息（可选）
        copyright_frame = tk.Frame(main_frame, bg='#ffffff')
        copyright_frame.pack(fill=tk.X, padx=20, pady=(5, 8))
        
        copyright_label = tk.Label(copyright_frame, text="FaustLauncher", 
                                  font=('Microsoft YaHei', 8), bg='#ffffff', 
                                  fg='#94a3b8')
        copyright_label.pack(side=tk.RIGHT)
      
    def update_progress(self, percent, downloaded, total, speed):
        """更新进度显示"""
        self.progress_var.set(percent)
        
        # 更新状态指示器
        if percent < 10:
            self.status_var.set("🔄 初始化下载...")
        elif percent < 50:
            self.status_var.set("📥 下载中...")
        elif percent < 90:
            self.status_var.set("⚡ 马上就好...")
        elif percent < 100:
            self.status_var.set("🎯 即将完成...")
        else:
            self.status_var.set("下载完成!")
        
        # 格式化文件大小
        if total >= 1024*1024*1024:  # GB
            downloaded_str = f"{downloaded/1024/1024/1024:.1f}GB"
            total_str = f"{total/1024/1024/1024:.1f}GB"
        elif total >= 1024*1024:  # MB
            downloaded_str = f"{downloaded/1024/1024:.1f}MB"
            total_str = f"{total/1024/1024:.1f}MB"
        elif total >= 1024:  # KB
            downloaded_str = f"{downloaded/1024:.1f}KB"
            total_str = f"{total/1024:.1f}KB"
        else:  # Bytes
            downloaded_str = f"{downloaded}B"
            total_str = f"{total}B"
            
        self.progress_text_var.set(f"{percent:.1f}% ({downloaded_str}/{total_str})")
        
        # 格式化速度显示
        if speed >= 1024:  # MB/s
            speed_str = f"{speed/1024:.1f} MB/s"
        else:  # KB/s
            speed_str = f"{speed:.1f} KB/s"
            
        self.speed_var.set(f"速度: {speed_str}")
        self.root.update_idletasks()
        
    def start_download(self, dowload_func=None):
        """开始下载"""
        self.is_dowloading = True
        
        # 在新线程中运行下载
        thread = threading.Thread(target=self.run_download, args=(dowload_func,))
        thread.daemon = True
        thread.start()
        
    def run_download(self, dowload_func=None):
        """运行下载任务"""
        try:
            success = dowload_func(self, self.config_path) # type: ignore
            if success:
                self.root.destroy()
            else:
                self.current_file_var.set("❌ 下载失败，请检查错误信息")
                time.sleep(3)
                self.root.destroy()
        except Exception as e:
            self.current_file_var.set(f"❌ 下载过程中出现错误: {e}")
        finally:
            self.is_dowloading = False