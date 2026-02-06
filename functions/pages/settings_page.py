import tkinter as tk
from tkinter import ttk, filedialog, messagebox, colorchooser
from functions.settings_manager import get_settings_manager

class SettingsPage:
    def __init__(self, parent_frame, bg_color, lighten_bg_color):
        """初始化设置页面"""
        self.parent = parent_frame
        self.settings_manager = get_settings_manager()
        self.setting_widgets = {}
        self.bg_color = bg_color
        self.lighten_bg_color = lighten_bg_color
        self.create_widgets()
        self.auto_refresh()
    
    def create_widgets(self):
        """创建设置页面控件"""
        
        # 创建设置内容容器, 居中显示
        content_frame = tk.Frame(self.parent, bg=self.lighten_bg_color, relief='groove', borderwidth=3)
        content_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)
        
        # 创建标签页控件
        self.notebook = ttk.Notebook(content_frame)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        # 按page分组设置项
        settings_by_page = self.group_settings_by_page()
        
        # 为每个page创建标签页
        page_names = list(settings_by_page.keys())

        for page_name in page_names:
            page_frame = ttk.Frame(self.notebook)
            self.notebook.add(page_frame, text=page_name)
            
            # 创建滚动区域
            self.create_scrollable_settings_area(page_frame, settings_by_page[page_name])
        
        # 创建操作按钮区域
        button_frame = tk.Frame(content_frame, bg=self.lighten_bg_color)
        button_frame.pack(fill=tk.X, pady=5, padx=10)
        
        # 重置所有按钮
        reset_all_btn = tk.Button(button_frame, text="↺ 重置所有设置",
                                command=self.reset_all_settings,
                                font=('Microsoft YaHei UI', 11, 'bold'),
                                bg='#e67e22', fg='white',
                                relief='raised', borderwidth=2,
                                padx=20, pady=5)
        reset_all_btn.pack(anchor=tk.CENTER, padx=10)
    
    def group_settings_by_page(self):
        """按page分组设置项"""
        settings = self.settings_manager.get_all_settings()
        settings_by_page = {}
        
        for key, setting_info in settings.items():
            if setting_info.get('type') == 'UNABLE_TO_EDIT':
                continue  # 跳过无法编辑的设置项
                
            page = setting_info.get('page', '通用')  # 默认页面为通用
            if page not in settings_by_page:
                settings_by_page[page] = []
            settings_by_page[page].append((key, setting_info))
        
        return settings_by_page
    
    def create_scrollable_settings_area(self, parent, settings_list):
        """创建可滚动的设置区域"""
        # 创建滚动框架
        canvas = tk.Canvas(parent, bg=self.bg_color, highlightthickness=0)
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        scrollable_frame = tk.Frame(canvas, bg=self.bg_color)
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        # 动态生成设置控件
        self.create_settings_controls(scrollable_frame, settings_list)
        
        # 打包滚动区域
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        # 绑定鼠标滚轮事件
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        canvas.bind("<MouseWheel>", _on_mousewheel)
        scrollable_frame.bind("<MouseWheel>", _on_mousewheel)
    
    def create_settings_controls(self, parent, settings_list):
        """动态生成设置控件"""
        for i, (key, setting_info) in enumerate(settings_list):
            setting_type = setting_info.get('type', 'UNABLE_TO_EDIT')

            if setting_type == 'UNABLE_TO_EDIT':
                continue  # 跳过无法编辑的设置项

            # 创建设置项框架
            setting_frame = tk.Frame(parent, bg=self.bg_color, relief='raised', borderwidth=1)
            setting_frame.pack(fill=tk.X, padx=10, pady=8, ipady=8, ipadx=8)
            
            # 设置项标题和描述
            # 优先使用name字段，然后使用description字段，最后使用key
            setting_name = setting_info.get('name', setting_info.get('description', key))
            title_label = tk.Label(setting_frame, 
                                 text=setting_name,
                                 font=('微软雅黑', 11, 'bold'),
                                 bg=self.bg_color, fg='white')
            title_label.pack(anchor=tk.W, padx=15, pady=(5, 2))
            
            # 添加描述文本（如果description存在且与name不同）
            if 'description' in setting_info and setting_info['description'] != setting_name:
                desc_label = tk.Label(setting_frame, 
                                    text=setting_info['description'],
                                    font=('微软雅黑', 9),
                                    bg=self.bg_color, fg='#bdc3c7',
                                    wraplength=400, justify=tk.LEFT)
                desc_label.pack(anchor=tk.W, padx=15, pady=(0, 5))
            
            # 根据类型创建不同的控件
            current_value = self.settings_manager.get_setting(key)
            
            if setting_type == 'boolean':
                self.create_boolean_control(setting_frame, key, setting_info, current_value)
            elif setting_type == 'string':
                self.create_string_control(setting_frame, key, setting_info, current_value)
            elif setting_type in ['integer', 'float']:
                self.create_numeric_control(setting_frame, key, setting_info, current_value)
            elif setting_type == 'color':
                self.create_color_control(setting_frame, key, setting_info, current_value)
            elif setting_type == 'combobox':
                self.create_combobox_control(setting_frame, key, setting_info, current_value)
            
            # 添加重置按钮
            reset_btn = tk.Button(setting_frame, text="↺ 重置",
                                 command=lambda k=key: self.reset_setting(k),
                                 font=('Microsoft YaHei UI', 8),
                                 bg='#f39c12', fg='white',
                                 relief='flat', padx=8, pady=2)
            reset_btn.pack(anchor=tk.E, padx=15, pady=5)

    def create_combobox_control(self, parent, key, setting_info, current_value):
        """创建下拉框控件"""
        # 创建控件框架
        control_frame = tk.Frame(parent, bg=self.bg_color)
        control_frame.pack(fill=tk.X, padx=15, pady=5)
        
        # 获取选项列表
        options = setting_info.get('options', [])
        
        # 创建下拉框
        combobox = ttk.Combobox(control_frame,
                               values=options,
                               font=('Microsoft YaHei UI', 10),
                               state='readonly',
                               width=40)
        
        # 设置当前值
        if 0 <= current_value < len(options):
            combobox.set(options[current_value])
        else:
            combobox.set(options[0] if options else "")
        
        # 绑定选择事件
        combobox.bind('<<ComboboxSelected>>', lambda e, k=key, cb=combobox, opts=options: self.on_combobox_change(k, cb, opts))
        
        combobox.pack(fill=tk.X, expand=True)
        
        self.setting_widgets[key] = combobox

    def on_combobox_change(self, key, combobox, options):
        """下拉框改变事件"""
        selected_text = combobox.get()
        selected_index = options.index(selected_text) if selected_text in options else 0
        self.settings_manager.set_setting(key, selected_index)
    
    def create_boolean_control(self, parent, key, setting_info, current_value):
        """创建布尔值控件"""
        var = tk.BooleanVar(value=current_value)
        # 使用name字段作为复选框文本，如果没有name则使用description
        checkbox_text = setting_info.get('name', setting_info.get('description', key))
        
        # 创建控件框架
        control_frame = tk.Frame(parent, bg=self.bg_color)
        control_frame.pack(fill=tk.X, padx=15, pady=5)
        
        checkbox = tk.Checkbutton(control_frame, 
                                text=checkbox_text,
                                variable=var,
                                command=lambda: self.on_boolean_change(key, var),
                                font=('Microsoft YaHei UI', 10),
                                bg=self.bg_color, fg='white',
                                selectcolor='#3498db',
                                activebackground=self.bg_color,
                                activeforeground='white')
        checkbox.pack(anchor=tk.W)
        
        self.setting_widgets[key] = var
    
    def create_string_control(self, parent, key, setting_info, current_value):
        """创建字符串控件"""
        # 创建控件框架
        control_frame = tk.Frame(parent, bg=self.bg_color)
        control_frame.pack(fill=tk.X, padx=15, pady=5)
        
        if key == 'game_path':
            # 游戏路径特殊处理，添加浏览按钮
            entry = tk.Entry(control_frame, 
                           font=('Microsoft YaHei UI', 10),
                           width=40)
            entry.insert(0, current_value)
            entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
            
            browse_btn = tk.Button(control_frame, text="浏览",
                                 command=lambda: self.browse_game_path(entry),
                                 font=('Microsoft YaHei UI', 9),
                                 bg='#3498db', fg='white',
                                 relief='flat', padx=10)
            browse_btn.pack(side=tk.RIGHT)
        else:
            entry = tk.Entry(control_frame, 
                           font=('Microsoft YaHei UI', 10),
                           width=50)
            entry.insert(0, current_value)
            entry.pack(fill=tk.X, expand=True)
            entry.bind('<KeyRelease>', lambda e, k=key: self.on_string_change(k, entry))
        
        self.setting_widgets[key] = entry
    
    def create_numeric_control(self, parent, key, setting_info, current_value):
        """创建数值控件"""
        # 创建控件框架
        control_frame = tk.Frame(parent, bg=self.bg_color)
        control_frame.pack(fill=tk.X, padx=15, pady=5)
        
        # 标签显示当前值
        value_label = tk.Label(control_frame, 
                             text=f"当前值: {current_value}",
                             font=('Microsoft YaHei UI', 9),
                             bg=self.bg_color, fg='#bdc3c7')
        value_label.pack(side=tk.LEFT, padx=(0, 10))
        
        # 滑动条
        min_val = setting_info.get('min', 0)
        max_val = setting_info.get('max', 100)
        step = setting_info.get('step', 1)
        
        scale = tk.Scale(control_frame,
                        from_=min_val, to=max_val,
                        resolution=step,
                        orient=tk.HORIZONTAL,
                        length=200,
                        showvalue=False,
                        command=lambda v, k=key, l=value_label: self.on_scale_change(k, v, l),
                        bg=self.bg_color, fg='white',
                        troughcolor=self.bg_color,
                        highlightbackground=self.bg_color)
        scale.set(current_value)
        scale.pack(side=tk.RIGHT, fill=tk.X, expand=True)
        
        self.setting_widgets[key] = scale
    
    def create_color_control(self, parent, key, setting_info, current_value):
        """创建颜色选择控件"""
        # 创建控件框架
        control_frame = tk.Frame(parent, bg=self.bg_color)
        control_frame.pack(fill=tk.X, padx=15, pady=5)
        
        # 颜色显示
        color_frame = tk.Frame(control_frame, bg=current_value, width=50, height=30, relief='sunken', borderwidth=2)
        color_frame.pack(side=tk.LEFT, padx=(0, 10))
        
        # 颜色值文本框
        color_entry = tk.Entry(control_frame, font=('Microsoft YaHei UI', 10), width=10)
        color_entry.insert(0, current_value)
        color_entry.pack(side=tk.LEFT, padx=(0, 5))
        color_entry.bind('<KeyRelease>', lambda e, k=key, ce=color_entry, cf=color_frame: self.on_color_entry_change(k, ce, cf))
        
        # 颜色选择按钮
        color_btn = tk.Button(control_frame, text="选择颜色",
                            command=lambda k=key, ce=color_entry, cf=color_frame: self.on_color_button_click(k, ce, cf),
                            font=('Microsoft YaHei UI', 9),
                            bg='#3498db', fg='white',
                            relief='flat', padx=8)
        color_btn.pack(side=tk.LEFT)
        
        self.setting_widgets[key] = color_entry
    
    def on_boolean_change(self, key, var):
        """布尔值改变事件"""
        self.settings_manager.set_setting(key, var.get())
    
    def on_string_change(self, key, entry):
        """字符串改变事件"""
        self.settings_manager.set_setting(key, entry.get())
    
    def on_scale_change(self, key, value, value_label):
        """滑动条改变事件"""
        value = float(value)
        self.settings_manager.set_setting(key, value)
        value_label.config(text=f"当前值: {value:.1f}")
    
    def on_color_entry_change(self, key, entry, color_frame):
        """颜色文本框改变事件"""
        color_value = entry.get()
        # 验证颜色格式
        try:
            # 尝试设置颜色
            color_frame.config(bg=color_value)
            self.settings_manager.set_setting(key, color_value)
        except:
            pass  # 忽略无效颜色
    
    def on_color_button_click(self, key, entry, color_frame):
        """颜色选择按钮点击事件"""
        current_color = entry.get()
        color = colorchooser.askcolor(initialcolor=current_color)[1]
        if color:
            entry.delete(0, tk.END)
            entry.insert(0, color)
            color_frame.config(bg=color)
            self.settings_manager.set_setting(key, color)
    
    def browse_game_path(self, entry):
        """浏览游戏路径"""
        path = filedialog.askopenfilename(title="选择边狱巴士主程序", filetypes=[("边狱巴士主程序", "LimbusCompany.exe")])
        path = path.replace('LimbusCompany.exe', '')
        if path:
            entry.delete(0, tk.END)
            entry.insert(0, path)
            self.settings_manager.set_setting('game_path', path)
    
    def reset_setting(self, key):
        """重置单个设置项"""
        setting_info = self.settings_manager.get_setting_info(key)
        setting_name = setting_info.get('name', setting_info.get('description', key)) if setting_info else key
        
        if self.settings_manager.reset_setting(key):
            self.save_all_settings()
            self.refresh_all_displays()
            messagebox.showinfo("成功", f"已重置设置项: {setting_name}")
    
    def reset_all_settings(self):
        """重置所有设置"""
        if messagebox.askyesno("确认", "确定要重置所有设置为默认值吗？\n\n这将使用当前值更新默认值。"):
            self.settings_manager.reset_all_settings()
            self.save_all_settings()
            self.refresh_all_displays()
            messagebox.showinfo("成功", "已重置所有设置")
    
    def save_all_settings(self):
        """保存所有设置"""
        if self.settings_manager.save_settings():
            pass
        else:
            messagebox.showerror("错误", "保存设置失败")
    
    def refresh_setting_display(self, key):
        """刷新单个设置项的显示"""
        current_value = self.settings_manager.get_setting(key)
        setting_info = self.settings_manager.get_setting_info(key)
        
        if key in self.setting_widgets:
            widget = self.setting_widgets[key]
            setting_type = setting_info.get('type', 'string') # type: ignore
            
            if setting_type == 'boolean':
                widget.set(current_value)
            elif setting_type == 'string':
                if isinstance(widget, tk.Entry):
                    widget.delete(0, tk.END)
                    widget.insert(0, current_value) # type: ignore
            elif setting_type in ['integer', 'float']:
                widget.set(current_value)
            elif setting_type == 'color':
                if isinstance(widget, tk.Entry):
                    widget.delete(0, tk.END)
                    widget.insert(0, current_value) # type: ignore
                    # 更新颜色显示
                    color_frame = widget.master.winfo_children()[0]
                    if hasattr(color_frame, 'config'):
                        try:
                            color_frame.config(bg=current_value) # type: ignore
                        except:
                            pass
            elif setting_type == 'combobox':
                if isinstance(widget, ttk.Combobox):
                    options = setting_info.get('options', []) # type: ignore
                    if 0 <= current_value < len(options): # type: ignore
                        widget.set(options[current_value])
                    else:
                        widget.set(options[0] if options else "")
    
    def refresh_all_displays(self):
        """刷新所有设置项的显示"""
        for key in self.settings_manager.get_all_settings():
            self.refresh_setting_display(key)

    def auto_refresh(self):
        """自动刷新所有设置项的显示"""
        self.save_all_settings()
        self.parent.after(1000, self.auto_refresh)  # 每1秒刷新一次

def init_settings_page(parent_frame, bg_color:str, lighten_bg_color:str) -> SettingsPage:
    """初始化设置页面"""
    return SettingsPage(parent_frame, bg_color, lighten_bg_color)