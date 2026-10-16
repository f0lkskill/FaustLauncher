import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import os
import shutil
from PIL import Image, ImageTk, ImageFont, ImageDraw
from functions.base.window_utils import center_window
from functions.base.color_scheme import C
from functions.base.custom_notebook import CustomNotebook

class FontSelectorGUI:
    def __init__(self, window, root):
        self.root = tk.Toplevel(root)
        self.root.withdraw()

        self.root.title("字体替换工具")
        self.root.geometry("500x600")
        self.root.resizable(True, True)
        self.parent = window
        self.root.configure(bg=self.parent.lighten_bg_color)

        center_window(self.root)

        try:
            if os.path.exists("assets/images/icon/icon.ico"):
                self.root.iconbitmap("assets/images/icon/icon.ico")
        except:
            pass
        
        self.context_font_path = "assets\\Font\\Context\\ChineseFont.ttf"
        self.title_font_path = "assets\\Font\\Title\\ChineseFont.ttf"
        
        self.context_preview_data = {
            'canvas': None,
            'photo_refs': [],
            'info_text': None
        }
        self.title_preview_data = {
            'canvas': None,
            'photo_refs': [],
            'info_text': None
        }
        
        self.create_widgets()
        
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        
    def on_close(self):
        for preview_data in [self.context_preview_data, self.title_preview_data]:
            preview_data['photo_refs'] = []
        self.root.destroy()

    def create_widgets(self):
        
        main_frame = tk.Frame(self.root, bg=self.parent.bg_color)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)
        
        notebook = CustomNotebook(main_frame, bg=self.parent.bg_color, accent=C.ACCENT)
        notebook.pack(fill=tk.BOTH, expand=True)
        
        context_frame = tk.Frame(notebook, bg=self.parent.bg_color)
        notebook.add(context_frame, text="Context 字体")
        self.create_font_tab(context_frame, "Context", self.context_font_path, self.context_preview_data)
        
        title_frame = tk.Frame(notebook, bg=self.parent.bg_color)
        notebook.add(title_frame, text="Title 字体")
        self.create_font_tab(title_frame, "Title", self.title_font_path, self.title_preview_data)
        
    def create_font_tab(self, parent, font_type, font_path, preview_data):
        info_frame = tk.Frame(parent, bg=self.parent.bg_color)
        info_frame.pack(fill=tk.X, padx=10, pady=(10, 5))
        
        info_label = tk.Label(info_frame, text=f"{font_type} 字体信息",
                             font=('Microsoft YaHei UI', 12, 'bold'),
                              bg=self.parent.bg_color, fg=C.TEXT_PRIMARY, anchor=tk.W)
        info_label.pack(fill=tk.X)
        
        info_text = tk.Text(info_frame, height=3, width=60,
                           font=('Microsoft YaHei UI', 9),
                           bg=self.parent.lighten_bg_color, fg='#ecf0f1',
                           relief=tk.FLAT, borderwidth=1,
                           wrap=tk.WORD)
        info_text.pack(fill=tk.X, pady=(5, 0))
        info_text.config(state=tk.DISABLED)
        preview_data['info_text'] = info_text
        
        preview_frame = tk.Frame(parent, bg=self.parent.bg_color)
        preview_frame.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)
        
        preview_label = tk.Label(preview_frame, text="字体预览",
                               font=('Microsoft YaHei UI', 12, 'bold'),
                               bg=self.parent.lighten_bg_color, fg=C.TEXT_PRIMARY, anchor=tk.W)
        preview_label.pack(fill=tk.X)
        
        canvas_frame = tk.Frame(preview_frame, bg=self.parent.lighten_bg_color, relief=tk.RAISED, borderwidth=1)
        canvas_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 0))
        
        preview_canvas = tk.Canvas(canvas_frame, width=600, height=250, 
                                  bg=self.parent.lighten_bg_color, highlightthickness=0)
        preview_canvas.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)
        preview_data['canvas'] = preview_canvas
        
        button_frame = tk.Frame(parent, bg=self.parent.bg_color)
        button_frame.pack(fill=tk.X, padx=10, pady=10)
        
        self.create_button(button_frame, "选择字体文件", 
                          lambda: self.select_font_file(font_type, font_path, preview_data),
                          side=tk.LEFT, padx=(0, 8))
        
        self.create_button(button_frame, "删除当前字体", 
                          lambda: self.delete_font(font_type, font_path, preview_data),
                          side=tk.LEFT)
        
        self.update_font_info(font_type, font_path, preview_data)
    
    def create_button(self, parent, text, command, **pack_args):
        btn = tk.Button(parent, text=text, command=command,
                       font=('Microsoft YaHei UI', 10),
                        bg=C.LEGACY_BLUE, fg=C.TEXT_WHITE,
                        activebackground=C.LEGACY_BLUE_HOVER,
                        activeforeground=C.TEXT_WHITE,
                       relief=tk.RAISED, borderwidth=2,
                       padx=15, pady=8)
        btn.pack(**pack_args)
        
        def on_enter(e):
            btn.config(bg=C.LEGACY_BLUE_HOVER)
        def on_leave(e):
            btn.config(bg=C.LEGACY_BLUE)
        
        btn.bind("<Enter>", on_enter)
        btn.bind("<Leave>", on_leave)
        
        return btn
    
    def update_font_info(self, font_type, font_path, preview_data):
        info_text = preview_data['info_text']
        info_text.config(state=tk.NORMAL)
        info_text.delete(1.0, tk.END)
        
        if os.path.exists(font_path):
            try:
                font = ImageFont.truetype(font_path, 16)
                file_size = os.path.getsize(font_path) / 1024
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
        try:
            img = Image.new('RGB', (600, 450), color=self.parent.lighten_bg_color)
            draw = ImageDraw.Draw(img)
            
            font_large = ImageFont.truetype(font_path, 32)
            font_medium = ImageFont.truetype(font_path, 20)
            font_small = ImageFont.truetype(font_path, 16)
            
            draw.text((20, 15), f"{font_type} 字体预览", font=font_large, fill=C.TEXT_PRIMARY)
            draw.text((20, 60), "中文预览：你好，世界！这是一段测试文本", font=font_medium, fill=C.TEXT_SECONDARY)
            draw.text((20, 88), "English: Hello World! This is a test text", font=font_medium, fill=C.TEXT_SECONDARY)
            draw.text((20, 116), "日本語: こんにちは、世界！これはテストテキストです", font=font_medium, fill=C.TEXT_SECONDARY)
            draw.text((20, 144), "한국어: 안녕하세요, 세계! 이것은 테스트 텍스트입니다", font=font_medium, fill=C.TEXT_SECONDARY)
            draw.text((20, 172), "数字符号：1234567890+-x÷＞＜≤≥Σ²³", font=font_small, fill=C.TEXT_MUTED)
            draw.text((20, 196), "特殊字符：!@#$%^&*()_+-=[]{}|;:'\",.<>/?", font=font_small, fill=C.TEXT_MUTED)
            draw.text((20, 220), "emoji字符：😊 😂 😃 😄 �️ 😁 😍 😎 😐 😞 😯 😭 😢 😄 😅 😃 😄 😅 😃 😄 😅 😃 😄 😅 😃 😄 😅 😃 😄 😅 😃 😄 😅 😃 😅 😃 😄 😅 😃 �", font=font_small, fill=C.TEXT_MUTED)
            draw.text((20, 244), "字体路径：" + os.path.basename(font_path), font=font_small, fill='#7f8c8d')
            
            photo = ImageTk.PhotoImage(img)
            preview_canvas = preview_data['canvas']
            preview_canvas.delete("all")
            preview_canvas.create_image(0, 0, anchor=tk.NW, image=photo)
            
            preview_data['photo_refs'].append(photo)
            
        except Exception as e:
            self.show_error_preview(font_type, preview_data, str(e))
    
    def show_error_preview(self, font_type, preview_data, error_msg=None):
        img = Image.new('RGB', (600, 250), color=self.parent.lighten_bg_color)
        draw = ImageDraw.Draw(img)
        
        try:
            font_large = ImageFont.truetype("ChineseFont.ttf", 24)
        except:
            try:
                font_large = ImageFont.load_default()
            except:
                font_large = None
        
        if font_large:
            draw.text((20, 30), f"{font_type} 字体", font=font_large, fill=C.DANGER)
            draw.text((20, 70), "字体不存在或已损坏", font=font_large, fill=C.DANGER)
            
            if error_msg:
                draw.text((20, 110), f"错误: {error_msg}", font=font_large, fill=C.WARNING)
            else:
                draw.text((20, 110), "请选择有效的字体文件进行替换", font=font_large, fill=C.TEXT_MUTED)
            
            draw.text((20, 150), "支持的格式: .ttf 字体文件", font=font_large, fill='#7f8c8d')
        else:
            draw.text((20, 30), f"{font_type} 字体", fill=C.DANGER)
            draw.text((20, 70), "字体不存在或已损坏", fill=C.DANGER)
            if error_msg:
                draw.text((20, 110), f"错误: {error_msg}", fill=C.WARNING)
            else:
                draw.text((20, 110), "请选择有效的字体文件进行替换", fill=C.TEXT_MUTED)
            draw.text((20, 150), "支持的格式: .ttf 字体文件", fill='#7f8c8d')
        
        photo = ImageTk.PhotoImage(img)
        preview_canvas = preview_data['canvas']
        preview_canvas.delete("all")
        preview_canvas.create_image(0, 0, anchor=tk.NW, image=photo)
        
        preview_data['photo_refs'].append(photo)
    
    def select_font_file(self, font_type, target_path, preview_data):
        file_path = filedialog.askopenfilename(
            title=f"选择{font_type}字体文件",
            filetypes=[("TrueType字体文件", "*.ttf"), ("OpenType字体文件", "*.otf"), ("所有文件", "*.*")]
        )
        
        if file_path:
            try:
                test_font = ImageFont.truetype(file_path, 16)
                
                os.makedirs(os.path.dirname(target_path), exist_ok=True)
                
                if os.path.exists(target_path):
                    os.remove(target_path)
                
                shutil.copy2(file_path, target_path)
                
                self.update_font_info(font_type, target_path, preview_data)
                messagebox.showinfo("成功", 
                                  f"{font_type}字体已成功替换！")
                
            except Exception as e:
                messagebox.showerror("错误", 
                                   f"字体文件无效或替换失败:\n{str(e)}\n"
                                   f"请确保选择的是有效的TrueType字体文件(.ttf)")
    
    def delete_font(self, font_type, target_path, preview_data):
        if not os.path.exists(target_path):
            messagebox.showinfo("提示", f"当前没有已替换的{font_type}字体文件，无需删除")
            return
        if not messagebox.askyesno("确认删除",
                                   f"确定要删除 {font_type} 字体文件吗？\n\n"
                                   f"文件: {target_path}\n"
                                   f"删除后游戏将使用默认字体。"):
            return
        try:
            os.remove(target_path)
            self.update_font_info(font_type, target_path, preview_data)
            messagebox.showinfo("成功", f"{font_type}字体已删除，游戏将使用默认字体")
        except Exception as e:
            messagebox.showerror("错误", f"删除字体失败:\n{str(e)}")
    
    def run(self):
        self.root.update_idletasks()
        x = (self.root.winfo_screenwidth() // 2) - (self.root.winfo_width() // 2)
        y = (self.root.winfo_screenheight() // 2) - (self.root.winfo_height() // 2)
        self.root.geometry(f"+{x}+{y}")
        
        self.root.wait_window()

def select_font_gui(root):
    try:
        app = FontSelectorGUI(root, root.root)
        app.run()
    except Exception as e:
        messagebox.showerror("启动错误", f"无法启动字体选择工具:\n{str(e)}")
