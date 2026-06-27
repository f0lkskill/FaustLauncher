import tkinter as tk
from tkinter import ttk, messagebox
import os, shutil
import threading
from PIL import Image, ImageTk
import requests
from functions.web_update.web_trigger import WebTrigger
from functions.extension.mod.mod_ulits import ModManager
from functions.extension.addon.addon_ulit import AddonManager
from functions.base.color_ulits import darken_color, lighten_color


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

        # 派生颜色常量（卡片底色/描边）
        self._card_bg = lighten_color(self.bg_color, 5)
        self._card_border = darken_color(self.bg_color, 0.55)

        # 配置 ttk 滚动条自定义样式（与设置页风格保持一致）
        self._configure_scrollbar_style()

        # 平滑滚动动画状态
        self._anim_steps = 12        # 动画帧数
        self._anim_px_per_unit = 40  # 每格滚动像素基数
        
        self.setup_ui()

        # 检测更新
        # 初始化时自动获取列表
        self.root.root.after(1000, self.load_all_data)
        self.root.root.after(3000, self.total_detect_update)

    def _configure_scrollbar_style(self):
        """配置风格一致的自定义滚动条样式。"""
        try:
            style = ttk.Style()

            thumb_normal = darken_color(self.lighten_bg_color, 0.75)
            thumb_active = '#3498db'
            trough_color = darken_color(self.bg_color, 0.7)

            try:
                style.configure('Download.Vertical.TScrollbar',
                                background=thumb_normal,
                                bordercolor=thumb_normal,
                                arrowcolor='#bdc3c7',
                                troughcolor=trough_color,
                                gripcount=0,
                                relief='flat',
                                borderwidth=0)
                style.map('Download.Vertical.TScrollbar',
                          background=[('active', thumb_active),
                                      ('disabled', thumb_normal)])

                style.configure('Download.Horizontal.TScrollbar',
                                background=thumb_normal,
                                bordercolor=thumb_normal,
                                arrowcolor='#bdc3c7',
                                troughcolor=trough_color,
                                gripcount=0,
                                relief='flat',
                                borderwidth=0)
                style.map('Download.Horizontal.TScrollbar',
                          background=[('active', thumb_active),
                                      ('disabled', thumb_normal)])
            except tk.TclError:
                pass
        except Exception:
            pass

    def _bind_mousewheel_recursive(self, widget, handler):
        """递归绑定鼠标滚轮事件到 widget 及其所有子控件。"""
        try:
            widget.bind("<MouseWheel>", handler)
        except tk.TclError:
            pass
        for child in widget.winfo_children():
            self._bind_mousewheel_recursive(child, handler)

    def load_all_data(self):
        self.load_addon_data()
        self.load_mod_data()
        
    def smoth_mousewheel(self, event, canvas, anim_state):
        """平滑滚动鼠标滚轮事件处理函数。"""
        # 1) 取消正在进行的动画
        if anim_state['after_id'] is not None:
            try:
                canvas.after_cancel(anim_state['after_id'])
            except Exception:
                pass
            anim_state['after_id'] = None

        # 2) 计算目标位置
        try:
            region = canvas.cget('scrollregion')
            if region:
                parts = list(map(int, region.split()))
                region_h = parts[3] - parts[1]
            else:
                region_h = 0
        except (tk.TclError, ValueError):
            region_h = 0

        win_h = max(canvas.winfo_height(), 1)
        delta_steps = int(-1 * (event.delta / 120))  # Windows: ±120
        px = delta_steps * max(win_h * 0.18, self._anim_px_per_unit)

        if region_h > win_h:
            delta_frac = px / (region_h - win_h)
        else:
            delta_frac = 0.0

        try:
            current_frac = float(canvas.yview()[0])
        except (tk.TclError, Exception):
            current_frac = 0.0

        anim_state['target_frac'] = max(0.0, min(1.0, current_frac + delta_frac))
        anim_state['start_frac'] = current_frac
        anim_state['step_count'] = 0
        anim_state['total_steps'] = self._anim_steps

        # 3) 启动逐帧动画（ease-in-out cubic）
        def _step():
            anim_state['step_count'] += 1
            t = anim_state['step_count'] / anim_state['total_steps']
            eased = t * t * (3 - 2 * t) if t < 1 else 1.0

            new_frac = anim_state['start_frac'] + (anim_state['target_frac'] - anim_state['start_frac']) * eased
            new_frac = max(0.0, min(1.0, new_frac))

            try:
                canvas.yview_moveto(new_frac)
            except tk.TclError:
                return

            if anim_state['step_count'] < anim_state['total_steps'] and abs(anim_state['target_frac'] - new_frac) > 0.0008:
                anim_state['after_id'] = canvas.after(12, _step)
            else:
                anim_state['after_id'] = None

        _step()

    def setup_ui(self):
        # 创建设置内容容器, 居中显示
        content_frame = tk.Frame(self.parent, bg=self.lighten_bg_color,
                                 highlightthickness=1,
                                 highlightbackground=darken_color(self.lighten_bg_color, 0.65))
        content_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)

        # 创建标签页控件
        self.notebook = ttk.Notebook(content_frame)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        # 创建插件下载标签页
        self.create_addons_tab()

        # 创建Mod下载标签页
        self.create_mods_tab()

    def create_addons_tab(self):
        """创建插件下载标签页"""
        addons_frame = tk.Frame(self.notebook, bg=self.bg_color)
        self.notebook.add(addons_frame, text="🔌 插件下载")

        # 创建滚动区域
        canvas = tk.Canvas(addons_frame, bg=self.bg_color,
                           highlightthickness=1,
                           highlightbackground=darken_color(self.bg_color, 0.68),
                           bd=0)
        scrollbar = ttk.Scrollbar(addons_frame, orient="vertical",
                                  command=canvas.yview,
                                  style='Download.Vertical.TScrollbar')
        self.addon_scrollable_frame = tk.Frame(canvas, bg=self.bg_color)
        self.addon_canvas = canvas

        self.addon_scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        def _sync_width(event):
            canvas.itemconfigure('scroll_window', width=event.width)
        canvas.bind('<Configure>', _sync_width)

        canvas.create_window((0, 0), window=self.addon_scrollable_frame,
                             anchor="nw", tags='scroll_window')
        canvas.configure(yscrollcommand=scrollbar.set)

        # 平滑滚动动画状态（每个 tab 独立一个）
        anim_state = {'target_frac': 0.0, 'step_count': 0, 'total_steps': self._anim_steps, 'after_id': None}

        def _on_mousewheel(event):
            self.smoth_mousewheel(event, canvas, anim_state)

        self._addon_wheel_handler = _on_mousewheel

        canvas.bind("<MouseWheel>", _on_mousewheel)
        self.addon_scrollable_frame.bind("<MouseWheel>", _on_mousewheel)
        # 递归绑定已有的子控件（此时 scrollable_frame 还空，但先绑定）
        self._bind_mousewheel_recursive(self.addon_scrollable_frame, _on_mousewheel)
        self._bind_mousewheel_recursive(canvas, _on_mousewheel)

        # 打包滚动区域
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

    def create_mods_tab(self):
        """创建Mod下载标签页"""
        mods_frame = tk.Frame(self.notebook, bg=self.bg_color)
        self.notebook.add(mods_frame, text="🎮 Mod下载")

        # 创建滚动区域
        canvas = tk.Canvas(mods_frame, bg=self.bg_color,
                           highlightthickness=1,
                           highlightbackground=darken_color(self.bg_color, 0.68),
                           bd=0)
        scrollbar = ttk.Scrollbar(mods_frame, orient="vertical",
                                  command=canvas.yview,
                                  style='Download.Vertical.TScrollbar')
        self.mod_scrollable_frame = tk.Frame(canvas, bg=self.bg_color)
        self.mod_canvas = canvas

        self.mod_scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        def _sync_width(event):
            canvas.itemconfigure('scroll_window', width=event.width)
        canvas.bind('<Configure>', _sync_width)

        canvas.create_window((0, 0), window=self.mod_scrollable_frame,
                             anchor="nw", tags='scroll_window')
        canvas.configure(yscrollcommand=scrollbar.set)

        # 平滑滚动动画状态（每个 tab 独立一个）
        anim_state = {'target_frac': 0.0, 'step_count': 0, 'total_steps': self._anim_steps, 'after_id': None}

        def _on_mousewheel(event):
            self.smoth_mousewheel(event, canvas, anim_state)

        self._mod_wheel_handler = _on_mousewheel
        
        canvas.bind("<MouseWheel>", _on_mousewheel)
        self.mod_scrollable_frame.bind("<MouseWheel>", _on_mousewheel)
        # 递归绑定已有的子控件
        self._bind_mousewheel_recursive(self.mod_scrollable_frame, _on_mousewheel)
        self._bind_mousewheel_recursive(canvas, _on_mousewheel)

        # 打包滚动区域
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

    def load_data(self):
        # 在后台线程中加载数据
        def load_data_addon():
            try:
                self.addon_data = self.web_trigger.fectch_all_addon_info()
                if self.addon_data:
                    self.display_addon_page(1)
                else:
                    self.show_error("未获取到插件数据")
            except Exception as e:
                self.show_error(f"加载插件数据失败: {str(e)}")

        def load_data_mod():
            try:
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
            fg='#ffffff',
            font=('Microsoft YaHei UI', 11, 'bold')
        )
        loading_label.pack(pady=40)
        self.addon_scrollable_frame.update()

        def load_data_addon():
            try:
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
            fg='#ffffff',
            font=('Microsoft YaHei UI', 11, 'bold')
        )
        loading_label.pack(pady=40)
        self.mod_scrollable_frame.update()

        def load_data_mod():
            try:
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
                                   font=('Microsoft YaHei UI', 10),
                                   bg=self.bg_color, fg='#bdc3c7')
            empty_label.pack(expand=True, pady=50)
            return

        self.current_addon_page = page_num
        addon_page_data = self.addon_data[page_num - 1]

        # 分页导航
        pagination_frame = tk.Frame(self.addon_scrollable_frame, bg=self.bg_color)
        pagination_frame.pack(fill=tk.X, padx=10, pady=(8, 4))

        page_label = tk.Label(
            pagination_frame,
            text=f"第 {page_num} 页，共 {len(self.addon_data)} 页",
            bg=self.bg_color,
            fg='#ffffff',
            font=('Microsoft YaHei UI', 9)
        )
        page_label.pack(side=tk.LEFT, padx=10)

        # 上一页按钮
        prev_button = tk.Button(
            pagination_frame,
            text="上一页",
            command=lambda: self.display_addon_page(page_num - 1) if page_num > 1 else None,
            bg=self.lighten_bg_color,
            fg='#ffffff',
            activebackground=darken_color(self.lighten_bg_color, 0.9),
            activeforeground='#ffffff',
            relief=tk.FLAT,
            borderwidth=0,
            cursor='hand2',
            highlightthickness=1,
            highlightbackground=darken_color(self.lighten_bg_color, 0.7),
            padx=12,
            pady=5,
            font=('Microsoft YaHei UI', 9)
        )
        prev_button.pack(side=tk.LEFT, padx=5)

        # 下一页按钮
        next_button = tk.Button(
            pagination_frame,
            text="下一页",
            command=lambda: self.display_addon_page(page_num + 1) if page_num < len(self.addon_data) else None,
            bg=self.lighten_bg_color,
            fg='#ffffff',
            activebackground=darken_color(self.lighten_bg_color, 0.9),
            activeforeground='#ffffff',
            relief=tk.FLAT,
            borderwidth=0,
            cursor='hand2',
            highlightthickness=1,
            highlightbackground=darken_color(self.lighten_bg_color, 0.7),
            padx=12,
            pady=5,
            font=('Microsoft YaHei UI', 9)
        )
        next_button.pack(side=tk.LEFT, padx=5)

        # 显示插件列表
        for addon in addon_page_data:
            self.create_addon_card(addon)

        if hasattr(self, '_addon_wheel_handler'):
            self._bind_mousewheel_recursive(self.addon_scrollable_frame,
                                            self._addon_wheel_handler)

    def display_mod_page(self, page_num):
        # 清空现有内容
        for widget in self.mod_scrollable_frame.winfo_children():
            widget.destroy()

        if not self.mod_data or page_num < 1 or page_num > len(self.mod_data):
            empty_label = tk.Label(self.mod_scrollable_frame,
                                   text="未获取到Mod数据\n请检查网络连接后重试",
                                   font=('Microsoft YaHei UI', 10),
                                   bg=self.bg_color, fg='#bdc3c7')
            empty_label.pack(expand=True, pady=50)
            return

        self.current_mod_page = page_num
        mod_page_data = self.mod_data[page_num - 1]

        # 分页导航
        pagination_frame = tk.Frame(self.mod_scrollable_frame, bg=self.bg_color)
        pagination_frame.pack(fill=tk.X, padx=10, pady=(8, 4))

        page_label = tk.Label(
            pagination_frame,
            text=f"第 {page_num} 页，共 {len(self.mod_data)} 页",
            bg=self.bg_color,
            fg='#ffffff',
            font=('Microsoft YaHei UI', 9)
        )
        page_label.pack(side=tk.LEFT, padx=10)

        # 上一页按钮
        prev_button = tk.Button(
            pagination_frame,
            text="上一页",
            command=lambda: self.display_mod_page(page_num - 1) if page_num > 1 else None,
            bg=self.lighten_bg_color,
            fg='#ffffff',
            activebackground=darken_color(self.lighten_bg_color, 0.9),
            activeforeground='#ffffff',
            relief=tk.FLAT,
            borderwidth=0,
            cursor='hand2',
            highlightthickness=1,
            highlightbackground=darken_color(self.lighten_bg_color, 0.7),
            padx=12,
            pady=5,
            font=('Microsoft YaHei UI', 9)
        )
        prev_button.pack(side=tk.LEFT, padx=5)

        # 下一页按钮
        next_button = tk.Button(
            pagination_frame,
            text="下一页",
            command=lambda: self.display_mod_page(page_num + 1) if page_num < len(self.mod_data) else None,
            bg=self.lighten_bg_color,
            fg='#ffffff',
            activebackground=darken_color(self.lighten_bg_color, 0.9),
            activeforeground='#ffffff',
            relief=tk.FLAT,
            borderwidth=0,
            cursor='hand2',
            highlightthickness=1,
            highlightbackground=darken_color(self.lighten_bg_color, 0.7),
            padx=12,
            pady=5,
            font=('Microsoft YaHei UI', 9)
        )
        next_button.pack(side=tk.LEFT, padx=5)

        # 显示Mod列表
        for mod in mod_page_data:
            self.create_mod_card(mod)

        # ===== 所有卡片创建完毕后，再次递归绑定滚轮事件 =====
        if hasattr(self, '_mod_wheel_handler'):
            self._bind_mousewheel_recursive(self.mod_scrollable_frame,
                                            self._mod_wheel_handler)

    def create_addon_card(self, addon:dict):
        unable_download = addon.get('disabled', False)
        card_bg = self._card_bg if not unable_download else darken_color(self._card_bg, 0.5)
        text_color = '#ffffff' if not unable_download else '#bdc3c7'
        darken_text_color = darken_color(text_color, 0.8)
        
        # 卡片外框：使用 card_bg + card_border 做清晰描边
        addon_frame = tk.Frame(self.addon_scrollable_frame,
                               bg=card_bg,
                               relief='flat',
                               borderwidth=0,
                               highlightthickness=1,
                               highlightbackground=self._card_border)
        addon_frame.pack(fill=tk.X, padx=22, pady=8)

        # 插件头部（包含图标和标题）
        header_frame = tk.Frame(addon_frame, bg=card_bg)
        header_frame.pack(fill=tk.X, padx=16, pady=(6, 2))

        # 下载并显示图标
        icon_path = self.download_icon(addon.get('icon_url', ''),  addon.get('name', 'unknown'))
        if icon_path and os.path.exists(icon_path):
            try:
                image = Image.open(icon_path)
                image = image.resize((64, 64), Image.Resampling.LANCZOS)
                icon = ImageTk.PhotoImage(image)
                icon_label = tk.Label(header_frame, image=icon, bg=card_bg)
                icon_label.image = icon  # type: ignore
                icon_label.pack(side=tk.LEFT, padx=(0, 12))
            except Exception as e:
                print(f"加载图标失败: {e}")

        # 名称和版本
        title_version_frame = tk.Frame(header_frame, bg=card_bg)
        title_version_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # 插件标题
        addon_name = addon.get('name', '未知插件')
        if unable_download:
            addon_name = f"{addon_name} (暂不可用)"
        title_label = tk.Label(title_version_frame,
                             text=addon_name,
                             font=('Microsoft YaHei UI', 11, 'bold'),
                             bg=card_bg, fg=text_color)
        title_label.pack(anchor=tk.W, pady=(0, 2))

        # 插件版本
        version = addon.get('version', '未知版本')
        version_label = tk.Label(title_version_frame,
                               text=f"版本: {version}",
                               font=('Microsoft YaHei UI', 9),
                               bg=card_bg, fg=darken_text_color)
        version_label.pack(anchor=tk.W)

        # 插件描述
        description = addon.get('desc', '无描述')
        desc_label = tk.Label(addon_frame,
                            text=description,
                            font=('Microsoft YaHei UI', 9),
                            bg=card_bg, fg=darken_text_color,
                            wraplength=500, justify=tk.LEFT)
        desc_label.pack(anchor=tk.W, padx=16, pady=(0, 5))

        # 插件作者
        authors = addon.get('authors', {})
        if authors:
            authors_frame = tk.Frame(addon_frame, bg=card_bg)
            authors_frame.pack(fill=tk.X, padx=16, pady=(0, 5))

            authors_label = tk.Label(authors_frame,
                                   text="作者:",
                                   font=('Microsoft YaHei UI', 9, 'bold'),
                                   bg=card_bg, fg=darken_text_color)
            authors_label.pack(anchor=tk.W, pady=(0, 2))

            for author_name, author_url in authors.items():
                author_frame = tk.Frame(authors_frame, bg=card_bg)
                author_frame.pack(anchor=tk.W, pady=1)

                author_name_label = tk.Label(author_frame,
                                           text=author_name,
                                           font=('Microsoft YaHei UI', 9),
                                           bg=card_bg, fg='#3498db',
                                           cursor='hand2')
                author_name_label.pack(side=tk.LEFT, padx=(0, 5))
                author_name_label.bind('<Button-1>', lambda e, url=author_url: self.open_url(url))

                if author_url:
                    url_label = tk.Label(author_frame,
                                       text=author_url,
                                       font=('Microsoft YaHei UI', 8),
                                       bg=card_bg, fg=darken_text_color)
                    url_label.pack(side=tk.LEFT)

        # 下载次数
        download_count = addon.get('download_count', 0)
        download_count_label = tk.Label(header_frame,
                                       text=f"下载次数: {download_count}",
                                       font=('Microsoft YaHei UI', 8),
                                       bg=card_bg, fg=darken_text_color)
        download_count_label.pack(anchor=tk.E, padx=10, pady=(0, 2))

        # 操作按钮
        buttons_frame = tk.Frame(addon_frame, bg=card_bg)
        buttons_frame.pack(fill=tk.X, padx=16, pady=(2, 8))

        download_button = tk.Button(buttons_frame,
                                 text="📥 下载",
                                 command=lambda a=addon: self.download_addon(a),
                                 font=('Microsoft YaHei UI', 9),
                                 bg='#27ae60', fg=text_color,
                                 activebackground=darken_color('#27ae60', 0.85),
                                 activeforeground=text_color,
                                 relief='flat', borderwidth=0,
                                 cursor='hand2',
                                 highlightthickness=1,
                                 highlightbackground=darken_color('#27ae60', 0.7),
                                 padx=16, pady=4,
                                 state=tk.DISABLED if unable_download else tk.NORMAL
        )
        download_button.pack(side=tk.RIGHT, padx=5)

    def create_mod_card(self, mod:dict):
        unable_download = mod.get('disabled', False)
        card_bg = self._card_bg if not unable_download else darken_color(self._card_bg, 0.5)
        text_color = '#ffffff' if not unable_download else '#bdc3c7'
        darken_text_color = darken_color(text_color, 0.8)
        
        # 卡片外框：使用 card_bg + card_border 做清晰描边
        mod_frame = tk.Frame(self.mod_scrollable_frame,
                             bg=card_bg,
                             relief='flat',
                             borderwidth=0,
                             highlightthickness=1,
                             highlightbackground=self._card_border)
        mod_frame.pack(fill=tk.X, padx=22, pady=8)

        # Mod头部（包含图标和标题）
        header_frame = tk.Frame(mod_frame, bg=card_bg)
        header_frame.pack(fill=tk.X, padx=16, pady=(6, 2))

        # 下载并显示图标
        icon_path = self.download_icon(mod.get('icon_url', ''), mod.get('name', 'unknown'))
        if icon_path and os.path.exists(icon_path):
            try:
                image = Image.open(icon_path)
                image = image.resize((64, 64), Image.Resampling.LANCZOS)
                icon = ImageTk.PhotoImage(image)
                icon_label = tk.Label(header_frame, image=icon, bg=card_bg)
                icon_label.image = icon  # type: ignore
                icon_label.pack(side=tk.LEFT, padx=(0, 12))
            except Exception as e:
                print(f"加载图标失败: {e}")

        # 名称和版本
        title_version_frame = tk.Frame(header_frame, bg=card_bg)
        title_version_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # Mod标题
        mod_name = mod.get('name', '未知Mod')
        if unable_download:
            mod_name = f"{mod_name} (暂不可用)"
        title_label = tk.Label(title_version_frame,
                             text=mod_name,
                             font=('Microsoft YaHei UI', 11, 'bold'),
                             bg=card_bg, fg=text_color)
        title_label.pack(anchor=tk.W, pady=(0, 2))

        # Mod版本
        version = mod.get('version', '未知版本')
        version_label = tk.Label(title_version_frame,
                               text=f"版本: {version}",
                               font=('Microsoft YaHei UI', 9),
                               bg=card_bg, fg=darken_text_color)
        version_label.pack(anchor=tk.W)

        # Mod描述
        description = mod.get('desc', '无描述')
        desc_label = tk.Label(mod_frame,
                            text=description,
                            font=('Microsoft YaHei UI', 9),
                            bg=card_bg, fg=darken_text_color,
                            wraplength=500, justify=tk.LEFT)
        desc_label.pack(anchor=tk.W, padx=16, pady=(0, 5))

        # Mod作者
        authors = mod.get('authors', {})
        if authors:
            authors_frame = tk.Frame(mod_frame, bg=card_bg)
            authors_frame.pack(fill=tk.X, padx=16, pady=(0, 5))

            authors_label = tk.Label(authors_frame,
                                   text="作者:",
                                   font=('Microsoft YaHei UI', 9, 'bold'),
                                   bg=card_bg, fg=darken_text_color)
            authors_label.pack(anchor=tk.W, pady=(0, 2))

            for author_name, author_url in authors.items():
                author_frame = tk.Frame(authors_frame, bg=card_bg)
                author_frame.pack(anchor=tk.W, pady=1)

                author_name_label = tk.Label(author_frame,
                                           text=author_name,
                                           font=('Microsoft YaHei UI', 9),
                                           bg=card_bg, fg='#3498db',
                                           cursor='hand2')
                author_name_label.pack(side=tk.LEFT, padx=(0, 5))
                author_name_label.bind('<Button-1>', lambda e, url=author_url: self.open_url(url))

                if author_url:
                    url_label = tk.Label(author_frame,
                                       text=author_url,
                                       font=('Microsoft YaHei UI', 8),
                                       bg=card_bg, fg=darken_text_color)
                    url_label.pack(side=tk.LEFT)

        # 下载次数
        download_count = mod.get('download_count', 0)
        download_count_label = tk.Label(header_frame,
                                       text=f"下载次数: {download_count}",
                                       font=('Microsoft YaHei UI', 8),
                                       bg=card_bg, fg=darken_text_color)
        download_count_label.pack(anchor=tk.E, padx=10, pady=(0, 2))

        # 操作按钮
        buttons_frame = tk.Frame(mod_frame, bg=card_bg)
        buttons_frame.pack(fill=tk.X, padx=16, pady=(2, 8))

        download_button = tk.Button(buttons_frame,
                                 text="📥 下载",
                                 command=lambda m=mod: self.download_mod(m),
                                 font=('Microsoft YaHei UI', 9),
                                 bg='#27ae60', fg=text_color,
                                 activebackground=darken_color('#27ae60', 0.85),
                                 activeforeground=text_color,
                                 relief='flat', borderwidth=0,
                                 state=tk.DISABLED if unable_download else tk.NORMAL,
                                 cursor='hand2',
                                 highlightthickness=1,
                                 highlightbackground=darken_color('#27ae60', 0.7),
                                 padx=16, pady=4)
        download_button.pack(side=tk.RIGHT, padx=5)

    def download_icon(self, icon_url:str, item_name:str):
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
        download_url = addon.get('dowload_url')
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
            gui = DownloadGUI(self.root.root, addon_path, False, download_func=download_and_extract_gui)
            thread = threading.Thread(target=download_and_extract_gui, args=(gui, addon_path, download_files), daemon=True)
            thread.start()

        except Exception as e:
            messagebox.showerror("错误", f"下载过程中发生错误: {str(e)}")
        finally:
            # 恢复状态栏
            pass

        threading.Thread(target=self.web_trigger.add_download_nummber_addon, args=(addon.get('name', None),)).start()  # 增加下载次数
        threading.Thread(target=self.refresh_center).start()  # 刷新界面显示最新下载次数

    def download_mod(self, mod):
        # 准备下载信息
        download_url = mod.get('dowload_url')
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

            gui = DownloadGUI(self.root.root, mod_path, False, download_func=download_and_extract_gui)
            thread = threading.Thread(target=download_and_extract_gui, args=(gui, mod_path, download_files))
            thread.start()

        except Exception as e:
            messagebox.showerror("错误", f"下载过程中发生错误: {str(e)}")
        finally:
            # 恢复状态栏
            pass

        threading.Thread(target=self.web_trigger.add_download_nummber_mod, args=(mod.get('name', None),)).start()  # 增加下载次数
        threading.Thread(target=self.refresh_center).start()  # 刷新界面显示最新下载次数

    def detect_mod_update(self):
        mod_paths = ModManager.get_mod_path()

        for mod_path in mod_paths:
            mod_name = os.path.basename(mod_path)

            mod_info = ModManager.get_mod_info(mod_name)
            if mod_info.get('disabled', False):
                continue
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
        am = AddonManager([])
        addon_names = am.addon_names

        for addon_name in addon_names:
            addon_info: dict = am.get_addon_info(addon_name)  # type: ignore
            if addon_info.get('disabled', False):
                continue
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
        self.detect_addon_update()
        self.detect_mod_update()

    def open_url(self, url):
        if os.name == 'nt':
            os.startfile(url)
        elif os.name == 'posix':
            os.system(f'xdg-open "{url}"')
        else:
            os.system(f'open "{url}"')

    def show_error(self, message):
        try:
            messagebox.showerror("下载中心", message)
        except Exception:
            print(f"[错误] {message}")


def init_download_center(parent, root, bg_color, lighten_bg_color) -> DownloadCenterPage:
    return DownloadCenterPage(parent, root, bg_color, lighten_bg_color)