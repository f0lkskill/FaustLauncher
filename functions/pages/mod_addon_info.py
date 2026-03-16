import tkinter as tk
from tkinter import ttk, messagebox
import os
import json
from PIL import Image, ImageTk
from functions.addon.addon_ulit import AddonManager

class ModAddonManagerPage:
    def __init__(self, parent_frame, bg_color, lighten_bg_color):
        """初始化插件&mod管理器页面"""
        self.parent = parent_frame
        self.bg_color = bg_color
        self.lighten_bg_color = lighten_bg_color
        self.addon_manager = AddonManager([])
        self.mods_dir = 'mods'
        self.create_widgets()

        self.refresh_all_tabs()
    
    def create_widgets(self):
        """创建页面控件"""
        
        # 创建设置内容容器, 居中显示
        content_frame = tk.Frame(self.parent, bg=self.lighten_bg_color, relief='groove', borderwidth=1)
        content_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)
        
        # 创建标签页控件
        self.notebook = ttk.Notebook(content_frame)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        # 创建插件管理标签页
        self.create_addons_tab()
        
        # 创建新Mod架构管理标签页
        self.create_new_mods_tab()

        # self.notebook.add(tk.Frame(self.notebook), text="")
    
    def create_addons_tab(self):
        """创建插件管理标签页"""
        addons_frame = ttk.Frame(self.notebook)
        self.notebook.add(addons_frame, text="🔌 插件管理")
        
        # 创建滚动区域
        canvas = tk.Canvas(addons_frame, bg=self.bg_color, highlightthickness=0)
        scrollbar = ttk.Scrollbar(addons_frame, orient="vertical", command=canvas.yview)
        scrollable_frame = tk.Frame(canvas, bg=self.bg_color)
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        # 绑定鼠标滚轮事件
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        canvas.bind("<MouseWheel>", _on_mousewheel)
        scrollable_frame.bind("<MouseWheel>", _on_mousewheel)
        
        # 显示插件列表
        self.show_addons(scrollable_frame)
        
        # 打包滚动区域
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
    
    def create_new_mods_tab(self):
        """创建新Mod架构管理标签页"""
        mods_frame = ttk.Frame(self.notebook)
        self.notebook.add(mods_frame, text="🎮 Mod管理")
        
        # 创建滚动区域
        canvas = tk.Canvas(mods_frame, bg=self.bg_color, highlightthickness=0)
        scrollbar = ttk.Scrollbar(mods_frame, orient="vertical", command=canvas.yview)
        scrollable_frame = tk.Frame(canvas, bg=self.bg_color)
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        # 绑定鼠标滚轮事件
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        canvas.bind("<MouseWheel>", _on_mousewheel)
        scrollable_frame.bind("<MouseWheel>", _on_mousewheel)
        
        # 显示Mod列表
        self.show_mods(scrollable_frame)
        
        # 打包滚动区域
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        # 创建状态栏
        status_frame = tk.Frame(mods_frame, bg=self.bg_color, height=25)
        status_frame.pack(fill=tk.X, side=tk.BOTTOM, pady=(10, 0))
        status_frame.pack_propagate(False)
        
        self.status_var = tk.StringVar()
        self.status_var.set("就绪 - 双击Mod可查看详情")
        status_label = tk.Label(status_frame, textvariable=self.status_var,
                               font=('Microsoft YaHei UI', 9),
                               bg=self.bg_color, fg='#95a5a6', anchor=tk.W)
        status_label.pack(fill=tk.X, padx=10, pady=5)
    
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
    
    def show_addons(self, parent):
        """显示插件列表"""
        # 扫描插件
        self.addon_manager.scan_addons()
        addons = self.addon_manager.get_all_addons()
        
        if not addons:
            return
        
        for addon in addons:
            addon_frame = tk.Frame(parent, bg=self.bg_color, relief='raised', borderwidth=1)
            addon_frame.pack(fill=tk.X, padx=10, pady=8, ipady=8, ipadx=8)
            
            # 插件头部（包含图标和标题）
            header_frame = tk.Frame(addon_frame, bg=self.bg_color)
            header_frame.pack(fill=tk.X, padx=15, pady=(5, 5))
            
            # 插件图标
            icon_path = os.path.join(addon['path'], 'icon.png')
            if os.path.exists(icon_path):
                try:
                    image = Image.open(icon_path)
                    image = image.resize((64, 64), Image.Resampling.LANCZOS)
                    icon = ImageTk.PhotoImage(image)
                    icon_label = tk.Label(header_frame, image=icon, bg=self.bg_color)
                    icon_label.image = icon  # type: ignore # 保存引用
                    icon_label.pack(side=tk.LEFT, padx=(0, 10))
                except:
                    pass
            
            # 插件标题和版本
            title_version_frame = tk.Frame(header_frame, bg=self.bg_color)
            title_version_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)
            
            # 插件标题
            addon_name = addon['info'].get('name', addon['name'])
            title_label = tk.Label(title_version_frame, 
                                 text=addon_name,
                                 font=('微软雅黑', 11, 'bold'),
                                 bg=self.bg_color, fg='white')
            title_label.pack(anchor=tk.W, pady=(0, 2))
            
            # 插件版本
            version = addon['info'].get('addon_version', '未知版本')
            version_label = tk.Label(title_version_frame, 
                                   text=f"版本: {version}",
                                   font=('微软雅黑', 9),
                                   bg=self.bg_color, fg='#95a5a6')
            version_label.pack(anchor=tk.W)
            
            # 插件描述
            description = addon['info'].get('desc', '无描述')
            desc_label = tk.Label(addon_frame, 
                                text=description,
                                font=('微软雅黑', 9),
                                bg=self.bg_color, fg='#bdc3c7',
                                wraplength=400, justify=tk.LEFT)
            desc_label.pack(anchor=tk.W, padx=15, pady=(0, 5))
            
            # 插件作者
            authors = addon['info'].get('authors', {})
            if authors:
                authors_frame = tk.Frame(addon_frame, bg=self.bg_color)
                authors_frame.pack(fill=tk.X, padx=15, pady=(0, 5))
                
                authors_label = tk.Label(authors_frame, 
                                       text="作者:",
                                       font=('微软雅黑', 9, 'bold'),
                                       bg=self.bg_color, fg='#ecf0f1')
                authors_label.pack(anchor=tk.W, pady=(0, 2))
                
                for author_name, author_url in authors.items():
                    author_frame = tk.Frame(authors_frame, bg=self.bg_color)
                    author_frame.pack(anchor=tk.W, pady=1)
                    
                    author_name_label = tk.Label(author_frame, 
                                               text=author_name,
                                               font=('微软雅黑', 9),
                                               bg=self.bg_color, fg='#3498db',
                                               cursor='hand2')
                    author_name_label.pack(side=tk.LEFT, padx=(0, 5))
                    author_name_label.bind('<Button-1>', lambda e, url=author_url: self.open_url(url))
                    
                    if author_url:
                        url_label = tk.Label(author_frame, 
                                           text=author_url,
                                           font=('微软雅黑', 8),
                                           bg=self.bg_color, fg='#95a5a6')
                        url_label.pack(side=tk.LEFT)
            
            # 插件设置
            settings = addon['info'].get('settings', {})
            if settings:
                settings_frame = tk.Frame(addon_frame, bg=self.lighten_bg_color, relief='groove', borderwidth=1)
                settings_frame.pack(fill=tk.X, padx=15, pady=5, ipady=5, ipadx=5)
                
                settings_label = tk.Label(settings_frame, 
                                        text="设置",
                                        font=('微软雅黑', 10, 'bold'),
                                        bg=self.lighten_bg_color, fg='white')
                settings_label.pack(anchor=tk.W, pady=(0, 8))
                
                for setting_key, setting_value in settings.items():
                    setting_row = tk.Frame(settings_frame, bg=self.lighten_bg_color)
                    setting_row.pack(fill=tk.X, pady=3)
                    
                    setting_name_label = tk.Label(setting_row, 
                                               text=setting_key,
                                               font=('微软雅黑', 9),
                                               bg=self.lighten_bg_color, fg='#ecf0f1',
                                               width=20, anchor=tk.W)
                    setting_name_label.pack(side=tk.LEFT, padx=5)
                    
                    if isinstance(setting_value, bool):
                        var = tk.BooleanVar(value=setting_value)
                        checkbox = tk.Checkbutton(setting_row, 
                                                variable=var,
                                                command=lambda a=addon, k=setting_key, v=var: self.on_addon_setting_change(a, k, v),
                                                font=('Microsoft YaHei UI', 10),
                                                bg=self.lighten_bg_color, fg='white',
                                                selectcolor='#3498db',
                                                activebackground=self.lighten_bg_color,
                                                activeforeground='white')
                        checkbox.pack(side=tk.LEFT, padx=5)
                    else:
                        entry = tk.Entry(setting_row, 
                                       font=('Microsoft YaHei UI', 10),
                                       width=30,
                                       bg=self.bg_color, fg='white',
                                       relief='flat', borderwidth=1)
                        entry.insert(0, setting_value)
                        entry.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
                        entry.bind('<KeyRelease>', lambda e, a=addon, k=setting_key, ent=entry: self.on_addon_setting_change(a, k, ent))
            
            # 操作按钮
            buttons_frame = tk.Frame(addon_frame, bg=self.bg_color)
            buttons_frame.pack(fill=tk.X, padx=15, pady=5)
            
            run_button = tk.Button(buttons_frame, 
                                 text="▶ 运行",
                                 command=lambda a=addon['name']: self.run_addon(a),
                                 font=('Microsoft YaHei UI', 9),
                                 bg='#3498db', fg='white',
                                 relief='flat', padx=10, pady=3)
            run_button.pack(side=tk.LEFT, padx=5)
            
            open_folder_button = tk.Button(buttons_frame, 
                                         text="📂 插件目录",
                                         command=lambda p=addon['path']: self.open_addon_folder(p),
                                         font=('Microsoft YaHei UI', 9),
                                         bg='#f39c12', fg='white',
                                         relief='flat', padx=10, pady=3)
            open_folder_button.pack(side=tk.LEFT, padx=5)
            
            delete_button = tk.Button(buttons_frame, 
                                    text="🗑️ 删除插件",
                                    command=lambda a=addon['name']: self.delete_addon(a),
                                    font=('Microsoft YaHei UI', 9),
                                    bg='#e74c3c', fg='white',
                                    relief='flat', padx=10, pady=3)
            delete_button.pack(side=tk.LEFT, padx=5)
    
    def on_addon_setting_change(self, addon, setting_key, value_var):
        """插件设置变更事件"""
        try:
            # 获取当前值
            if isinstance(value_var, tk.BooleanVar):
                new_value = value_var.get()
            elif isinstance(value_var, tk.Entry):
                new_value = value_var.get()
            else:
                return
            
            # 更新插件信息
            addon_info_path = os.path.join(addon['path'], 'addon_info.json')
            with open(addon_info_path, 'r', encoding='utf-8') as f:
                info = json.load(f)
            
            if 'settings' not in info:
                info['settings'] = {}
            
            info['settings'][setting_key] = new_value
            
            # 保存更新后的信息
            with open(addon_info_path, 'w', encoding='utf-8') as f:
                json.dump(info, f, indent=4, ensure_ascii=False)
            
            print(f"更新插件 {addon['name']} 的设置 {setting_key} 为 {new_value}")
        except Exception as e:
            print(f"更新插件设置失败: {e}")
            messagebox.showerror("错误", f"更新插件设置失败: {str(e)}")
    
    def run_addon(self, addon_name):
        """运行插件"""
        try:
            self.addon_manager.run_addon(addon_name)
            messagebox.showinfo("成功", f"插件 {addon_name} 已运行")
        except Exception as e:
            print(f"运行插件失败: {e}")
            messagebox.showerror("错误", f"运行插件失败: {str(e)}")
    
    def open_url(self, url):
        """打开URL"""
        import webbrowser
        webbrowser.open(url)
    
    def show_mods(self, parent):
        """显示新架构的Mod列表"""
        # 确保mods目录存在
        if not os.path.exists(self.mods_dir):
            os.makedirs(self.mods_dir)
            return
        
        # 获取所有mod
        mods = []
        for item in os.listdir(self.mods_dir):
            item_path = os.path.join(self.mods_dir, item)
            if os.path.isdir(item_path):
                mod_info_path = os.path.join(item_path, 'mod_info.json')
                if os.path.exists(mod_info_path):
                    try:
                        with open(mod_info_path, 'r', encoding='utf-8') as f:
                            info = json.load(f)
                        mods.append({
                            'name': item,
                            'path': item_path,
                            'info': info
                        })
                    except:
                        pass
        
        if not mods:
            return
        
        for mod in mods:
            mod_frame = tk.Frame(parent, bg=self.bg_color, relief='raised', borderwidth=1)
            mod_frame.pack(fill=tk.X, padx=10, pady=8, ipady=8, ipadx=8)
            
            # Mod头部（包含图标和标题）
            header_frame = tk.Frame(mod_frame, bg=self.bg_color)
            header_frame.pack(fill=tk.X, padx=15, pady=(5, 5))
            
            # Mod图标
            icon_path = os.path.join(mod['path'], 'icon.png')
            if os.path.exists(icon_path):
                try:
                    image = Image.open(icon_path)
                    image = image.resize((64, 64), Image.Resampling.LANCZOS)
                    icon = ImageTk.PhotoImage(image)
                    icon_label = tk.Label(header_frame, image=icon, bg=self.bg_color)
                    icon_label.image = icon  # type: ignore # 保存引用
                    icon_label.pack(side=tk.LEFT, padx=(0, 10))
                except:
                    pass
            
            # Mod标题和版本
            title_version_frame = tk.Frame(header_frame, bg=self.bg_color)
            title_version_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)
            
            # Mod标题
            mod_name = mod['info'].get('name', mod['name'])
            title_label = tk.Label(title_version_frame, 
                                 text=mod_name,
                                 font=('微软雅黑', 11, 'bold'),
                                 bg=self.bg_color, fg='white')
            title_label.pack(anchor=tk.W, pady=(0, 2))
            
            # Mod版本
            version = mod['info'].get('addon_version', '未知版本')
            version_label = tk.Label(title_version_frame, 
                                   text=f"版本: {version}",
                                   font=('微软雅黑', 9),
                                   bg=self.bg_color, fg='#95a5a6')
            version_label.pack(anchor=tk.W)
            
            # Mod描述
            description = mod['info'].get('desc', '无描述')
            desc_label = tk.Label(mod_frame, 
                                text=description,
                                font=('微软雅黑', 9),
                                bg=self.bg_color, fg='#bdc3c7',
                                wraplength=400, justify=tk.LEFT)
            desc_label.pack(anchor=tk.W, padx=15, pady=(0, 5))
            
            # Mod作者
            authors = mod['info'].get('authors', {})
            if authors:
                authors_frame = tk.Frame(mod_frame, bg=self.bg_color)
                authors_frame.pack(fill=tk.X, padx=15, pady=(0, 5))
                
                authors_label = tk.Label(authors_frame, 
                                       text="作者:",
                                       font=('微软雅黑', 9, 'bold'),
                                       bg=self.bg_color, fg='#ecf0f1')
                authors_label.pack(anchor=tk.W, pady=(0, 2))
                
                for author_name, author_url in authors.items():
                    author_frame = tk.Frame(authors_frame, bg=self.bg_color)
                    author_frame.pack(anchor=tk.W, pady=1)
                    
                    author_name_label = tk.Label(author_frame, 
                                               text=author_name,
                                               font=('微软雅黑', 9),
                                               bg=self.bg_color, fg='#3498db',
                                               cursor='hand2')
                    author_name_label.pack(side=tk.LEFT, padx=(0, 5))
                    author_name_label.bind('<Button-1>', lambda e, url=author_url: self.open_url(url))
                    
                    if author_url:
                        url_label = tk.Label(author_frame, 
                                           text=author_url,
                                           font=('微软雅黑', 8),
                                           bg=self.bg_color, fg='#95a5a6')
                        url_label.pack(side=tk.LEFT)
            
            # Mod文件
            file_names = mod['info'].get('file_names', [])
            if file_names:
                files_frame = tk.Frame(mod_frame, bg=self.bg_color)
                files_frame.pack(fill=tk.X, padx=15, pady=(0, 5))
                
                files_label = tk.Label(files_frame, 
                                     text="文件:",
                                     font=('微软雅黑', 9, 'bold'),
                                     bg=self.bg_color, fg='#ecf0f1')
                files_label.pack(anchor=tk.W, pady=(0, 2))
                
                for file_name in file_names:
                    file_label = tk.Label(files_frame, 
                                        text=f"  • {file_name}",
                                        font=('微软雅黑', 9),
                                        bg=self.bg_color, fg='#bdc3c7')
                    file_label.pack(anchor=tk.W)
            
            # Mod设置
            settings = mod['info'].get('settings', {})
            if settings:
                settings_frame = tk.Frame(mod_frame, bg=self.lighten_bg_color, relief='groove', borderwidth=1)
                settings_frame.pack(fill=tk.X, padx=15, pady=5, ipady=5, ipadx=5)
                
                settings_label = tk.Label(settings_frame, 
                                        text="设置",
                                        font=('微软雅黑', 10, 'bold'),
                                        bg=self.lighten_bg_color, fg='white')
                settings_label.pack(anchor=tk.W, pady=(0, 8))
                
                for setting_key, setting_value in settings.items():
                    setting_row = tk.Frame(settings_frame, bg=self.lighten_bg_color)
                    setting_row.pack(fill=tk.X, pady=3)
                    
                    setting_name_label = tk.Label(setting_row, 
                                               text=setting_key,
                                               font=('微软雅黑', 9),
                                               bg=self.lighten_bg_color, fg='#ecf0f1',
                                               width=20, anchor=tk.W)
                    setting_name_label.pack(side=tk.LEFT, padx=5)
                    
                    if isinstance(setting_value, bool):
                        var = tk.BooleanVar(value=setting_value)
                        checkbox = tk.Checkbutton(setting_row, 
                                                variable=var,
                                                command=lambda m=mod, k=setting_key, v=var: self.on_mod_setting_change(m, k, v),
                                                font=('Microsoft YaHei UI', 10),
                                                bg=self.lighten_bg_color, fg='white',
                                                selectcolor='#3498db',
                                                activebackground=self.lighten_bg_color,
                                                activeforeground='white')
                        checkbox.pack(side=tk.LEFT, padx=5)
                    else:
                        entry = tk.Entry(setting_row, 
                                       font=('Microsoft YaHei UI', 10),
                                       width=30,
                                       bg=self.bg_color, fg='white',
                                       relief='flat', borderwidth=1)
                        entry.insert(0, setting_value)
                        entry.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
                        entry.bind('<KeyRelease>', lambda e, m=mod, k=setting_key, ent=entry: self.on_mod_setting_change(m, k, ent))
            
            # 操作按钮
            buttons_frame = tk.Frame(mod_frame, bg=self.bg_color)
            buttons_frame.pack(fill=tk.X, padx=15, pady=5)
            
            open_folder_button = tk.Button(buttons_frame, 
                                         text="📂 打开文件夹",
                                         command=lambda p=mod['path']: self.open_addon_folder(p),
                                         font=('Microsoft YaHei UI', 9),
                                         bg='#f39c12', fg='white',
                                         relief='flat', padx=10, pady=3)
            open_folder_button.pack(side=tk.LEFT, padx=5)
            
            delete_button = tk.Button(buttons_frame, 
                                    text="🗑️ 删除Mod",
                                    command=lambda m=mod['name']: self.delete_mod(m),
                                    font=('Microsoft YaHei UI', 9),
                                    bg='#e74c3c', fg='white',
                                    relief='flat', padx=10, pady=3)
            delete_button.pack(side=tk.LEFT, padx=5)
    
    def on_mod_setting_change(self, mod, setting_key, value_var):
        """Mod设置变更事件"""
        try:
            # 获取当前值
            if isinstance(value_var, tk.BooleanVar):
                new_value = value_var.get()
            elif isinstance(value_var, tk.Entry):
                new_value = value_var.get()
            else:
                return
            
            # 更新Mod信息
            mod_info_path = os.path.join(mod['path'], 'mod_info.json')
            with open(mod_info_path, 'r', encoding='utf-8') as f:
                info = json.load(f)
            
            if 'settings' not in info:
                info['settings'] = {}
            
            info['settings'][setting_key] = new_value
            
            # 保存更新后的信息
            with open(mod_info_path, 'w', encoding='utf-8') as f:
                json.dump(info, f, indent=4, ensure_ascii=False)
            
            print(f"更新Mod {mod['name']} 的设置 {setting_key} 为 {new_value}")
        except Exception as e:
            print(f"更新Mod设置失败: {e}")
            messagebox.showerror("错误", f"更新Mod设置失败: {str(e)}")
    
    def delete_mod(self, mod_name):
        """删除Mod"""
        mod_path = os.path.join(self.mods_dir, mod_name)
        if os.path.exists(mod_path):
            if messagebox.askyesno("确认删除", f"确定要删除Mod {mod_name} 吗？"):
                try:
                    import shutil
                    shutil.rmtree(mod_path)
                    # 刷新Mod列表
                    self.refresh_mods_tab()
                except Exception as e:
                    messagebox.showerror("错误", f"删除Mod失败: {str(e)}")
    
    def refresh_mods_tab(self):
        """刷新Mod标签页"""
        # 获取Mod标签页
        mods_tab = self.notebook.nametowidget(self.notebook.tabs()[1])
        
        # 清空所有子控件
        for widget in mods_tab.winfo_children():
            widget.destroy()
        
        # 重新创建滚动区域
        canvas = tk.Canvas(mods_tab, bg=self.bg_color, highlightthickness=0)
        scrollbar = ttk.Scrollbar(mods_tab, orient="vertical", command=canvas.yview)
        scrollable_frame = tk.Frame(canvas, bg=self.bg_color)
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        # 绑定鼠标滚轮事件
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        canvas.bind("<MouseWheel>", _on_mousewheel)
        scrollable_frame.bind("<MouseWheel>", _on_mousewheel)
        
        # 显示Mod列表
        self.show_mods(scrollable_frame)
        
        # 打包滚动区域
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        # 重新创建状态栏
        status_frame = tk.Frame(mods_tab, bg=self.bg_color, height=25)
        status_frame.pack(fill=tk.X, side=tk.BOTTOM, pady=(10, 0))
        status_frame.pack_propagate(False)
        
        self.status_var = tk.StringVar()
        self.status_var.set("就绪 - 双击Mod可查看详情")
        status_label = tk.Label(status_frame, textvariable=self.status_var,
                               font=('Microsoft YaHei UI', 9),
                               bg=self.bg_color, fg='#95a5a6', anchor=tk.W)
        status_label.pack(fill=tk.X, padx=10, pady=5)
    
    def open_addon_folder(self, path):
        """打开插件文件夹"""
        if os.path.exists(path):
            os.startfile(path)
        else:
            messagebox.showinfo("信息", "插件文件夹不存在")
    
    def delete_addon(self, addon_name):
        """删除插件"""
        if messagebox.askyesno("确认删除", f"确定要删除插件 {addon_name} 吗？"):
            if self.addon_manager.remove_addon(addon_name):
                # 刷新插件列表
                self.refresh_addons_tab()
            else:
                messagebox.showerror("错误", f"删除插件 {addon_name} 失败")
    
    def refresh_addons_tab(self):
        """刷新插件标签页"""
        # 清空插件标签页
        addons_tab = self.notebook.nametowidget(self.notebook.tabs()[0])
        for widget in addons_tab.winfo_children():
            widget.destroy()
        
        # 重新创建插件标签页内容
        # 创建滚动区域
        canvas = tk.Canvas(addons_tab, bg=self.bg_color, highlightthickness=0)
        scrollbar = ttk.Scrollbar(addons_tab, orient="vertical", command=canvas.yview)
        scrollable_frame = tk.Frame(canvas, bg=self.bg_color)
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        # 绑定鼠标滚轮事件
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        canvas.bind("<MouseWheel>", _on_mousewheel)
        scrollable_frame.bind("<MouseWheel>", _on_mousewheel)
        
        # 显示插件列表
        self.show_addons(scrollable_frame)
        
        # 打包滚动区域
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

    def refresh_all_tabs(self):
        """刷新所有标签页"""
        self.refresh_addons_tab()
        self.refresh_mods_tab()

def init_mod_addon_manager(parent_frame, bg_color, lighten_bg_color):
    """初始化插件&mod管理器页面"""
    return ModAddonManagerPage(parent_frame, bg_color, lighten_bg_color)