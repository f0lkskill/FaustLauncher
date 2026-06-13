import tkinter as tk
from tkinter import messagebox, ttk
import os
import re
from functions.base.window_ulits import center_window
from functions.base.settings_manager import get_settings_manager

bg_color:str = get_settings_manager().get_setting('bg_color') # type: ignore
version_info:str = get_settings_manager().get_setting('version_info') # type: ignore


# ============================================================
# GitHub Markdown 渲染器（基于 tkinter Text 组件的 tag 系统）
# ============================================================

def _setup_markdown_tags(tw):
    """配置 Markdown 各元素的 Text 标签样式"""
    F = ('Microsoft YaHei',)
    tw.tag_configure("h1", font=(*F, 16, 'bold'), foreground='#f8fafc',
                     spacing1=12, spacing3=6)
    tw.tag_configure("h2", font=(*F, 14, 'bold'), foreground='#e2e8f0',
                     spacing1=10, spacing3=4)
    tw.tag_configure("h3", font=(*F, 12, 'bold'), foreground='#cbd5e1',
                     spacing1=6, spacing3=3)
    tw.tag_configure("bold", font=(*F, 10, 'bold'))
    tw.tag_configure("italic", font=(*F, 10, 'italic'))
    tw.tag_configure("bold_italic", font=(*F, 10, 'bold italic'))
    tw.tag_configure("code_inline", font=('Consolas', 9),
                     background='#334155', foreground='#f87171')
    tw.tag_configure("code_block", font=('Consolas', 9),
                     background='#1e293b', foreground='#e2e8f0',
                     lmargin1=20, lmargin2=20, spacing1=2, spacing3=2)
    tw.tag_configure("strikethrough", overstrike=True, foreground='#94a3b8')
    tw.tag_configure("link", foreground='#3b82f6', underline=True)
    tw.tag_configure("blockquote", background='#334155',
                     lmargin1=15, lmargin2=15, foreground='#94a3b8',
                     font=(*F, 10, 'italic'))
    tw.tag_configure("list_item", lmargin1=20, lmargin2=35)
    tw.tag_configure("hr", foreground='#475569', spacing1=5, spacing3=5)
    tw.tag_configure("normal", font=(*F, 10), foreground='#D3D3D3')
    tw.tag_configure("task_checked", foreground='#22c55e', font=(*F, 10))
    tw.tag_configure("task_unchecked", foreground='#94a3b8', font=(*F, 10))
    tw.tag_configure("table_cell", font=('Consolas', 9),
                     background='#1e293b', foreground='#e2e8f0')


def _render_github_markdown(tw, md_text):
    """将 GitHub 风格 Markdown 文本渲染到 tkinter Text 组件中"""
    lines = md_text.split('\n')
    in_code_block = False
    code_lines = []

    for line in lines:
        stripped = line.strip()

        # ── 代码块 ──
        if stripped.startswith('```'):
            if in_code_block:
                if code_lines:
                    tw.insert(tk.END, '\n', 'normal')
                    for cl in code_lines:
                        tw.insert(tk.END, cl + '\n', 'code_block')
                    tw.insert(tk.END, '\n', 'normal')
                code_lines = []
                in_code_block = False
            else:
                in_code_block = True
            continue

        if in_code_block:
            code_lines.append(line)
            continue

        # ── 空行 ──
        if not stripped:
            tw.insert(tk.END, '\n', 'normal')
            continue

        # ── 标题 # ~ ###### ──
        hm = re.match(r'^(#{1,6})\s+(.+)$', stripped)
        if hm:
            level = min(len(hm.group(1)), 3)
            _insert_inline(tw, hm.group(2) + '\n', f'h{level}')
            if level == 1:
                tw.insert(tk.END, '\n', 'normal')
            continue

        # ── 水平分割线 ──
        if re.match(r'^[-*_]{3,}$', stripped):
            tw.insert(tk.END, '─' * 50 + '\n\n', 'hr')
            continue

        # ── 引用块 ──
        if stripped.startswith('>'):
            quote_text = re.sub(r'^>\s?', '', stripped)
            _insert_inline(tw, quote_text + '\n', 'blockquote')
            continue

        # ── 任务列表 - [ ] / - [x] ──
        tm = re.match(r'^[-*+]\s+$$([ xX])$$\s+(.+)$', stripped)
        if tm:
            checked = tm.group(1).lower() == 'x'
            checkbox = '☑ ' if checked else '☐ '
            tag = 'task_checked' if checked else 'task_unchecked'
            tw.insert(tk.END, checkbox, tag)
            _insert_inline(tw, tm.group(2) + '\n', tag)
            continue

        # ── 无序列表 ──
        um = re.match(r'^[-*+]\s+(.+)$', stripped)
        if um:
            tw.insert(tk.END, '• ', 'normal')
            _insert_inline(tw, um.group(1) + '\n', 'list_item')
            continue

        # ── 有序列表 ──
        om = re.match(r'^(\d+)\.\s+(.+)$', stripped)
        if om:
            tw.insert(tk.END, f'{om.group(1)}. ', 'normal')
            _insert_inline(tw, om.group(2) + '\n', 'list_item')
            continue

        # ── 表格 ──
        if '|' in stripped and re.match(r'^\|', stripped):
            _insert_table_row(tw, stripped)
            continue

        # ── 普通段落 ──
        _insert_inline(tw, stripped + '\n', 'normal')


def _insert_inline(tw, text, base_tag):
    """状态机方式插入带内联格式的文本。
    支持: **粗体**  *斜体*  ***粗斜体***  `行内代码`  ~~删除线~~  [链接](url)  ![图片](url)
    """
    i, n = 0, len(text)
    buf = []
    styles = set()

    def flush():
        if buf:
            seg = ''.join(buf)
            tags = [base_tag]
            if 'bi' in styles:
                tags.append('bold_italic')
            else:
                if 'b' in styles:
                    tags.append('bold')
                if 'i' in styles:
                    tags.append('italic')
            if 'c' in styles:
                tags.append('code_inline')
            if 's' in styles:
                tags.append('strikethrough')
            if 'l' in styles:
                tags.append('link')
            tw.insert(tk.END, seg, *tags)
            buf.clear()

    while i < n:
        # 图片 ![alt](url) → 显示为 [图片:alt]
        if text[i:i + 2] == '![':
            cb = text.find(']', i + 2)
            if cb != -1 and cb + 1 < n and text[cb + 1] == '(':
                cp = text.find(')', cb + 2)
                if cp != -1:
                    flush()
                    tw.insert(tk.END, f'[图片:{text[i + 2:cb]}]',
                              base_tag, 'code_inline')
                    i = cp + 1
                    continue

        # 链接 [text](url) → 蓝色下划线显示
        if text[i] == '[':
            cb = text.find(']', i + 1)
            if cb != -1 and cb + 1 < n and text[cb + 1] == '(':
                cp = text.find(')', cb + 2)
                if cp != -1:
                    flush()
                    tw.insert(tk.END, text[i + 1:cb], base_tag, 'link')
                    i = cp + 1
                    continue

        # 粗斜体 ***
        if text[i:i + 3] == '***':
            flush()
            if 'bi' in styles:
                styles.discard('bi')
            else:
                styles.add('bi')
            i += 3
            continue

        # 粗体 **
        if text[i:i + 2] == '**':
            flush()
            if 'b' in styles:
                styles.discard('b')
            else:
                styles.add('b')
            i += 2
            continue

        # 斜体 * (非 **)
        if text[i] == '*' and (i + 1 >= n or text[i + 1] != '*'):
            flush()
            if 'i' in styles:
                styles.discard('i')
            else:
                styles.add('i')
            i += 1
            continue

        # 删除线 ~~
        if text[i:i + 2] == '~~':
            flush()
            if 's' in styles:
                styles.discard('s')
            else:
                styles.add('s')
            i += 2
            continue

        # 行内代码 `
        if text[i] == '`':
            flush()
            if 'c' in styles:
                styles.discard('c')
            else:
                styles.add('c')
            i += 1
            continue

        buf.append(text[i])
        i += 1

    flush()


def _insert_table_row(tw, line):
    """渲染 Markdown 表格行"""
    cells = [c.strip() for c in line.split('|')]
    if cells and cells[0] == '':
        cells = cells[1:]
    if cells and cells[-1] == '':
        cells = cells[:-1]

    # 分隔行 (|---|---|)
    if all(re.match(r'^[-:]+[-:\s]*$', c) for c in cells if c):
        tw.insert(tk.END, '├' + '─' * 48 + '┤\n', 'hr')
        return

    # 数据行
    row_text = '│ ' + ' │ '.join(cells) + ' │\n'
    tw.insert(tk.END, row_text, 'table_cell')


# ============================================================
# 版本更新对话框
# ============================================================

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
        root.title(info)
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
        
        # ──────── 改进：完整 GitHub Markdown 渲染 ────────
        description = latest_info.get('description', '暂无详细说明')
        _setup_markdown_tags(desc_text)
        _render_github_markdown(desc_text, description)
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