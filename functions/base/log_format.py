"""终端单行日志的格式规则。

一条完整日志形如 ``[时间] [模块] [级别] [文件:行号]: 正文``。这里负责：
从调用栈推断“模块/位置”（跳过日志框架自身的帧）、按正文关键词猜级别、
解析 ``[模块] 正文`` 前缀、按模块名分配颜色，以及按需裁剪毫秒时间戳。

:class:`LogRecord` 是给日志管理器落盘用的结构化记录；终端渲染入口是
:func:`build_line` / :func:`format_message`。
"""

from __future__ import annotations

import datetime
import os
import re
import sys
from dataclasses import dataclass

__all__ = [
    "LogRecord", "build_line", "format_message", "short_stamp", "resolve_site",
    "strip_ansi", "palette", "PALETTE", "level_of", "split_area",
]

SKIP_FRAMES = {
    ("log_format.py", None),
    ("console_log.py", None),
    ("terminal_redirect.py", None),
    ("log_manager.py", None),
    ("logger.py", None),
    ("stdio.py", None),
    ("traceback.py", None),
    ("app_core.py", "add_terminal_message"),
}

_TAG_RE = re.compile(r"^\[([^\[\]\r\n]{1,16})\][ \t]+(\S.*)$", re.S)

PALETTE = {
    "reset": "\x1b[0m",
    "time": "\x1b[90m",
    "area": "\x1b[96m",
    "DEBUG": "\x1b[90m",
    "INFO": "\x1b[94m",
    "WARN": "\x1b[93m",
    "ERROR": "\x1b[91m",
    "site": "\x1b[96m",
}
AREA_COLORS = ("\x1b[96m", "\x1b[92m", "\x1b[95m", "\x1b[93m", "\x1b[94m", "\x1b[97m")

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

LEVEL_RULES = (
    ("ERROR", ("失败", "错误", "异常", "无法", "不存在", "崩溃", "error", "failed",
               "traceback")),
    ("WARN", ("警告", "跳过", "未找到", "缺少", "不完整", "已禁用", "回退",
              "failed", "warning", "warn")),
    ("DEBUG", ("debug", "调试", "明细", "trace")),
)
LEVELS = ("DEBUG", "INFO", "WARN", "ERROR")
LEVEL_ORDER = {"DEBUG": 10, "INFO": 20, "WARN": 30, "ERROR": 40}

_ANSI_OK = True

@dataclass(frozen=True)
class LogRecord:
    """一条结构化日志（时间、级别、模块、来源文件/行号、正文）。"""

    timestamp: str
    level: str
    area: str
    filename: str
    lineno: int
    message: str

def strip_ansi(text: str) -> str:
    """去掉文本里的 ANSI 颜色控制序列。"""
    return _ANSI_RE.sub("", text)

def _area_of(filename: str) -> str:
    """从源文件路径推断模块名：取 functions/addons 后的一级目录。"""
    parts = re.split(r"[\\/]", os.path.abspath(filename))
    for marker in ("functions", "addons"):
        if marker not in parts:
            continue
        idx = len(parts) - 1 - parts[::-1].index(marker)
        if idx + 2 < len(parts):
            return parts[idx + 1]
    return os.path.splitext(parts[-1])[0]

def resolve_site() -> tuple[str, int, str]:
    """从调用栈里找第一个不属于日志框架自身的帧。

    Returns:
        tuple[str, int, str]: ``(文件名, 行号, 模块名)``；找不到时为 ``('?', 0, '?')``。
    """
    frame = sys._getframe(1)
    while frame is not None:
        code = frame.f_code
        name = os.path.basename(code.co_filename)
        if not any(name == skipped and (func is None or func == code.co_name)
                   for skipped, func in SKIP_FRAMES):
            return name, frame.f_lineno, _area_of(code.co_filename)
        frame = frame.f_back
    return "?", 0, "?"

# Ignore zero-valued counters, not nonzero values starting with 0 (e.g. 0.1/01).
_ZERO_STAT_RE = re.compile(
    r"\s*[:：=]?\s*0(?![\d.a-z_])(?:\s*[个次条项分%])?", re.I)

def _mentions(message: str, word: str) -> bool:
    """判断关键词是否真的出现：忽略“0 个/0 次”这类零值统计噪声。"""
    start = 0
    while True:
        idx = message.find(word, start)
        if idx < 0:
            return False
        if not _ZERO_STAT_RE.match(message, idx + len(word)):
            return True
        start = idx + len(word)

def _level_of(message) -> str:
    """按关键词（失败/警告/调试等）猜一条日志的级别，没有命中就是 INFO。"""
    if not isinstance(message, str):
        message = str(message)
    lowered = message.lower()
    for level, words in LEVEL_RULES:
        if any(_mentions(message, word) or _mentions(lowered, word)
               for word in words):
            return level
    return "INFO"

def _split_area(message: str, fallback: str) -> tuple[str, str]:
    """拆出 ``[模块] 正文`` 前缀；没有前缀时用 fallback 作为模块名。"""
    match = _TAG_RE.match(message)
    if match:
        return match.group(1), match.group(2)
    return fallback, message

def level_of(message: str) -> str:
    """公开入口：按关键词推断日志级别。"""
    return _level_of(message)

def split_area(message: str, fallback: str) -> tuple[str, str]:
    """公开入口：拆出模块名与正文。"""
    return _split_area(message, fallback)

def _now_stamp() -> str:
    """当前时间字符串 ``YYYY-MM-DD HH:MM:SS.mmm``。"""
    now = datetime.datetime.now()
    return now.strftime("%Y-%m-%d %H:%M:%S") + f".{now.microsecond // 1000:03d}"

def palette(enabled: bool = True):
    """返回颜色表；``enabled=False`` 时返回 None 表示不着色。"""
    return PALETTE if enabled else None

def _paint(text: str, code: str | None, palette_map: dict | None) -> str:
    """用给定的 ANSI 颜色码包住文本；没有颜色表时原样返回。"""
    if not palette_map or not code:
        return text
    return f"{code}{text}{PALETTE['reset']}"

def _color(text: str, style: str | None, palette_map: dict | None) -> str:
    """按颜色表里的 style 名给文本上色；名字不存在则原样返回。"""
    if not palette_map or not style:
        return text
    return _paint(text, palette_map.get(style), palette_map)

def build_line(message: str, *,
               site: tuple[str, int, str] | None = None,
               level: str | None = None,
               palette_map: dict | None = None,
               stamp: str | None = None) -> str:
    """把一条正文渲染成终端单行日志。

    Args:
        message: 正文，可带 ``[模块]`` 前缀。
        site: 可选的 ``(文件名, 行号, 默认模块)``；省略时从调用栈推断。
        level: 强制级别；省略时按正文关键词推断。
        palette_map: 颜色表；None 表示纯文本。
        stamp: 强制时间戳，便于日志回放。

    Returns:
        str: 渲染后的一行文本（已去掉正文尾部换行）。
    """
    if site is None:
        site = resolve_site()
    filename, lineno, fallback_area = site

    message = message.rstrip("\r\n")
    area, body = _split_area(message, fallback_area or "?")
    if level is None:
        level = _level_of(body)
    level = level.upper()
    if level not in LEVELS:
        level = "INFO"

    site_text = f"{filename}:{lineno}"
    area_color = AREA_COLORS[sum(area.encode("utf-8")) % len(AREA_COLORS)]
    head = " ".join((
        _color(f"[{stamp or _now_stamp()}]", "time", palette_map),
        _paint(f"[{area}]", area_color if palette_map else None, palette_map),
        _color(f"[{level}]", level, palette_map),
        _color(f"[{site_text}]:", "site", palette_map),
    ))
    return f"{head} {body}" if body else head

def format_message(message: str, *,
                   palette_map: dict | None = None) -> str:
    """格式化多行文本：只有第一行加日志头，后续行原样保留。"""
    lines = message.rstrip("\r\n").split("\n")
    if not lines:
        return ""
    rendered = [build_line(lines[0], palette_map=palette_map)]
    rendered.extend(lines[1:])
    return "\n".join(rendered)

_STAMP_DATE_RE = re.compile(
    r"^((?:\x1b\[[0-9;]*m)*)\[\d{4}-\d{2}-\d{2} (\d{2}:\d{2}:\d{2})(\.\d{3})?\]")

def short_stamp(line: str, *, keep_ms: bool = False) -> str:
    """裁剪日志行里的时间戳；默认去掉毫秒，可保留。

    Args:
        line: 带 ``[YYYY-MM-DD HH:MM:SS.mmm]`` 前缀的一行日志。
        keep_ms: True 时保留毫秒部分。

    Returns:
        str: 时间戳被裁剪后的整行。
    """
    if keep_ms:
        return _STAMP_DATE_RE.sub(r"\1[\2\3]", line, count=1)
    return _STAMP_DATE_RE.sub(r"\1[\2]", line, count=1)
