import tkinter as tk
from tkinter import messagebox, ttk
import os
import re
from functions.base.window_utils import center_window
from functions.base.settings_manager import get_settings_manager
from functions.base.color_scheme import C

bg_color:str = get_settings_manager().get_setting('bg_color') # type: ignore
version_info:str = get_settings_manager().get_setting('version_info') # type: ignore

def _setup_markdown_tags(tw):
    F = ('Microsoft YaHei',)

    tw.tag_configure("normal", font=(*F, 10), foreground=C.MARKDOWN_NORMAL)
    tw.tag_configure("list_item", lmargin1=20, lmargin2=35,
                     font=(*F, 10), foreground=C.MARKDOWN_NORMAL)
    tw.tag_configure("hr", foreground=C.GRAY_DARK, spacing1=5, spacing3=5)

    tw.tag_configure("blockquote", background=C.MARKDOWN_QUOTE_BG,
                     lmargin1=15, lmargin2=15, foreground=C.MARKDOWN_QUOTE_FG,
                     font=(*F, 10, 'italic'), spacing1=2, spacing3=2)

    tw.tag_configure("code_block", font=('Consolas', 9),
                     background=C.MARKDOWN_CODE_BG, foreground=C.MARKDOWN_CODE_FG,
                     lmargin1=20, lmargin2=20, spacing1=2, spacing3=2)
    tw.tag_configure("table_cell", font=('Consolas', 9),
                     background=C.MARKDOWN_CODE_BG, foreground=C.MARKDOWN_CODE_FG)

    tw.tag_configure("task_checked", foreground=C.MARKDOWN_CHECKED, font=(*F, 10))
    tw.tag_configure("task_unchecked", foreground=C.MARKDOWN_UNCHECKED, font=(*F, 10))

    tw.tag_configure("h1", font=(*F, 16, 'bold'), foreground=C.MARKDOWN_H1,
                     spacing1=12, spacing3=6)
    tw.tag_configure("h2", font=(*F, 14, 'bold'), foreground=C.MARKDOWN_H2,
                     spacing1=10, spacing3=4)
    tw.tag_configure("h3", font=(*F, 12, 'bold'), foreground=C.MARKDOWN_H3,
                     spacing1=6, spacing3=3)

    tw.tag_configure("code_inline", font=('Consolas', 9),
                     background=C.MARKDOWN_QUOTE_BG, foreground='#f87171')
    tw.tag_configure("link", foreground=C.ACCENT_SECONDARY, underline=True)
    tw.tag_configure("strikethrough", overstrike=True, foreground=C.MARKDOWN_UNCHECKED)

    tw.tag_configure("bold", font=(*F, 10, 'bold'))
    tw.tag_configure("italic", font=(*F, 10, 'italic'))
    tw.tag_configure("bold_italic", font=(*F, 10, 'bold italic'))

def _render_github_markdown(tw, md_text):
    md_text = md_text.replace('\r\n', '\n').replace('\r', '\n')
    lines = md_text.split('\n')
    in_code_block = False
    code_lines = []
    code_lang = ''

    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        stripped = line.strip()

        if stripped.startswith('```'):
            if in_code_block:
                if code_lines:
                    tw.insert(tk.END, '\n', 'normal')
                    for cl in code_lines:
                        tw.insert(tk.END, cl + '\n', 'code_block')
                    tw.insert(tk.END, '\n', 'normal')
                code_lines = []
                code_lang = ''
                in_code_block = False
            else:
                in_code_block = True
                lang = stripped[3:].strip()
                if lang:
                    code_lang = lang
            i += 1
            continue

        if in_code_block:
            code_lines.append(line)
            i += 1
            continue

        if not stripped:
            tw.insert(tk.END, '\n', 'normal')
            i += 1
            continue

        hm = re.match(r'^(#{1,6})\s+(.+?)\s*#*\s*$', stripped)
        if hm:
            level = min(len(hm.group(1)), 3)
            _insert_inline(tw, hm.group(2) + '\n', f'h{level}')
            if level == 1:
                tw.insert(tk.END, '\n', 'normal')
            i += 1
            continue

        if i + 1 < n and re.match(r'^=+\s*$', lines[i + 1].strip()):
            _insert_inline(tw, stripped + '\n', 'h1')
            tw.insert(tk.END, '\n', 'normal')
            i += 2
            continue
        if i + 1 < n and re.match(r'^-+\s*$', lines[i + 1].strip()) and stripped:
            _insert_inline(tw, stripped + '\n', 'h2')
            i += 2
            continue

        if re.match(r'^([-*_])(\s*\1\s*){2,}$', stripped):
            tw.insert(tk.END, '─' * 50 + '\n\n', 'hr')
            i += 1
            continue

        if stripped.startswith('>'):
            block_lines = []
            while i < n and lines[i].strip().startswith('>'):
                block_lines.append(re.sub(r'^>\s?', '', lines[i].strip()))
                i += 1
                if i < n and lines[i].strip() == '>':
                    block_lines.append('')
                    i += 1
            _insert_inline(tw, '\n'.join(block_lines) + '\n', 'blockquote')
            tw.insert(tk.END, '\n', 'normal')
            continue

        tm = re.match(r'^\s*[-*+]\s+\[([ xX])\]\s+(.+)$', stripped)
        if tm:
            checked = tm.group(1).lower() == 'x'
            checkbox = '☑ ' if checked else '☐ '
            tag = 'task_checked' if checked else 'task_unchecked'
            tw.insert(tk.END, '  ' + checkbox, tag)
            _insert_inline(tw, tm.group(2) + '\n', tag)
            i += 1
            continue

        um = re.match(r'^\s*[-*+]\s+(.+)$', stripped)
        if um:
            tw.insert(tk.END, '  • ', 'normal')
            _insert_inline(tw, um.group(1) + '\n', 'list_item')
            i += 1
            continue

        om = re.match(r'^\s*(\d+)\.\s+(.+)$', stripped)
        if om:
            tw.insert(tk.END, f'  {om.group(1)}. ', 'normal')
            _insert_inline(tw, om.group(2) + '\n', 'list_item')
            i += 1
            continue

        if '|' in stripped:
            table_lines = []
            while i < n and '|' in lines[i].strip():
                table_lines.append(lines[i].strip())
                i += 1
            _insert_table(tw, table_lines)
            tw.insert(tk.END, '\n', 'normal')
            continue

        para_lines = [stripped]
        i += 1
        while i < n and lines[i].strip() and not _is_block_start(lines[i].strip()):
            para_lines.append(lines[i].strip())
            i += 1
        _insert_inline(tw, ' '.join(para_lines) + '\n', 'normal')

def _is_block_start(stripped):
    if not stripped:
        return True
    if stripped.startswith('#'):
        return bool(re.match(r'^#{1,6}\s+', stripped))
    if stripped.startswith('```'):
        return True
    if stripped.startswith('>'):
        return True
    if re.match(r'^\s*[-*+]\s+', stripped):
        return True
    if re.match(r'^\s*\d+\.\s+', stripped):
        return True
    if re.match(r'^[-*_]{3,}$', stripped):
        return True
    if '|' in stripped:
        return True
    return False

def _insert_table(tw, table_lines):
    if not table_lines:
        return

    def parse_row(line):
        s = line.strip()
        if s.startswith('|'):
            s = s[1:]
        if s.endswith('|'):
            s = s[:-1]
        return [c.strip() for c in s.split('|')]

    rows = [parse_row(l) for l in table_lines]
    if not rows:
        return

    separator_idx = -1
    for idx, r in enumerate(rows):
        if idx == 0:
            continue
        if r and all(re.match(r'^:?-+:?$', c) for c in r):
            separator_idx = idx
            break

    if separator_idx == -1:
        for r in rows:
            _insert_table_row_text(tw, r)
        return

    header = rows[0]
    data_rows = rows[separator_idx + 1:]
    separator_row = rows[separator_idx]

    num_cols = max(len(header), max((len(r) for r in data_rows), default=0), len(separator_row))
    aligns = ['left'] * num_cols
    for j in range(num_cols):
        if j < len(separator_row):
            c = separator_row[j]
            if c.startswith(':') and c.endswith(':'):
                aligns[j] = 'center'
            elif c.endswith(':'):
                aligns[j] = 'right'
            else:
                aligns[j] = 'left'

    all_cells = [header] + data_rows
    widths = [0] * num_cols
    for r in all_cells:
        for j in range(num_cols):
            cell = r[j] if j < len(r) else ''
            widths[j] = max(widths[j], _visible_width(cell))

    def format_cell(cell, width, align):
        pad = max(0, width - _visible_width(cell))
        if align == 'right':
            return ' ' * pad + cell
        elif align == 'center':
            left = pad // 2
            right = pad - left
            return ' ' * left + cell + ' ' * right
        return cell + ' ' * pad

    def draw_border(left, mid, right, dash):
        sep = left
        parts = [dash * (w + 2) for w in widths]
        sep += mid.join(parts)
        sep += right
        tw.insert(tk.END, sep + '\n', 'hr')

    draw_border('┌', '┬', '┐', '─')

    header_cells = [format_cell(header[j] if j < len(header) else '', widths[j], aligns[j]) for j in range(num_cols)]
    tw.insert(tk.END, '│ ' + ' │ '.join(header_cells) + ' │\n', 'table_cell')

    draw_border('├', '┼', '┤', '─')

    for r in data_rows:
        row_cells = [format_cell(r[j] if j < len(r) else '', widths[j], aligns[j]) for j in range(num_cols)]
        tw.insert(tk.END, '│ ' + ' │ '.join(row_cells) + ' │\n', 'table_cell')

    draw_border('└', '┴', '┘', '─')

def _visible_width(text):
    w = 0
    for ch in text:
        w += 2 if ord(ch) > 127 else 1
    return w

def _insert_table_row_text(tw, cells):
    row_text = '│ ' + ' │ '.join(cells) + ' │\n'
    tw.insert(tk.END, row_text, 'table_cell')

_TAG_FONT_INFO = {
    'normal':         (10, False, False),
    'list_item':      (10, False, False),
    'task_checked':   (10, False, False),
    'task_unchecked': (10, False, False),
    'blockquote':     (10, False, True),
    'h1':             (16, True,  False),
    'h2':             (14, True,  False),
    'h3':             (12, True,  False),
}

def _ensure_font_tag(tw, base_tag, fmt):
    F = ('Microsoft YaHei',)
    info = _TAG_FONT_INFO.get(base_tag)

    if info is None or (info[1] == False and info[2] == False):
        return fmt

    size, base_bold, base_italic = info

    if fmt == 'bold':
        final_bold, final_italic = True, base_italic
    elif fmt == 'italic':
        final_bold, final_italic = base_bold, True
    elif fmt == 'bold_italic':
        final_bold, final_italic = True, True
    else:
        return fmt

    if final_bold == base_bold and final_italic == base_italic:
        return base_tag

    composite = f"{base_tag}_{fmt}"
    if composite not in tw.tag_names():
        font_list = [*F, size]
        if final_bold:
            font_list.append('bold')
        if final_italic:
            font_list.append('italic')
        tw.tag_configure(composite, font=tuple(font_list))

    return composite

def _insert_inline(tw, text, base_tag):
    i, n = 0, len(text)
    buf = []

    def ft(fmt):
        return _ensure_font_tag(tw, base_tag, fmt)

    def flush(extra_tags=None):
        if buf:
            seg = ''.join(buf)
            tags = [base_tag]
            if extra_tags:
                for et in extra_tags:
                    if et in ('bold', 'italic', 'bold_italic'):
                        resolved = _ensure_font_tag(tw, base_tag, et)
                        if resolved != base_tag:
                            if resolved not in tags:
                                tags.append(resolved)
                    else:
                        tags.append(et)
            tw.insert(tk.END, seg, *tags)
            buf.clear()

    def find_inline_link(link_start):
        if text[link_start] != '[':
            return None
        depth = 0
        j = link_start + 1
        while j < n:
            if text[j] == '\\' and j + 1 < n:
                j += 2
                continue
            if text[j] == '[':
                depth += 1
            elif text[j] == ']':
                if depth == 0:
                    break
                depth -= 1
            j += 1
        if j >= n or text[j] != ']':
            return None
        if j + 1 >= n or text[j + 1] != '(':
            return None
        k = j + 2
        while k < n and text[k] != ')':
            if text[k] == '\\' and k + 1 < n:
                k += 2
                continue
            k += 1
        if k >= n:
            return None
        return (j, k)

    while i < n:
        if re.match(r'^(?:[(（]?)?(bold_italic|bold|italic)[)）]?\s+', text[i:], re.IGNORECASE):
            match = re.match(r'^(?:[(（]?)?(bold_italic|bold|italic)[)）]?\s+', text[i:], re.IGNORECASE)
            assert match is not None
            fmt_keyword = match.group(1).lower()
            fmt_map = {'bold': 'bold', 'italic': 'italic', 'bold_italic': 'bold_italic'}
            target_fmt = fmt_map[fmt_keyword]

            flush()

            remaining = text[i + match.end():]
            end_idx = len(text)
            scan = 0
            while scan < len(remaining):
                ch = remaining[scan]
                if ch == '\n':
                    end_idx = i + match.end() + scan
                    break
                if ch in 'ibIB(（' and scan + 3 < len(remaining):
                    look = remaining[scan:]
                    if re.match(r'^(?:[(（]?)?(bold_italic|bold|italic)[)）]?\s+', look, re.IGNORECASE):
                        end_idx = i + match.end() + scan
                        break
                scan += 1

            segment_text = text[i + match.end():end_idx]
            ftag = _ensure_font_tag(tw, base_tag, target_fmt)
            if ftag != base_tag:
                tw.insert(tk.END, segment_text, base_tag, ftag)
            else:
                tw.insert(tk.END, segment_text, base_tag)
            i = end_idx
            continue

        if text[i] == '\\' and i + 1 < n:
            buf.append(text[i + 1])
            i += 2
            continue

        if text[i:i + 2] == '![':
            result = find_inline_link(i + 1)
            if result:
                text_end, url_end = result
                alt_text = text[i + 2:text_end]
                flush()
                tw.insert(tk.END, f'[图片:{alt_text}]', base_tag, 'code_inline')
                i = url_end + 1
                continue

        if text[i] == '[':
            result = find_inline_link(i)
            if result:
                text_end, url_end = result
                link_text = text[i + 1:text_end]
                flush()
                tw.insert(tk.END, link_text, base_tag, 'link')
                i = url_end + 1
                continue

        if text[i] == '<':
            gt = text.find('>', i + 1)
            if gt != -1:
                inner = text[i + 1:gt]
                if re.match(r'^(https?://|ftp://|mailto:|\S+@\S+\.\S+)', inner):
                    flush()
                    tw.insert(tk.END, inner, base_tag, 'link')
                    i = gt + 1
                    continue

        if re.match(r'^https?://', text[i:]) or re.match(r'^www\.', text[i:]):
            m = re.match(r'^(https?://[^\s)>\]]+|www\.[^\s)>\]]+)', text[i:])
            if m:
                url = m.group(1)
                while url and url[-1] in '.,;:!?)>"\'':
                    url = url[:-1]
                if url:
                    flush()
                    tw.insert(tk.END, url, base_tag, 'link')
                    i += len(url)
                    continue

        triple = text[i:i + 3]
        if triple == '***' or triple == '___':
            end = text.find(triple, i + 3)
            if end != -1:
                inner = text[i + 3:end]
                if inner.strip():
                    flush()
                    ftag = ft('bold_italic')
                    tw.insert(tk.END, inner, base_tag, ftag) if ftag != base_tag else tw.insert(tk.END, inner, base_tag)
                    i = end + 3
                    continue

        double = text[i:i + 2]
        if double == '**' or double == '__':
            end = text.find(double, i + 2)
            if end != -1:
                inner = text[i + 2:end]
                if inner.strip():
                    flush()
                    ftag = ft('bold')
                    if ftag != base_tag:
                        tw.insert(tk.END, inner, base_tag, ftag)
                    else:
                        tw.insert(tk.END, inner, base_tag)
                    i = end + 2
                    continue

        single = text[i]
        if single in ('*', '_'):
            if text[i:i + 2] in ('**', '__'):
                buf.append(single)
                i += 1
                continue
            if single == '_':
                before = text[i - 1] if i > 0 else ' '
                after_ch = text[i + 1] if i + 1 < n else ' '
                if before.isalnum() and after_ch.isalnum():
                    buf.append(single)
                    i += 1
                    continue
            end = text.find(single, i + 1)
            if end != -1 and end > i + 1:
                inner = text[i + 1:end]
                after_end = text[end + 1] if end + 1 < n else ' '
                if single == '_' and after_end.isalnum():
                    buf.append(single)
                    i += 1
                    continue
                if inner.strip():
                    flush()
                    ftag = ft('italic')
                    if ftag != base_tag:
                        tw.insert(tk.END, inner, base_tag, ftag)
                    else:
                        tw.insert(tk.END, inner, base_tag)
                    i = end + 1
                    continue

        if text[i:i + 2] == '~~':
            end = text.find('~~', i + 2)
            if end != -1 and end > i + 2:
                inner = text[i + 2:end]
                if inner.strip():
                    flush()
                    tw.insert(tk.END, inner, base_tag, 'strikethrough')
                    i = end + 2
                    continue

        if text[i] == '`':
            bt_count = 0
            j = i
            while j < n and text[j] == '`':
                bt_count += 1
                j += 1
            marker = '`' * bt_count
            end = text.find(marker, j)
            if end != -1:
                inner = text[j:end].strip()
                flush()
                tw.insert(tk.END, inner, base_tag, 'code_inline')
                i = end + bt_count
                continue

        buf.append(text[i])
        i += 1

    flush()

def show_version_update_dialog(current_version, latest_info, info='发现新版本', root=None):
    try:
        root = tk.Toplevel(root)
        root.withdraw()
        root.title(info)
        root.geometry("600x700")
        center_window(root)
        root.resizable(True, True)
        root.configure(bg=bg_color)
        root.attributes('-topmost', True)
        
        try:
            icon_path = "assets/images/icon/icon.ico"
            if os.path.exists(icon_path):
                root.iconbitmap(icon_path)
        except:
            pass
        
        main_frame = tk.Frame(root, bg=bg_color, bd=2, relief='solid')
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        title_frame = tk.Frame(main_frame, bg=C.ACCENT_SECONDARY, height=45)
        title_frame.pack(fill=tk.X, padx=0, pady=0)
        title_frame.pack_propagate(False)
        
        title_label = tk.Label(title_frame, text="🎉 版本信息 🎉", 
                              font=('Microsoft YaHei', 16, 'bold'), 
                               bg=C.ACCENT_SECONDARY, fg=C.TEXT_WHITE)
        title_label.pack(expand=True)
        
        version_frame = tk.Frame(main_frame, bg=bg_color)
        version_frame.pack(fill=tk.X, padx=20, pady=5)
        
        current_version_label = tk.Label(version_frame, 
                                       text=f"当前版本: {version_info}", 
                                       font=('Microsoft YaHei', 10),
                                       bg=bg_color, fg='#64748b')
        current_version_label.pack(anchor=tk.W)
        
        new_version_label = tk.Label(version_frame, 
                                   text=f"最新版本: {latest_info['version_name']}", 
                                   font=('Microsoft YaHei', 12, 'bold'),
                                    bg=bg_color, fg=C.SUCCESS_HOVER)
        new_version_label.pack(anchor=tk.W, pady=(5, 0))
        
        separator = ttk.Separator(main_frame, orient='horizontal')
        separator.pack(fill=tk.X, padx=20, pady=10)
        
        description_frame = tk.Frame(main_frame, bg=bg_color)
        description_frame.pack(fill=tk.X, expand=True, padx=20, pady=5)
        
        desc_title_label = tk.Label(description_frame, text="📋 版本介绍",
                                  font=('Microsoft YaHei', 12, 'bold'),
                                   bg=bg_color, fg=C.TEXT_PRIMARY)
        desc_title_label.pack(anchor=tk.W)
        
        desc_text_frame = tk.Frame(description_frame, bg=bg_color)
        desc_text_frame.pack(fill=tk.X, expand=True, pady=(5, 0))
        
        scrollbar = tk.Scrollbar(desc_text_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        desc_text = tk.Text(desc_text_frame, 
                          wrap=tk.WORD, 
                          font=('Microsoft YaHei', 10),
                          bg=bg_color, 
                           fg=C.MARKDOWN_NORMAL,
                          relief='flat',
                          padx=10, pady=10,
                          yscrollcommand=scrollbar.set)
        desc_text.pack(side=tk.LEFT, fill=tk.X, expand=True)
        scrollbar.config(command=desc_text.yview)
        
        description = latest_info.get('description', '暂无详细说明')
        _setup_markdown_tags(desc_text)
        _render_github_markdown(desc_text, description)
        desc_text.config(state=tk.DISABLED)
        
        if latest_info.get('date'):
            time_frame = tk.Frame(version_frame, bg=bg_color)
            time_frame.pack(fill=tk.X, padx=5, pady=0)
            
            time_text = latest_info['date']
            if hasattr(time_text, 'strftime'):
                time_text = time_text.strftime('%Y-%m-%d %H:%M:%S')
            
            time_label = tk.Label(time_frame, 
                                text=f"🕐 发布时间: {time_text}",
                                font=('Microsoft YaHei', 9),
                                bg=bg_color, fg=C.TEXT_MUTED)
            time_label.pack(anchor=tk.W, side=tk.LEFT)
        
        if latest_info.get('bilibili_url'):
            link_frame = tk.Frame(version_frame, bg=bg_color)
            link_frame.pack(fill=tk.X, padx=5, pady=0)
            
            link_label = tk.Label(link_frame, 
                                text="🔗 相关链接:",
                                font=('Microsoft YaHei', 9),
                                bg=bg_color, fg=C.TEXT_MUTED)
            link_label.pack(anchor=tk.W, side=tk.LEFT)
            
            def open_bilibili():
                import webbrowser
                webbrowser.open(latest_info['bilibili_url'])
            
            link_button = tk.Label(link_frame, 
                                 text=latest_info['bilibili_url'],
                                 font=('Microsoft YaHei', 9, 'underline'),
                                 bg=bg_color, fg=C.ACCENT_SECONDARY,
                                 cursor='hand2')
            link_button.pack(anchor=tk.W, pady=(2, 0))
            link_button.bind('<Button-1>', lambda e: open_bilibili())
        
        button_frame = tk.Frame(main_frame, bg=bg_color)
        button_frame.pack(fill=tk.X, padx=20, pady=15)
        
        ok_button = tk.Button(button_frame, 
                            text="确定", 
                            font=('Microsoft YaHei', 10, 'bold'),
                            bg=C.ACCENT_SECONDARY, 
                            fg=C.TEXT_WHITE,
                            relief='flat',
                            padx=30,
                            command=root.destroy)
        ok_button.pack(side=tk.RIGHT)
        
        def on_enter(e):
            ok_button.config(bg=C.INFO_HOVER)
        
        def on_leave(e):
            ok_button.config(bg=C.ACCENT_SECONDARY)
        
        ok_button.bind("<Enter>", on_enter)
        ok_button.bind("<Leave>", on_leave)
        
        root.bind('<Return>', lambda e: root.destroy())
        root.bind('<Escape>', lambda e: root.destroy())
        
        ok_button.focus_set()
        
        root.mainloop()
        return True
        
    except Exception as e:
        print(f"显示更新对话框时出错: {e}")
        messagebox.showinfo("版本更新", 
                           f"{info}: {latest_info['version_name']}\n\n"
                           f"版本介绍: {latest_info.get('version_description', '暂无说明')}")
        return False
