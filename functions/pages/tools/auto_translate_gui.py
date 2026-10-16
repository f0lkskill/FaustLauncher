import tkinter as tk
from tkinter import ttk, messagebox
import threading
from functions.translate.auto_translate import auto_translate
from functions.base.window_utils import center_window
from functions.base.color_scheme import C
from functions.base.style_utils import apply_scrollbar_style
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
        
        self.bg_color = window.bg_color if hasattr(window, 'bg_color') else '#1a1a1a'
        self.lighten_bg_color = window.lighten_bg_color if hasattr(window, 'lighten_bg_color') else '#2a2a2a'
        self.text_color = C.TEXT_WHITE
        self.accent_color = C.LEGACY_BLUE
        self.success_color = C.LEGACY_GREEN
        self.error_color = C.DANGER
        
        self.configure_styles()
        
        try:
            self.root.iconbitmap("assets/images/icon/icon.ico")
        except:
            pass
        
        self.create_widgets()
        self.is_running = False
    
    def configure_styles(self):
        style = ttk.Style()
        
        style.configure('Dark.TFrame', background=self.bg_color)
        style.configure('Light.TFrame', background=self.lighten_bg_color)
        
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
                        foreground=C.TEXT_SECONDARY,
                       font=('Microsoft YaHei UI', 11))
        
        style.configure('Primary.TButton',
                       background=self.accent_color,
                       foreground=self.text_color,
                       focuscolor='none',
                       font=('Microsoft YaHei UI', 10, 'bold'))
        
        style.map('Primary.TButton',
                  background=[('active', C.LEGACY_BLUE_HOVER), ('pressed', '#21618c')])
        
        style.configure('Secondary.TButton',
                       background=self.lighten_bg_color,
                       foreground=self.text_color,
                       focuscolor='none',
                       font=('Microsoft YaHei UI', 10))
        
        style.map('Secondary.TButton',
                 background=[('active', '#3a3a3a'), ('pressed', '#4a4a4a')])
        
        style.configure('Custom.Horizontal.TProgressbar',
                       background=self.accent_color,
                       troughcolor=self.lighten_bg_color,
                       borderwidth=0,
                       lightcolor=self.accent_color,
                       darkcolor=self.accent_color)
    
    def create_widgets(self):
        self.root.configure(bg=self.bg_color)
        
        self._scrollbar_style = apply_scrollbar_style(
            'Custom.Vertical.TScrollbar', self.bg_color, self.accent_color)
        
        main_frame = ttk.Frame(self.root, padding="25", style='Dark.TFrame')
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        title_frame = ttk.Frame(main_frame, style='Dark.TFrame')
        title_frame.pack(fill=tk.X, pady=(0, 20))
        
        title_label = ttk.Label(title_frame, text="自动翻译工具", style='Title.TLabel')
        title_label.pack(side=tk.LEFT)
        
        subtitle_label = ttk.Label(title_frame, text="自动汉化工具", style='Subtitle.TLabel')
        subtitle_label.pack(side=tk.LEFT, padx=(10, 0))
        
        path_info_frame = ttk.Frame(main_frame, style='Light.TFrame', padding="15")
        path_info_frame.pack(fill=tk.X, pady=(0, 20))
        
        blacklist_frame = ttk.Frame(main_frame, style='Light.TFrame', padding="15")
        blacklist_frame.pack(fill=tk.X, pady=(0, 5))
        
        ttk.Label(blacklist_frame, text="黑名单文件配置", style='Dark.TLabel', 
                 font=('Microsoft YaHei UI', 12, 'bold')).pack(anchor=tk.W, pady=(0, 5))
        
        ttk.Label(blacklist_frame, text="每行一个文件名 (以#开头的行会被忽略):", 
                 style='Subtitle.TLabel').pack(anchor=tk.W)
        
        self.mode_combo_box = ttk.Combobox(blacklist_frame, values=["仅主线剧情"],
                                      state="readonly", style='App.TCombobox')
        self.mode_combo_box.current(0)
        self.mode_combo_box.pack(fill=tk.X, pady=5)
        
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
        
        text_scroll = ttk.Scrollbar(text_frame, style='Custom.Vertical.TScrollbar')
        text_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.blacklist_text.config(yscrollcommand=text_scroll.set)
        text_scroll.config(command=self.blacklist_text.yview)
        
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

        log_frame = ttk.Frame(main_frame, style='Light.TFrame', padding="15")
        log_frame.pack(fill=tk.BOTH, expand=False, pady=(0, 10))
        
        ttk.Label(log_frame, text="处理日志", style='Dark.TLabel',
                 font=('Microsoft YaHei UI', 12, 'bold')).pack(anchor=tk.W, pady=(0, 10))
        
        log_text_frame = ttk.Frame(log_frame, style='Light.TFrame')
        log_text_frame.pack(fill=tk.BOTH, expand=False)
        
        self.log_text = tk.Text(log_text_frame, height=6, bg=self.lighten_bg_color,
                               fg=self.text_color, insertbackground=self.text_color,
                               selectbackground=self.accent_color, 
                               font=('Consolas', 9),
                               relief='flat', bd=2, highlightthickness=1,
                               highlightcolor=self.accent_color,
                               highlightbackground='#555555')
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        log_scroll = ttk.Scrollbar(log_text_frame, style='Custom.Vertical.TScrollbar')
        log_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.config(yscrollcommand=log_scroll.set)
        log_scroll.config(command=self.log_text.yview)

        button_frame = tk.Frame(main_frame, bg=self.bg_color, height=60)
        button_frame.pack(fill=tk.X, pady=15, padx=10)
        button_frame.pack_propagate(False)
        
        button_container = tk.Frame(button_frame, bg=self.bg_color)
        button_container.place(relx=0.5, rely=0.5, anchor=tk.CENTER)
        
        self.start_button = tk.Button(button_container, text="🚀 开始翻译", 
                                     command=self.start_translation,
                                     bg=self.accent_color, fg=self.text_color,
                                     font=('Microsoft YaHei UI', 12, 'bold'),
                                     relief='flat', bd=0, padx=20, pady=10)
        self.start_button.pack(side=tk.LEFT, padx=(0, 10))
        
        self.stop_button = tk.Button(button_container, text="⏹️ 停止", 
                                    command=self.stop_translation, state=tk.DISABLED,
                                    bg=self.lighten_bg_color, fg=self.text_color,
                                    font=('Microsoft YaHei UI', 12),
                                    relief='flat', bd=0, padx=20, pady=10)
        self.stop_button.pack(side=tk.LEFT, padx=(0, 10))
        
        clear_button = tk.Button(button_container, text="🗑️ 清空日志", 
                                command=self.clear_log,
                                bg=self.lighten_bg_color, fg=self.text_color,
                                font=('Microsoft YaHei UI', 10),
                                relief='flat', bd=0, padx=15, pady=8)
        clear_button.pack(side=tk.LEFT)
    
    def get_blacklist_files(self):
        text = self.blacklist_text.get('1.0', tk.END).strip()
        files = []
        for line in text.split('\n'):
            line = line.strip()
            if line and not line.startswith('#'):
                files.append(line)
        return files
    
    def log_message(self, message):
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        self.log_text.insert(tk.END, f"[{timestamp}] {message}\n")
        self.log_text.see(tk.END)
        self.root.update_idletasks()
    
    def clear_log(self):
        self.log_text.delete('1.0', tk.END)
        self.log_message("日志已清空")
    
    def update_progress(self, current, total, message):
        if total > 0:
            progress = (current / total) * 100
            self.progress_bar['value'] = progress
        
        status_text = f"{message}"
        if total > 0:
            status_text += f" ({current}/{total})"
        
        self.progress_var.set(status_text)
        self.root.update_idletasks()
    
    def start_translation(self):
        if not self.source_path or not self.target_path:
            messagebox.showerror("错误", "请设置源路径和目标路径")
            return
        
        self.is_running = True
        self.start_button.config(state=tk.DISABLED)
        self.stop_button.config(state=tk.NORMAL)
        self.progress_bar['value'] = 0
        self.clear_log()
        
        thread = threading.Thread(target=self.run_translation)
        thread.daemon = True
        thread.start()

    def get_translation_mode(self):
        mode = self.mode_combo_box.get()
        return mode
    
    def run_translation(self):
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
                self.source_path, self.target_path = self.dict_path[mode]
                is_skill = True

            self.log_message("开始翻译任务...")
            self.log_message(f"源路径: {self.source_path}")
            self.log_message(f"目标路径: {self.target_path}")
            if blacklist_files:
                self.log_message(f"黑名单文件: {blacklist_files}")
            
            success = auto_translate(self, self.source_path, self.target_path, blacklist_files, progress_callback, is_skill)
            
            if self.is_running:
                self.log_message("翻译任务完成!")
                messagebox.showinfo("完成", "翻译任务已完成!")
        
        except Exception as e:
            self.log_message(f"翻译任务异常: {e}")
            messagebox.showerror("错误", f"翻译任务异常: {e}")

        finally:
            self.root.after(0, self.translation_finished)

    def stop_translation(self):
        self.is_running = False
        self.log_message("正在停止翻译任务...")
        self.stop_button.config(state=tk.DISABLED)
    
    def translation_finished(self):
        self.is_running = False
        self.start_button.config(state=tk.NORMAL)
        self.stop_button.config(state=tk.DISABLED)
        if self.progress_bar['value'] < 100:
            self.progress_bar['value'] = 100
        self.progress_var.set("任务完成")

def show_auto_translate_gui(window, source_path="", target_path=""):
    root = tk.Toplevel(window.root)
    app = AutoTranslateGUI(window, root, source_path, target_path)
    return app
