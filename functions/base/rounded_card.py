"""
圆角绘制工具 — 在 Canvas 上画圆角矩形
"""
import tkinter as tk


def draw_rounded_rect(canvas: tk.Canvas, x: float, y: float, w: float, h: float, *,
                      fill: str = '', outline: str = '', radius: int = 10, **kw):
    """在 Canvas 上绘制圆角矩形，返回绘制的 item id 列表"""
    r = radius
    d = r * 2
    rx = x + w - 1
    ry = y + h - 1
    ids = []
    
    if fill:
        ids.append(canvas.create_rectangle(x + r, y, rx - r, ry + 1, fill=fill, outline='', width=0, **kw))
        ids.append(canvas.create_rectangle(x, y + r, rx + 1, ry - r, fill=fill, outline='', width=0, **kw))
    
    if outline:
        ids.append(canvas.create_arc(x, y, x + d, y + d, start=90, extent=90, style='arc', outline=outline, **kw))
        ids.append(canvas.create_arc(rx - d, y, rx, y + d, start=0, extent=90, style='arc', outline=outline, **kw))
        ids.append(canvas.create_arc(x, ry - d, x + d, ry, start=180, extent=90, style='arc', outline=outline, **kw))
        ids.append(canvas.create_arc(rx - d, ry - d, rx, ry, start=270, extent=90, style='arc', outline=outline, **kw))
        ids.append(canvas.create_line(x + r, y, rx - r, y, fill=outline, **kw))
        ids.append(canvas.create_line(x + r, ry, rx - r, ry, fill=outline, **kw))
        ids.append(canvas.create_line(x, y + r, x, ry - r, fill=outline, **kw))
        ids.append(canvas.create_line(rx, y + r, rx, ry - r, fill=outline, **kw))
    
    return ids
