
def center_window(root, auto_deiconify=True, size = None):
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
