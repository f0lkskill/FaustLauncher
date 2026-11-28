"""启动器共用的轻量 Markdown 渲染器。

该模块服务于版本说明、公告等内容展示场景，不执行原始 HTML，并对链接和
图片地址做协议白名单校验。支持常用 Markdown 语法、任务列表、表格、
Markdown 图片以及图片直链。

渲染分两层：:func:`md_to_html` 逐行识别块级结构（标题/列表/表格/引用/
代码块），:func:`_inline` 处理行内强调、链接、图片和自动链接。所有属性
都经过 HTML 转义，链接/图片地址再经协议白名单校验，不能注入脚本。
"""

from __future__ import annotations

import html
import re
from urllib.parse import urlsplit

_IMAGE_EXTENSIONS = (
    ".apng", ".avif", ".bmp", ".gif", ".jpeg", ".jpg", ".png", ".svg", ".webp",
)


def _esc(value) -> str:
    """转义正文文本（不转义引号），用于标签之间的内容。"""
    return html.escape(str(value or ""), quote=False)


def _esc_attr(value) -> str:
    """转义属性值（含引号），用于 ``href``/``src``/``alt``。"""
    return html.escape(str(value or ""), quote=True)


def _safe_href(url: str) -> str:
    """链接白名单：只允许 http/https/mailto 和站内相对路径，否则返回空串。"""
    value = html.unescape(str(url or "").strip())
    if not value or any(ord(char) < 32 for char in value):
        return ""
    try:
        parts = urlsplit(value)
    except ValueError:
        return ""
    if parts.scheme.lower() in ("http", "https", "mailto"):
        return value
    if not parts.scheme and value.startswith(("/", "#", "./", "../")):
        return value
    return ""


def _safe_image_url(url: str) -> str:
    """图片地址白名单：只保留 http/https，``//`` 开头补成 https。"""
    value = html.unescape(str(url or "").strip())
    if value.startswith("//"):
        value = "https:" + value
    if not value or any(ord(char) < 32 for char in value):
        return ""
    try:
        parts = urlsplit(value)
    except ValueError:
        return ""
    return value if parts.scheme.lower() in ("http", "https") else ""


def _is_image_url(url: str) -> bool:
    """按路径扩展名判断是不是图片直链（用于把裸 URL 渲染成 img）。"""
    try:
        path = urlsplit(str(url or "")).path.lower()
    except ValueError:
        return False
    return path.endswith(_IMAGE_EXTENSIONS)


def _image_html(url: str, alt: str) -> str:
    """生成懒加载的 img 标签；地址不安全时退化为 ``[图片:alt]`` 文本。"""
    safe_url = _safe_image_url(url)
    if not safe_url:
        return _esc("[图片:%s]" % alt)
    return (
        '<img class="md-image" src="%s" alt="%s" loading="lazy" '
        'decoding="async">' % (_esc_attr(safe_url), _esc_attr(alt))
    )


def _find_link(text: str, link_start: int):
    """找 ``[...](...)`` 结构的括号位置，支持方括号嵌套与反斜杠转义。

    Returns:
        tuple[int, int]|None: ``(右方括号下标, 右圆括号下标)``；结构不完整返回 None。
    """
    if text[link_start] != "[":
        return None
    depth = 0
    index = link_start + 1
    length = len(text)
    while index < length:
        if text[index] == "\\" and index + 1 < length:
            index += 2
            continue
        if text[index] == "[":
            depth += 1
        elif text[index] == "]":
            if depth == 0:
                break
            depth -= 1
        index += 1
    if index >= length or text[index] != "]":
        return None
    if index + 1 >= length or text[index + 1] != "(":
        return None
    end = index + 2
    while end < length and text[end] != ")":
        if text[end] == "\\" and end + 1 < length:
            end += 2
            continue
        end += 1
    if end >= length:
        return None
    return index, end


def _inline(text: str) -> str:
    """渲染行内语法：强调、删除线、代码、链接、图片与自动链接。"""
    index, length = 0, len(text)
    buffer: list[str] = []
    output: list[str] = []

    def flush() -> None:
        """把暂存普通文本一次性转义并追加到输出，避免漏掉未识别的字符。"""
        if buffer:
            output.append(_esc("".join(buffer)))
            buffer.clear()

    while index < length:
        keyword_match = re.match(
            r"^(?:[(（]?)?(bold_italic|bold|italic)[)）]?\s+",
            text[index:],
            re.IGNORECASE,
        )
        if keyword_match:
            keyword = keyword_match.group(1).lower()
            remaining = text[index + keyword_match.end():]
            end_index = len(remaining)
            scan = 0
            while scan < len(remaining):
                char = remaining[scan]
                if char == "\n":
                    end_index = scan
                    break
                if char in "ibIB(（" and scan + 3 < len(remaining):
                    if re.match(
                        r"^(?:[(（]?)?(bold_italic|bold|italic)[)）]?\s+",
                        remaining[scan:],
                        re.IGNORECASE,
                    ):
                        end_index = scan
                        break
                scan += 1

            segment = remaining[:end_index]
            flush()
            if keyword == "bold":
                output.append(f"<strong>{_esc(segment)}</strong>")
            elif keyword == "italic":
                output.append(f"<em>{_esc(segment)}</em>")
            else:
                output.append(f"<strong><em>{_esc(segment)}</em></strong>")
            index += keyword_match.end() + end_index
            continue

        if text[index] == "\\" and index + 1 < length:
            buffer.append(text[index + 1])
            index += 2
            continue

        if text[index:index + 2] == "![":
            result = _find_link(text, index + 1)
            if result:
                text_end, url_end = result
                alt = text[index + 2:text_end]
                target = text[text_end + 2:url_end].split(None, 1)[0]
                flush()
                output.append(_image_html(target, alt))
                index = url_end + 1
                continue

        if text[index] == "[":
            result = _find_link(text, index)
            if result:
                text_end, url_end = result
                link_text = text[index + 1:text_end]
                link_url = _safe_href(text[text_end + 2:url_end])
                flush()
                if link_url:
                    output.append(
                        '<a href="%s">%s</a>'
                        % (_esc_attr(link_url), _esc(link_text))
                    )
                else:
                    output.append(_esc(link_text))
                index = url_end + 1
                continue

        if text[index] == "<":
            greater = text.find(">", index + 1)
            if greater != -1:
                inner = text[index + 1:greater]
                if re.match(r"^(https?://|ftp://|mailto:|\S+@\S+\.\S+)", inner):
                    flush()
                    href = inner if "@" not in inner or ":" in inner else "mailto:" + inner
                    safe_url = _safe_href(href)
                    if _is_image_url(safe_url):
                        output.append(_image_html(safe_url, ""))
                    elif safe_url:
                        output.append(
                            '<a href="%s">%s</a>'
                            % (_esc_attr(safe_url), _esc(inner))
                        )
                    else:
                        output.append(_esc(inner))
                    index = greater + 1
                    continue

        if re.match(r"^https?://", text[index:]) or re.match(r"^www\.", text[index:]):
            match = re.match(r"^(https?://[^\s)>\]]+|www\.[^\s)>\]]+)", text[index:])
            if match:
                visible_url = match.group(1)
                while visible_url and visible_url[-1] in '.,;:!?)>"\'':
                    visible_url = visible_url[:-1]
                if visible_url:
                    href = (
                        visible_url
                        if visible_url.startswith("http")
                        else "http://" + visible_url
                    )
                    flush()
                    if _is_image_url(href):
                        output.append(_image_html(href, ""))
                    else:
                        output.append(
                            '<a href="%s">%s</a>'
                            % (_esc_attr(href), _esc(visible_url))
                        )
                    index += len(visible_url)
                    continue

        triple = text[index:index + 3]
        if triple in ("***", "___"):
            end = text.find(triple, index + 3)
            if end != -1 and text[index + 3:end].strip():
                flush()
                output.append(
                    f"<strong><em>{_esc(text[index + 3:end])}</em></strong>"
                )
                index = end + 3
                continue

        double = text[index:index + 2]
        if double in ("**", "__"):
            end = text.find(double, index + 2)
            if end != -1 and text[index + 2:end].strip():
                flush()
                output.append(f"<strong>{_esc(text[index + 2:end])}</strong>")
                index = end + 2
                continue

        single = text[index]
        if single in ("*", "_"):
            if text[index:index + 2] in ("**", "__"):
                buffer.append(single)
                index += 1
                continue
            if single == "_":
                before = text[index - 1] if index > 0 else " "
                after = text[index + 1] if index + 1 < length else " "
                if before.isalnum() and after.isalnum():
                    buffer.append(single)
                    index += 1
                    continue
            end = text.find(single, index + 1)
            if end != -1 and end > index + 1:
                inner = text[index + 1:end]
                after_end = text[end + 1] if end + 1 < length else " "
                if single == "_" and after_end.isalnum():
                    buffer.append(single)
                    index += 1
                    continue
                if inner.strip():
                    flush()
                    output.append(f"<em>{_esc(inner)}</em>")
                    index = end + 1
                    continue

        if text[index:index + 2] == "~~":
            end = text.find("~~", index + 2)
            if end != -1 and end > index + 2 and text[index + 2:end].strip():
                flush()
                output.append(f"<del>{_esc(text[index + 2:end])}</del>")
                index = end + 2
                continue

        if text[index] == "`":
            ticks = 1
            while index + ticks < length and text[index + ticks] == "`":
                ticks += 1
            marker = "`" * ticks
            end = text.find(marker, index + ticks)
            if end != -1:
                flush()
                output.append(
                    f"<code>{_esc(text[index + ticks:end].strip())}</code>"
                )
                index = end + ticks
                continue

        buffer.append(text[index])
        index += 1

    flush()
    return "".join(output)


def _is_block_start(stripped: str) -> bool:
    """判断一行是不是新块级结构的开头（段落聚合时据此断行）。"""
    if not stripped:
        return True
    if stripped.startswith("#"):
        return bool(re.match(r"^#{1,6}\s+", stripped))
    if stripped.startswith("```") or stripped.startswith(">"):
        return True
    if re.match(r"^\s*[-*+]\s+", stripped):
        return True
    if re.match(r"^\s*\d+\.\s+", stripped):
        return True
    if re.match(r"^[-*_]{3,}$", stripped) or "|" in stripped:
        return True
    return False


def _table_html(table_lines: list[str]) -> str:
    """把连续的表格行渲染成 table；识别第二行的 ``:---:`` 对齐分隔。"""
    def parse_row(line: str) -> list[str]:
        value = line.strip()
        if value.startswith("|"):
            value = value[1:]
        if value.endswith("|"):
            value = value[:-1]
        return [cell.strip() for cell in value.split("|")]

    rows = [parse_row(line) for line in table_lines]
    if not rows:
        return ""

    separator_index = -1
    for index, row in enumerate(rows[1:], start=1):
        if row and all(re.match(r"^:?-+:?$", cell) for cell in row):
            separator_index = index
            break

    if separator_index == -1:
        body = "".join(
            "<tr>%s</tr>" % "".join(
                f"<td>{_inline(cell)}</td>" for cell in row
            )
            for row in rows
        )
        return f"<table><tbody>{body}</tbody></table>"

    header = rows[0]
    separator = rows[separator_index]
    data_rows = rows[separator_index + 1:]
    alignments = []
    for cell in separator:
        if cell.startswith(":") and cell.endswith(":"):
            alignments.append("center")
        elif cell.endswith(":"):
            alignments.append("right")
        else:
            alignments.append("left")

    def render_cells(row: list[str], cell_tag: str) -> str:
        return "".join(
            '<%s style="text-align:%s">%s</%s>'
            % (
                cell_tag,
                alignments[index] if index < len(alignments) else "left",
                _inline(cell),
                cell_tag,
            )
            for index, cell in enumerate(row)
        )

    head = f"<thead><tr>{render_cells(header, 'th')}</tr></thead>"
    body = "<tbody>%s</tbody>" % "".join(
        f"<tr>{render_cells(row, 'td')}</tr>" for row in data_rows
    )
    return f"<table>{head}{body}</table>"


def md_to_html(md_text: str) -> str:
    """将 Markdown 文本转换为启动器内容区可安全插入的 HTML。

    支持标题、分隔线、引用、有序/无序/任务列表、表格、代码块和段落；行内
    部分交给 :func:`_inline`。原始 HTML 不会被直接放行。

    Args:
        md_text: Markdown 原文，None 当空串处理。

    Returns:
        str: 可赋给 ``innerHTML`` 的 HTML 片段。
    """
    source = str(md_text or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = source.split("\n")
    index = 0
    output: list[str] = []

    while index < len(lines):
        stripped = lines[index].strip()

        if stripped.startswith("```"):
            language = re.sub(r"[^0-9A-Za-z_+-]", "", stripped[3:].strip())
            code_lines = []
            index += 1
            while index < len(lines) and not lines[index].strip().startswith("```"):
                code_lines.append(lines[index])
                index += 1
            index += 1
            class_attr = f' class="language-{language}"' if language else ""
            output.append(
                f"<pre><code{class_attr}>"
                f"{_esc(chr(10).join(code_lines))}</code></pre>"
            )
            continue

        if not stripped:
            index += 1
            continue

        heading_match = re.match(r"^(#{1,6})\s+(.+?)\s*#*\s*$", stripped)
        if heading_match:
            level = min(len(heading_match.group(1)), 3)
            output.append(
                f"<h{level}>{_inline(heading_match.group(2))}</h{level}>"
            )
            index += 1
            continue

        if index + 1 < len(lines) and re.match(
            r"^=+\s*$", lines[index + 1].strip()
        ):
            output.append(f"<h1>{_inline(stripped)}</h1>")
            index += 2
            continue
        if (
            index + 1 < len(lines)
            and re.match(r"^-+\s*$", lines[index + 1].strip())
            and stripped
        ):
            output.append(f"<h2>{_inline(stripped)}</h2>")
            index += 2
            continue

        if re.match(r"^([-*_])(\s*\1\s*){2,}$", stripped):
            output.append("<hr>")
            index += 1
            continue

        if stripped.startswith(">"):
            quote_lines = []
            while index < len(lines) and lines[index].strip().startswith(">"):
                quote_lines.append(
                    re.sub(r"^>\s?", "", lines[index].strip())
                )
                index += 1
            output.append(
                f'<blockquote><p>{_inline(" ".join(quote_lines))}</p></blockquote>'
            )
            continue

        task_match = re.match(
            r"^\s*[-*+]\s+\[([ xX])\]\s+(.+)$", stripped
        )
        bullet_match = (
            None if task_match else re.match(r"^\s*[-*+]\s+(.+)$", stripped)
        )
        ordered_match = (
            None
            if (task_match or bullet_match)
            else re.match(r"^\s*(\d+)\.\s+(.+)$", stripped)
        )
        if task_match or bullet_match or ordered_match:
            ordered = bool(ordered_match)
            items = []
            while index < len(lines):
                current = lines[index].strip()
                task = re.match(
                    r"^\s*[-*+]\s+\[([ xX])\]\s+(.+)$", current
                )
                bullet = (
                    None
                    if task
                    else re.match(r"^\s*[-*+]\s+(.+)$", current)
                )
                ordered_item = (
                    None
                    if (task or bullet)
                    else re.match(r"^\s*(\d+)\.\s+(.+)$", current)
                )
                if not (task or bullet or ordered_item):
                    break
                if (task or bullet) and ordered:
                    break
                if ordered_item and not ordered:
                    break
                if task:
                    checked = (
                        "checked" if task.group(1).lower() == "x" else ""
                    )
                    items.append(
                        '<li class="task"><input type="checkbox" disabled %s>%s</li>'
                        % (checked, _inline(task.group(2)))
                    )
                elif bullet:
                    items.append(f"<li>{_inline(bullet.group(1))}</li>")
                else:
                    assert ordered_item is not None
                    items.append(f"<li>{_inline(ordered_item.group(2))}</li>")
                index += 1
            tag = "ol" if ordered else "ul"
            output.append(f"<{tag}>{''.join(items)}</{tag}>")
            continue

        if "|" in stripped:
            table_lines = []
            while index < len(lines) and "|" in lines[index].strip():
                table_lines.append(lines[index].strip())
                index += 1
            output.append(_table_html(table_lines))
            continue

        paragraph_lines = [stripped]
        index += 1
        while (
            index < len(lines)
            and lines[index].strip()
            and not _is_block_start(lines[index].strip())
        ):
            paragraph_lines.append(lines[index].strip())
            index += 1
        output.append(f'<p>{_inline(" ".join(paragraph_lines))}</p>')

    return "\n".join(output)


__all__ = ["md_to_html"]
