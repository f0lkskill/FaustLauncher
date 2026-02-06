import tkinter as tk
from tkinter import ttk, messagebox
import threading
from pathlib import Path
from functions.translate.auto_translate import auto_translate
from functions.window_ulits import center_window
import datetime

class AutoTranslateGUI:
    def __init__(self, window, root, source_path="", target_path=""):
        self.root = root
        self.root.title("自动翻译工具 - Faust Launcher")
        self.root.geometry("650x700")
        self.root.resizable(True, True)
        self.window = window
        self.source_path = source_path
        self.target_path = target_path

        self.dict_path = {
            "全部": [source_path, target_path],
            "仅主线剧情": [source_path + "/StoryData", target_path + "/StoryData"],
            "仅人格技能": [source_path, target_path],
        }

        center_window(self.root)
        
        # 设置颜色主题
        self.bg_color = window.bg_color if hasattr(window, 'bg_color') else '#1a1a1a'
        self.lighten_bg_color = window.lighten_bg_color if hasattr(window, 'lighten_bg_color') else '#2a2a2a'
        self.text_color = '#ffffff'
        self.accent_color = '#3498db'
        self.success_color = '#27ae60'
        self.error_color = '#e74c3c'
        
        # 配置样式
        self.configure_styles()
        
        # 设置窗口图标
        try:
            self.root.iconbitmap("assets/images/icon/icon.ico")
        except:
            pass
        
        self.create_widgets()
        self.is_running = False
    
    def configure_styles(self):
        """配置现代化样式"""
        style = ttk.Style()
        
        # 配置主框架样式
        style.configure('Dark.TFrame', background=self.bg_color)
        style.configure('Light.TFrame', background=self.lighten_bg_color)
        
        # 配置标签样式
        style.configure('Dark.TLabel', 
                       background=self.bg_color, 
                       foreground=self.text_color,
                       font=('Microsoft YaHei UI', 10))
        
        style.configure('Title.TLabel',
                       background=self.bg_color,
                       foreground=self.text_color,
                       font=('Microsoft YaHei UI', 18, 'bold'))
        
        style.configure('Subtitle.TLabel',
                       background=self.bg_color,
                       foreground='#bdc3c7',
                       font=('Microsoft YaHei UI', 11))
        
        # 配置按钮样式
        style.configure('Primary.TButton',
                       background=self.accent_color,
                       foreground=self.text_color,
                       focuscolor='none',
                       font=('Microsoft YaHei UI', 10, 'bold'))
        
        style.map('Primary.TButton',
                 background=[('active', '#2980b9'), ('pressed', '#21618c')])
        
        style.configure('Secondary.TButton',
                       background=self.lighten_bg_color,
                       foreground=self.text_color,
                       focuscolor='none',
                       font=('Microsoft YaHei UI', 10))
        
        style.map('Secondary.TButton',
                 background=[('active', '#3a3a3a'), ('pressed', '#4a4a4a')])
        
        # 配置进度条样式
        style.configure('Custom.Horizontal.TProgressbar',
                       background=self.accent_color,
                       troughcolor=self.lighten_bg_color,
                       borderwidth=0,
                       lightcolor=self.accent_color,
                       darkcolor=self.accent_color)
        
        # 配置滚动条样式
        style.configure('Custom.Vertical.TScrollbar',
                       background=self.lighten_bg_color,
                       troughcolor=self.bg_color,
                       bordercolor=self.bg_color,
                       arrowcolor=self.text_color)
    
    def create_widgets(self):
        # 设置主窗口背景色
        self.root.configure(bg=self.bg_color)
        
        # 主框架
        main_frame = ttk.Frame(self.root, padding="25", style='Dark.TFrame')
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # 标题区域
        title_frame = ttk.Frame(main_frame, style='Dark.TFrame')
        title_frame.pack(fill=tk.X, pady=(0, 20))
        
        title_label = ttk.Label(title_frame, text="自动翻译工具", style='Title.TLabel')
        title_label.pack(side=tk.LEFT)
        
        # 副标题
        subtitle_label = ttk.Label(title_frame, text="自动汉化工具", style='Subtitle.TLabel')
        subtitle_label.pack(side=tk.LEFT, padx=(10, 0))
        
        # 路径信息显示
        path_info_frame = ttk.Frame(main_frame, style='Light.TFrame', padding="15")
        path_info_frame.pack(fill=tk.X, pady=(0, 20))
        
        # 黑名单设置区域
        blacklist_frame = ttk.Frame(main_frame, style='Light.TFrame', padding="15")
        blacklist_frame.pack(fill=tk.X, pady=(0, 5))
        
        ttk.Label(blacklist_frame, text="黑名单文件配置", style='Dark.TLabel', 
                 font=('Microsoft YaHei UI', 12, 'bold')).pack(anchor=tk.W, pady=(0, 5))
        
        ttk.Label(blacklist_frame, text="每行一个文件名 (以#开头的行会被忽略):", 
                 style='Subtitle.TLabel').pack(anchor=tk.W)
        
        # 翻译模式选择
        self.mode_combo_box = ttk.Combobox(blacklist_frame, values=["仅主线剧情"],
                                      state="readonly", style='Secondary.TButton')
        self.mode_combo_box.current(0)
        self.mode_combo_box.pack(fill=tk.X, pady=5)
        
        # 创建带样式的文本框
        text_frame = ttk.Frame(blacklist_frame, style='Light.TFrame')
        text_frame.pack(fill=tk.X, pady=3)
        
        self.blacklist_text = tk.Text(text_frame, height=4, bg=self.lighten_bg_color, 
                                     fg=self.text_color, insertbackground=self.text_color,
                                     selectbackground=self.accent_color, 
                                     font=('Microsoft YaHei UI', 9),
                                     relief='flat', bd=2, highlightthickness=1,
                                     highlightcolor=self.accent_color,
                                     highlightbackground='#555555')
        self.blacklist_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        # 滚动条
        text_scroll = ttk.Scrollbar(text_frame, style='Custom.Vertical.TScrollbar')
        text_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.blacklist_text.config(yscrollcommand=text_scroll.set)
        text_scroll.config(command=self.blacklist_text.yview)
        
        # 添加示例黑名单
        example_blacklist = """ProjectGSLessonName.json
P10705.json
3D309I.json
S908A.json
BattleSpeechBubbleDlg.json
BattleSpeechBubbleDlg_Cultivation.json
BattleSpeechBubbleDlg_mowe.json
EGOgift.json
# 注释: 以#开头的行会被忽略"""
        self.blacklist_text.insert('1.0', example_blacklist)
        
        # 进度显示区域
        progress_frame = ttk.Frame(main_frame, style='Light.TFrame', padding="15")
        progress_frame.pack(fill=tk.X, pady=(0, 5))
        
        ttk.Label(progress_frame, text="翻译进度", style='Dark.TLabel',
                 font=('Microsoft YaHei UI', 12, 'bold')).pack(anchor=tk.W, pady=(0, 5))
        
        self.progress_var = tk.StringVar(value="准备开始翻译任务")
        self.progress_label = ttk.Label(progress_frame, textvariable=self.progress_var, 
                                      style='Subtitle.TLabel')
        self.progress_label.pack(anchor=tk.W, pady=(0, 5))
        
        self.progress_bar = ttk.Progressbar(progress_frame, mode='determinate',
                                          style='Custom.Horizontal.TProgressbar')
        self.progress_bar.pack(fill=tk.X, pady=5)

        # 日志显示区域 - 限制高度，为按钮留出空间
        log_frame = ttk.Frame(main_frame, style='Light.TFrame', padding="15")
        log_frame.pack(fill=tk.BOTH, expand=False, pady=(0, 10))  # 改为expand=False
        
        ttk.Label(log_frame, text="处理日志", style='Dark.TLabel',
                 font=('Microsoft YaHei UI', 12, 'bold')).pack(anchor=tk.W, pady=(0, 10))
        
        # 创建带样式的日志文本框 - 限制高度
        log_text_frame = ttk.Frame(log_frame, style='Light.TFrame')
        log_text_frame.pack(fill=tk.BOTH, expand=False)  # 改为expand=False
        
        self.log_text = tk.Text(log_text_frame, height=6, bg=self.lighten_bg_color,  # 减少高度
                               fg=self.text_color, insertbackground=self.text_color,
                               selectbackground=self.accent_color, 
                               font=('Consolas', 9),
                               relief='flat', bd=2, highlightthickness=1,
                               highlightcolor=self.accent_color,
                               highlightbackground='#555555')
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        # 日志滚动条
        log_scroll = ttk.Scrollbar(log_text_frame, style='Custom.Vertical.TScrollbar')
        log_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.config(yscrollcommand=log_scroll.set)
        log_scroll.config(command=self.log_text.yview)

        # 按钮框架 - 确保有足够空间显示
        button_frame = tk.Frame(main_frame, bg=self.bg_color, height=60)  # 设置固定高度
        button_frame.pack(fill=tk.X, pady=15, padx=10)
        button_frame.pack_propagate(False)  # 防止子组件改变框架大小
        
        # 按钮容器
        button_container = tk.Frame(button_frame, bg=self.bg_color)
        button_container.place(relx=0.5, rely=0.5, anchor=tk.CENTER)  # 居中显示
        
        # 开始翻译按钮
        self.start_button = tk.Button(button_container, text="🚀 开始翻译", 
                                     command=self.start_translation,
                                     bg=self.accent_color, fg=self.text_color,
                                     font=('Microsoft YaHei UI', 12, 'bold'),
                                     relief='flat', bd=0, padx=20, pady=10)
        self.start_button.pack(side=tk.LEFT, padx=(0, 10))
        
        # 停止按钮
        self.stop_button = tk.Button(button_container, text="⏹️ 停止", 
                                    command=self.stop_translation, state=tk.DISABLED,
                                    bg=self.lighten_bg_color, fg=self.text_color,
                                    font=('Microsoft YaHei UI', 12),
                                    relief='flat', bd=0, padx=20, pady=10)
        self.stop_button.pack(side=tk.LEFT, padx=(0, 10))
        
        # 清空日志按钮
        clear_button = tk.Button(button_container, text="🗑️ 清空日志", 
                                command=self.clear_log,
                                bg=self.lighten_bg_color, fg=self.text_color,
                                font=('Microsoft YaHei UI', 10),
                                relief='flat', bd=0, padx=15, pady=8)
        clear_button.pack(side=tk.LEFT)
    
    def get_blacklist_files(self):
        """从文本框获取黑名单文件列表"""
        text = self.blacklist_text.get('1.0', tk.END).strip()
        files = []
        for line in text.split('\n'):
            line = line.strip()
            if line and not line.startswith('#'):  # 忽略空行和注释
                files.append(line)
        return files
    
    def log_message(self, message):
        """添加日志消息"""
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        self.log_text.insert(tk.END, f"[{timestamp}] {message}\n")
        self.log_text.see(tk.END)
        self.root.update_idletasks()
    
    def clear_log(self):
        """清空日志"""
        self.log_text.delete('1.0', tk.END)
        self.log_message("日志已清空")
    
    def update_progress(self, current, total, message):
        """更新进度条和状态"""
        if total > 0:
            progress = (current / total) * 100
            self.progress_bar['value'] = progress
        
        status_text = f"{message}"
        if total > 0:
            status_text += f" ({current}/{total})"
        
        self.progress_var.set(status_text)
        self.root.update_idletasks()
    
    def start_translation(self):
        """开始翻译"""
        if not self.source_path or not self.target_path:
            messagebox.showerror("错误", "请设置源路径和目标路径")
            return
        
        self.is_running = True
        self.start_button.config(state=tk.DISABLED)
        self.stop_button.config(state=tk.NORMAL)
        self.progress_bar['value'] = 0
        self.clear_log()
        
        # 在新线程中运行翻译
        thread = threading.Thread(target=self.run_translation)
        thread.daemon = True
        thread.start()

    def get_translation_mode(self):
        """获取翻译模式"""
        mode = self.mode_combo_box.get()
        return mode
    
    def run_translation(self):
        """运行翻译任务"""
        try:
            blacklist_files = self.get_blacklist_files()
            is_skill = False
            
            def progress_callback(current, total, message):
                if self.is_running:
                    self.root.after(0, lambda: self.update_progress(current, total, message))

            mode = self.get_translation_mode()
            if mode in ["仅主线剧情", "全部"]:
                self.source_path, self.target_path = self.dict_path[mode]
            else:
                # Skills_personality-0*.json (12个)
                self.source_path, self.target_path = self.dict_path[mode]
                is_skill = True

            self.log_message("🎯 开始翻译任务...")
            self.log_message(f"📁 源路径: {self.source_path}")
            self.log_message(f"📂 目标路径: {self.target_path}")
            if blacklist_files:
                self.log_message(f"🚫 黑名单文件: {blacklist_files}")
            
            success = auto_translate(self, self.source_path, self.target_path, blacklist_files, progress_callback, is_skill)
            
            if self.is_running:
                self.log_message("翻译任务完成!")
                messagebox.showinfo("完成", "翻译任务已完成!")
        
        except Exception as e:
            self.log_message(f"💥 翻译任务异常: {e}")
            messagebox.showerror("错误", f"翻译任务异常: {e}")

        finally:
            self.root.after(0, self.translation_finished)

    def stop_translation(self):
        """停止翻译"""
        self.is_running = False
        self.log_message("🛑 正在停止翻译任务...")
        self.stop_button.config(state=tk.DISABLED)
    
    def translation_finished(self):
        """翻译完成后的清理工作"""
        self.is_running = False
        self.start_button.config(state=tk.NORMAL)
        self.stop_button.config(state=tk.DISABLED)
        if self.progress_bar['value'] < 100:
            self.progress_bar['value'] = 100
        self.progress_var.set("任务完成")

def show_auto_translate_gui(window, source_path="", target_path=""):
    """显示自动翻译GUI"""
    root = tk.Toplevel(window.root)
    app = AutoTranslateGUI(window, root, source_path, target_path)
    return app