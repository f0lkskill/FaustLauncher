#! 本界面已经废弃

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import os
import shutil
from pathlib import Path
from functions.base.window_ulits import center_window

class ModManager:
    def __init__(self, parent_root, parent):
        self.parent = parent
        self.mod_dir = self.get_mod_directory()
        self.allowed_extensions = {'.bank', '.carra2'}
        self.disabled_suffix = '.disabled'
        
        # 创建子窗口
        self.window = tk.Toplevel(parent_root)
        self.window.withdraw()  # 先隐藏窗口，防止闪烁

        self.window.title("🎮 Mod管理器")
        self.window.geometry("800x650")
        self.window.resizable(True, True)
        self.window.configure(bg=parent.bg_color)

        center_window(self.window)

        self.parent = parent
        
        # 设置窗口图标
        try:
            if os.path.exists("assets/images/icon/icon.ico"):
                self.window.iconbitmap("assets/images/icon/icon.ico")
        except:
            pass
        
        # 创建主框架
        self.main_frame = tk.Frame(self.window, bg=parent.bg_color)
        self.main_frame.pack(fill=tk.BOTH, expand=True, padx=15, pady=15)
        
        # 创建标题
        title_frame = tk.Frame(self.main_frame, bg=parent.bg_color)
        title_frame.pack(fill=tk.X, pady=(0, 10))
        
        title_label = tk.Label(title_frame, text="🎮 Mod管理器", 
                              font=('Microsoft YaHei UI', 20, 'bold'),
                              bg=parent.bg_color, fg='#ecf0f1')
        title_label.pack(pady=5)
        
        # 创建路径显示
        path_label = tk.Label(title_frame, text=f"Mod目录: {self.mod_dir}",
                             font=('Microsoft YaHei UI', 10),
                             bg=parent.bg_color, fg='#bdc3c7')
        path_label.pack()
        
        self.set_style()

        # 创建工具栏
        self.create_toolbar()
        
        # 创建文件列表
        self.create_file_list()
        
        # 创建状态栏
        self.create_status_bar()
        
        # 加载文件列表
        self.refresh_file_list()
    
    def get_mod_directory(self):
        """获取Mod目录路径"""
        roaming_path = os.getenv('APPDATA')
        mod_path = os.path.join(roaming_path, 'LimbusCompanyMods') # type: ignore
        
        # 如果目录不存在则创建
        if not os.path.exists(mod_path):
            os.makedirs(mod_path)
            print(f"创建Mod目录: {mod_path}")
        
        return mod_path
    
    def create_toolbar(self):
        """创建工具栏"""
        toolbar_frame = tk.Frame(self.main_frame, bg=self.parent.bg_color, relief=tk.RAISED, borderwidth=1)
        toolbar_frame.pack(fill=tk.X, pady=(0, 10))
        
        # 工具栏内部容器
        toolbar_inner = tk.Frame(toolbar_frame, bg=self.parent.bg_color)
        toolbar_inner.pack(padx=10, pady=8)
        
        # 添加文件按钮
        add_button = self.create_styled_button(toolbar_inner, "📁 添加文件", 
                                             self.add_files_dialog, '#3498db')
        add_button.pack(side=tk.LEFT, padx=5)
        
        # 刷新按钮
        refresh_button = self.create_styled_button(toolbar_inner, "🔄 刷新", 
                                                 self.refresh_file_list, '#9b59b6')
        refresh_button.pack(side=tk.LEFT, padx=5)
        
        # 启用选中按钮
        enable_button = self.create_styled_button(toolbar_inner, " 启用选中", 
                                                self.enable_selected, '#27ae60')
        enable_button.pack(side=tk.LEFT, padx=5)
        
        # 禁用选中按钮
        disable_button = self.create_styled_button(toolbar_inner, "⛔ 禁用选中", 
                                                 self.disable_selected, '#e67e22')
        disable_button.pack(side=tk.LEFT, padx=5)
        
        # 打开目录按钮
        open_dir_button = self.create_styled_button(toolbar_inner, "📂 打开目录", 
                                                  self.open_mod_directory, '#f39c12')
        open_dir_button.pack(side=tk.LEFT, padx=5)
        
        # 删除选中按钮
        delete_button = self.create_styled_button(toolbar_inner, "🗑️ 删除选中", 
                                                self.delete_selected, '#e74c3c')
        delete_button.pack(side=tk.LEFT, padx=5)
    
    def create_styled_button(self, parent, text, command, color):
        """创建样式统一的按钮"""
        btn = tk.Button(parent, text=text, command=command,
                       font=('Microsoft YaHei UI', 10, 'bold'),
                       bg=color, fg='white',
                       activebackground=self.darken_color(color),
                       activeforeground='white',
                       relief=tk.RAISED, borderwidth=2,
                       padx=12, pady=6,
                       cursor='hand2')
        
        # 添加悬停效果
        def on_enter(e):
            btn.config(bg=self.darken_color(color))
        def on_leave(e):
            btn.config(bg=color)
        
        btn.bind("<Enter>", on_enter)
        btn.bind("<Leave>", on_leave)
        
        return btn
    
    def darken_color(self, color):
        """加深颜色"""
        if color.startswith('#'):
            r = int(color[1:3], 16)
            g = int(color[3:5], 16)
            b = int(color[5:7], 16)
            r = max(0, r - 30)
            g = max(0, g - 30)
            b = max(0, b - 30)
            return f"#{r:02x}{g:02x}{b:02x}"
        return color
    
    def create_file_list(self):
        """创建文件列表"""
        # 创建Treeview框架
        tree_frame = tk.Frame(self.main_frame, bg=self.parent.bg_color, relief=tk.SUNKEN, borderwidth=1)
        tree_frame.pack(fill=tk.BOTH, expand=True)
        
        # 创建滚动条
        scrollbar = tk.Scrollbar(tree_frame, bg=self.parent.bg_color, troughcolor=self.parent.lighten_bg_color)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # 创建Treeview
        self.tree = ttk.Treeview(tree_frame, columns=('status', 'size', 'type'), 
                               show='tree headings', yscrollcommand=scrollbar.set,
                               height=15)
        self.tree.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)
        
        # 配置滚动条
        scrollbar.config(command=self.tree.yview)
        
        # 配置列
        self.tree.column('#0', width=200, anchor=tk.W)
        self.tree.column('status', width=100, anchor=tk.CENTER)
        self.tree.column('size', width=100, anchor=tk.E)
        self.tree.column('type', width=150, anchor=tk.W)
        
        # 配置标题
        self.tree.heading('#0', text='文件名')
        self.tree.heading('status', text='状态')
        self.tree.heading('size', text='大小')
        self.tree.heading('type', text='类型')
        
        # 绑定双击事件
        self.tree.bind('<Double-1>', self.on_item_double_click)
        
        # 绑定右键菜单
        self.tree.bind('<Button-3>', self.show_context_menu)
    
    def create_status_bar(self):
        """创建状态栏"""
        status_frame = tk.Frame(self.main_frame, bg=self.parent.bg_color, height=25)
        status_frame.pack(fill=tk.X, side=tk.BOTTOM, pady=(10, 0))
        status_frame.pack_propagate(False)
        
        self.status_var = tk.StringVar()
        self.status_var.set("就绪 - 双击文件可打开，右键点击可快速操作")
        status_label = tk.Label(status_frame, textvariable=self.status_var,
                               font=('Microsoft YaHei UI', 9),
                               bg=self.parent.bg_color, fg='#95a5a6', anchor=tk.W)
        status_label.pack(fill=tk.X, padx=10, pady=5)
    
    def show_context_menu(self, event):
        """显示右键菜单"""
        item = self.tree.identify_row(event.y)
        if item:
            self.tree.selection_set(item)
            
            # 创建右键菜单
            menu = tk.Menu(self.window, tearoff=0, bg=self.parent.bg_color, fg='#ecf0f1',
                          activebackground=self.parent.lighten_bg_color, activeforeground='white')
            
            filename = self.tree.item(item, 'text').split(' ', 1)[1]
            file_path = os.path.join(self.mod_dir, filename)
            
            # 根据文件状态添加菜单项
            if self.is_file_disabled(filename):
                menu.add_command(label="√ 启用", command=lambda: self.enable_file(filename))
            else:
                menu.add_command(label="⛔ 禁用", command=lambda: self.disable_file(filename))
            
            menu.add_separator()
            menu.add_command(label="📂 打开文件", command=lambda: os.startfile(file_path))
            menu.add_command(label="🗑️ 删除文件", command=lambda: self.delete_file(filename))
            menu.add_separator()
            menu.add_command(label="📋 复制文件名", command=lambda: self.copy_filename(filename))
            
            # 显示菜单
            menu.post(event.x_root, event.y_root)
    
    def get_original_filename(self, filename):
        """获取原始文件名（移除.disabled后缀）"""
        if filename.endswith(self.disabled_suffix):
            return filename[:-len(self.disabled_suffix)]
        return filename

    def is_file_disabled(self, filename):
        """检查文件是否被禁用"""
        return filename.endswith(self.disabled_suffix)
    
    def add_files_dialog(self):
        """打开文件选择对话框"""
        file_types = [
            ("Mod文件", "*.bank *.carra2"),
            ("所有文件", "*.*")
        ]
        
        files = filedialog.askopenfilenames(
            title="选择Mod文件",
            filetypes=file_types
        )
        
        for file_path in files:
            self.add_file(file_path)
    
    def add_file(self, file_path):
        """添加文件到Mod目录"""
        if not os.path.isfile(file_path):
            return
        
        file_ext = Path(file_path).suffix.lower()
        if file_ext not in self.allowed_extensions:
            messagebox.showwarning("警告", 
                f"不支持的文件类型: {file_ext}\n只支持 .bank 和 .carra2 文件")
            return
        
        filename = os.path.basename(file_path)
        dest_path = os.path.join(self.mod_dir, filename)
        
        try:
            shutil.copy2(file_path, dest_path)
            self.status_var.set(f" 已添加文件: {filename}")
            self.refresh_file_list()
        except Exception as e:
            messagebox.showerror("错误", f"添加文件失败: {str(e)}")
    
    def refresh_file_list(self):
        """刷新文件列表"""
        # 清空现有列表
        for item in self.tree.get_children():
            self.tree.delete(item)
        
        # 获取所有文件
        if os.path.exists(self.mod_dir):
            for filename in os.listdir(self.mod_dir):
                file_path = os.path.join(self.mod_dir, filename)
                
                # 检查文件类型（考虑禁用状态）
                original_filename = self.get_original_filename(filename)
                original_ext = Path(original_filename).suffix.lower()
                
                # 只显示允许的文件类型（包括禁用状态的文件）
                if os.path.isfile(file_path) and original_ext in self.allowed_extensions:
                    # 获取文件信息
                    file_ext = original_ext
                    file_icon = self.get_file_icon(file_ext)
                    file_type = self.get_file_type(file_ext)
                    file_size = self.get_file_size(file_path)
                    file_status = self.get_file_status(filename)
                    
                    # 显示文件名（如果是禁用状态，显示原始文件名）
                    if self.is_file_disabled(filename):
                        display_name = f"❌ {filename}"
                    else:
                        display_name = f" {filename}"
                    
                    # 添加到列表
                    item = self.tree.insert('', 'end', text=display_name, 
                                          values=(file_status, file_size, file_type))
        
        self.status_var.set(f"📁 已加载 {len(self.tree.get_children())} 个文件")
    
    def get_file_status(self, filename):
        """获取文件状态"""
        if self.is_file_disabled(filename):
            return "❌ 禁用"
        else:
            return " 启用"
    
    def get_file_size(self, file_path):
        """获取文件大小"""
        size = os.path.getsize(file_path)
        if size < 1024:
            return f"{size} B"
        elif size < 1024 * 1024:
            return f"{size/1024:.1f} KB"
        else:
            return f"{size/(1024*1024):.1f} MB"
    
    def get_file_type(self, file_ext):
        """获取文件类型描述"""
        if file_ext == '.bank':
            return "🎵 音效文件"
        elif file_ext == '.carra2':
            return "🖼️ 贴图文件"
        else:
            return "❓ 未知文件"
    
    def get_file_icon(self, file_ext):
        """获取文件图标"""
        if file_ext == '.bank':
            return "🔊"
        elif file_ext == '.carra2':
            return "🖼️"
        else:
            return "📄"
    
    def on_item_double_click(self, event):
        """双击文件事件"""
        selection = self.tree.selection()
        if selection:
            item = selection[0]
            display_text = self.tree.item(item, 'text')
            # 移除图标和空格
            filename = display_text.split(' ', 1)[1] if ' ' in display_text else display_text
            original_filename = self.get_original_filename(filename)
            file_path = os.path.join(self.mod_dir, original_filename)
            
            if os.path.exists(file_path):
                os.startfile(file_path)
    
    def open_mod_directory(self):
        """打开Mod目录"""
        if os.path.exists(self.mod_dir):
            os.startfile(self.mod_dir)
            self.status_var.set("📂 已打开Mod目录")
        else:
            messagebox.showinfo("信息", "Mod目录不存在")
    
    def enable_selected(self):
        """启用选中的文件"""
        selection = self.tree.selection()
        if not selection:
            messagebox.showinfo("信息", "请先选择要启用的文件")
            return
        
        enabled_count = 0
        for item in selection:
            display_text = self.tree.item(item, 'text')
            filename = display_text.split(' ', 1)[1] if ' ' in display_text else display_text
            
            if self.enable_file(filename):
                enabled_count += 1
        
        if enabled_count > 0:
            self.status_var.set(f" 已启用 {enabled_count} 个文件")
        self.refresh_file_list()
    
    def disable_selected(self):
        """禁用选中的文件"""
        selection = self.tree.selection()
        if not selection:
            messagebox.showinfo("信息", "请先选择要禁用的文件")
            return
        
        disabled_count = 0
        for item in selection:
            display_text = self.tree.item(item, 'text')
            filename = display_text.split(' ', 1)[1] if ' ' in display_text else display_text
            original_filename = self.get_original_filename(filename)
            
            if self.disable_file(original_filename):
                disabled_count += 1
        
        if disabled_count > 0:
            self.status_var.set(f"⛔ 已禁用 {disabled_count} 个文件")
        self.refresh_file_list()
    
    def enable_file(self, filename):
        """启用单个文件"""
        try:
            # 如果文件已经启用，直接返回
            if not self.is_file_disabled(filename):
                return True
                
            original_filename = self.get_original_filename(filename)
            current_path = os.path.join(self.mod_dir, filename)
            new_path = os.path.join(self.mod_dir, original_filename)
            
            if os.path.exists(current_path):
                os.rename(current_path, new_path)
                return True
        except Exception as e:
            messagebox.showerror("错误", f"启用文件失败: {str(e)}")
        finally:
            self.refresh_file_list()
        return False
    
    def disable_file(self, filename):
        """禁用单个文件"""
        try:
            # 如果文件已经禁用，直接返回
            if self.is_file_disabled(filename):
                return True
                
            current_path = os.path.join(self.mod_dir, filename)
            new_path = os.path.join(self.mod_dir, filename + self.disabled_suffix)
            
            if os.path.exists(current_path):
                os.rename(current_path, new_path)
                return True
        except Exception as e:
            messagebox.showerror("错误", f"禁用文件失败: {str(e)}")
        finally:
            self.refresh_file_list()
        return False
    
    def delete_selected(self):
        """删除选中的文件"""
        selection = self.tree.selection()
        if not selection:
            messagebox.showinfo("信息", "请先选择要删除的文件")
            return
        
        if messagebox.askyesno("确认删除", "确定要删除选中的文件吗？"):
            deleted_count = 0
            for item in selection:
                display_text = self.tree.item(item, 'text')
                filename = display_text.split(' ', 1)[1] if ' ' in display_text else display_text
                original_filename = self.get_original_filename(filename)
                file_path = os.path.join(self.mod_dir, original_filename)
                
                try:
                    if os.path.exists(file_path):
                        os.remove(file_path)
                        deleted_count += 1
                except Exception as e:
                    messagebox.showerror("错误", f"删除文件失败: {str(e)}")
            
            if deleted_count > 0:
                self.status_var.set(f"🗑️ 已删除 {deleted_count} 个文件")
                self.refresh_file_list()
    
    def delete_file(self, filename):
        """删除单个文件"""
        original_filename = self.get_original_filename(filename)
        file_path = os.path.join(self.mod_dir, original_filename)
        
        if messagebox.askyesno("确认删除", f"确定要删除文件 {original_filename} 吗？"):
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
                    self.status_var.set(f"🗑️ 已删除文件: {original_filename}")
                    self.refresh_file_list()
            except Exception as e:
                messagebox.showerror("错误", f"删除文件失败: {str(e)}")
    
    def copy_filename(self, filename):
        """复制文件名到剪贴板"""
        original_filename = self.get_original_filename(filename)
        self.window.clipboard_clear()
        self.window.clipboard_append(original_filename)
        self.status_var.set(f"📋 已复制文件名: {original_filename}")

    def set_style(self):
        """设置样式"""
        style = ttk.Style()
        style.theme_use('clam')
        
        # 配置Treeview样式
        style.configure('Treeview', 
                       background=self.parent.bg_color,
                       foreground='#ecf0f1',
                       fieldbackground=self.parent.bg_color,
                       borderwidth=0)
        
        style.configure('Treeview.Heading',
                       background=self.parent.bg_color,
                       foreground='#ecf0f1',
                       relief='flat',
                       borderwidth=0)
        
        style.map('Treeview', 
                 background=[('selected', self.parent.lighten_bg_color)],
                 foreground=[('selected', 'white')])

def open_mod_manager(parent):
    """打开Mod管理器"""
    return ModManager(parent.root, parent)