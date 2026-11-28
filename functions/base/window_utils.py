"""base 子模块：<window_utils>（具体职责见函数文档）。"""


def center_window(root, auto_deiconify=True, size = None):
    """center窗口相关处理。"""
    root.update_idletasks()
    
    if not size:
        screen_width = root.winfo_screenwidth()
        screen_height = root.winfo_screenheight()
    else:
        screen_width, screen_height = size
        
    x = (screen_width - root.winfo_width()) // 2
    y = (screen_height - root.winfo_height()) // 2
    root.geometry(f"+{x}+{y}")
    
    if auto_deiconify:
        root.deiconify()
