"""
自定义标签页组件 — 不依赖 ttk 主题，纯 tk 实现
所有机器外观一致，支持完整的现代化样式定制
"""
import tkinter as tk
from functions.base.color_scheme import C


class CustomNotebook(tk.Frame):
    def __init__(self, master, *, bg=None, accent=None, **kwargs):
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
        """在两色之间混合"""
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
            if self._current_index != i:
                b.configure(fg=C.TEXT_PRIMARY, bg=self._tab_hover_bg)
        
        def on_leave(e, b=btn, i=idx):
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
        def _place():
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
        if sequence == '<<NotebookTabChanged>>':
            self._tab_changed_callbacks.append(callback)
        else:
            super().bind(sequence, callback, add)
    
    @property
    def current_index(self) -> int:
        return self._current_index
