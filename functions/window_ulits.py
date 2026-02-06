""""
这个模块包含与窗口实用程序相关的函数。

函数：
    - `center_window(self)`: 用于将窗口居中显示。
"""

def center_window(root, auto_deiconify=True):
    """居中显示窗口"""
    root.update_idletasks()
    screen_width = root.winfo_screenwidth()
    screen_height = root.winfo_screenheight()
    x = (screen_width - root.winfo_width()) // 2
    y = (screen_height - root.winfo_height()) // 2
    root.geometry(f"+{x}+{y}")
    
    if auto_deiconify:
        root.deiconify()  # 显示窗口