import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import os
import shutil
from PIL import Image, ImageTk, ImageFont, ImageDraw
from functions.window_ulits import center_window

class FontSelectorGUI:
    def __init__(self, window, root):
        self.root = tk.Toplevel(root)  # 改为Toplevel而不是Tk
        self.root.withdraw()  # 先隐藏窗口，防止闪烁

        self.root.title("字体替换工具")
        self.root.geometry("700x600")
        self.root.resizable(True, True)
        self.parent = window  # 保存父窗口引用
        self.root.configure(bg=self.parent.lighten_bg_color)  # 继承父窗口的背景颜色

        center_window(self.root)

        # 设置应用程序图标
        try:
            if os.path.exists("assets/images/icon/icon.ico"):
                self.root.iconbitmap("assets/images/icon/icon.ico")
        except:
            pass
        
        # 字体路径
        self.context_font_path = "Font\\Context\\ChineseFont.ttf"
        self.title_font_path = "Font\\Title\\ChineseFont.ttf"
        
        # 为每个选项卡创建独立的预览对象和图片引用列表
        self.context_preview_data = {
            'canvas': None,
            'photo_refs': [],  # 改为列表存储多个图片引用
            'info_text': None
        }
        self.title_preview_data = {
            'canvas': None,
            'photo_refs': [],  # 改为列表存储多个图片引用
            'info_text': None
        }
        
        # 创建界面
        self.create_widgets()
        
        # 绑定窗口关闭事件
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        
    def on_close(self):
        """窗口关闭时的清理操作"""
        # 清理图片引用
        for preview_data in [self.context_preview_data, self.title_preview_data]:
            preview_data['photo_refs'] = []
        self.root.destroy()

    def create_widgets(self):
        """创建界面组件"""
        # 主标题
        title_frame = tk.Frame(self.root, bg=self.parent.lighten_bg_color)
        title_frame.pack(fill=tk.X, padx=20, pady=(20, 10))
        
        title_label = tk.Label(title_frame, text="字体替换工具", 
                              font=('Microsoft YaHei UI', 18, 'bold'),
                              bg=self.parent.lighten_bg_color, fg='#ecf0f1')
        title_label.pack()
        
        subtitle_label = tk.Label(title_frame, text="管理 Context 和 Title 字体文件",
                                 font=('Microsoft YaHei UI', 10),
                                 bg=self.parent.lighten_bg_color, fg='#bdc3c7')
        subtitle_label.pack(pady=(5, 0))
        
        # 主内容区域
        main_frame = tk.Frame(self.root, bg=self.parent.bg_color)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)
        
        # 创建选项卡
        notebook = ttk.Notebook(main_frame)
        notebook.pack(fill=tk.BOTH, expand=True)
        
        # 设置选项卡样式
        style = ttk.Style()
        style.configure('TNotebook', background=self.parent.bg_color)
        style.configure('TNotebook.Tab', background=self.parent.lighten_bg_color, foreground='#ecf0f1',
                       padding=[15, 5], font=('Microsoft YaHei UI', 10))
        style.map('TNotebook.Tab', background=[('selected', '#3498db')])
        
        # Context字体选项卡
        context_frame = tk.Frame(notebook, bg=self.parent.bg_color)
        notebook.add(context_frame, text="Context 字体")
        self.create_font_tab(context_frame, "Context", self.context_font_path, self.context_preview_data)
        
        # Title字体选项卡
        title_frame = tk.Frame(notebook, bg=self.parent.bg_color)
        notebook.add(title_frame, text="Title 字体")
        self.create_font_tab(title_frame, "Title", self.title_font_path, self.title_preview_data)
        
        # 状态栏
        status_frame = tk.Frame(self.root, bg=self.parent.lighten_bg_color, height=30)
        status_frame.pack(fill=tk.X, side=tk.BOTTOM)
        status_frame.pack_propagate(False)
        
        self.status_var = tk.StringVar()
        self.status_var.set("就绪")
        status_label = tk.Label(status_frame, textvariable=self.status_var,
                               font=('Microsoft YaHei UI', 9),
                               bg=self.parent.lighten_bg_color, fg='#95a5a6', anchor=tk.W)
        status_label.pack(fill=tk.X, padx=20, pady=5)
        
    def create_font_tab(self, parent, font_type, font_path, preview_data):
        """创建字体选项卡"""
        # 当前字体信息区域
        info_frame = tk.Frame(parent, bg=self.parent.bg_color)
        info_frame.pack(fill=tk.X, padx=10, pady=(10, 5))
        
        info_label = tk.Label(info_frame, text=f"{font_type} 字体信息",
                             font=('Microsoft YaHei UI', 12, 'bold'),
                             bg=self.parent.bg_color, fg='#ecf0f1', anchor=tk.W)
        info_label.pack(fill=tk.X)
        
        # 为每个选项卡创建独立的信息文本框
        info_text = tk.Text(info_frame, height=3, width=60,
                           font=('Microsoft YaHei UI', 9),
                           bg=self.parent.lighten_bg_color, fg='#ecf0f1',
                           relief=tk.FLAT, borderwidth=1,
                           wrap=tk.WORD)
        info_text.pack(fill=tk.X, pady=(5, 0))
        info_text.config(state=tk.DISABLED)
        preview_data['info_text'] = info_text
        
        # 预览区域
        preview_frame = tk.Frame(parent, bg=self.parent.bg_color)
        preview_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        preview_label = tk.Label(preview_frame, text="字体预览",
                               font=('Microsoft YaHei UI', 12, 'bold'),
                               bg=self.parent.lighten_bg_color, fg='#ecf0f1', anchor=tk.W)
        preview_label.pack(fill=tk.X)
        
        # 为每个选项卡创建独立的预览画布
        canvas_frame = tk.Frame(preview_frame, bg=self.parent.lighten_bg_color, relief=tk.RAISED, borderwidth=2)
        canvas_frame.pack(fill=tk.BOTH, expand=True, pady=(5, 0))
        
        preview_canvas = tk.Canvas(canvas_frame, width=600, height=200, 
                                  bg=self.parent.lighten_bg_color, highlightthickness=0)
        preview_canvas.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)
        preview_data['canvas'] = preview_canvas
        
        # 按钮区域
        button_frame = tk.Frame(parent, bg=self.parent.bg_color)
        button_frame.pack(fill=tk.X, padx=10, pady=10)
        
        # 创建按钮
        self.create_button(button_frame, "选择字体文件", 
                          lambda: self.select_font_file(font_type, font_path, preview_data),
                          side=tk.LEFT, padx=(0, 10))

        # TODO 完成重置功能
        # self.create_button(button_frame, "重置为默认", 
        #                   lambda: self.reset_font(font_type, font_path, preview_data),
        #                   side=tk.LEFT)
        
        # 初始化字体信息
        self.update_font_info(font_type, font_path, preview_data)
    
    def create_button(self, parent, text, command, **pack_args):
        """创建样式统一的按钮"""
        btn = tk.Button(parent, text=text, command=command,
                       font=('Microsoft YaHei UI', 10),
                       bg='#3498db', fg='white',
                       activebackground='#2980b9',
                       activeforeground='white',
                       relief=tk.RAISED, borderwidth=2,
                       padx=15, pady=8)
        btn.pack(**pack_args)
        
        # 添加悬停效果
        def on_enter(e):
            btn.config(bg='#2980b9')
        def on_leave(e):
            btn.config(bg='#3498db')
        
        btn.bind("<Enter>", on_enter)
        btn.bind("<Leave>", on_leave)
        
        return btn
    
    def update_font_info(self, font_type, font_path, preview_data):
        """更新字体信息显示"""
        info_text = preview_data['info_text']
        info_text.config(state=tk.NORMAL)
        info_text.delete(1.0, tk.END)
        
        if os.path.exists(font_path):
            try:
                # 测试字体文件
                font = ImageFont.truetype(font_path, 16)
                file_size = os.path.getsize(font_path) / 1024  # KB
                file_mtime = os.path.getmtime(font_path)
                from datetime import datetime
                mtime_str = datetime.fromtimestamp(file_mtime).strftime('%Y-%m-%d %H:%M:%S')
                
                info_text_content = (f"字体文件: {os.path.basename(font_path)}\n"
                                   f"文件大小: {file_size:.1f} KB\n"
                                   f"修改时间: {mtime_str}\n"
                                   f"状态: ✓ 字体文件正常")
                
                info_text.insert(tk.END, info_text_content)
                self.update_preview(font_path, font_type, preview_data)
                
            except Exception as e:
                info_text_content = (f"字体文件: {os.path.basename(font_path)}\n"
                                   f"状态: ✗ 字体文件损坏 ({str(e)})")
                info_text.insert(tk.END, info_text_content)
                self.show_error_preview(font_type, preview_data)
        else:
            info_text_content = (f"字体文件: ChineseFont.ttf\n"
                               f"状态: ⚠ 字体文件不存在\n"
                               f"请选择字体文件进行替换")
            info_text.insert(tk.END, info_text_content)
            self.show_error_preview(font_type, preview_data)
        
        info_text.config(state=tk.DISABLED)
    
    def update_preview(self, font_path, font_type, preview_data):
        """更新字体预览"""
        try:
            # 创建更大的预览图像
            img = Image.new('RGB', (600, 200), color=self.parent.lighten_bg_color)
            draw = ImageDraw.Draw(img)
            
            # 加载字体 - 使用更大的字号
            font_large = ImageFont.truetype(font_path, 32)
            font_medium = ImageFont.truetype(font_path, 20)
            font_small = ImageFont.truetype(font_path, 16)
            
            # 绘制预览文本 - 更好的布局
            draw.text((20, 20), f"{font_type} 字体预览", font=font_large, fill='#ecf0f1')
            draw.text((20, 70), "中文预览：你好，世界！这是一段测试文本", font=font_medium, fill='#bdc3c7')
            draw.text((20, 100), "English: Hello World! This is a test text", font=font_medium, fill='#bdc3c7')
            draw.text((20, 130), "数字符号：1234567890 !@#$%^&*()", font=font_small, fill='#95a5a6')
            draw.text((20, 155), "字体路径：" + os.path.basename(font_path), font=font_small, fill='#7f8c8d')
            
            # 显示图像到对应的画布
            photo = ImageTk.PhotoImage(img)
            preview_canvas = preview_data['canvas']
            preview_canvas.delete("all")
            preview_canvas.create_image(0, 0, anchor=tk.NW, image=photo)
            
            # 保存引用防止垃圾回收 - 使用列表存储
            preview_data['photo_refs'].append(photo)
            
        except Exception as e:
            self.show_error_preview(font_type, preview_data, str(e))
    
    def show_error_preview(self, font_type, preview_data, error_msg=None):
        """显示错误预览"""
        img = Image.new('RGB', (600, 200), color=self.parent.lighten_bg_color)
        draw = ImageDraw.Draw(img)
        
        # 使用系统默认字体
        try:
            # 尝试使用系统字体
            font_large = ImageFont.truetype("ChineseFont.ttf", 24)
        except:
            try:
                font_large = ImageFont.load_default()
            except:
                # 如果都失败，使用默认字体
                font_large = None
        
        # 绘制错误信息
        if font_large:
            draw.text((20, 30), f"{font_type} 字体", font=font_large, fill='#e74c3c')
            draw.text((20, 70), "字体不存在或已损坏", font=font_large, fill='#e74c3c')
            
            if error_msg:
                draw.text((20, 110), f"错误: {error_msg}", font=font_large, fill='#e67e22')
            else:
                draw.text((20, 110), "请选择有效的字体文件进行替换", font=font_large, fill='#95a5a6')
            
            draw.text((20, 150), "支持的格式: .ttf 字体文件", font=font_large, fill='#7f8c8d')
        else:
            # 如果没有字体，直接绘制文本
            draw.text((20, 30), f"{font_type} 字体", fill='#e74c3c')
            draw.text((20, 70), "字体不存在或已损坏", fill='#e74c3c')
            if error_msg:
                draw.text((20, 110), f"错误: {error_msg}", fill='#e67e22')
            else:
                draw.text((20, 110), "请选择有效的字体文件进行替换", fill='#95a5a6')
            draw.text((20, 150), "支持的格式: .ttf 字体文件", fill='#7f8c8d')
        
        # 显示图像到对应的画布
        photo = ImageTk.PhotoImage(img)
        preview_canvas = preview_data['canvas']
        preview_canvas.delete("all")
        preview_canvas.create_image(0, 0, anchor=tk.NW, image=photo)
        
        # 保存引用防止垃圾回收 - 使用列表存储
        preview_data['photo_refs'].append(photo)
    
    def select_font_file(self, font_type, target_path, preview_data):
        """选择字体文件"""
        file_path = filedialog.askopenfilename(
            title=f"选择{font_type}字体文件",
            filetypes=[("TrueType字体文件", "*.ttf"), ("OpenType字体文件", "*.otf"), ("所有文件", "*.*")]
        )
        
        if file_path:
            try:
                # 验证是否为有效的字体文件
                test_font = ImageFont.truetype(file_path, 16)
                
                # 确保目标目录存在
                os.makedirs(os.path.dirname(target_path), exist_ok=True)
                
                # 删除原字体文件（如果存在）
                if os.path.exists(target_path):
                    os.remove(target_path)
                
                # 复制新字体文件并重命名
                shutil.copy2(file_path, target_path)
                
                # 更新显示
                self.update_font_info(font_type, target_path, preview_data)
                self.status_var.set(f"✓ {font_type}字体替换成功！")
                messagebox.showinfo("成功", 
                                  f"{font_type}字体已成功替换！")
                
            except Exception as e:
                self.status_var.set(f"✗ 字体替换失败: {str(e)}")
                messagebox.showerror("错误", 
                                   f"字体文件无效或替换失败:\n{str(e)}\n"
                                   f"请确保选择的是有效的TrueType字体文件(.ttf)")
    
    def reset_font(self, font_type, target_path, preview_data):
        """重置字体为默认（删除当前字体）"""
        try:
            # 删除当前字体
            if os.path.exists(target_path):
                os.remove(target_path)
            shutil.copy2("ChineseFont.ttf", target_path)
            
            # 更新显示
            self.update_font_info(font_type, target_path, preview_data)
            self.status_var.set(f"✓ {font_type}字体已重置为默认")
            messagebox.showinfo("成功", 
                              f"{font_type}字体已重置为默认状态")
            
        except Exception as e:
            self.status_var.set(f"✗ 重置失败: {str(e)}")
            messagebox.showerror("错误", f"重置字体失败:\n{str(e)}")
    
    def run(self):
        """运行GUI"""
        # 居中显示窗口
        self.root.update_idletasks()
        x = (self.root.winfo_screenwidth() // 2) - (self.root.winfo_width() // 2)
        y = (self.root.winfo_screenheight() // 2) - (self.root.winfo_height() // 2)
        self.root.geometry(f"+{x}+{y}")
        
        # 等待窗口关闭
        self.root.wait_window()

def select_font_gui(root):
    """主函数"""
    try:
        app = FontSelectorGUI(root, root.root)
        app.run()
    except Exception as e:
        messagebox.showerror("启动错误", f"无法启动字体选择工具:\n{str(e)}")