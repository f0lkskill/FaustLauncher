import tkinter as tk
from tkinter import ttk, messagebox
import os, shutil
import threading
from PIL import Image, ImageTk
import requests
from functions.base.web_trigger import WebTrigger
from functions.extension.mod.mod_ulits import ModManager
from functions.extension.addon.addon_ulit import AddonManager

class DownloadCenterPage:
    def __init__(self, parent, root, bg_color, lighten_bg_color):
        self.parent = parent
        self.root = root
        self.bg_color = bg_color
        self.lighten_bg_color = lighten_bg_color
        self.web_trigger = WebTrigger()
        self.icon_cache_dir = "cache/icons"
        os.makedirs(self.icon_cache_dir, exist_ok=True)
        
        self.current_addon_page = 1
        self.current_mod_page = 1
        self.addon_data = []
        self.mod_data = []
        
        self.setup_ui()
        
        # 检测更新
        # 初始化时自动获取列表
        self.root.root.after(1000, self.load_all_data)
        self.root.root.after(3000, self.total_detect_update)

    def load_all_data(self):
        self.load_addon_data()
        self.load_mod_data()

    def setup_ui(self):
        # 创建设置内容容器, 居中显示
        content_frame = tk.Frame(self.parent, bg=self.lighten_bg_color, relief='groove', borderwidth=1)
        content_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)
        
        # 创建标签页控件
        self.notebook = ttk.Notebook(content_frame)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        # 创建插件下载标签页
        self.create_addons_tab()
        
        # 创建Mod下载标签页
        self.create_mods_tab()
        
        # 创建状态栏
        status_frame = tk.Frame(content_frame, bg=self.bg_color, height=25)
        status_frame.pack(fill=tk.X, side=tk.BOTTOM, pady=(10, 0))
        status_frame.pack_propagate(False)
        
        self.status_var = tk.StringVar()
        self.status_var.set("就绪 - 点击下载按钮开始下载")
        status_label = tk.Label(status_frame, textvariable=self.status_var,
                               font=('Microsoft YaHei UI', 9),
                               bg=self.bg_color, fg='#95a5a6', anchor=tk.W)
        status_label.pack(fill=tk.X, padx=10, pady=5)
    
    def create_addons_tab(self):
        """创建插件下载标签页"""
        addons_frame = ttk.Frame(self.notebook)
        self.notebook.add(addons_frame, text="🔌 插件下载")
        
        # 创建滚动区域
        canvas = tk.Canvas(addons_frame, bg=self.bg_color, highlightthickness=0)
        scrollbar = ttk.Scrollbar(addons_frame, orient="vertical", command=canvas.yview)
        self.addon_scrollable_frame = tk.Frame(canvas, bg=self.bg_color)
        
        self.addon_scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=self.addon_scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        # 绑定鼠标滚轮事件
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        canvas.bind("<MouseWheel>", _on_mousewheel)
        self.addon_scrollable_frame.bind("<MouseWheel>", _on_mousewheel)
        
        # 打包滚动区域
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
    
    def create_mods_tab(self):
        """创建Mod下载标签页"""
        mods_frame = ttk.Frame(self.notebook)
        self.notebook.add(mods_frame, text="🎮 Mod下载")
        
        # 创建滚动区域
        canvas = tk.Canvas(mods_frame, bg=self.bg_color, highlightthickness=0)
        scrollbar = ttk.Scrollbar(mods_frame, orient="vertical", command=canvas.yview)
        self.mod_scrollable_frame = tk.Frame(canvas, bg=self.bg_color)
        
        self.mod_scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=self.mod_scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        # 绑定鼠标滚轮事件
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        canvas.bind("<MouseWheel>", _on_mousewheel)
        self.mod_scrollable_frame.bind("<MouseWheel>", _on_mousewheel)
        
        # 打包滚动区域
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
    
    def load_data(self):
        # 在后台线程中加载数据
        def load_data_addon():
            try:
                self.status_var.set("正在获取插件列表...")
                self.addon_data = self.web_trigger.fectch_all_addon_info()
                if self.addon_data:
                    self.display_addon_page(1)
                else:
                    self.show_error("未获取到插件数据")
            except Exception as e:
                self.show_error(f"加载插件数据失败: {str(e)}")
        def load_data_mod():
            try:
                self.status_var.set("正在获取Mod列表...")
                self.mod_data = self.web_trigger.fectch_all_mod_info()
                if self.mod_data:
                    self.display_mod_page(1)
                else:
                    self.show_error("未获取到Mod数据")
            except Exception as e:
                self.show_error(f"加载Mod数据失败: {str(e)}")
        
        thread = threading.Thread(target=load_data_addon)
        thread2 = threading.Thread(target=load_data_mod)
        thread2.start()
        thread.start()
    
    def load_addon_data(self):
        # 清空现有内容
        for widget in self.addon_scrollable_frame.winfo_children():
            widget.destroy()
        
        # 显示加载中
        loading_label = tk.Label(
            self.addon_scrollable_frame, 
            text="加载中...", 
            bg=self.bg_color, 
            fg="#ecf0f1",
            font=('微软雅黑', 12)
        )
        loading_label.pack(pady=20)
        self.addon_scrollable_frame.update()

        def load_data_addon():
            try:
                self.status_var.set("正在获取插件列表...")
                self.addon_data = self.web_trigger.fectch_all_addon_info()
                if self.addon_data:
                    self.display_addon_page(1)
                else:
                    self.show_error("未获取到插件数据")
            except Exception as e:
                self.show_error(f"加载插件数据失败: {str(e)}")

        thread = threading.Thread(target=load_data_addon)
        thread.start()

    def load_mod_data(self):
        # 清空现有内容
        for widget in self.mod_scrollable_frame.winfo_children():
            widget.destroy()
        
        # 显示加载中
        loading_label = tk.Label(
            self.mod_scrollable_frame, 
            text="加载中...", 
            bg=self.bg_color, 
            fg="#ecf0f1",
            font=('微软雅黑', 12)
        )
        loading_label.pack(pady=20)
        self.mod_scrollable_frame.update()
        
        def load_data_mod():
            try:
                self.status_var.set("正在获取Mod列表...")
                self.mod_data = self.web_trigger.fectch_all_mod_info()
                if self.mod_data:
                    self.display_mod_page(1)
                else:
                    self.show_error("未获取到Mod数据")
            except Exception as e:
                self.show_error(f"加载Mod数据失败: {str(e)}")

        thread = threading.Thread(target=load_data_mod)
        thread.start()
    
    def display_addon_page(self, page_num):
        # 清空现有内容
        for widget in self.addon_scrollable_frame.winfo_children():
            widget.destroy()
        
        if not self.addon_data or page_num < 1 or page_num > len(self.addon_data):
            empty_label = tk.Label(self.addon_scrollable_frame, 
                                 text="未获取到插件数据\n请检查网络连接后重试",
                                 font=('微软雅黑', 12),
                                 bg=self.bg_color, fg='#bdc3c7')
            empty_label.pack(expand=True, pady=50)
            return
        
        self.current_addon_page = page_num
        addon_page_data = self.addon_data[page_num - 1]
        
        # 显示分页信息
        pagination_frame = tk.Frame(self.addon_scrollable_frame, bg=self.bg_color)
        pagination_frame.pack(fill=tk.X, pady=10)
        
        page_label = tk.Label(
            pagination_frame, 
            text=f"第 {page_num} 页，共 {len(self.addon_data)} 页", 
            bg=self.bg_color, 
            fg="#ecf0f1"
        )
        page_label.pack(side=tk.LEFT, padx=10)
        
        # 上一页按钮
        prev_button = tk.Button(
            pagination_frame, 
            text="上一页", 
            command=lambda: self.display_addon_page(page_num - 1) if page_num > 1 else None,
            bg=self.lighten_bg_color,
            fg="#ecf0f1",
            relief=tk.FLAT,
            padx=10,
            pady=5
        )
        prev_button.pack(side=tk.LEFT, padx=5)
        
        # 下一页按钮
        next_button = tk.Button(
            pagination_frame, 
            text="下一页", 
            command=lambda: self.display_addon_page(page_num + 1) if page_num < len(self.addon_data) else None,
            bg=self.lighten_bg_color,
            fg="#ecf0f1",
            relief=tk.FLAT,
            padx=10,
            pady=5
        )
        next_button.pack(side=tk.LEFT, padx=5)
        
        # 显示插件列表
        for addon in addon_page_data:
            self.create_addon_card(addon)
    
    def display_mod_page(self, page_num):
        # 清空现有内容
        for widget in self.mod_scrollable_frame.winfo_children():
            widget.destroy()
        
        if not self.mod_data or page_num < 1 or page_num > len(self.mod_data):
            empty_label = tk.Label(self.mod_scrollable_frame, 
                                 text="未获取到Mod数据\n请检查网络连接后重试",
                                 font=('微软雅黑', 12),
                                 bg=self.bg_color, fg='#bdc3c7')
            empty_label.pack(expand=True, pady=50)
            return
        
        self.current_mod_page = page_num
        mod_page_data = self.mod_data[page_num - 1]
        
        # 显示分页信息
        pagination_frame = tk.Frame(self.mod_scrollable_frame, bg=self.bg_color)
        pagination_frame.pack(fill=tk.X, pady=10)
        
        page_label = tk.Label(
            pagination_frame, 
            text=f"第 {page_num} 页，共 {len(self.mod_data)} 页", 
            bg=self.bg_color, 
            fg="#ecf0f1"
        )
        page_label.pack(side=tk.LEFT, padx=10)
        
        # 上一页按钮
        prev_button = tk.Button(
            pagination_frame, 
            text="上一页", 
            command=lambda: self.display_mod_page(page_num - 1) if page_num > 1 else None,
            bg=self.lighten_bg_color,
            fg="#ecf0f1",
            relief=tk.FLAT,
            padx=10,
            pady=5
        )
        prev_button.pack(side=tk.LEFT, padx=5)
        
        # 下一页按钮
        next_button = tk.Button(
            pagination_frame, 
            text="下一页", 
            command=lambda: self.display_mod_page(page_num + 1) if page_num < len(self.mod_data) else None,
            bg=self.lighten_bg_color,
            fg="#ecf0f1",
            relief=tk.FLAT,
            padx=10,
            pady=5
        )
        next_button.pack(side=tk.LEFT, padx=5)
        
        # 显示Mod列表
        for mod in mod_page_data:
            self.create_mod_card(mod)
    
    def create_addon_card(self, addon):
        addon_frame = tk.Frame(self.addon_scrollable_frame, bg=self.bg_color, relief='raised', borderwidth=1)
        addon_frame.pack(fill=tk.X, padx=10, pady=8, ipady=8, ipadx=8)
        
        # 插件头部（包含图标和标题）
        header_frame = tk.Frame(addon_frame, bg=self.bg_color)
        header_frame.pack(fill=tk.X, padx=15, pady=(2, 2))
        
        # 下载并显示图标
        icon_path = self.download_icon(addon.get('icon_url'), addon.get('name', 'unknown'))
        if icon_path and os.path.exists(icon_path):
            try:
                image = Image.open(icon_path)
                image = image.resize((64, 64), Image.Resampling.LANCZOS)
                icon = ImageTk.PhotoImage(image)
                icon_label = tk.Label(header_frame, image=icon, bg=self.bg_color)
                icon_label.image = icon  # type: ignore # 保存引用
                icon_label.pack(side=tk.LEFT, padx=(0, 10))
            except Exception as e:
                print(f"加载图标失败: {e}")
        
        # 名称和版本
        title_version_frame = tk.Frame(header_frame, bg=self.bg_color)
        title_version_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        # 插件标题
        addon_name = addon.get('name', '未知插件')
        title_label = tk.Label(title_version_frame, 
                             text=addon_name,
                             font=('微软雅黑', 11, 'bold'),
                             bg=self.bg_color, fg='white')
        title_label.pack(anchor=tk.W, pady=(0, 2))
        
        # 插件版本
        version = addon.get('version', '未知版本')
        version_label = tk.Label(title_version_frame, 
                               text=f"版本: {version}",
                               font=('微软雅黑', 9),
                               bg=self.bg_color, fg='#95a5a6')
        version_label.pack(anchor=tk.W)
        
        # 插件描述
        description = addon.get('desc', '无描述')
        desc_label = tk.Label(addon_frame, 
                            text=description,
                            font=('微软雅黑', 9),
                            bg=self.bg_color, fg='#bdc3c7',
                            wraplength=400, justify=tk.LEFT)
        desc_label.pack(anchor=tk.W, padx=15, pady=(0, 5))
        
        # 插件作者
        authors = addon.get('authors', {})
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

        # 下载次数
        download_count = addon.get('download_count', 0)
        download_count_label = tk.Label(header_frame,
                                       text=f"下载次数: {download_count}",
                                       font=('微软雅黑', 8),
                                       bg=self.bg_color, fg='#95a5a6')
        download_count_label.pack(anchor=tk.E, padx=10, pady=(0, 2))
        
        # 操作按钮
        buttons_frame = tk.Frame(addon_frame, bg=self.bg_color)
        buttons_frame.pack(fill=tk.X, padx=15, pady=5)
        
        download_button = tk.Button(buttons_frame, 
                                 text="📥 下载",
                                 command=lambda a=addon: self.download_addon(a),
                                 font=('Microsoft YaHei UI', 9),
                                 bg='#27ae60', fg='white',
                                 relief='flat', padx=10, pady=3)
        download_button.pack(side=tk.RIGHT, padx=5)
    
    def create_mod_card(self, mod):
        mod_frame = tk.Frame(self.mod_scrollable_frame, bg=self.bg_color, relief='raised', borderwidth=1)
        mod_frame.pack(fill=tk.X, padx=10, pady=8, ipady=8, ipadx=8)
        
        # Mod头部（包含图标和标题）
        header_frame = tk.Frame(mod_frame, bg=self.bg_color)
        header_frame.pack(fill=tk.X, padx=15, pady=(2, 2))
        
        # 下载并显示图标
        icon_path = self.download_icon(mod.get('icon_url'), mod.get('name', 'unknown'))
        if icon_path and os.path.exists(icon_path):
            try:
                image = Image.open(icon_path)
                image = image.resize((64, 64), Image.Resampling.LANCZOS)
                icon = ImageTk.PhotoImage(image)
                icon_label = tk.Label(header_frame, image=icon, bg=self.bg_color)
                icon_label.image = icon  # type: ignore # 保存引用
                icon_label.pack(side=tk.LEFT, padx=(0, 10))
            except Exception as e:
                print(f"加载图标失败: {e}")
        
        # 名称和版本
        title_version_frame = tk.Frame(header_frame, bg=self.bg_color)
        title_version_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        # Mod标题
        mod_name = mod.get('name', '未知Mod')
        title_label = tk.Label(title_version_frame, 
                             text=mod_name,
                             font=('微软雅黑', 11, 'bold'),
                             bg=self.bg_color, fg='white')
        title_label.pack(anchor=tk.W, pady=(0, 2))
        
        # Mod版本
        version = mod.get('version', '未知版本')
        version_label = tk.Label(title_version_frame, 
                               text=f"版本: {version}",
                               font=('微软雅黑', 9),
                               bg=self.bg_color, fg='#95a5a6')
        version_label.pack(anchor=tk.W)
        
        # Mod描述
        description = mod.get('desc', '无描述')
        desc_label = tk.Label(mod_frame, 
                            text=description,
                            font=('微软雅黑', 9),
                            bg=self.bg_color, fg='#bdc3c7',
                            wraplength=400, justify=tk.LEFT)
        desc_label.pack(anchor=tk.W, padx=15, pady=(0, 5))
        
        # Mod作者
        authors = mod.get('authors', {})
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

        # 下载次数
        download_count = mod.get('download_count', 0)
        download_count_label = tk.Label(header_frame,
                                        text=f"下载次数: {download_count}",
                                        font=('微软雅黑', 8),
                                        bg=self.bg_color, fg='#95a5a6')
        download_count_label.pack(anchor=tk.E, padx=10, pady=(0, 2))
        
        # 操作按钮
        buttons_frame = tk.Frame(mod_frame, bg=self.bg_color)
        buttons_frame.pack(fill=tk.X, padx=15, pady=5)
        
        download_button = tk.Button(buttons_frame, 
                                 text="📥 下载",
                                 command=lambda m=mod: self.download_mod(m),
                                 font=('Microsoft YaHei UI', 9),
                                 bg='#27ae60', fg='white',
                                 relief='flat', padx=10, pady=3)
        download_button.pack(side=tk.RIGHT, padx=5)
    
    def download_icon(self, icon_url, item_name):
        if not icon_url:
            return None
        
        # 生成图标缓存路径
        icon_filename = f"{item_name.replace(' ', '_')}_icon.png"
        icon_path = os.path.join(self.icon_cache_dir, icon_filename)
        
        # 如果图标已存在，直接返回
        if os.path.exists(icon_path):
            return icon_path
        
        # 下载图标
        try:
            # print(f"正在下载图标: {icon_url}")
            response = requests.get(icon_url, timeout=10, verify=False)
            if response.status_code == 200:
                with open(icon_path, 'wb') as f:
                    f.write(response.content)
                # print(f"图标下载成功: {icon_path}")
                return icon_path
            else:
                print(f"图标下载失败，状态码: {response.status_code}")
        except Exception as e:
            print(f"图标下载异常: {str(e)}")
        
        return None
    
    def refresh_center(self):
        self.load_data()  # 重新加载数据
        self.root.mod_addon_page.refresh_all_tabs()  # 刷新列表
    
    def download_addon(self, addon):
        # 准备下载信息
        download_url = addon.get('download_url')
        if not download_url:
            messagebox.showerror("错误", "插件下载链接无效")
            return
        
        # 调用下载函数
        download_files = [{
            'url': download_url,
            'name': addon.get('name', 'unknown'),
            'temp_filename': f"{addon.get('name', 'unknown')}.7z"
        }]

        try:
            shutil.rmtree('addons/' + addon.get('name', 'unknown'))
        except:
            pass
        
        # 导入下载模块并执行下载
        try:
            from functions.web_update.zeroasso_dow import download_and_extract_gui, DownloadGUI
            addon_path = "addons"

            print(f"准备下载插件: {addon.get('name', 'unknown')}，下载链接: {download_url}")

            # 更新状态栏
            self.status_var.set(f"插件: {addon.get('name', 'unknown')}")
            
            gui = DownloadGUI(self.root.root, addon_path, False, download_func=download_and_extract_gui)
            thread = threading.Thread(target=download_and_extract_gui, args=(gui, addon_path, download_files), daemon=True)
            thread.start()

        except Exception as e:
            messagebox.showerror("错误", f"下载过程中发生错误: {str(e)}")
        finally:
            # 恢复状态栏
            self.status_var.set("就绪 - 点击下载按钮开始下载")

        threading.Thread(target=self.web_trigger.add_download_nummber_addon, args=(addon.get('name', None),)).start()  # 增加下载次数
        threading.Thread(target=self.refresh_center).start()  # 刷新界面显示最新下载次数
    
    def download_mod(self, mod):
        # 准备下载信息
        download_url = mod.get('download_url')
        if not download_url:
            messagebox.showerror("错误", "Mod下载链接无效")
            return
        
        # 调用下载函数
        download_files = [{
            'url': download_url,
            'name': mod.get('name', 'unknown'),
            'temp_filename': f"{mod.get('name', 'unknown')}.7z"
        }]

        try:
            shutil.rmtree('mods/' + mod.get('name', 'unknown'))
        except:
            pass
        
        # 导入下载模块并执行下载
        try:
            from functions.web_update.zeroasso_dow import download_and_extract_gui, DownloadGUI
            # 获取游戏路径
            mod_path = "mods"
            
            # 更新状态栏
            self.status_var.set(f"Mod: {mod.get('name', 'unknown')}")

            gui = DownloadGUI(self.root.root, mod_path, False, download_func=download_and_extract_gui)
            thread = threading.Thread(target=download_and_extract_gui, args=(gui, mod_path, download_files))
            thread.start()

        except Exception as e:
            messagebox.showerror("错误", f"下载过程中发生错误: {str(e)}")
        finally:
            # 恢复状态栏
            self.status_var.set("就绪 - 点击下载按钮开始下载")
            
        threading.Thread(target=self.web_trigger.add_download_nummber_mod, args=(mod.get('name', None),)).start()  # 增加下载次数
        threading.Thread(target=self.refresh_center).start()  # 刷新界面显示最新下载次数

    def detect_mod_update(self):
        '''检测模组更新'''
        mod_paths = ModManager.get_mod_path()

        for mod_path in mod_paths:
            mod_name = os.path.basename(mod_path)
            
            mod_info = ModManager.get_mod_info(mod_name)
            version = mod_info.get('version', 'unknown')

            for page in self.mod_data:
                for web_mod_data in page:
                    if web_mod_data['name'] == mod_info['name']:
                        if web_mod_data['version'] != version:
                            print(f"检测到模组: {mod_info['name']}，当前版本: {version}，网络版本: {web_mod_data['version']}, 准备下载更新...")
                            self.download_mod(web_mod_data)
                        else:
                            print(f"模组: {mod_info['name']} 已是最新版本: {version}")

    def detect_addon_update(self):
        '''检测插件更新'''
        am = AddonManager([])
        addon_names = am.addon_names

        for addon_name in addon_names:
            addon_info:dict = am.get_addon_info(addon_name) # type: ignore
            version = addon_info.get('version', 'unknown')
            for page in self.addon_data:
                for web_addon_data in page:
                    if web_addon_data['name'] == addon_info['name']:
                        if web_addon_data['version'] != version:
                            print(f"检测到插件: {addon_info['name']}，当前版本: {version}，网络版本: {web_addon_data['version']}, 准备下载更新...")
                            self.download_addon(web_addon_data)
                        else:
                            print(f"插件: {addon_info['name']} 已是最新版本: {version}")

    def total_detect_update(self):
        '''检测所有更新'''
        # 检测模组和插件更新...
        self.detect_addon_update()
        self.detect_mod_update()
    
    def open_url(self, url):
        import webbrowser
        webbrowser.open(url)
    
    def show_error(self, message):
        # 在主线程中显示错误信息
        def show():
            messagebox.showerror("错误", message)
            # 更新状态栏
            self.status_var.set("就绪 - 点击下载按钮开始下载")
        
        if self.parent.winfo_exists():
            self.parent.after(0, show)

def init_download_center(parent, root, bg_color, lighten_bg_color):
    """初始化下载中心页面"""
    return DownloadCenterPage(parent, root, bg_color, lighten_bg_color)