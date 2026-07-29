import tkinter as tk
from tkinter import messagebox, ttk
import os
import re
from functions.base.window_ulits import center_window
from functions.base.settings_manager import get_settings_manager
from functions.base.color_scheme import C

bg_color:str = get_settings_manager().get_setting('bg_color') # type: ignore
version_info:str = get_settings_manager().get_setting('version_info') # type: ignore


# ============================================================
# GitHub Markdown 渲染器（基于 tkinter Text 组件的 tag 系统）
# ============================================================

def _setup_markdown_tags(tw):
    """配置 Markdown 各元素的 Text 标签样式。
    注意：tag 定义顺序决定优先级（后定义的覆盖先定义的），
    所以基础样式 normal 要最先定义，内联格式 bold/italic 要最后定义。
    """
    F = ('Microsoft YaHei',)

    # 1. 基础样式（优先级最低）
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

    # 7. 内联格式（优先级最高，必须最后定义，以便覆盖 normal 的 font 设置）
    tw.tag_configure("bold", font=(*F, 10, 'bold'))
    tw.tag_configure("italic", font=(*F, 10, 'italic'))
    tw.tag_configure("bold_italic", font=(*F, 10, 'bold italic'))


def _render_github_markdown(tw, md_text):
    """将 GitHub 风格 Markdown 文本渲染到 tkinter Text 组件中"""
    # 统一换行符，处理 Windows \r\n
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

        # ── 代码块 ``` ... ``` ──
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

        # ── 空行 ──
        if not stripped:
            tw.insert(tk.END, '\n', 'normal')
            i += 1
            continue

        # ── 标题 # ~ ###### ──
        hm = re.match(r'^(#{1,6})\s+(.+?)\s*#*\s*$', stripped)
        if hm:
            level = min(len(hm.group(1)), 3)
            _insert_inline(tw, hm.group(2) + '\n', f'h{level}')
            if level == 1:
                tw.insert(tk.END, '\n', 'normal')
            i += 1
            continue

        # ── Setext 风格标题（下划线式）：下一行全是 = 或 - ──
        if i + 1 < n and re.match(r'^=+\s*$', lines[i + 1].strip()):
            _insert_inline(tw, stripped + '\n', 'h1')
            tw.insert(tk.END, '\n', 'normal')
            i += 2
            continue
        if i + 1 < n and re.match(r'^-+\s*$', lines[i + 1].strip()) and stripped:
            _insert_inline(tw, stripped + '\n', 'h2')
            i += 2
            continue

        # ── 水平分割线（只能由同一字符组成：--- 或 *** 或 ___）──
        if re.match(r'^([-*_])(\s*\1\s*){2,}$', stripped):
            tw.insert(tk.END, '─' * 50 + '\n\n', 'hr')
            i += 1
            continue

        # ── 引用块（多行连续引用） ──
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

        # ── 任务列表 - [ ] / - [x] ──
        tm = re.match(r'^\s*[-*+]\s+\[([ xX])\]\s+(.+)$', stripped)
        if tm:
            checked = tm.group(1).lower() == 'x'
            checkbox = '☑ ' if checked else '☐ '
            tag = 'task_checked' if checked else 'task_unchecked'
            tw.insert(tk.END, '  ' + checkbox, tag)
            _insert_inline(tw, tm.group(2) + '\n', tag)
            i += 1
            continue

        # ── 无序列表 ──
        um = re.match(r'^\s*[-*+]\s+(.+)$', stripped)
        if um:
            tw.insert(tk.END, '  • ', 'normal')
            _insert_inline(tw, um.group(1) + '\n', 'list_item')
            i += 1
            continue

        # ── 有序列表 ──
        om = re.match(r'^\s*(\d+)\.\s+(.+)$', stripped)
        if om:
            tw.insert(tk.END, f'  {om.group(1)}. ', 'normal')
            _insert_inline(tw, om.group(2) + '\n', 'list_item')
            i += 1
            continue

        # ── 表格 ──
        if '|' in stripped:
            table_lines = []
            while i < n and '|' in lines[i].strip():
                table_lines.append(lines[i].strip())
                i += 1
            _insert_table(tw, table_lines)
            tw.insert(tk.END, '\n', 'normal')
            continue

        # ── 普通段落（合并连续非空行为一段） ──
        para_lines = [stripped]
        i += 1
        while i < n and lines[i].strip() and not _is_block_start(lines[i].strip()):
            para_lines.append(lines[i].strip())
            i += 1
        _insert_inline(tw, ' '.join(para_lines) + '\n', 'normal')


def _is_block_start(stripped):
    """判断一行是否是块级元素的起始行（用于段落合并）"""
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
    """渲染完整 Markdown 表格（含表头、分隔行、数据行）"""
    if not table_lines:
        return

    def parse_row(line):
        # 去除首尾的 | 再分割
        s = line.strip()
        if s.startswith('|'):
            s = s[1:]
        if s.endswith('|'):
            s = s[:-1]
        return [c.strip() for c in s.split('|')]

    rows = [parse_row(l) for l in table_lines]
    if not rows:
        return

    # 识别分隔行
    separator_idx = -1
    for idx, r in enumerate(rows):
        if idx == 0:
            continue
        if r and all(re.match(r'^:?-+:?$', c) for c in r):
            separator_idx = idx
            break

    if separator_idx == -1:
        # 没有标准分隔行，直接逐行渲染
        for r in rows:
            _insert_table_row_text(tw, r)
        return

    header = rows[0]
    data_rows = rows[separator_idx + 1:]
    separator_row = rows[separator_idx]

    # 计算每列对齐方式与最大宽度
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

    # 渲染
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
    """计算文本的显示宽度（中文按 2 算）"""
    w = 0
    for ch in text:
        w += 2 if ord(ch) > 127 else 1
    return w


def _insert_table_row_text(tw, cells):
    """渲染简单表格行（无表头时使用）"""
    row_text = '│ ' + ' │ '.join(cells) + ' │\n'
    tw.insert(tk.END, row_text, 'table_cell')


# 各 base_tag 的基础字体信息 (字号, 默认粗体否, 默认斜体否)
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
    """简化版：确保返回一个在 base_tag 上下文中正确设置了字体属性的 tag。"""
    F = ('Microsoft YaHei',)
    info = _TAG_FONT_INFO.get(base_tag)

    # normal/list_item 等基础 tag 直接用全局的 bold/italic tag
    if info is None or (info[1] == False and info[2] == False):
        return fmt

    size, base_bold, base_italic = info

    # 根据 fmt 计算目标样式
    if fmt == 'bold':
        final_bold, final_italic = True, base_italic
    elif fmt == 'italic':
        final_bold, final_italic = base_bold, True
    elif fmt == 'bold_italic':
        final_bold, final_italic = True, True
    else:
        return fmt

    # 如果最终样式和 base_tag 完全一致，不需要额外 tag
    if final_bold == base_bold and final_italic == base_italic:
        return base_tag

    # 需要创建复合 tag
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
    """状态机方式插入带内联格式的文本。
    支持: **粗体** __粗体__ *斜体* _斜体_ ***粗斜体*** ___粗斜体___
          `行内代码`  ~~删除线~~  [链接](url)  ![图片](url)  <url>  http://...
    """
    i, n = 0, len(text)
    buf = []

    # 根据 base_tag 计算正确的格式 tag 名称
    def ft(fmt):
        return _ensure_font_tag(tw, base_tag, fmt)

    def flush(extra_tags=None):
        if buf:
            seg = ''.join(buf)
            tags = [base_tag]
            if extra_tags:
                for et in extra_tags:
                    # bold/italic/bold_italic 需要用计算后的复合 tag
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
        """解析 [text](url) 格式，返回 (text_end, url_end) 或 None"""
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
        # ══ 非标准 Markdown：关键字格式切换 italic / bold / bold_italic ══
        # 格式："italic 文字"、"bold 文字"、"bold_italic 文字"（支持中英文括号）
        if re.match(r'^(?:[(（]?)?(bold_italic|bold|italic)[)）]?\s+', text[i:], re.IGNORECASE):
            match = re.match(r'^(?:[(（]?)?(bold_italic|bold|italic)[)）]?\s+', text[i:], re.IGNORECASE)
            assert match is not None
            fmt_keyword = match.group(1).lower()
            fmt_map = {'bold': 'bold', 'italic': 'italic', 'bold_italic': 'bold_italic'}
            target_fmt = fmt_map[fmt_keyword]

            flush()

            # 查找此格式的结束边界：
            # 1) 遇到另一个格式关键字 (bold|italic|bold_italic) 前缀
            # 2) 遇到行尾（\n 或字符串末尾）
            remaining = text[i + match.end():]
            end_idx = len(text)  # 默认到文本末尾
            scan = 0
            while scan < len(remaining):
                ch = remaining[scan]
                if ch == '\n':
                    end_idx = i + match.end() + scan
                    break
                # 检查是否到达另一个格式关键字的起点
                if ch in 'ibIB(（' and scan + 3 < len(remaining):
                    look = remaining[scan:]
                    if re.match(r'^(?:[(（]?)?(bold_italic|bold|italic)[)）]?\s+', look, re.IGNORECASE):
                        end_idx = i + match.end() + scan
                        break
                scan += 1

            segment_text = text[i + match.end():end_idx]
            ftag = _ensure_font_tag(tw, base_tag, target_fmt)
            if ftag != base_tag:
                # 注意：先写 base_tag，再写格式 tag（后定义的 tag 优先级更高）
                tw.insert(tk.END, segment_text, base_tag, ftag)
            else:
                tw.insert(tk.END, segment_text, base_tag)
            i = end_idx
            continue

        # 转义 \
        if text[i] == '\\' and i + 1 < n:
            buf.append(text[i + 1])
            i += 2
            continue

        # 图片 ![alt](url)
        if text[i:i + 2] == '![':
            result = find_inline_link(i + 1)
            if result:
                text_end, url_end = result
                alt_text = text[i + 2:text_end]
                flush()
                tw.insert(tk.END, f'[图片:{alt_text}]', base_tag, 'code_inline')
                i = url_end + 1
                continue

        # 链接 [text](url)
        if text[i] == '[':
            result = find_inline_link(i)
            if result:
                text_end, url_end = result
                link_text = text[i + 1:text_end]
                flush()
                tw.insert(tk.END, link_text, base_tag, 'link')
                i = url_end + 1
                continue

        # 自动链接 <url> 或 <email>
        if text[i] == '<':
            gt = text.find('>', i + 1)
            if gt != -1:
                inner = text[i + 1:gt]
                if re.match(r'^(https?://|ftp://|mailto:|\S+@\S+\.\S+)', inner):
                    flush()
                    tw.insert(tk.END, inner, base_tag, 'link')
                    i = gt + 1
                    continue

        # 自动 URL 识别
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

        # 粗斜体 ***text*** 或 ___text___
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

        # 粗体 **text** 或 __text__
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

        # 斜体 *text* 或 _text_
        single = text[i]
        if single in ('*', '_'):
            # 避免与 ** 或 __ 冲突
            if text[i:i + 2] in ('**', '__'):
                buf.append(single)
                i += 1
                continue
            # _ 的边界检查
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

        # 删除线 ~~text~~
        if text[i:i + 2] == '~~':
            end = text.find('~~', i + 2)
            if end != -1 and end > i + 2:
                inner = text[i + 2:end]
                if inner.strip():
                    flush()
                    tw.insert(tk.END, inner, base_tag, 'strikethrough')
                    i = end + 2
                    continue

        # 行内代码 `code` 或 ``code with ` inside``
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
        root.geometry("600x700")
        center_window(root)
        root.resizable(True, True)
        root.configure(bg=bg_color)
        root.attributes('-topmost', True)
        
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
        title_frame = tk.Frame(main_frame, bg=C.ACCENT_SECONDARY, height=45)
        title_frame.pack(fill=tk.X, padx=0, pady=0)
        title_frame.pack_propagate(False)
        
        # 标题文本
        title_label = tk.Label(title_frame, text="🎉 版本信息 🎉", 
                              font=('Microsoft YaHei', 16, 'bold'), 
                               bg=C.ACCENT_SECONDARY, fg=C.TEXT_WHITE)
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
                                    bg=bg_color, fg=C.SUCCESS_HOVER)
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
                                   bg=bg_color, fg=C.TEXT_PRIMARY)
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
                           fg=C.MARKDOWN_NORMAL,
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
        
        # B站链接（如果有）
        if latest_info.get('bilibili_url'):
            link_frame = tk.Frame(version_frame, bg=bg_color)
            link_frame.pack(fill=tk.X, padx=5, pady=0)
            
            link_label = tk.Label(link_frame, 
                                text="🔗 相关链接:",
                                font=('Microsoft YaHei', 9),
                                bg=bg_color, fg=C.TEXT_MUTED)
            link_label.pack(anchor=tk.W, side=tk.LEFT)
            
            # 创建可点击的链接标签
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
        
        # 按钮区域
        button_frame = tk.Frame(main_frame, bg=bg_color)
        button_frame.pack(fill=tk.X, padx=20, pady=15)
        
        # 确定按钮
        ok_button = tk.Button(button_frame, 
                            text="确定", 
                            font=('Microsoft YaHei', 10, 'bold'),
                            bg=C.ACCENT_SECONDARY, 
                            fg=C.TEXT_WHITE,
                            relief='flat',
                            padx=30,
                            command=root.destroy)
        ok_button.pack(side=tk.RIGHT)
        
        # 添加悬停效果
        def on_enter(e):
            ok_button.config(bg=C.INFO_HOVER)
        
        def on_leave(e):
            ok_button.config(bg=C.ACCENT_SECONDARY)
        
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