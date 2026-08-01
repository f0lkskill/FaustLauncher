"""
统一 UI 样式工具 — 滚动条、圆角卡片、现代化按钮
"""
import tkinter as tk
from tkinter import ttk
from functions.base.color_scheme import C, darken_color, lighten_color


def apply_scrollbar_style(style_name='App.Vertical.TScrollbar',
                          bg_color='#1a1a1a',
                          accent=C.ACCENT):
    """创建并返回统一的自定义滚动条样式名"""
    style = ttk.Style()
    thumb = darken_color(lighten_color(bg_color, 8), 0.75)
    trough = darken_color(bg_color, 0.7)
    
    v_name = style_name
    h_name = style_name.replace('Vertical', 'Horizontal')
    
    for name in (v_name, h_name):
        try:
            style.configure(name,
                           background=thumb, bordercolor=thumb,
                           arrowcolor=C.TEXT_MUTED, troughcolor=trough,
                           gripcount=0, relief='flat', borderwidth=0, width=8)
            style.map(name, background=[('active', accent), ('disabled', thumb)])
        except tk.TclError:
            pass
    return v_name


def make_scrollbar(parent, orient='vertical', style_name='App.Vertical.TScrollbar', **kw):
    return ttk.Scrollbar(parent, orient=orient, style=style_name, **kw) # type: ignore


class RoundedFrame(tk.Canvas):
    """圆角卡片容器 — 填充和描边都是圆角"""
    
    def __init__(self, master, *, bg=None, border_color=None, radius=10,
                 padx=10, pady=10, **kwargs):
        self._bg = bg or '#1a1a1a'
        self._border = border_color or lighten_color(self._bg, 15)
        self._radius = radius
        self._padx = max(padx, radius + 4)
        self._pady = max(pady, radius + 4)
        
        super().__init__(master, bg=self._bg, highlightthickness=0, bd=0, **kwargs)
        self.inner = tk.Frame(self, bg=self._bg, bd=0, highlightthickness=0)
        self.bind('<Configure>', self._redraw)
    
    def _redraw(self, event=None):
        self.delete('rf')
        w = self.winfo_width()
        h = self.winfo_height()
        if w < 8 or h < 8:
            return
        r = self._radius
        d = r * 2
        t = 'rf'
        
        # 圆角填充（pieslice 会被 canvas 自动裁剪，无需偏移）
        self.create_arc(0, 0, d, d, start=90, extent=90, style='pieslice',
                       fill=self._bg, outline='', width=0, tags=t)
        self.create_arc(w - d, 0, w, d, start=0, extent=90, style='pieslice',
                       fill=self._bg, outline='', width=0, tags=t)
        self.create_arc(0, h - d, d, h, start=180, extent=90, style='pieslice',
                       fill=self._bg, outline='', width=0, tags=t)
        self.create_arc(w - d, h - d, w, h, start=270, extent=90, style='pieslice',
                       fill=self._bg, outline='', width=0, tags=t)
        self.create_rectangle(r, 0, w - r, h, fill=self._bg, outline='', width=0, tags=t)
        self.create_rectangle(0, r, w, h - r, fill=self._bg, outline='', width=0, tags=t)
        
        # 圆角描边（右/下边缘向内缩 1px，避免被父容器裁剪导致描边消失）
        if self._border:
            bw = w - 1
            bh = h - 1
            self.create_arc(0, 0, d, d, start=90, extent=90, style='arc',
                           outline=self._border, tags=t)
            self.create_arc(bw - d, 0, bw, d, start=0, extent=90, style='arc',
                           outline=self._border, tags=t)
            self.create_arc(0, bh - d, d, bh, start=180, extent=90, style='arc',
                           outline=self._border, tags=t)
            self.create_arc(bw - d, bh - d, bw, bh, start=270, extent=90, style='arc',
                           outline=self._border, tags=t)
            self.create_line(r, 0, bw - r, 0, fill=self._border, tags=t)
            self.create_line(r, bh, bw - r, bh, fill=self._border, tags=t)
            self.create_line(0, r, 0, bh - r, fill=self._border, tags=t)
            self.create_line(bw, r, bw, bh - r, fill=self._border, tags=t)
        
        self.create_window(self._padx, self._pady, window=self.inner, anchor='nw',
                          width=w - self._padx * 2, height=h - self._pady * 2, tags=t)
    
    def fit_content(self):
        self.inner.update_idletasks()
        needed = self.inner.winfo_reqheight() + self._pady * 2
        self.configure(height=needed)


class RoundedButton(tk.Canvas):
    """圆角按钮 — 纯 Canvas 实现，自带 hover"""
    
    def __init__(self, master, text='', command=None, *,
                 width=120, height=36, bg=C.ACCENT, fg=C.TEXT_WHITE,
                 hover_bg=None, font=('Microsoft YaHei UI', 10, 'bold'),
                 radius=8, state='normal', **kwargs):
        self._w = width
        self._h = height
        self._bg = bg
        self._fg = fg
        self._hover_bg = hover_bg or darken_color(bg, 0.85)
        self._radius = radius
        self._command = command
        self._text = text
        self._font = font
        self._state = state
        
        try:
            master_bg = master.cget('bg')
        except Exception:
            master_bg = None
        if not master_bg or master_bg == 'SystemButtonFace':
            master_bg = self._bg
        self._canvas_bg = master_bg
        
        super().__init__(master, width=width, height=height,
                        bg=self._canvas_bg,
                        highlightthickness=0, bd=0,
                        cursor='hand2' if state == 'normal' else '',
                        **kwargs)
        self._is_button = True
        
        if state == 'normal':
            self.bind('<Button-1>', self._on_click)
            self.bind('<Enter>', self._on_enter)
            self.bind('<Leave>', self._on_leave)
        self.bind('<Configure>', self._on_configure)
        self.after(10, self._initial_draw)
    
    def _on_click(self, event):
        if self._command:
            self._command()
    
    def _on_enter(self, event):
        self._draw(self._hover_bg)
    
    def _on_leave(self, event):
        self._draw(self._bg)
    
    def _on_configure(self, event):
        self._draw(self._bg)
    
    def _initial_draw(self):
        self._draw(self._bg)
    
    def _draw(self, fill):
        self.delete('btn')
        w = self.winfo_width()
        h = self.winfo_height()
        if w < 4 or h < 4:
            return
        r = self._radius
        d = r * 2
        t = 'btn'
        
        self.create_arc(0, 0, d, d, start=90, extent=90, style='pieslice',
                       fill=fill, outline='', width=0, tags=t)
        self.create_arc(w - d, 0, w, d, start=0, extent=90, style='pieslice',
                       fill=fill, outline='', width=0, tags=t)
        self.create_arc(0, h - d, d, h, start=180, extent=90, style='pieslice',
                       fill=fill, outline='', width=0, tags=t)
        self.create_arc(w - d, h - d, w, h, start=270, extent=90, style='pieslice',
                       fill=fill, outline='', width=0, tags=t)
        
        self.create_rectangle(r - 1, 0, w - r + 1, h, fill=fill, outline='', width=0, tags=t)
        self.create_rectangle(0, r - 1, w, h - r + 1, fill=fill, outline='', width=0, tags=t)
        
        self.create_text(w / 2, h / 2 - 1, text=self._text,
                        fill=self._fg, font=self._font, tags=t)
    
    def configure(self, **kwargs):
        if 'text' in kwargs:
            self._text = kwargs.pop('text')
        if 'bg' in kwargs:
            self._bg = kwargs.pop('bg')
        if 'command' in kwargs:
            self._command = kwargs.pop('command')
        super().configure(**kwargs)
        self._draw(self._bg)
    
    def pack(self, **kwargs):
        super().pack(**kwargs)
        return self


class ModernButton(tk.Button):
    """扁平 tk.Button — 自带 hover"""
    
    def __init__(self, master, text='', command=None,
                 bg=None, fg=C.TEXT_WHITE, hover_bg=None,
                 font=('Microsoft YaHei UI', 10, 'bold'),
                 padx=16, pady=6, **kwargs):
        bg = bg or C.ACCENT
        hover_bg = hover_bg or darken_color(bg, 0.85)
        super().__init__(master, text=text, command=command, # type: ignore
                        bg=bg, fg=fg, font=font,
                        relief='flat', borderwidth=0,
                        padx=padx, pady=pady,
                        cursor='hand2',
                        activebackground=hover_bg,
                        activeforeground=fg, **kwargs)
        self._normal_bg = bg
        self._hover_bg = hover_bg
        self.bind('<Enter>', lambda e: self.configure(bg=self._hover_bg))
        self.bind('<Leave>', lambda e: self.configure(bg=self._normal_bg))
