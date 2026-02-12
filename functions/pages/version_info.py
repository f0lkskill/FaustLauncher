import tkinter as tk
from tkinter import messagebox, ttk
import os
from functions.base.window_ulits import center_window
from functions.base.settings_manager import get_settings_manager

bg_color:str = get_settings_manager().get_setting('bg_color') # type: ignore
version_info:str = get_settings_manager().get_setting('version_info') # type: ignore

def show_version_update_dialog(current_version, latest_info, info='发现新版本', root=None):
    """
    显示优美的版本更新提示框，支持GitHub Markdown样式
    
    Args:
        current_version: 当前版本名称
        latest_info: 最新版本信息字典
        info: 提示信息标题
    """
    try:
        # 创建主窗口
        root = tk.Toplevel(root)
        root.withdraw()  # 隐藏主窗口
        root.title("版本更新")
        root.geometry("500x600")
        center_window(root)
        root.resizable(True, True)
        root.configure(bg=bg_color)
        root.attributes('-topmost', True)

        # print(latest_info)
        
        # 设置窗口图标（如果有的话）
        try:
            icon_path = "assets/images/icon/icon.ico"
            if os.path.exists(icon_path):
                root.iconbitmap(icon_path)
        except:
            pass
        
        # 创建主框架
        main_frame = tk.Frame(root, bg=bg_color, bd=2, relief='solid')
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # 标题区域
        title_frame = tk.Frame(main_frame, bg='#3b82f6', height=45)
        title_frame.pack(fill=tk.X, padx=0, pady=0)
        title_frame.pack_propagate(False)
        
        # 标题文本
        title_label = tk.Label(title_frame, text="🎉 版本信息 🎉", 
                              font=('Microsoft YaHei', 16, 'bold'), 
                              bg='#3b82f6', fg='white')
        title_label.pack(expand=True)
        
        # 版本信息区域
        version_frame = tk.Frame(main_frame, bg=bg_color)
        version_frame.pack(fill=tk.X, padx=20, pady=5)
        
        # 当前版本
        current_version_label = tk.Label(version_frame, 
                                       text=f"当前版本: {version_info}", 
                                       font=('Microsoft YaHei', 10),
                                       bg=bg_color, fg='#64748b')
        current_version_label.pack(anchor=tk.W)
        
        # 新版本
        new_version_label = tk.Label(version_frame, 
                                   text=f"最新版本: {latest_info['version_name']}", 
                                   font=('Microsoft YaHei', 12, 'bold'),
                                   bg=bg_color, fg='#059669')
        new_version_label.pack(anchor=tk.W, pady=(5, 0))
        
        # 分隔线
        separator = ttk.Separator(main_frame, orient='horizontal')
        separator.pack(fill=tk.X, padx=20, pady=10)
        
        # 版本介绍区域
        description_frame = tk.Frame(main_frame, bg=bg_color)
        description_frame.pack(fill=tk.X, expand=True, padx=20, pady=5)
        
        # 介绍标题
        desc_title_label = tk.Label(description_frame, text="📋 版本介绍",
                                  font=('Microsoft YaHei', 12, 'bold'),
                                  bg=bg_color, fg="#eaeaea")
        desc_title_label.pack(anchor=tk.W)
        
        # 介绍内容文本框（支持滚动）
        desc_text_frame = tk.Frame(description_frame, bg=bg_color)
        desc_text_frame.pack(fill=tk.X, expand=True, pady=(5, 0))
        
        # 添加滚动条
        scrollbar = tk.Scrollbar(desc_text_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # 文本区域
        desc_text = tk.Text(desc_text_frame, 
                          wrap=tk.WORD, 
                          font=('Microsoft YaHei', 10),
                          bg=bg_color, 
                          fg="#D3D3D3",
                          relief='flat',
                          padx=10, pady=10,
                          yscrollcommand=scrollbar.set)
        desc_text.pack(side=tk.LEFT, fill=tk.X, expand=True)
        scrollbar.config(command=desc_text.yview)
        
        # 插入版本介绍内容（支持简单的Markdown样式）
        description = latest_info.get('version_description', '暂无详细说明')
        
        # 简单的Markdown解析和格式化
        lines = description.split('\n')
        formatted_text = ""
        
        for line in lines:
            line = line.strip()
            if line.startswith('## '):
                # 二级标题
                formatted_text += f"\n{line[3:]}\n{'='*40}\n"
            elif line.startswith('# '):
                # 一级标题
                formatted_text += f"\n{line[2:]}\n{'='*50}\n"
            elif line.startswith('- ') or line.startswith('* '):
                # 列表项
                formatted_text += f"• {line[2:]}\n"
            elif line.startswith('1. '):
                # 有序列表
                formatted_text += f"  {line}\n"
            elif line.startswith('```'):
                # 代码块（简化处理）
                formatted_text += f"\n【代码块】\n"
            else:
                formatted_text += f"{line}\n"
        
        desc_text.insert(tk.END, formatted_text.strip())
        desc_text.config(state=tk.DISABLED)  # 设置为只读
        
        # 发布时间信息
        if latest_info.get('created_at'):
            time_frame = tk.Frame(version_frame, bg=bg_color)
            time_frame.pack(fill=tk.X, padx=5, pady=0)
            
            time_text = latest_info['created_at']
            if hasattr(time_text, 'strftime'):
                time_text = time_text.strftime('%Y-%m-%d %H:%M:%S')
            
            time_label = tk.Label(time_frame, 
                                text=f"🕐 发布时间: {time_text}",
                                font=('Microsoft YaHei', 9),
                                bg=bg_color, fg='#94a3b8')
            time_label.pack(anchor=tk.W, side=tk.LEFT)
        
        # B站链接（如果有）
        if latest_info.get('bilibili_url'):
            link_frame = tk.Frame(version_frame, bg=bg_color)
            link_frame.pack(fill=tk.X, padx=5, pady=0)
            
            link_label = tk.Label(link_frame, 
                                text="🔗 相关链接:",
                                font=('Microsoft YaHei', 9),
                                bg=bg_color, fg='#94a3b8')
            link_label.pack(anchor=tk.W, side=tk.LEFT)
            
            # 创建可点击的链接标签
            def open_bilibili():
                import webbrowser
                webbrowser.open(latest_info['bilibili_url'])
            
            link_button = tk.Label(link_frame, 
                                 text=latest_info['bilibili_url'],
                                 font=('Microsoft YaHei', 9, 'underline'),
                                 bg=bg_color, fg='#3b82f6',
                                 cursor='hand2')
            link_button.pack(anchor=tk.W, pady=(2, 0))
            link_button.bind('<Button-1>', lambda e: open_bilibili())
        
        # 按钮区域
        button_frame = tk.Frame(main_frame, bg=bg_color)
        button_frame.pack(fill=tk.X, padx=20, pady=15)
        
        # 确定按钮
        ok_button = tk.Button(button_frame, 
                            text="确定", 
                            font=('Microsoft YaHei', 10, 'bold'),
                            bg='#3b82f6', 
                            fg='white',
                            relief='flat',
                            padx=30,
                            command=root.destroy)
        ok_button.pack(side=tk.RIGHT)
        
        # 添加悬停效果
        def on_enter(e):
            ok_button.config(bg='#2563eb')
        
        def on_leave(e):
            ok_button.config(bg='#3b82f6')
        
        ok_button.bind("<Enter>", on_enter)
        ok_button.bind("<Leave>", on_leave)
        
        # 绑定回车键和ESC键
        root.bind('<Return>', lambda e: root.destroy())
        root.bind('<Escape>', lambda e: root.destroy())
        
        # 设置焦点
        ok_button.focus_set()
        
        # 显示窗口
        root.mainloop()
        return True
        
    except Exception as e:
        print(f"显示更新对话框时出错: {e}")
        # 出错时回退到普通消息框
        messagebox.showinfo("版本更新", 
                           f"{info}: {latest_info['version_name']}\n\n"
                           f"版本介绍: {latest_info.get('version_description', '暂无说明')}")
        return False