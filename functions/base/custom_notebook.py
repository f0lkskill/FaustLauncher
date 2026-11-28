"""自绘标签页容器，替代 ttk.Notebook 以完全控制外观。

顶部是一排扁平按钮，选中项下方有强调色指示条；切换时把对应 frame
``pack`` 到内容区，并通过 ``<<NotebookTabChanged>>`` 伪事件通知调用方。
"""

import tkinter as tk
from functions.base.color_scheme import C

class CustomNotebook(tk.Frame):
    """带自定义标签栏和切换回调的 Frame 容器。"""

    def __init__(self, master, *, bg=None, accent=None, **kwargs):
        """Args:
            master: 父控件。
            bg: 背景色，默认深色。
            accent: 选中态/指示条颜色，默认 C.ACCENT。
        """
        bg = bg or '#1a1a1a'
        super().__init__(master, bg=bg, bd=0, highlightthickness=0, **kwargs)
        
        self._bg = bg
        self._accent = accent or C.ACCENT
        self._tab_hover_bg = self._blend(bg, self._accent, 0.06)
        self._tabs: list[dict] = []
        self._current_index = -1
        self._tab_changed_callbacks: list[callable] = [] # type: ignore
        
        self._tab_bar = tk.Frame(self, bg=bg, height=40, bd=0, highlightthickness=0)
        self._tab_bar.pack(fill=tk.X, side=tk.TOP)
        self._tab_bar.pack_propagate(False)
        
        self._tab_center = tk.Frame(self._tab_bar, bg=bg, bd=0, highlightthickness=0)
        self._tab_center.pack(expand=True)
        
        self._separator = tk.Frame(self, bg=self._blend(bg, '#ffffff', 0.08), height=1, bd=0)
        self._separator.pack(fill=tk.X, side=tk.TOP, before=self._tab_bar)
        self._separator.pack_forget()
        
        self._bottom_line = tk.Frame(self, bg=self._blend(bg, '#ffffff', 0.06), height=1, bd=0)
        self._bottom_line.pack(fill=tk.X, side=tk.TOP)
        
        self._tab_buttons: list[tk.Button] = []
        self._indicator = tk.Frame(self._tab_center, bg=self._accent, height=3, bd=0)
    
    def _blend(self, bg: str, fg: str, ratio: float) -> str:
        """按比例混合两个 ``#RRGGBB`` 颜色，解析失败时退回 bg。"""
        try:
            br = int(bg[1:3], 16); bg_r = int(bg[3:5], 16); bb = int(bg[5:7], 16)
            fr = int(fg[1:3], 16); fg_g = int(fg[3:5], 16); fb = int(fg[5:7], 16)
            r = int(br + (fr - br) * ratio)
            g = int(bg_r + (fg_g - bg_r) * ratio)
            b = int(bb + (fb - bb) * ratio)
            return f'#{r:02x}{g:02x}{b:02x}'
        except Exception:
            return bg
    
    def add(self, frame: tk.Frame, text: str):
        """追加一个标签页；第一个标签页会自动选中。

        Args:
            frame: 已经建好内容的页面 Frame（背景色会被统一）。
            text: 标签按钮文字。
        """
        frame.configure(bg=self._bg)
        
        btn = tk.Button(
            self._tab_bar, text=text,
            bg=self._bg, fg=C.TEXT_MUTED,
            font=('Microsoft YaHei UI', 9),
            relief='flat', borderwidth=0, padx=10, pady=10,
            cursor='hand2', bd=0, highlightthickness=0,
            activebackground=self._bg,
            activeforeground=C.TEXT_PRIMARY,
        )
        idx = len(self._tabs)
        
        btn.configure(command=lambda i=idx: self.select(i))
        
        def on_enter(e, b=btn, i=idx):
            """响应enter。"""
            if self._current_index != i:
                b.configure(fg=C.TEXT_PRIMARY, bg=self._tab_hover_bg)
        
        def on_leave(e, b=btn, i=idx):
            """响应leave。"""
            if self._current_index != i:
                b.configure(fg=C.TEXT_MUTED, bg=self._bg)
        
        btn.bind('<Enter>', on_enter)
        btn.bind('<Leave>', on_leave)
        btn.pack(side=tk.LEFT, in_=self._tab_center)
        
        self._tab_buttons.append(btn)
        self._tabs.append({'frame': frame, 'text': text, 'button': btn})
        
        if self._current_index != -1:
            frame.pack_forget()
        
        if self._current_index == -1:
            self.select(0)
    
    def select(self, index: int):
        """切到指定下标的标签页；越界或已是当前页时什么都不做。"""
        if index < 0 or index >= len(self._tabs) or index == self._current_index:
            return
        
        old_index = self._current_index
        
        for i, tab in enumerate(self._tabs):
            tab['frame'].pack_forget()
            btn = self._tab_buttons[i]
            if i == index:
                btn.configure(fg=self._accent, bg=self._bg)
            else:
                btn.configure(fg=C.TEXT_MUTED, bg=self._bg)
        
        selected_frame = self._tabs[index]['frame']
        selected_frame.pack(fill=tk.BOTH, expand=True, after=self._bottom_line)
        self._current_index = index
        
        self._update_indicator(index)
        
        if old_index != index:
            event = type('Event', (), {'widget': self, 'x': 0, 'y': 0})()
            for cb in self._tab_changed_callbacks:
                cb(event)
    
    def _update_indicator(self, index: int):
        """把强调色指示条放到目标按钮下方；延后 10ms 等布局稳定。"""
        def _place():
            """内部place相关处理。"""
            self._indicator.place_forget()
            btn = self._tab_buttons[index]
            self._tab_center.update_idletasks()
            btn.update_idletasks()
            self._indicator.place(
                x=btn.winfo_x() + 4, y=37,
                width=max(btn.winfo_width() - 8, 1), height=3
            )
        self.after(10, _place)
    
    def bind(self, sequence: str, callback: callable, add=None): # type: ignore
        """重写 bind：截获 ``<<NotebookTabChanged>>`` 存进回调列表。"""
        if sequence == '<<NotebookTabChanged>>':
            self._tab_changed_callbacks.append(callback)
        else:
            super().bind(sequence, callback, add)
    
    @property
    def current_index(self) -> int:
        """当前选中标签页下标；没有标签页时为 -1。"""
        return self._current_index
