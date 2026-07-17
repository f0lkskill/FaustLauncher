import tkinter as tk
from tkinter import ttk, messagebox
import os
import json
from PIL import Image, ImageTk
from functions.extension.mod.mod_ulits import ModManager

class ModAddonManagerPage:
    def __init__(self, parent_frame, bg_color, lighten_bg_color, app):
        self.parent = parent_frame
        self.app = app
        self.bg_color = bg_color
        self.lighten_bg_color = lighten_bg_color
        self.addon_manager = app.core.addon_manager
        self.addon_page = 0
        self.mod_page = 0
        self.items_per_page = 5
        self.all_addons = []
        self.all_mods = []
        self.addon_enabled = {}
        self.mod_enabled = {}
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
        
        addons_frame = tk.Frame(self.notebook, bg=self.lighten_bg_color)
        self.notebook.add(addons_frame, text="🔌 插件管理")
        self.addons_list_frame = tk.Frame(addons_frame, bg=self.bg_color)
        self.addons_list_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        self.addons_page_frame = tk.Frame(addons_frame, bg=self.bg_color, height=40)
        self.addons_page_frame.pack(fill=tk.X, side=tk.BOTTOM, pady=(5, 5))
        self.addons_page_frame.pack_propagate(False)
        self.show_addons()
    
    def create_new_mods_tab(self):
        """创建新Mod架构管理标签页"""
        mods_frame = tk.Frame(self.notebook, bg=self.lighten_bg_color)
        self.notebook.add(mods_frame, text="🎮 Mod管理")
        self.mods_list_frame = tk.Frame(mods_frame, bg=self.bg_color)
        self.mods_list_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        self.mods_page_frame = tk.Frame(mods_frame, bg=self.bg_color, height=40)
        self.mods_page_frame.pack(fill=tk.X, side=tk.BOTTOM, pady=(5, 5))
        self.mods_page_frame.pack_propagate(False)
        self.show_mods()
    
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
    
    def show_addons(self):
        """显示插件管理列表"""
        
        self.addon_manager.scan_addons()
        self.all_addons = self.addon_manager.get_all_addons()
        self._load_enabled_state(self.all_addons, 'addon_info.json', self.addon_enabled)
        self.addon_page = 0
        self._display_page(self.addons_list_frame, self.addons_page_frame,
                           self.all_addons, self.addon_page, self.addon_enabled, 'addon')

    def _show_detail(self, item, item_type):
        """显示插件或Mod的详细信息"""
        
        info = item['info']
        display_name = info.get('name', item['name'])
        enabled = self._is_enabled(item_type, item['name'])
        detail = tk.Toplevel(self.parent)
        detail.title(f"{display_name}")
        detail.configure(bg=self.lighten_bg_color)
        detail.transient(self.parent.winfo_toplevel())
        detail.grab_set()
        w, h = 520, 520
        sw = detail.winfo_screenwidth()
        sh = detail.winfo_screenheight()
        detail.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")
        detail.resizable(False, False)
        main = tk.Frame(detail, bg=self.lighten_bg_color)
        main.pack(fill=tk.BOTH, expand=True, padx=15, pady=10)
        header = tk.Frame(main, bg=self.lighten_bg_color)
        header.pack(fill=tk.X)
        icon_path = os.path.join(item['path'], 'icon.png')

        if os.path.exists(icon_path):
            try:
                img = Image.open(icon_path)
                img = img.resize((64, 64), Image.Resampling.LANCZOS)
                self._detail_icon = ImageTk.PhotoImage(img)
                tk.Label(header, image=self._detail_icon, bg=self.lighten_bg_color).pack(side=tk.LEFT, padx=(0, 10))
                detail.iconbitmap(icon_path)
            except:
                pass

        title_frame = tk.Frame(header, bg=self.lighten_bg_color, padx=10, pady=5)
        title_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)
        version = info.get('version', '')
        tk.Label(title_frame, text=display_name,
                 font=('微软雅黑', 14, 'bold'), bg=self.lighten_bg_color, fg='white', anchor=tk.W).pack(fill=tk.X)
        if version:
            tk.Label(title_frame, text=f"版本: {version}",
                     font=('微软雅黑', 9), bg=self.lighten_bg_color, fg='#95a5a6', anchor=tk.W).pack(fill=tk.X)
            
        e_var = tk.BooleanVar(value=enabled)
                
        canvas = tk.Canvas(main, bg=self.bg_color, highlightthickness=0)
        scrollbar = ttk.Scrollbar(main, orient="vertical", command=canvas.yview)
        scroll_frame = tk.Frame(canvas, bg=self.bg_color, padx=10, pady=10, border=1)
        scroll_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scroll_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        def _on_mw(event):
            canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        canvas.bind("<MouseWheel>", _on_mw)
        scroll_frame.bind("<MouseWheel>", _on_mw)

        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        sep = {'bg': self.bg_color, 'font': ('微软雅黑', 10, 'bold'), 'fg': '#ecf0f1', 'anchor': tk.W}
        body = {'bg': self.bg_color, 'font': ('微软雅黑', 9), 'fg': '#bdc3c7', 'anchor': tk.W, 'justify': tk.LEFT, 'wraplength': 460}
        tk.Label(scroll_frame, text="简介", **sep).pack(fill=tk.X, pady=(10, 3))
        tk.Label(scroll_frame, text=info.get('desc', '无描述'), **body).pack(fill=tk.X, pady=(0, 8))

        authors = info.get('authors', {})
        if authors:
            tk.Label(scroll_frame, text="作者", **sep).pack(fill=tk.X, pady=(5, 3))
            for aname, aurl in authors.items():
                af = tk.Frame(scroll_frame, bg=self.bg_color)
                af.pack(fill=tk.X, pady=1)
                al = tk.Label(af, text=aname, font=('微软雅黑', 9), bg=self.bg_color, fg='#3498db', cursor='hand2')
                al.pack(side=tk.LEFT, padx=(10, 5))
                al.bind('<Button-1>', lambda e, u=aurl: self.open_url(u))
                if aurl:
                    tk.Label(af, text=aurl, font=('微软雅黑', 8), bg=self.bg_color, fg='#95a5a6').pack(side=tk.LEFT)

        # 0.6.0-pre.6 取消显示文件列表
        # if item_type == 'mod':
        #     file_names = info.get('file_names', [])
        #     if file_names:
        #         tk.Label(scroll_frame, text="文件", **sep).pack(fill=tk.X, pady=(8, 3))
        #         for fn in file_names:
        #             tk.Label(scroll_frame, text=f"  • {fn}", **body).pack(fill=tk.X)
        
        settings = info.get('settings', {})

        if settings:
            tk.Label(scroll_frame, text="设置", **sep).pack(fill=tk.X, pady=(10, 3))
            sf = tk.Frame(scroll_frame, bg=self.bg_color, relief='groove', borderwidth=1)
            sf.pack(fill=tk.X, ipady=5, ipadx=5)
            for sk, sv in settings.items():
                sr = tk.Frame(sf, bg=self.bg_color)
                sr.pack(fill=tk.X, pady=3)
                tk.Label(sr, text=sk, font=('微软雅黑', 9), bg=self.bg_color, fg='#ecf0f1', width=18, anchor=tk.W).pack(side=tk.LEFT, padx=5)

                if isinstance(sv, bool):
                    var = tk.BooleanVar(value=sv)
                    cb = tk.Checkbutton(sr, variable=var, font=('Microsoft YaHei UI', 10),
                                        bg=self.bg_color, fg='white', selectcolor='#3498db',
                                        activebackground=self.bg_color, activeforeground='white',
                                        command=lambda it=item, k=sk, v=var:
                                            self.on_addon_setting_change(it, k, v) if item_type == 'addon'
                                            else self.on_mod_setting_change(it, k, v))
                    cb.pack(side=tk.LEFT, padx=5)
                else:
                    ent = tk.Entry(sr, font=('Microsoft YaHei UI', 10), width=28, bg=self.bg_color, fg='white', relief='flat', borderwidth=1)
                    ent.insert(0, sv)
                    ent.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
                    ent.bind('<KeyRelease>', lambda e, it=item, k=sk, entr=ent:
                        self.on_addon_setting_change(it, k, entr) if item_type == 'addon'
                        else self.on_mod_setting_change(it, k, entr))
                    
        bf = {'font': ('Microsoft YaHei UI', 9), 'fg': 'white', 'relief': tk.FLAT, 'padx': 12, 'pady': 4, 'cursor': 'hand2'}

        # 插件按钮
        if item_type == 'addon':
            tk.Button(title_frame, text="▶ 运行", command=lambda: self.run_addon(item['name']), bg='#3498db', **bf).pack(side=tk.LEFT, padx=3)
            
        tk.Button(title_frame, text="📂 打开目录", command=lambda: self.open_addon_folder(item['path']), bg='#f39c12', **bf).pack(side=tk.LEFT, padx=3)
        del_cmd = self.delete_addon if item_type == 'addon' else self.delete_mod
        del_text = "🗑️ 删除插件" if item_type == 'addon' else "🗑️ 删除Mod"
        tk.Button(title_frame, text=del_text, command=lambda: (del_cmd(item['name']), detail.destroy()),
                  bg='#e74c3c', **bf).pack(side=tk.RIGHT, padx=3)

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
            
            # print(addon)
            if info['settings'].get('enable'):
                print(f"插件 {addon['name']} 已被启用，触发启用回调")
                self.addon_manager.when_addon_enabled(addon['name'])
            else:
                print(f"插件 {addon['name']} 已被禁用，触发禁用回调")
                self.addon_manager.when_addon_disabled(addon['name'])
            
            # 保存更新后的信息
            with open(addon_info_path, 'w', encoding='utf-8') as f:
                json.dump(info, f, indent=4, ensure_ascii=False)
            
            # 刷新插件列表
            self.refresh_addons_tab()
            
            self.app.core._on_reload_addons()
            
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
    
    def show_mods(self):
        mods_dir = ModManager.mod_dir
        if not os.path.exists(mods_dir):
            os.makedirs(mods_dir)
            self.all_mods = []
            return
        
        mods = []
        for item_path in ModManager.get_mod_path():
            if os.path.isdir(item_path):
                mod_info_path = os.path.join(item_path, 'mod_info.json')
                if os.path.exists(mod_info_path):
                    try:
                        with open(mod_info_path, 'r', encoding='utf-8') as f:
                            info = json.load(f)
                        mods.append({'name': os.path.basename(item_path), 'path': item_path, 'info': info})
                    except:
                        pass

        self.all_mods = mods
        self._load_enabled_state(self.all_mods, 'mod_info.json', self.mod_enabled)
        self.mod_page = 0
        self._display_page(self.mods_list_frame, self.mods_page_frame,
                           self.all_mods, self.mod_page, self.mod_enabled, 'mod')

    def _load_enabled_state(self, items, info_filename, enabled_dict):
        for item in items:
            info_path = os.path.join(item['path'], info_filename)
            try:
                if os.path.exists(info_path):
                    with open(info_path, 'r', encoding='utf-8') as f:
                        info = json.load(f)
                    enabled_dict[item['name']] = info.get('settings', {}).get('enable', True)
                else:
                    enabled_dict[item['name']] = True
            except:
                enabled_dict[item['name']] = True

    def _is_enabled(self, item_type, item_name):
        d = self.addon_enabled if item_type == 'addon' else self.mod_enabled
        return d.get(item_name, True)

    def _toggle_enabled(self, item_type, item):
        d = self.addon_enabled if item_type == 'addon' else self.mod_enabled
        info_filename = 'addon_info.json' if item_type == 'addon' else 'mod_info.json'
        current = d.get(item['name'], True)
        d[item['name']] = not current
        info_path = os.path.join(item['path'], info_filename)
        try:
            if os.path.exists(info_path):
                with open(info_path, 'r', encoding='utf-8') as f:
                    info = json.load(f)
                info['enabled'] = not current
                with open(info_path, 'w', encoding='utf-8') as f:
                    json.dump(info, f, indent=4, ensure_ascii=False)
        except:
            pass
        return not current

    def _addon_prev_page(self):
        if self.addon_page > 0:
            self.addon_page -= 1
            self._display_page(self.addons_list_frame, self.addons_page_frame,
                               self.all_addons, self.addon_page, self.addon_enabled, 'addon')

    def _addon_next_page(self):
        total = max(1, (len(self.all_addons) + self.items_per_page - 1) // self.items_per_page)
        if self.addon_page < total - 1:
            self.addon_page += 1
            self._display_page(self.addons_list_frame, self.addons_page_frame,
                               self.all_addons, self.addon_page, self.addon_enabled, 'addon')

    def _mod_prev_page(self):
        if self.mod_page > 0:
            self.mod_page -= 1
            self._display_page(self.mods_list_frame, self.mods_page_frame,
                               self.all_mods, self.mod_page, self.mod_enabled, 'mod')

    def _mod_next_page(self):
        total = max(1, (len(self.all_mods) + self.items_per_page - 1) // self.items_per_page)
        if self.mod_page < total - 1:
            self.mod_page += 1
            self._display_page(self.mods_list_frame, self.mods_page_frame,
                               self.all_mods, self.mod_page, self.mod_enabled, 'mod')

    def _display_page(self, list_frame, page_frame, items, page, enabled_dict, item_type):
        for widget in list_frame.winfo_children():
            widget.destroy()
        for widget in page_frame.winfo_children():
            widget.destroy()
        start = page * self.items_per_page
        page_items = items[start:start + self.items_per_page]

        for item in page_items:
            self._create_compact_row(list_frame, item, item_type, enabled_dict)

        for _ in range(len(page_items), self.items_per_page):
            f = tk.Frame(list_frame, bg=self.bg_color, height=72)
            f.pack(fill=tk.X, pady=2)
            f.pack_propagate(False)

        total = max(1, (len(items) + self.items_per_page - 1) // self.items_per_page)
        bcfg = {'font': ('Microsoft YaHei UI', 9), 'bg': self.lighten_bg_color, 'fg': 'white',
                'relief': tk.FLAT, 'padx': 10, 'pady': 2, 'cursor': 'hand2'}
        
        prev_cmd = self._addon_prev_page if item_type == 'addon' else self._mod_prev_page
        next_cmd = self._addon_next_page if item_type == 'addon' else self._mod_next_page

        tk.Button(page_frame, text="◀ 上一页", command=prev_cmd, **bcfg).pack(side=tk.LEFT, padx=10)
        tk.Label(page_frame, text=f"{page + 1} / {total}", font=('Microsoft YaHei UI', 10),
                 bg=self.bg_color, fg='#bdc3c7').pack(side=tk.LEFT, expand=True)
        tk.Button(page_frame, text="下一页 ▶", command=next_cmd, **bcfg).pack(side=tk.RIGHT, padx=10)

    def _create_compact_row(self, parent, item, item_type, enabled_dict):
        name_key = item['name']

        # print(item)
        # print(name_key)
        # print(enabled_dict)

        enabled = enabled_dict.get(name_key, True)

        row = tk.Frame(parent, bg=self.bg_color, height=72, relief='groove', borderwidth=1)
        row.pack(fill=tk.X, pady=2)
        row.pack_propagate(False)
        icon_path = os.path.join(item['path'], 'icon.png')
        if os.path.exists(icon_path):
            try:
                image = Image.open(icon_path)
                image = image.resize((48, 48), Image.Resampling.LANCZOS)
                icon = ImageTk.PhotoImage(image)
                icon_label = tk.Label(row, image=icon, bg=self.bg_color)
                icon_label.image = icon # type: ignore
                icon_label.pack(side=tk.LEFT, padx=(8, 8), pady=5)
            except:
                pass

        info_frame = tk.Frame(row, bg=self.bg_color)
        info_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, pady=5)
        display_name = item['info'].get('name', name_key)
        version = item['info'].get('version', '')
        title_text = f"{display_name}" + (f"  v{version}" if version else "")

        tk.Label(info_frame, text=title_text, font=('微软雅黑', 10, 'bold'),
                 bg=self.bg_color, fg='white', anchor=tk.W).pack(fill=tk.X)
        
        desc_raw = item['info'].get('desc', '无描述')
        desc_line = desc_raw.replace('\n', ' ').replace('\r', ' ').strip()
        if len(desc_line) > 30:
            desc_line = desc_line[:30] + '...'

        tk.Label(info_frame, text=desc_line, font=('微软雅黑', 8),
                 bg=self.bg_color, fg='#95a5a6', anchor=tk.W).pack(fill=tk.X)
        
        status_text = '● 已启用' if enabled else '● 已禁用'
        status_color = '#2ecc71' if enabled else '#e74c3c'
        tk.Label(row, text=status_text, font=('微软雅黑', 8, 'bold'),
                 bg=self.bg_color, fg=status_color).pack(side=tk.RIGHT, padx=(0, 5))
        
        detail_btn = tk.Button(row, text='⋯', font=('微软雅黑', 12, 'bold'),
                               bg=self.bg_color, fg='#bdc3c7', relief=tk.FLAT,
                               cursor='hand2', padx=8,
                               command=lambda i=item, t=item_type: self._show_detail(i, t))
        detail_btn.pack(side=tk.RIGHT, padx=(0, 5))
    
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
            
            # 刷新Mod列表
            self.refresh_mods_tab()

        except Exception as e:
            print(f"更新Mod设置失败: {e}")
            messagebox.showerror("错误", f"更新Mod设置失败: {str(e)}")
    
    def delete_mod(self, mod_name):
        """删除Mod"""
        mod_path = os.path.join(ModManager.mod_dir, mod_name)
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
        self.show_mods()
    
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
                self.app.core._on_reload_addons()
            else:
                messagebox.showerror("错误", f"删除插件 {addon_name} 失败")
    
    def refresh_addons_tab(self):
        self.show_addons()

    def refresh_all_tabs(self):
        """刷新所有标签页"""
        self.refresh_addons_tab()
        self.refresh_mods_tab()

def init_mod_addon_manager(parent_frame, bg_color, lighten_bg_color, app):
    """初始化插件&mod管理器页面"""
    return ModAddonManagerPage(parent_frame, bg_color, lighten_bg_color, app)