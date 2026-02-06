import tkinter as tk
from tkinter import ttk, messagebox
import os
import json
import re
from threading import Thread
from functions.window_ulits import center_window

class CustomTranslationTool:
    """自定义汉化工具类"""
    
    def __init__(self, root, parent_window):
        self.root = root
        self.parent_window = parent_window
        self.current_file = None
        self.original_data = {}
        self.changes = {}
        self.changes_file = "workshop/changes.json"
        self.workshop_dir = "workshop"
        self.undo_stack = []  # 撤销栈
        self.redo_stack = []  # 重做栈
        self.current_content = ""  # 当前编辑内容

        self.parent_window = tk.Toplevel(self.parent_window)
        self.parent_window.withdraw()
        self.parent_window.geometry("900x600")
        center_window(self.parent_window, False)

        self.parent_window.title("🔧 自定义汉化工具")
        
        # 设置窗口图标
        try:
            if os.path.exists("assets/images/icon/icon.ico"):
                self.parent_window.iconbitmap("assets/images/icon/icon.ico")
        except:
            pass

        # 确保workshop目录存在
        os.makedirs(self.workshop_dir, exist_ok=True)

        
        # 确保changes.json文件存在
        self.ensure_changes_file()
        
        # 初始化界面
        self.init_ui()
        
        # 加载现有的修改记录
        # self.load_existing_changes()
        
        # 刷新文件树
        self.refresh_file_tree()

        self.cycle_update()
    
    def ensure_changes_file(self):
        """确保changes.json文件存在"""
        os.makedirs(os.path.dirname(self.changes_file), exist_ok=True)
        if not os.path.exists(self.changes_file):
            with open(self.changes_file, 'w', encoding='utf-8') as f:
                json.dump({}, f, ensure_ascii=False, indent=4)
    
    def load_existing_changes(self):
        """加载现有的修改记录"""
        try:
            with open(self.changes_file, 'r', encoding='utf-8') as f:
                self.changes = json.load(f)
        except Exception as e:
            print(f"加载修改记录失败: {e}")
            self.changes = {}
    
    def init_ui(self):
        """初始化用户界面"""
        # 创建主容器 - 使用parent_window作为父容器
        main_container = tk.Frame(self.parent_window, bg=self.root.bg_color)
        main_container.pack(fill=tk.BOTH, expand=True)

        # 创建左右分栏容器
        split_frame = tk.Frame(main_container, bg=self.root.bg_color)
        split_frame.pack(fill=tk.BOTH, expand=True)
        
        # 左侧文件树区域
        left_frame = tk.Frame(split_frame, bg=self.root.lighten_bg_color, relief='raised', borderwidth=1)
        left_frame.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 5))
        left_frame.pack_propagate(False)
        left_frame.configure(width=300)
        
        # 左侧标题
        left_title = tk.Label(left_frame, text="📁 文件树", 
                             bg=self.root.lighten_bg_color, fg='white', 
                             font=('Microsoft YaHei UI', 11, 'bold'))
        left_title.pack(pady=10)
        
        # 搜索框和刷新按钮在同一行
        search_refresh_frame = tk.Frame(left_frame, bg=self.root.lighten_bg_color)
        search_refresh_frame.pack(fill=tk.X, padx=10, pady=5)
        
        # 搜索框
        search_label = tk.Label(search_refresh_frame, text="🔍 搜索:", 
                               bg=self.root.lighten_bg_color, fg='white',
                               font=('Microsoft YaHei UI', 9))
        search_label.pack(side=tk.LEFT)
        
        self.search_var = tk.StringVar()
        self.search_entry = tk.Entry(search_refresh_frame, textvariable=self.search_var,
                                    bg='#1e1e1e', fg='white', insertbackground='white',
                                    width=15)
        self.search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(5, 5))
        self.search_entry.bind('<KeyRelease>', self.on_search_changed)
        
        # 紧凑的刷新按钮
        refresh_btn = tk.Button(search_refresh_frame, text="↻",
                               command=self.refresh_file_tree,
                               bg='#3498db', fg='white',
                               font=('Microsoft YaHei UI', 9),
                               relief='flat', width=3)
        refresh_btn.pack(side=tk.RIGHT)
        
        # 文件树容器
        tree_frame = tk.Frame(left_frame, bg=self.root.lighten_bg_color)
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        # 文件树滚动条
        tree_scrollbar = ttk.Scrollbar(tree_frame)
        tree_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # 文件树
        self.file_tree = ttk.Treeview(tree_frame, 
                                     yscrollcommand=tree_scrollbar.set,
                                     selectmode='browse')
        self.file_tree.pack(fill=tk.BOTH, expand=True)
        
        # 绑定事件 - 修复：添加双击事件绑定
        self.file_tree.bind('<<TreeviewSelect>>', self.on_tree_selected)
        self.file_tree.bind('<Double-1>', self.on_tree_double_click)  # 添加双击事件
        
        tree_scrollbar.config(command=self.file_tree.yview)
        
        # 配置树形样式
        style = ttk.Style()
        style.configure("Treeview", 
                        background="#1e1e1e", 
                        foreground="white", 
                        fieldbackground="#1e1e1e")
        style.configure("Treeview.Heading", 
                        background=self.root.lighten_bg_color, 
                        foreground="white")
        
        # 右侧编辑区域
        right_frame = tk.Frame(split_frame, bg=self.root.lighten_bg_color, relief='raised', borderwidth=1)
        right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        
        # 右侧标题和工具栏
        toolbar_frame = tk.Frame(right_frame, bg=self.root.lighten_bg_color)
        toolbar_frame.pack(fill=tk.X, padx=10, pady=10)
        
        right_title = tk.Label(toolbar_frame, text="📝 编辑区域", 
                              bg=self.root.lighten_bg_color, fg='white',
                              font=('Microsoft YaHei UI', 11, 'bold'))
        right_title.pack(side=tk.LEFT)
        
        # 跳转工具栏
        jump_frame = tk.Frame(toolbar_frame, bg=self.root.lighten_bg_color)
        jump_frame.pack(side=tk.RIGHT)
        
        jump_label = tk.Label(jump_frame, text="跳转到行:", 
                             bg=self.root.lighten_bg_color, fg='white',
                             font=('Microsoft YaHei UI', 9))
        jump_label.pack(side=tk.LEFT, padx=(0, 5))
        
        self.line_var = tk.StringVar()
        self.line_entry = tk.Entry(jump_frame, textvariable=self.line_var,
                                  bg='#1e1e1e', fg='white', insertbackground='white',
                                  width=8)
        self.line_entry.pack(side=tk.LEFT, padx=(0, 5))
        self.line_entry.bind('<Return>', self.jump_to_line)
        
        jump_btn = tk.Button(jump_frame, text="跳转",
                            command=self.jump_to_line,
                            bg='#3498db', fg='white',
                            font=('Microsoft YaHei UI', 8),
                            relief='flat', padx=5)
        jump_btn.pack(side=tk.LEFT)
        
        # 搜索工具栏
        search_tool_frame = tk.Frame(toolbar_frame, bg='#2c3e50')
        search_tool_frame.pack(side=tk.RIGHT, padx=20)
        
        search_tool_label = tk.Label(search_tool_frame, text="查找:", 
                                    bg=self.root.lighten_bg_color, fg='white',
                                    font=('Microsoft YaHei UI', 9))
        search_tool_label.pack(side=tk.LEFT, padx=(0, 5))
        
        self.search_text_var = tk.StringVar()
        self.search_text_entry = tk.Entry(search_tool_frame, textvariable=self.search_text_var,
                                         bg='#1e1e1e', fg='white', insertbackground='white',
                                         width=15)
        self.search_text_entry.pack(side=tk.LEFT, padx=(0, 5))
        self.search_text_entry.bind('<Return>', self.find_text)
        
        find_btn = tk.Button(search_tool_frame, text="查找",
                            command=self.find_text,
                            bg='#3498db', fg='white',
                            font=('Microsoft YaHei UI', 8),
                            relief='flat', padx=5)
        find_btn.pack(side=tk.LEFT)
        
        # 当前文件路径显示
        self.current_file_label = tk.Label(right_frame, 
                                          text="未选择文件",
                                          bg=self.root.lighten_bg_color, fg='#95a5a6',
                                          font=('Microsoft YaHei UI', 9),
                                          justify=tk.LEFT)
        self.current_file_label.pack(pady=5, padx=10, anchor=tk.W)
        
        # 编辑容器
        edit_container = tk.Frame(right_frame, bg=self.root.lighten_bg_color)
        edit_container.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        # 创建行号框架
        line_frame = tk.Frame(edit_container, bg='#1e1e1e')
        line_frame.pack(fill=tk.BOTH, expand=True)
        
        # 行号文本框
        self.line_numbers = tk.Text(line_frame, 
                                   width=4, 
                                   bg=self.root.lighten_bg_color, 
                                   fg='#95a5a6',
                                   font=('Consolas', 10),
                                   state='disabled',
                                   padx=5, 
                                   pady=5)
        self.line_numbers.pack(side=tk.LEFT, fill=tk.Y)
        
        # JSON编辑区域
        edit_frame = tk.Frame(line_frame, bg='#1e1e1e')
        edit_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        # 滚动条
        edit_scrollbar = ttk.Scrollbar(edit_frame)
        edit_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # 文本编辑框
        self.json_text = tk.Text(edit_frame,
                                bg='#1e1e1e', fg='white',
                                font=('Consolas', 10),
                                yscrollcommand=self.on_text_scroll,
                                wrap=tk.NONE,
                                undo=True)
        self.json_text.pack(fill=tk.BOTH, expand=True)
        
        # 启用撤销/重做
        self.json_text.bind('<Control-z>', self.undo)
        self.json_text.bind('<Control-y>', self.redo)
        self.json_text.bind('<Control-Z>', self.undo)
        self.json_text.bind('<Control-Y>', self.redo)
        self.json_text.bind('<KeyRelease>', self.on_text_change)
        
        edit_scrollbar.config(command=self.on_scrollbar_move)
        
        # 操作按钮区域
        button_frame = tk.Frame(right_frame, bg=self.root.lighten_bg_color)
        button_frame.pack(pady=10)
        
        # 撤销按钮
        undo_btn = tk.Button(button_frame, text="↶ 撤销 (Ctrl+Z)",
                            command=self.undo,
                            bg='#f39c12', fg='white',
                            font=('Microsoft YaHei UI', 9),
                            relief='flat', padx=10, pady=5)
        undo_btn.pack(side=tk.LEFT, padx=5)
        
        # 重做按钮
        redo_btn = tk.Button(button_frame, text="↷ 重做 (Ctrl+Y)",
                            command=self.redo,
                            bg='#f39c12', fg='white',
                            font=('Microsoft YaHei UI', 9),
                            relief='flat', padx=10, pady=5)
        redo_btn.pack(side=tk.LEFT, padx=5)
        
        # 保存按钮
        save_btn = tk.Button(button_frame, text="💾 保存修改",
                            command=self.save_json_changes,
                            bg='#27ae60', fg='white',
                            font=('Microsoft YaHei UI', 10, 'bold'),
                            relief='flat', padx=15, pady=8)
        save_btn.pack(side=tk.LEFT, padx=5)
        
        # 重置按钮
        reset_btn = tk.Button(button_frame, text="🔄 重置编辑",
                             command=self.reset_json_edits,
                             bg='#e74c3c', fg='white',
                             font=('Microsoft YaHei UI', 10, 'bold'),
                             relief='flat', padx=15, pady=8)
        reset_btn.pack(side=tk.LEFT, padx=5)
        
        # 状态标签
        self.status_label = tk.Label(right_frame, 
                                    text="就绪",
                                    bg=self.root.lighten_bg_color, fg='#95a5a6',
                                    font=('Microsoft YaHei UI', 9))
        self.status_label.pack(pady=5)
    
    def refresh_file_tree(self):
        """刷新文件树"""
        print("开始刷新文件树...")
        
        # 检查workshop目录是否存在
        if not os.path.exists(self.workshop_dir):
            messagebox.showerror("错误", f"workshop目录不存在: {self.workshop_dir}")
            return
        
        # 清空树形结构
        for item in self.file_tree.get_children():
            self.file_tree.delete(item)
        
        # 添加根节点
        root_node = self.file_tree.insert('', 'end', text="workshop", values=("workshop", True))
        print("添加根节点: workshop")
        
        # 递归构建文件树
        from threading import Thread
        Thread(target=self.build_tree, args=(root_node, self.workshop_dir)).start()
        
        # 展开根节点
        self.file_tree.item(root_node, open=True)
        
        self.status_label.config(text="文件树已刷新")
        print("文件树刷新完成")
    
    def build_tree(self, parent, path):
        """递归构建文件树"""
        self.parent_window.withdraw()
        self.parent_window.after(1000, self.parent_window.deiconify)

        try:
            items = os.listdir(path)
            print(f"扫描目录 {path}, 找到 {len(items)} 个项目")
            
            # 先按字母顺序排序
            items.sort(key=lambda x: x.lower())
            
            # 先添加目录，再添加文件
            dirs = []
            files = []
            
            for item in items:
                item_path = os.path.join(path, item)
                if os.path.isdir(item_path):
                    dirs.append(item)
                elif item.lower().endswith('.json') and item != 'changes.json':
                    files.append(item)
            
            # 添加目录
            for dir_name in dirs:
                dir_path = os.path.join(path, dir_name)
                relative_path = os.path.relpath(dir_path, self.workshop_dir)
                node = self.file_tree.insert(parent, 'end', text=dir_name, 
                                            values=(relative_path, True))
                print(f"添加目录节点: {dir_name}")
                self.build_tree(node, dir_path)
            
            # 添加文件
            for file_name in files:
                file_path = os.path.join(path, file_name)
                relative_path = os.path.relpath(file_path, self.workshop_dir)
                self.file_tree.insert(parent, 'end', text=file_name, 
                                     values=(relative_path, False))
                
        except Exception as e:
            print(f"构建文件树错误: {e}")
   
    def on_tree_selected(self, event):
        """处理树形选择事件"""
        print("树形选择事件触发")
        selection = self.file_tree.selection()
        if selection:
            item = selection[0]
            values = self.file_tree.item(item, 'values')
            if values:
                print(f"选中项值: {values}")
                # 修复：正确处理字符串和布尔值的判断
                is_directory = values[1] if isinstance(values[1], bool) else values[1] == 'True'
                if not is_directory:  # 如果是文件而不是目录
                    file_path = os.path.join(self.workshop_dir, values[0])
                    print(f"加载文件: {file_path}")
                    self.load_json_file(file_path)
                else:
                    print("选中的是目录，不加载文件")
    
    def on_tree_double_click(self, event):
        """处理树形双击事件"""
        print("树形双击事件触发")
        selection = self.file_tree.selection()
        if selection:
            item = selection[0]
            values = self.file_tree.item(item, 'values')
            if values:
                # 修复：正确处理字符串和布尔值的判断
                is_directory = values[1] if isinstance(values[1], bool) else values[1] == 'True'
                if not is_directory:  # 如果是文件而不是目录
                    file_path = os.path.join(self.workshop_dir, values[0])
                    print(f"双击加载文件: {file_path}")
                    self.load_json_file(file_path)
    
    def on_search_changed(self, event):
        """处理搜索框内容变化"""
        search_text = self.search_var.get().lower()
        if not search_text:
            # 清空搜索，显示所有文件
            for item in self.file_tree.get_children():
                self.file_tree.item(item, open=True)
            return
        
        # 隐藏所有节点
        for item in self.file_tree.get_children():
            self.hide_unmatched_items(item, search_text)
    
    def hide_unmatched_items(self, item, search_text):
        """隐藏不匹配搜索条件的项目"""
        item_text = self.file_tree.item(item, 'text').lower()
        values = self.file_tree.item(item, 'values')
        
        if search_text in item_text:
            # 显示匹配的项目及其父级
            self.file_tree.item(item, open=True)
            parent = self.file_tree.parent(item)
            while parent:
                self.file_tree.item(parent, open=True)
                parent = self.file_tree.parent(parent)
            return True
        
        # 检查子项
        has_matching_child = False
        for child in self.file_tree.get_children(item):
            if self.hide_unmatched_items(child, search_text):
                has_matching_child = True
        
        if has_matching_child:
            self.file_tree.item(item, open=True)
            return True
        else:
            return False
    
    def on_text_scroll(self, *args):
        """处理文本滚动事件"""
        # 更新行号
        self.update_line_numbers()
        # 调用原始滚动命令
        if hasattr(self, '_scroll_command'):
            self._scroll_command(*args) # type: ignore
    
    def on_scrollbar_move(self, *args):
        """处理滚动条移动事件"""
        self.json_text.yview(*args)
        self.update_line_numbers()
    
    def update_line_numbers(self):
        """更新行号显示"""
        # 获取当前可见行范围
        first_visible_line = self.json_text.yview()[0]
        last_visible_line = self.json_text.yview()[1]
        
        # 获取总行数
        total_lines = int(self.json_text.index('end-1c').split('.')[0])
        
        # 计算可见行号
        first_line = int(first_visible_line * total_lines) + 1
        last_line = int(last_visible_line * total_lines)
        
        # 生成行号文本
        line_numbers_text = '\n'.join(str(i) for i in range(first_line, last_line + 1))
        
        # 更新行号文本框
        self.line_numbers.config(state='normal')
        self.line_numbers.delete(1.0, tk.END)
        self.line_numbers.insert(1.0, line_numbers_text)
        self.line_numbers.config(state='disabled')
    
    def on_text_change(self, event):
        """处理文本内容变化"""
        # 保存当前内容到撤销栈
        current_content = self.json_text.get(1.0, tk.END)
        if current_content != self.current_content:
            if self.current_content:
                self.undo_stack.append(self.current_content)
                self.redo_stack.clear()  # 清空重做栈
            self.current_content = current_content
    
    def undo(self, event=None):
        """撤销操作"""
        if self.undo_stack:
            previous_content = self.undo_stack.pop()
            self.redo_stack.append(self.current_content)
            self.json_text.delete(1.0, tk.END)
            self.json_text.insert(1.0, previous_content)
            self.current_content = previous_content
            self.status_label.config(text="已撤销")
            self.apply_json_syntax_highlighting()
    
    def redo(self, event=None):
        """重做操作"""
        if self.redo_stack:
            next_content = self.redo_stack.pop()
            self.undo_stack.append(self.current_content)
            self.json_text.delete(1.0, tk.END)
            self.json_text.insert(1.0, next_content)
            self.current_content = next_content
            self.status_label.config(text="已重做")
            self.apply_json_syntax_highlighting()
    
    def jump_to_line(self, event=None):
        """跳转到指定行"""
        try:
            line_num = int(self.line_var.get())
            if line_num > 0:
                self.json_text.see(f"{line_num}.0")
                self.json_text.mark_set("insert", f"{line_num}.0")
                self.json_text.focus()
                self.status_label.config(text=f"已跳转到第 {line_num} 行")
        except ValueError:
            messagebox.showerror("错误", "请输入有效的行号")
    
    def find_text(self, event=None):
        """查找文本"""
        search_text = self.search_text_var.get()
        if not search_text:
            return
        
        # 从当前光标位置开始搜索
        start_pos = self.json_text.index("insert")
        end_pos = self.json_text.index("end")
        
        # 搜索文本
        pos = self.json_text.search(search_text, start_pos, end_pos)
        
        if pos:
            # 选中找到的文本
            end_pos = f"{pos}+{len(search_text)}c"
            self.json_text.tag_remove("sel", 1.0, "end")
            self.json_text.tag_add("sel", pos, end_pos)
            self.json_text.mark_set("insert", pos)
            self.json_text.see(pos)
            self.json_text.focus()
            self.status_label.config(text=f"已找到: {search_text}")
        else:
            self.status_label.config(text="未找到匹配的文本")
    
    def load_json_file(self, file_path):
        """加载JSON文件到编辑框"""
        print(f"开始加载文件: {file_path}")
        
        # 检查文件是否存在
        if not os.path.exists(file_path):
            messagebox.showerror("错误", f"文件不存在: {file_path}")
            return
        
        try:
            # 读取原始JSON文件
            with open(file_path, 'r', encoding='utf-8') as f:
                original_data = json.load(f)
            
            print(f"原始文件读取成功，数据长度: {len(str(original_data))}")
            
            # 保存原始数据
            self.original_data = original_data
            self.current_file = file_path
            
            # 应用changes.json中的修改
            modified_data = self.apply_changes(original_data, file_path)
            print(f"应用修改后数据长度: {len(str(modified_data))}")
            
            # 格式化JSON用于编辑
            formatted_json = self.format_json_for_editing(modified_data)
            print(f"格式化后JSON长度: {len(formatted_json)}")
            
            # 清空编辑框并插入内容
            self.json_text.delete(1.0, tk.END)
            self.json_text.insert(1.0, formatted_json)
            
            # 应用语法高亮
            # TODO 当文件内容太多的时候，语法高亮会非常卡顿，暂时注释掉
            Thread(target=self.apply_json_syntax_highlighting).start()
            
            # 更新当前文件显示
            relative_path = os.path.relpath(file_path, self.workshop_dir)
            self.current_file_label.config(text=f"当前文件: {relative_path}")
            
            # 更新状态
            self.status_label.config(text="文件加载成功")
            print("文件加载完成")
            
        except Exception as e:
            error_msg = f"加载文件失败: {str(e)}"
            print(error_msg)
            messagebox.showerror("错误", error_msg)

    def apply_changes(self, original_data, file_path):
        """应用changes.json中的修改"""
        relative_path = os.path.relpath(file_path, self.workshop_dir)
        
        if relative_path in self.changes:
            changes = self.changes[relative_path]
            return self.recursive_apply_changes(original_data, changes)
        
        return original_data
    
    def recursive_apply_changes(self, original, changes):
        """递归应用修改 - 适配包含id键值对的修改记录结构"""
        if isinstance(original, dict) and isinstance(changes, dict):
            result = {}
            for key, value in original.items():
                if key in changes:
                    # 如果changes中有对应的键，应用修改
                    if isinstance(value, (dict, list)) and isinstance(changes[key], (dict, list)):
                        result[key] = self.recursive_apply_changes(value, changes[key])
                    else:
                        result[key] = changes[key]
                else:
                    result[key] = value
            return result
        elif isinstance(original, list) and isinstance(changes, list):
            result = []
            has_applied_changes = False
            
            # 首先处理包含id的修改记录
            for change_item in changes:
                if isinstance(change_item, dict) and 'id' in change_item:
                    # 这是包含id的修改记录
                    target_id = change_item['id']
                    change_data = change_item.get('changes', {})
                    action = change_item.get('action', 'modified')  # 默认为修改操作
                    
                    # 在原始列表中查找匹配id的项
                    found = False
                    for i, original_item in enumerate(original):
                        if (isinstance(original_item, dict) and 
                            original_item.get('id') == target_id):
                            found = True
                            
                            if action == 'deleted':
                                # 删除操作：跳过该项
                                pass
                            elif action == 'added':
                                # 新增操作：添加修改后的项
                                result.append(change_data)
                            else:
                                # 修改操作：应用修改
                                if isinstance(original_item, (dict, list)) and isinstance(change_data, (dict, list)):
                                    result.append(self.recursive_apply_changes(original_item, change_data))
                                else:
                                    result.append(change_data)
                            has_applied_changes = True
                            break
                    
                    # 如果没有找到匹配项且是新增操作，则添加新项
                    if not found and action == 'added':
                        result.append(change_data)
                        has_applied_changes = True
            
            # 如果没有应用任何包含id的修改，或者还有未处理的项，使用原来的逻辑
            if not has_applied_changes:
                for i, item in enumerate(original):
                    if i < len(changes):
                        if isinstance(item, (dict, list)) and isinstance(changes[i], (dict, list)):
                            result.append(self.recursive_apply_changes(item, changes[i]))
                        else:
                            result.append(changes[i])
                    else:
                        result.append(item)
            else:
                # 处理未被修改的项（未被标记为删除的项）
                for i, original_item in enumerate(original):
                    if isinstance(original_item, dict) and 'id' in original_item:
                        # 检查该项是否已经被处理过
                        item_id = original_item['id']
                        already_processed = False
                        for change_item in changes:
                            if (isinstance(change_item, dict) and 
                                change_item.get('id') == item_id and
                                change_item.get('action') != 'deleted'):
                                already_processed = True
                                break
                        
                        if not already_processed:
                            result.append(original_item)
                    else:
                        # 对于不包含id的项，检查是否在修改范围内
                        if i < len(changes) and not isinstance(changes[i], dict):
                            # 使用原来的逻辑处理
                            if isinstance(original_item, (dict, list)) and isinstance(changes[i], (dict, list)):
                                result.append(self.recursive_apply_changes(original_item, changes[i]))
                            else:
                                result.append(changes[i])
                        else:
                            result.append(original_item)
            
            return result
        else:
            return original
    
    def format_json_for_editing(self, data):
        """格式化JSON用于编辑"""
        return json.dumps(data, ensure_ascii=False, indent=4)
    
    def apply_json_syntax_highlighting(self):
        """应用JSON语法高亮"""
        return
        # 卡顿问题待解决

        # 配置标签
        self.json_text.tag_configure("key", foreground="#7be2f7")      # 粉色
        self.json_text.tag_configure("string", foreground="#ffdb4b")   # 黄色
        self.json_text.tag_configure("number", foreground="#96f993")   # 紫色
        self.json_text.tag_configure("boolean", foreground="#ff5555")  # 红色
        self.json_text.tag_configure("null", foreground="#ff5555")     # 红色
        
        # 清除现有标签
        for tag in self.json_text.tag_names():
            self.json_text.tag_remove(tag, 1.0, tk.END)
        
        # 获取文本内容
        content = self.json_text.get(1.0, tk.END)
        
        # 匹配JSON键
        key_pattern = r'"([^"]+)"\s*:'
        for match in re.finditer(key_pattern, content):
            start = f"1.0+{match.start()}c"
            end = f"1.0+{match.end()}c"
            self.json_text.tag_add("key", start, end)
        
        # 匹配字符串值
        string_pattern = r':\s*"([^"]*)"'
        for match in re.finditer(string_pattern, content):
            start = f"1.0+{match.start()+2}c"  # 跳过冒号和空格
            end = f"1.0+{match.end()-1}c"      # 跳过引号
            self.json_text.tag_add("string", start, end)
        
        # 匹配数字
        number_pattern = r':\s*(\d+(?:\.\d+)?)'
        for match in re.finditer(number_pattern, content):
            start = f"1.0+{match.start()+2}c"  # 跳过冒号和空格
            end = f"1.0+{match.end()}c"
            self.json_text.tag_add("number", start, end)
        
        # 匹配布尔值
        boolean_pattern = r':\s*(true|false)'
        for match in re.finditer(boolean_pattern, content, re.IGNORECASE):
            start = f"1.0+{match.start()+2}c"  # 跳过冒号和空格
            end = f"1.0+{match.end()}c"
            self.json_text.tag_add("boolean", start, end)
        
        # 匹配null
        null_pattern = r':\s*(null)'
        for match in re.finditer(null_pattern, content, re.IGNORECASE):
            start = f"1.0+{match.start()+2}c"  # 跳过冒号和空格
            end = f"1.0+{match.end()}c"
            self.json_text.tag_add("null", start, end)
    
    def save_json_changes(self):
        """保存JSON修改"""
        if not self.current_file:
            messagebox.showwarning("警告", "请先选择一个文件")
            return
        
        try:
            # 获取编辑框内容
            content = self.json_text.get(1.0, tk.END).strip()
            
            # 验证JSON格式
            try:
                edited_data = json.loads(content)
            except json.JSONDecodeError as e:
                messagebox.showerror("错误", f"JSON格式错误: {str(e)}")
                return
            
            # 验证数据结构是否一致
            if not self.validate_data_structure(self.original_data, edited_data):
                messagebox.showerror("错误", "数据结构不一致！请确保只修改值内容，不要删除或添加键")
                return
            
            # 比较并保存修改
            self.compare_and_save_changes(edited_data)
            
            self.status_label.config(text="修改已保存")
            messagebox.showinfo("成功", "修改已保存到changes.json")
            
        except Exception as e:
            error_msg = f"保存失败: {str(e)}"
            print(error_msg)
            messagebox.showerror("错误", error_msg)
    
    def validate_data_structure(self, original, edited):
        """验证数据结构是否一致"""
        if type(original) != type(edited):
            return False
        
        if isinstance(original, dict):
            if set(original.keys()) != set(edited.keys()):
                return False
            
            for key in original:
                if not self.validate_data_structure(original[key], edited[key]):
                    return False
                    
        elif isinstance(original, list):
            if len(original) != len(edited):
                return False
            
            for i in range(len(original)):
                if not self.validate_data_structure(original[i], edited[i]):
                    return False
        
        return True
    
    def compare_and_save_changes(self, edited_data):
        """比较并保存修改"""
        relative_path = os.path.relpath(self.current_file, self.workshop_dir) # type: ignore
        
        # 比较修改
        changes = self.find_changes(self.original_data, edited_data)
        
        if changes:
            self.changes[relative_path] = changes
        elif relative_path in self.changes:
            # 如果没有修改，删除该文件的修改记录
            del self.changes[relative_path]
        
        # 保存到文件
        with open(self.changes_file, 'w', encoding='utf-8') as f:
            json.dump(self.changes, f, ensure_ascii=False, indent=4)
    
    def find_changes(self, original, edited):
        """查找修改 - 记录实际修改的值，同时记录id键值对以便识别具体修改内容"""
        if isinstance(original, dict) and isinstance(edited, dict):
            changes = {}
            for key in original:
                if key in edited:
                    child_changes = self.find_changes(original[key], edited[key])
                    if child_changes is not None:
                        changes[key] = child_changes
                # 不再记录被删除的键，因为我们不允许删除键
            
            # 检查是否有新增的键（不应该发生，因为验证过结构一致）
            for key in edited:
                if key not in original:
                    changes[key] = edited[key]  # 新增的键
            
            return changes if changes else None
            
        elif isinstance(original, list) and isinstance(edited, list):
            changes = []
            has_changes = False
            
            for i in range(min(len(original), len(edited))):
                # 检查当前列表项是否为字典且包含id键
                if (isinstance(original[i], dict) and isinstance(edited[i], dict) and 
                    'id' in original[i] and 'id' in edited[i]):
                    # 对于包含id的字典项，记录修改时同时记录id
                    child_changes = self.find_changes(original[i], edited[i])
                    if child_changes is not None:
                        # 创建一个包含id和修改内容的记录
                        change_record = {
                            'id': original[i]['id'],  # 记录原始id
                            'changes': child_changes
                        }
                        changes.append(change_record)
                        has_changes = True
                else:
                    # 对于不包含id的列表项，使用原来的逻辑
                    child_changes = self.find_changes(original[i], edited[i])
                    if child_changes is not None:
                        changes.append(child_changes)
                        has_changes = True
            
            # 处理长度不一致的情况
            if len(edited) > len(original):
                # 新增的元素
                for i in range(len(original), len(edited)):
                    if isinstance(edited[i], dict) and 'id' in edited[i]:
                        # 对于包含id的新增字典项，记录id和完整内容
                        change_record = {
                            'id': edited[i]['id'],
                            'changes': edited[i],
                            'action': 'added'  # 标记为新增
                        }
                        changes.append(change_record)
                    else:
                        changes.append(edited[i])
                    has_changes = True
            elif len(edited) < len(original):
                # 删除的元素（不应该发生，但我们记录为None）
                for i in range(len(edited), len(original)):
                    if isinstance(original[i], dict) and 'id' in original[i]:
                        # 对于包含id的被删除字典项，记录id
                        change_record = {
                            'id': original[i]['id'],
                            'action': 'deleted'  # 标记为删除
                        }
                        changes.append(change_record)
                    else:
                        changes.append(None)
                    has_changes = True
            
            return changes if has_changes else None
            
        else:
            # 基本类型 - 只有当值确实改变时才记录
            return edited if original != edited else None

    def reset_json_edits(self):
        """撤销所有修改"""
        if self.current_file:
            relative_path = os.path.relpath(self.current_file, self.workshop_dir) # type: ignore
            if relative_path in self.changes:
                del self.changes[relative_path]
                with open(self.changes_file, 'w', encoding='utf-8') as f:
                    json.dump(self.changes, f, ensure_ascii=False, indent=4)
                self.load_json_file(self.current_file)  # 重新加载原始文件
                self.status_label.config(text="所有修改已撤销")
                messagebox.showinfo("成功", "所有修改已撤销")
            else:
                messagebox.showinfo("信息", "没有任何修改需要撤销")
        else:
            messagebox.showwarning("警告", "请先选择一个文件")
        
    def cycle_update(self):
        """循环更新"""
    
        #TODO 优化卡顿

        Thread(target=self.apply_json_syntax_highlighting).start()
        Thread(target=self.update_line_numbers).start()

        self.parent_window.after(10000, self.cycle_update)

def open_custom_translation_tool(root):
    CustomTranslationTool(root, root.root)