#! 版本更新提示窗口
#? 使用 pywebview 展示: html/version_update/index.html (GitHub 文档风格, 与今日指令窗口同一模式)
#? pywebview 6 要求 webview.start() 运行在主线程, 与 tkinter 主循环互斥,
#? 故以独立子进程方式拉起窗口:
#? - 源码模式: 用 pythonw 运行本脚本子进程
#? - 打包模式 (sys.frozen): 用自身 exe 以 --update-window 参数二次启动原生子进程

import base64
import html
import json
import os
import re
import subprocess
import sys
import time
from threading import Thread

if getattr(sys, "frozen", False):
    # 打包环境下模块在临时解压目录, 以 exe 所在目录为项目根目录 (config/html/assets 在 exe 旁)
    _PROJECT_ROOT = os.path.dirname(os.path.abspath(sys.executable))
else:
    _PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

RESULT_FILE = os.path.join(_PROJECT_ROOT, "cache", "update_choice.json")
HTML_PATH = os.path.join(_PROJECT_ROOT, "html", "version_update", "index.html")


# ============================================================
# Markdown → GitHub 风格 HTML 渲染 (离线渲染, 与版本介绍数据同源)
# ============================================================

def _esc(text):
    return html.escape(text, quote=False)


def _find_link(text, link_start):
    """解析 [text](url) 格式，返回 (text_end, url_end) 或 None"""
    if text[link_start] != '[':
        return None
    depth = 0
    j = link_start + 1
    n = len(text)
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


def _inline(text):
    """状态机方式解析行内格式, 输出 HTML。
    支持: **粗体** __粗体__ *斜体* _斜体_ ***粗斜体*** ___粗斜体___
          `行内代码`  ~~删除线~~  [链接](url)  ![图片](url)  <url>  http://...
          关键字格式: "bold 文字" "italic 文字" "bold_italic 文字"
    """
    i, n = 0, len(text)
    buf = []
    out = []

    def flush():
        if buf:
            out.append(_esc(''.join(buf)))
            buf.clear()

    while i < n:
        # ══ 非标准 Markdown: 关键字格式切换 bold / italic / bold_italic ══
        if re.match(r'^(?:[(（]?)?(bold_italic|bold|italic)[)）]?\s+', text[i:], re.IGNORECASE):
            match = re.match(r'^(?:[(（]?)?(bold_italic|bold|italic)[)）]?\s+', text[i:], re.IGNORECASE)
            assert match is not None
            keyword = match.group(1).lower()

            remaining = text[i + match.end():]
            end_idx = len(text)
            scan = 0
            while scan < len(remaining):
                ch = remaining[scan]
                if ch == '\n':
                    end_idx = i + match.end() + scan
                    break
                if ch in 'ibIB(（' and scan + 3 < len(remaining):
                    if re.match(r'^(?:[(（]?)?(bold_italic|bold|italic)[)）]?\s+', remaining[scan:], re.IGNORECASE):
                        end_idx = i + match.end() + scan
                        break
                scan += 1

            segment = text[i + match.end():end_idx]
            flush()
            if keyword == 'bold':
                out.append(f'<strong>{_esc(segment)}</strong>')
            elif keyword == 'italic':
                out.append(f'<em>{_esc(segment)}</em>')
            else:
                out.append(f'<strong><em>{_esc(segment)}</em></strong>')
            i = end_idx
            continue

        # 转义 \
        if text[i] == '\\' and i + 1 < n:
            buf.append(text[i + 1])
            i += 2
            continue

        # 图片 ![alt](url) → 以文字占位
        if text[i:i + 2] == '![':
            result = _find_link(text, i + 1)
            if result:
                text_end, url_end = result
                flush()
                out.append(_esc(f'[图片:{text[i + 2:text_end]}]'))
                i = url_end + 1
                continue

        # 链接 [text](url)
        if text[i] == '[':
            result = _find_link(text, i)
            if result:
                text_end, url_end = result
                link_text = text[i + 1:text_end]
                link_url = text[text_end + 2:url_end]
                flush()
                out.append(f'<a href="{_esc(link_url)}">{_esc(link_text)}</a>')
                i = url_end + 1
                continue

        # 自动链接 <url> 或 <email>
        if text[i] == '<':
            gt = text.find('>', i + 1)
            if gt != -1:
                inner = text[i + 1:gt]
                if re.match(r'^(https?://|ftp://|mailto:|\S+@\S+\.\S+)', inner):
                    flush()
                    out.append(f'<a href="{_esc(inner)}">{_esc(inner)}</a>')
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
                    href = url if url.startswith('http') else 'http://' + url
                    flush()
                    out.append(f'<a href="{_esc(href)}">{_esc(url)}</a>')
                    i += len(url)
                    continue

        # 粗斜体 ***text*** 或 ___text___
        triple = text[i:i + 3]
        if triple == '***' or triple == '___':
            end = text.find(triple, i + 3)
            if end != -1 and text[i + 3:end].strip():
                flush()
                out.append(f'<strong><em>{_esc(text[i + 3:end])}</em></strong>')
                i = end + 3
                continue

        # 粗体 **text** 或 __text__
        double = text[i:i + 2]
        if double == '**' or double == '__':
            end = text.find(double, i + 2)
            if end != -1 and text[i + 2:end].strip():
                flush()
                out.append(f'<strong>{_esc(text[i + 2:end])}</strong>')
                i = end + 2
                continue

        # 斜体 *text* 或 _text_
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
                    out.append(f'<em>{_esc(inner)}</em>')
                    i = end + 1
                    continue

        # 删除线 ~~text~~
        if text[i:i + 2] == '~~':
            end = text.find('~~', i + 2)
            if end != -1 and end > i + 2:
                inner = text[i + 2:end]
                if inner.strip():
                    flush()
                    out.append(f'<del>{_esc(inner)}</del>')
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
                out.append(f'<code>{_esc(inner)}</code>')
                i = end + bt_count
                continue

        buf.append(text[i])
        i += 1

    flush()
    return ''.join(out)


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


def _table_html(table_lines):
    """渲染完整 Markdown 表格 HTML（含表头、分隔行、数据行与对齐）"""
    def parse_row(line):
        s = line.strip()
        if s.startswith('|'):
            s = s[1:]
        if s.endswith('|'):
            s = s[:-1]
        return [c.strip() for c in s.split('|')]

    rows = [parse_row(l) for l in table_lines]
    if not rows:
        return ''

    separator_idx = -1
    for idx, r in enumerate(rows):
        if idx == 0:
            continue
        if r and all(re.match(r'^:?-+:?$', c) for c in r):
            separator_idx = idx
            break

    if separator_idx == -1:
        body = ''.join(f'<tr>{"".join(f"<td>{_inline(c)}</td>" for c in r)}</tr>' for r in rows)
        return f'<table><tbody>{body}</tbody></table>'

    header = rows[0]
    data_rows = rows[separator_idx + 1:]
    separator_row = rows[separator_idx]

    aligns = []
    for c in separator_row:
        if c.startswith(':') and c.endswith(':'):
            aligns.append('center')
        elif c.endswith(':'):
            aligns.append('right')
        else:
            aligns.append('left')

    def row_cells(r, cell_tag):
        return ''.join(
            f'<{cell_tag} style="text-align:{aligns[j] if j < len(aligns) else "left"}">{_inline(r[j])}</{cell_tag}>'
            for j in range(len(r))
        )

    thead = f'<thead><tr>{row_cells(header, "th")}</tr></thead>'
    tbody = '<tbody>' + ''.join(f'<tr>{row_cells(r, "td")}</tr>' for r in data_rows) + '</tbody>'
    return f'<table>{thead}{tbody}</table>'


def md_to_html(md_text):
    """将 GitHub 风格 Markdown 文本渲染为 HTML 字符串"""
    md_text = md_text.replace('\r\n', '\n').replace('\r', '\n')
    lines = md_text.split('\n')
    n = len(lines)
    i = 0
    out = []

    while i < n:
        stripped = lines[i].strip()

        # ── 代码块 ``` ... ``` ──
        if stripped.startswith('```'):
            lang = stripped[3:].strip()
            code_lines = []
            i += 1
            while i < n and not lines[i].strip().startswith('```'):
                code_lines.append(lines[i])
                i += 1
            i += 1  # 跳过结束围栏
            cls = f' class="language-{_esc(lang)}"' if lang else ''
            out.append(f'<pre><code{cls}>{_esc(chr(10).join(code_lines))}</code></pre>')
            continue

        # ── 空行 ──
        if not stripped:
            i += 1
            continue

        # ── 标题 # ~ ###### ──
        hm = re.match(r'^(#{1,6})\s+(.+?)\s*#*\s*$', stripped)
        if hm:
            level = min(len(hm.group(1)), 3)
            out.append(f'<h{level}>{_inline(hm.group(2))}</h{level}>')
            i += 1
            continue

        # ── Setext 风格标题（下划线式）──
        if i + 1 < n and re.match(r'^=+\s*$', lines[i + 1].strip()):
            out.append(f'<h1>{_inline(stripped)}</h1>')
            i += 2
            continue
        if i + 1 < n and re.match(r'^-+\s*$', lines[i + 1].strip()) and stripped:
            out.append(f'<h2>{_inline(stripped)}</h2>')
            i += 2
            continue

        # ── 水平分割线 ──
        if re.match(r'^([-*_])(\s*\1\s*){2,}$', stripped):
            out.append('<hr>')
            i += 1
            continue

        # ── 引用块（多行连续引用合并）──
        if stripped.startswith('>'):
            block_lines = []
            while i < n and lines[i].strip().startswith('>'):
                block_lines.append(re.sub(r'^>\s?', '', lines[i].strip()))
                i += 1
            out.append(f'<blockquote><p>{_inline(" ".join(block_lines))}</p></blockquote>')
            continue

        # ── 任务列表 / 无序列表 / 有序列表（连续条目合并为一个列表）──
        tm = re.match(r'^\s*[-*+]\s+\[([ xX])\]\s+(.+)$', stripped)
        um = None if tm else re.match(r'^\s*[-*+]\s+(.+)$', stripped)
        om = None if (tm or um) else re.match(r'^\s*(\d+)\.\s+(.+)$', stripped)
        if tm or um or om:
            ordered = bool(om)
            items = []
            while i < n:
                s = lines[i].strip()
                t2 = re.match(r'^\s*[-*+]\s+\[([ xX])\]\s+(.+)$', s)
                u2 = None if t2 else re.match(r'^\s*[-*+]\s+(.+)$', s)
                o2 = None if (t2 or u2) else re.match(r'^\s*(\d+)\.\s+(.+)$', s)
                if not (t2 or u2 or o2):
                    break
                if (t2 or u2) and ordered:
                    break
                if o2 and not ordered:
                    break
                if t2:
                    checked = 'checked' if t2.group(1).lower() == 'x' else ''
                    items.append(f'<li class="task"><input type="checkbox" disabled {checked}>{_inline(t2.group(2))}</li>')
                elif u2:
                    items.append(f'<li>{_inline(u2.group(1))}</li>')
                else:
                    assert o2 is not None
                    items.append(f'<li>{_inline(o2.group(2))}</li>')
                i += 1
            tag = 'ol' if ordered else 'ul'
            out.append(f'<{tag}>{"".join(items)}</{tag}>')
            continue

        # ── 表格 ──
        if '|' in stripped:
            table_lines = []
            while i < n and '|' in lines[i].strip():
                table_lines.append(lines[i].strip())
                i += 1
            out.append(_table_html(table_lines))
            continue

        # ── 普通段落（合并连续非空行为一段）──
        para_lines = [stripped]
        i += 1
        while i < n and lines[i].strip() and not _is_block_start(lines[i].strip()):
            para_lines.append(lines[i].strip())
            i += 1
        out.append(f'<p>{_inline(" ".join(para_lines))}</p>')

    return '\n'.join(out)


# ============================================================
# pywebview js_api 与窗口
# ============================================================

class VersionUpdateApi:
    """pywebview js_api: 供前端获取版本数据与回传用户选择"""

    def __init__(self, payload):
        self._payload = payload

    def get_data(self):
        """返回前端渲染所需的全部数据, description 已渲染为 GitHub 风格 HTML"""
        data = dict(self._payload)
        try:
            data['html'] = md_to_html(data.get('description') or '')
        except Exception as e:
            print(f"[版本更新] Markdown 渲染失败: {e}")
            data['html'] = _esc(data.get('description') or '')
        data.pop('description', None)
        return data

    def choose(self, action):
        """用户点击按钮: update=立即更新 later=稍后再说 ok=确定"""
        _write_choice(action)

    def assets(self):
        """返回背景装饰图的 base64 data URI (使用 icon.png)"""
        import base64 as _b64

        def data_uri(rel_path, mime):
            try:
                with open(os.path.join(_PROJECT_ROOT, rel_path), "rb") as f:
                    return f"data:{mime};base64," + _b64.b64encode(f.read()).decode("ascii")
            except Exception:
                return None

        return {"bg": data_uri(os.path.join("assets", "images", "icon", "icon.png"), "image/png")}


def _write_choice(action):
    """写入用户选择结果文件, 供主进程读取"""
    try:
        os.makedirs(os.path.dirname(RESULT_FILE), exist_ok=True)
        with open(RESULT_FILE, "w", encoding="utf-8") as f:
            json.dump({"action": action}, f)
    except Exception as e:
        print(f"[版本更新] 写入选择结果失败: {e}")
    try:
        import webview
        if webview.windows:
            webview.windows[0].destroy()
    except Exception:
        pass


def _msgbox(title, text, is_error=True):
    """原生消息框 (ctypes MessageBoxW), 不依赖 tkinter"""
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, text, title, 0x10 if is_error else 0x40)
    except Exception:
        pass


def _center_xy(width, height):
    """主屏居中坐标, 失败时返回 (None, None)"""
    try:
        import ctypes
        u = ctypes.windll.user32
        screen_w = u.GetSystemMetrics(0)  # SM_CXSCREEN
        screen_h = u.GetSystemMetrics(1)  # SM_CYSCREEN
        return max((screen_w - width) // 2, 0), max((screen_h - height) // 2, 0)
    except Exception:
        return None, None


def run_update_window(payload_b64=None, debug: bool = False):
    """子进程入口: 直接运行版本更新 pywebview 窗口"""
    try:
        import webview
    except BaseException as e:
        import traceback
        try:
            with open(os.path.join(_PROJECT_ROOT, "update_window_error.log"), "a", encoding="utf-8") as f:
                f.write("import webview failed:\n" + traceback.format_exc())
        except Exception:
            pass
        _msgbox("版本更新", f"未安装 pywebview 依赖:\n{type(e).__name__}: {e}")
        raise SystemExit(1)

    if not os.path.exists(HTML_PATH):
        _msgbox("版本更新", f"找不到页面文件:\n{HTML_PATH}")
        raise SystemExit(1)

    payload = {}
    if payload_b64:
        try:
            raw = base64.urlsafe_b64decode(payload_b64.encode('ascii')).decode('utf-8')
            payload = json.loads(raw)
        except Exception as e:
            print(f"[版本更新] 解析参数失败: {e}")

    window_kwargs = dict(
        title="版本更新",
        url=HTML_PATH,
        js_api=VersionUpdateApi(payload),
        width=560,
        height=640,
        min_size=(440, 460),
        background_color="#060f22",
        on_top=True,   # 系统级置顶 (WS_EX_TOPMOST), 不被其他窗口遮挡
    )
    x, y = _center_xy(560, 640)
    if x is not None and y is not None:
        window_kwargs["x"] = x
        window_kwargs["y"] = y

    try:
        webview.create_window(**window_kwargs) # type: ignore
        webview.start(debug=debug)
    except BaseException as e:
        import traceback
        try:
            with open(os.path.join(_PROJECT_ROOT, "update_window_error.log"), "a", encoding="utf-8") as f:
                f.write(traceback.format_exc())
        except Exception:
            pass
        _msgbox("版本更新", f"无法启动窗口:\n{type(e).__name__}: {e}")
        raise SystemExit(1)


def _build_payload(current_version, latest_info, info, ask_update):
    def _dt(value):
        if hasattr(value, 'strftime'):
            return value.strftime('%Y-%m-%d %H:%M:%S')
        return str(value or '')

    description = latest_info.get('description') or latest_info.get('version_description') or ''
    date = latest_info.get('date') or latest_info.get('data') or latest_info.get('created_at')
    url = latest_info.get('bilibili_url') or latest_info.get('url') or ''

    return {
        'title': info,
        'current_version': str(current_version or ''),
        'new_version': str(latest_info.get('version_name', '') or ''),
        'date': _dt(date),
        'bilibili_url': url,
        'description': description,
        'can_update': bool(url),
        'ask_update': bool(ask_update),
    }


# 记录最近一次更新询问窗口的打开时间, 供通知逻辑去重 (避免询问窗与详情窗同时弹出)
_ASK_WINDOW_OPENED = {'t': 0.0}


def ask_window_just_opened(within_seconds=5):
    """判断更新询问窗口是否刚刚打开 (用于跳过重复的详情窗口)"""
    return time.time() - _ASK_WINDOW_OPENED['t'] < within_seconds


def open_version_update_window(current_version, latest_info, info='发现新版本', root=None,
                               ask_update: bool = False, on_result=None, timeout: int = 600):
    """非阻塞拉起版本更新 pywebview 窗口 (GitHub 文档风格)。

    与今日指令窗口同一模式: 窗口运行在独立子进程, 本函数立即返回,
    调用方 (tkinter 主线程) 不会被阻塞。

    Args:
        current_version: 当前版本名称
        latest_info: 最新版本信息字典, 支持键:
            version_name / description | version_description / date | data | created_at
            bilibili_url | url (下载链接, 存在时前端显示"立即更新"按钮)
        info: 提示信息标题
        root: 兼容旧接口的 tkinter 根窗口 (不使用)
        ask_update: 是否等待用户选择"立即更新/稍后再说"
        on_result: ask_update 模式下, 后台线程监听用户选择后的回调
            (运行在后台线程); 参数 action: 'update' / 'later' / None(超时或窗口直接关闭)
        timeout: 等待用户选择的超时秒数

    Returns:
        True: 窗口成功拉起; None: 拉起失败 (调用方自行回退到其他提示方式)
    """
    # 更新询问模式必须要有下载链接, 否则窗口无按钮可点, 直接拒绝更新
    url = latest_info.get('bilibili_url') or latest_info.get('url') or ''
    if ask_update and not url:
        print("[版本更新] 无下载链接, 跳过更新询问")
        return False

    payload = _build_payload(current_version, latest_info, info, ask_update)
    payload_b64 = base64.urlsafe_b64encode(
        json.dumps(payload, ensure_ascii=False).encode('utf-8')
    ).decode('ascii')

    # ---- 以独立子进程拉起窗口 (与今日指令同一模式) ----
    if getattr(sys, "frozen", False):
        cmd = [os.path.abspath(sys.executable), "--update-window", "--update-payload", payload_b64]
    else:
        script = os.path.join(_PROJECT_ROOT, "functions", "pages", "notice", "version_update_window.py")
        if not os.path.exists(script):
            print("[版本更新] 找不到窗口脚本, 已跳过")
            return None
        pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
        if not os.path.exists(pythonw):
            pythonw = sys.executable
        cmd = [pythonw, script, "--update-payload", payload_b64]

    try:
        if os.path.exists(RESULT_FILE):
            os.remove(RESULT_FILE)
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        proc = subprocess.Popen(cmd, cwd=_PROJECT_ROOT, creationflags=flags)
    except Exception as e:
        print(f"[版本更新] 无法启动窗口进程: {e}")
        return None

    if ask_update:
        _ASK_WINDOW_OPENED['t'] = time.time()

    # 非询问模式, 或调用方不关心选择结果: 直接返回, 不阻塞
    if not ask_update or on_result is None:
        return True

    def _watch():
        action = None
        deadline = time.time() + timeout
        while time.time() < deadline:
            if os.path.exists(RESULT_FILE):
                try:
                    with open(RESULT_FILE, "r", encoding="utf-8") as f:
                        action = json.load(f).get("action")
                except Exception:
                    action = None
                break
            if proc.poll() is not None:
                break
            time.sleep(0.2)
        try:
            if os.path.exists(RESULT_FILE):
                os.remove(RESULT_FILE)
        except Exception:
            pass
        try:
            on_result(action)
        except Exception as e:
            print(f"[版本更新] 选择回调执行失败: {e}")

    Thread(target=_watch, daemon=True).start()
    return True


def show_version_update_window(current_version, latest_info, info='发现新版本', root=None,
                               ask_update: bool = False, timeout: int = 600):
    """兼容入口: 非阻塞拉起版本更新窗口 (不等待用户选择, 立即返回)。

    原阻塞式接口已废弃; 需要监听用户选择请使用 open_version_update_window(on_result=...)。

    Returns:
        True: 窗口成功拉起; None: 拉起失败; False: 询问模式但无下载链接
    """

    return open_version_update_window(current_version, latest_info, info, root,
                                      ask_update=ask_update, on_result=None, timeout=timeout)


if __name__ == "__main__":
    payload_arg = None
    if "--update-payload" in sys.argv:
        idx = sys.argv.index("--update-payload")
        if idx + 1 < len(sys.argv):
            payload_arg = sys.argv[idx + 1]
    run_update_window(payload_arg, debug="--debug" in sys.argv)
