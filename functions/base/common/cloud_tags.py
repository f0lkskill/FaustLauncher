"""云端资源标签协议的规范化工具。

资源条目可携带 ``tags: ["推荐", "工具"]``，目录头部可携带
``tags_style: {"推荐": "#ffffff"}``。本模块只接受短文本标签和十六进制颜色，
避免云端数据直接进入 HTML 样式时引入无效值。
"""

import re


MAX_TAGS = 8
MAX_TAGS_STYLE = 64
_COLOR_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


def normalize_tags(value, limit=MAX_TAGS):
    """将标签输入整理为去重后的短文本列表。

    字符串会按中英文逗号或换行拆分；非字符串、空标签、超长标签会被忽略。
    """
    if isinstance(value, str):
        value = re.split(r"[,，\n\r]+", value)
    if not isinstance(value, (list, tuple, set)):
        return []

    result = []
    seen = set()
    for raw in value:
        if not isinstance(raw, str):
            continue
        tag = raw.strip()
        if not tag or len(tag) > 32 or tag in seen:
            continue
        seen.add(tag)
        result.append(tag)
        if len(result) >= limit:
            break
    return result


def normalize_color(value):
    """返回合法的 ``#RGB`` / ``#RRGGBB`` 颜色，否则返回空字符串。"""
    color = str(value or "").strip()
    return color if _COLOR_RE.fullmatch(color) else ""


def normalize_tags_style(value):
    """将标签颜色映射整理为 ``{tag: color}``，并过滤无效颜色。"""
    if not isinstance(value, dict):
        return {}
    result = {}
    for raw_tag, raw_color in value.items():
        tags = normalize_tags([raw_tag], limit=1)
        color = normalize_color(raw_color)
        if tags and color:
            result[tags[0]] = color
        if len(result) >= MAX_TAGS_STYLE:
            break
    return result


def merge_tags_style(existing, incoming):
    """合并两组标签样式，``incoming`` 中的同标签颜色优先。"""
    merged = normalize_tags_style(existing)
    merged.update(normalize_tags_style(incoming))
    return merged
