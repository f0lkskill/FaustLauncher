import tkinter as tk
from tkinter import ttk, filedialog, messagebox, colorchooser
from functions.base.settings_manager import get_settings_manager
from functions.base.color_scheme import C, ThemeColors, border_color
from functions.base.custom_notebook import CustomNotebook
from functions.base.style_utils import apply_scrollbar_style, RoundedFrame, RoundedButton
from functions.base.animation_ulits import smooth_scroll

# ===== 统一字体配置 - 现代化 =====
_TITLE_FONT = ('Microsoft YaHei UI', 12, 'bold')
_DESC_FONT = ('Microsoft YaHei UI', 9)
_CONTROL_FONT = ('Microsoft YaHei UI', 10)
_SMALL_FONT = ('Microsoft YaHei UI', 9)
_BUTTON_FONT = ('Microsoft YaHei UI', 9, 'bold')
_BIG_BUTTON_FONT = ('Microsoft YaHei UI', 11, 'bold')


class SettingsPage:
    def __init__(self, parent_frame, bg_color, lighten_bg_color):
        self.parent = parent_frame
        self.settings_manager = get_settings_manager()
        self.setting_widgets = {}
        self.bg_color = bg_color
        self.lighten_bg_color = lighten_bg_color
        self.theme = ThemeColors(bg_color)
        self._card_bg = self.theme.surface
        self._card_border = self.theme.card_border
        self._entry_bg = self.theme.entry_bg
        self._trough_color = self.theme.trough

        self._anim_states = {}
        self._canvas_list = []

        self._scrollbar_style = apply_scrollbar_style(
            'Settings.Vertical.TScrollbar', bg_color, C.ACCENT)

        self.create_widgets()
        self.auto_refresh()

    def create_widgets(self):
        outer_frame = RoundedFrame(self.parent,
                                   bg=self.lighten_bg_color,
                                   border_color=border_color(self.lighten_bg_color),
                                   radius=8)
        outer_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)

        content_frame = tk.Frame(outer_frame.inner, bg=self.lighten_bg_color)
        content_frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=12)

        # 创建标签页
        self.notebook = CustomNotebook(content_frame, bg=self.bg_color, accent=C.ACCENT)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=2, pady=(0, 8))

        settings_by_page = self.group_settings_by_page()
        page_names = list(settings_by_page.keys())
        for page_name in page_names:
            page_frame = tk.Frame(self.notebook, bg=self.bg_color)  # 用 tk.Frame 控制底色，避免受 ttk 默认主题影响
            self.notebook.add(page_frame, text=page_name)
            self.create_scrollable_settings_area(page_frame, settings_by_page[page_name])

        # 操作按钮区域
        button_frame = tk.Frame(content_frame, bg=self.lighten_bg_color)
        button_frame.pack(fill=tk.X, pady=(6, 0), padx=10)

        # 圆角重置按钮
        reset_all_btn = RoundedButton(button_frame, text="↺ 重置所有设置",
                                      command=self.reset_all_settings,
                                      width=180, height=36,
                                      bg=C.WARNING,
                                      hover_bg=C.WARNING_HOVER,
                                      font=_BIG_BUTTON_FONT,
                                      radius=7)
        reset_all_btn.pack(anchor=tk.CENTER, padx=10)

    def group_settings_by_page(self):
        """按page分组设置项"""
        settings = self.settings_manager.get_all_settings()
        settings_by_page = {}
        for key, setting_info in settings.items():
            if setting_info.get('type') == 'UNABLE_TO_EDIT':
                continue
            page = setting_info.get('page', '通用')
            if page not in settings_by_page:
                settings_by_page[page] = []
            settings_by_page[page].append((key, setting_info))
        return settings_by_page

    def create_scrollable_settings_area(self, parent, settings_list):
        """创建可滚动的设置区域"""
        canvas_holder = tk.Frame(parent, bg=self.lighten_bg_color)
        canvas_holder.pack(fill=tk.BOTH, expand=True)

        canvas = tk.Canvas(canvas_holder, bg=self.bg_color,
                           highlightthickness=1,
                           highlightbackground=border_color(self.bg_color),
                           bd=0)
        scrollbar = ttk.Scrollbar(canvas_holder, orient="vertical",
                                  command=canvas.yview,
                                  style='Settings.Vertical.TScrollbar')
        scrollable_frame = tk.Frame(canvas, bg=self.bg_color)

        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        def _sync_canvas_width(event):
            canvas.itemconfigure('scroll_window', width=event.width)
        canvas.bind('<Configure>', _sync_canvas_width)

        canvas.create_window((0, 0), window=scrollable_frame,
                             anchor="nw", tags='scroll_window')
        canvas.configure(yscrollcommand=scrollbar.set)

        self.create_settings_controls(scrollable_frame, settings_list)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self._canvas_list.append(canvas)
        self._anim_states[id(canvas)] = {'target': 0.0, 'current': 0.0,
                                         'start': 0.0, 'step': 0, 'steps': 0,
                                         'anim_id': None}

        def _on_mousewheel(event):
            smooth_scroll(self, canvas, event.delta, self._anim_states[id(canvas)])

        canvas.bind("<MouseWheel>", _on_mousewheel)
        scrollable_frame.bind("<MouseWheel>", _on_mousewheel)
        self._bind_mousewheel_recursive(scrollable_frame, _on_mousewheel)

    def _animate_scroll_step(self, canvas):
        """单帧动画：ease-in-out cubic"""
        state = self._anim_states.get(id(canvas))
        if state is None or state['steps'] <= 0:
            return

        state['step'] += 1
        t = state['step'] / state['steps']
        # ease-in-out cubic: 3t² - 2t³
        eased = t * t * (3 - 2 * t) if t < 1 else 1.0

        target = state['target']
        start = state.get('start', state['current'])
        new_frac = start + (target - start) * eased
        new_frac = max(0.0, min(1.0, new_frac))

        try:
            canvas.yview_moveto(new_frac)
        except tk.TclError:
            return

        state['current'] = new_frac

        if state['step'] < state['steps'] and abs(target - new_frac) > 0.0008:
            state['anim_id'] = canvas.after(12,
                                            lambda c=canvas: self._animate_scroll_step(c))
        else:
            state['anim_id'] = None
            state['current'] = target

    def _bind_mousewheel_recursive(self, widget, handler):
        """递归绑定鼠标滚轮事件，跳过 Combobox/Spinbox 等表单控件"""
        try:
            klass = widget.winfo_class()
            if klass not in ('TCombobox', 'TSpinbox'):
                widget.bind("<MouseWheel>", handler)
        except tk.TclError:
            pass
        for child in widget.winfo_children():
            self._bind_mousewheel_recursive(child, handler)

    def create_settings_controls(self, parent, settings_list):
        """动态生成设置控件"""
        tk.Frame(parent, bg=self.bg_color, height=8).pack(fill=tk.X)

        for i, (key, setting_info) in enumerate(settings_list):
            setting_type = setting_info.get('type', 'UNABLE_TO_EDIT')
            if setting_type == 'UNABLE_TO_EDIT':
                continue

            # 边框用 _card_border，保证有清晰边界
            card_frame = tk.Frame(parent, bg=self._card_bg,
                                  relief='flat', borderwidth=0,
                                  highlightthickness=1,
                                  highlightbackground=border_color(self._card_bg))
            card_frame.pack(fill=tk.X, padx=18, pady=6)

            setting_frame = tk.Frame(card_frame, bg=self._card_bg)
            setting_frame.pack(fill=tk.X, padx=16, pady=12)

            setting_name = setting_info.get('name', setting_info.get('description', key))
            title_label = tk.Label(setting_frame,
                                   text=setting_name,
                                   font=_TITLE_FONT,
                                   bg=self._card_bg, fg=C.TEXT_PRIMARY)
            title_label.pack(anchor=tk.W, pady=(0, 4))

            if 'description' in setting_info and setting_info['description'] != setting_name:
                desc_label = tk.Label(setting_frame,
                                      text=setting_info['description'],
                                      font=_DESC_FONT,
                                      bg=self._card_bg, fg=C.TEXT_SECONDARY,
                                      wraplength=600, justify=tk.LEFT)
                desc_label.pack(anchor=tk.W, pady=(0, 8))

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

            # 圆角重置按钮
            reset_btn = RoundedButton(setting_frame, text="↺ 重置",
                                      command=lambda k=key: self.reset_setting(k),
                                      width=70, height=26,
                                      bg=C.DANGER_HOVER,
                                      hover_bg=C.DANGER_DARK,
                                      font=_SMALL_FONT,
                                      radius=6)
            reset_btn.pack(anchor=tk.E, pady=(6, 0))

        tk.Frame(parent, bg=self.bg_color, height=10).pack(fill=tk.X)

    def create_combobox_control(self, parent, key, setting_info, current_value):
        control_frame = tk.Frame(parent, bg=self._card_bg)
        control_frame.pack(fill=tk.X, pady=4)

        options = setting_info.get('options', [])
        combobox = ttk.Combobox(control_frame,
                                values=options,
                                style='App.TCombobox',
                                font=_CONTROL_FONT,
                                state='readonly',
                                width=45)

        if isinstance(current_value, int) and 0 <= current_value < len(options):
            combobox.set(options[current_value])
        else:
            combobox.set(options[0] if options else "")

        combobox.bind('<<ComboboxSelected>>',
                      lambda e, k=key, cb=combobox, opts=options:
                          self.on_combobox_change(k, cb, opts))
        combobox.pack(fill=tk.X, expand=True)
        self.setting_widgets[key] = combobox

    def on_combobox_change(self, key, combobox, options):
        selected_text = combobox.get()
        selected_index = options.index(selected_text) if selected_text in options else 0
        self.settings_manager.set_setting(key, selected_index)

    def create_boolean_control(self, parent, key, setting_info, current_value):
        var = tk.BooleanVar(value=current_value)
        checkbox_text = "  启用该选项"

        control_frame = tk.Frame(parent, bg=self._card_bg)
        control_frame.pack(fill=tk.X, pady=4)

        checkbox = tk.Checkbutton(control_frame,
                                  text=checkbox_text,
                                  variable=var,
                                  command=lambda: self.on_boolean_change(key, var),
                                  font=_CONTROL_FONT,
                                  bg=self._card_bg, fg=C.TEXT_PRIMARY,
                                  selectcolor=C.ACCENT,
                                  activebackground=self._card_bg,
                                  activeforeground=C.TEXT_PRIMARY,
                                  cursor='hand2',
                                  highlightthickness=0, bd=0)
        checkbox.pack(anchor=tk.W)
        self.setting_widgets[key] = var

    def create_string_control(self, parent, key, setting_info, current_value):
        control_frame = tk.Frame(parent, bg=self._card_bg)
        control_frame.pack(fill=tk.X, pady=4)

        if key == 'game_path':
            entry = tk.Entry(control_frame,
                             font=_CONTROL_FONT,
                             width=45,
                             relief='flat',
                             bg=self._entry_bg,
                             fg=C.TEXT_PRIMARY,
                             insertbackground=C.TEXT_PRIMARY,
                             highlightthickness=1,
                             highlightbackground=self._card_border,
                             highlightcolor=C.ACCENT)
            entry.insert(0, current_value)
            entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))

            browse_btn = RoundedButton(control_frame, text="浏览",
                                       command=lambda: self.browse_game_path(entry),
                                       width=60, height=26,
                                       bg=C.ACCENT,
                                       hover_bg=C.LEGACY_BLUE_HOVER,
                                       font=_BUTTON_FONT,
                                       radius=6)
            browse_btn.pack(side=tk.RIGHT)
        else:
            entry = tk.Entry(control_frame,
                             font=_CONTROL_FONT,
                             relief='flat',
                             bg=self._entry_bg,
                             fg=C.TEXT_PRIMARY,
                             insertbackground=C.TEXT_PRIMARY,
                             highlightthickness=1,
                             highlightbackground=self._card_border,
                             highlightcolor=C.ACCENT)
            entry.insert(0, current_value)
            entry.pack(fill=tk.X, expand=True)
            entry.bind('<KeyRelease>', lambda e, k=key: self.on_string_change(k, entry))

        self.setting_widgets[key] = entry

    def create_numeric_control(self, parent, key, setting_info, current_value):
        control_frame = tk.Frame(parent, bg=self._card_bg)
        control_frame.pack(fill=tk.X, pady=4)

        min_val = setting_info.get('min', 0)
        max_val = setting_info.get('max', 100)
        step = setting_info.get('step', 1)
        is_int = setting_info.get('type') == 'integer'

        value_text = (f"当前值: {int(current_value)}" if is_int
                      else f"当前值: {current_value:.1f}")

        value_label = tk.Label(control_frame,
                               text=value_text,
                               font=_SMALL_FONT,
                               bg=self._card_bg, fg=C.TEXT_MUTED)
        value_label.pack(anchor=tk.W, pady=(0, 2))

        range_label = tk.Label(control_frame,
                               text=f"范围: {min_val} ~ {max_val}  (步长: {step})",
                               font=('Microsoft YaHei UI', 8),
                               bg=self._card_bg, fg=C.TEXT_MUTED)
        range_label.pack(anchor=tk.E, pady=(0, 2))

        # 滑动条：槽色与卡片底色形成对比
        scale = tk.Scale(control_frame,
                         from_=min_val, to=max_val,
                         resolution=step,
                         orient=tk.HORIZONTAL,
                         length=300,
                         showvalue=False,
                         command=lambda v, k=key, l=value_label, is_int=is_int:
                             self.on_scale_change(k, v, l, is_int),
                         bg=self._card_bg,
                         fg=C.TEXT_PRIMARY,
                         troughcolor=self._trough_color,
                         activebackground=C.ACCENT,
                         highlightthickness=1,
                         highlightbackground=self._card_border,
                         cursor='hand2',
                         bd=0)
        scale.set(current_value)
        scale.pack(fill=tk.X, expand=True)
        self.setting_widgets[key] = scale

    def create_color_control(self, parent, key, setting_info, current_value):
        control_frame = tk.Frame(parent, bg=self._card_bg)
        control_frame.pack(fill=tk.X, pady=4)

        color_frame = tk.Frame(control_frame, bg=current_value,
                               width=56, height=34,
                               relief='flat', borderwidth=0,
                               highlightthickness=1,
                               highlightbackground=self._card_border)
        color_frame.pack_propagate(False)
        color_frame.pack(side=tk.LEFT, padx=(0, 10))

        color_entry = tk.Entry(control_frame, font=_CONTROL_FONT, width=12,
                               relief='flat',
                               bg=self._entry_bg,
                               fg=C.TEXT_PRIMARY,
                               insertbackground=C.TEXT_PRIMARY,
                               highlightthickness=1,
                               highlightbackground=self._card_border,
                               highlightcolor=C.ACCENT)
        color_entry.insert(0, current_value)
        color_entry.pack(side=tk.LEFT, padx=(0, 8))
        color_entry.bind('<KeyRelease>',
                         lambda e, k=key, ce=color_entry, cf=color_frame:
                             self.on_color_entry_change(k, ce, cf))

        color_btn = RoundedButton(control_frame, text="选择颜色",
                                  command=lambda k=key, ce=color_entry, cf=color_frame:
                                      self.on_color_button_click(k, ce, cf),
                                  width=80, height=26,
                                  bg=C.ACCENT,
                                  hover_bg=C.LEGACY_BLUE_HOVER,
                                  font=_BUTTON_FONT,
                                  radius=6)
        color_btn.pack(side=tk.LEFT)

        self.setting_widgets[key] = color_entry

    def on_boolean_change(self, key, var):
        self.settings_manager.set_setting(key, var.get())

    def on_string_change(self, key, entry):
        self.settings_manager.set_setting(key, entry.get())

    def on_scale_change(self, key, value, value_label, is_int=False):
        value = float(value)
        stored_value = int(value) if is_int else value
        self.settings_manager.set_setting(key, stored_value)
        value_label.config(text=f"当前值: {int(value)}" if is_int else f"当前值: {value:.1f}")

    def on_color_entry_change(self, key, entry, color_frame):
        color_value = entry.get().strip()
        if not color_value:
            return
        try:
            color_frame.config(bg=color_value)
            self.settings_manager.set_setting(key, color_value)
        except (tk.TclError, Exception):
            pass

    def on_color_button_click(self, key, entry, color_frame):
        current_color = entry.get().strip() or '#ffffff'
        try:
            result = colorchooser.askcolor(initialcolor=current_color)
            color = result[1] if result else None
        except (tk.TclError, Exception):
            color = None
        if color:
            entry.delete(0, tk.END)
            entry.insert(0, color)
            color_frame.config(bg=color)
            self.settings_manager.set_setting(key, color)

    def browse_game_path(self, entry):
        path = filedialog.askopenfilename(
            title="选择边狱巴士主程序",
            filetypes=[("边狱巴士主程序", "LimbusCompany.exe")])
        if not path:
            return
        if path.endswith('LimbusCompany.exe'):
            path = path[:-len('LimbusCompany.exe')]
        entry.delete(0, tk.END)
        entry.insert(0, path)
        self.settings_manager.set_setting('game_path', path)

    def reset_setting(self, key):
        setting_info = self.settings_manager.get_setting_info(key)
        setting_name = (setting_info.get('name', setting_info.get('description', key))
                        if setting_info else key)

        if self.settings_manager.reset_setting(key):
            self.save_all_settings()
            self.refresh_all_displays()
            messagebox.showinfo("成功", f"已重置设置项: {setting_name}")

    def reset_all_settings(self):
        if messagebox.askyesno("确认", "确定要重置所有设置为默认值吗？"):
            self.settings_manager.reset_all_settings()
            self.save_all_settings()
            self.refresh_all_displays()
            messagebox.showinfo("成功", "已重置所有设置")

    def save_all_settings(self):
        if self.settings_manager.save_settings():
            pass
        else:
            messagebox.showerror("错误", "保存设置失败")

    def refresh_setting_display(self, key):
        current_value: str = self.settings_manager.get_setting(key) # type: ignore
        setting_info: dict = self.settings_manager.get_setting_info(key)  # type: ignore

        if key in self.setting_widgets:
            widget = self.setting_widgets[key]
            setting_type = setting_info.get('type', 'string')

            if setting_type == 'boolean':
                try:
                    widget.set(current_value)
                except (tk.TclError, AttributeError):
                    pass
            elif setting_type == 'string':
                if isinstance(widget, tk.Entry):
                    widget.delete(0, tk.END)
                    widget.insert(0, current_value)
            elif setting_type in ['integer', 'float']:
                try:
                    widget.set(current_value)
                except (tk.TclError, AttributeError):
                    pass
            elif setting_type == 'color':
                if isinstance(widget, tk.Entry):
                    widget.delete(0, tk.END)
                    widget.insert(0, current_value)
                    color_frame = widget.master.winfo_children()[0]
                    if hasattr(color_frame, 'config'):
                        try:
                            color_frame.config(bg=current_value) # type: ignore
                        except (tk.TclError, Exception):
                            pass
            elif setting_type == 'combobox':
                if isinstance(widget, ttk.Combobox):
                    options = setting_info.get('options', [])
                    if isinstance(current_value, int) and 0 <= current_value < len(options):
                        widget.set(options[current_value])
                    else:
                        widget.set(options[0] if options else "")

    def refresh_all_displays(self):
        for key in self.settings_manager.get_all_settings():
            self.refresh_setting_display(key)

    def auto_refresh(self):
        self.save_all_settings()
        self.parent.after(1000, self.auto_refresh)


def init_settings_page(parent_frame, bg_color: str, lighten_bg_color: str) -> SettingsPage:
    return SettingsPage(parent_frame, bg_color, lighten_bg_color)