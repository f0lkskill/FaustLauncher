
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

    timestamp: str
    level: str
    area: str
    filename: str
    lineno: int
    message: str

def strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)

def _area_of(filename: str) -> str:
    parts = re.split(r"[\\/]", os.path.abspath(filename))
    for marker in ("functions", "addons"):
        if marker not in parts:
            continue
        idx = len(parts) - 1 - parts[::-1].index(marker)
        if idx + 2 < len(parts):
            return parts[idx + 1]
    return os.path.splitext(parts[-1])[0]

def resolve_site() -> tuple[str, int, str]:
    frame = sys._getframe(1)
    while frame is not None:
        code = frame.f_code
        name = os.path.basename(code.co_filename)
        if not any(name == skipped and (func is None or func == code.co_name)
                   for skipped, func in SKIP_FRAMES):
            return name, frame.f_lineno, _area_of(code.co_filename)
        frame = frame.f_back
    return "?", 0, "?"

_ZERO_STAT_RE = re.compile(r"\s*[:：]?\s*0(?:\s*[个次条项分%])?")

def _mentions(message: str, word: str) -> bool:
    start = 0
    while True:
        idx = message.find(word, start)
        if idx < 0:
            return False
        if not _ZERO_STAT_RE.match(message, idx + len(word)):
            return True
        start = idx + len(word)

def _level_of(message) -> str:
    if not isinstance(message, str):
        message = str(message)
    lowered = message.lower()
    for level, words in LEVEL_RULES:
        if any(_mentions(message, word) or _mentions(lowered, word)
               for word in words):
            return level
    return "INFO"

def _split_area(message: str, fallback: str) -> tuple[str, str]:
    match = _TAG_RE.match(message)
    if match:
        return match.group(1), match.group(2)
    return fallback, message

def level_of(message: str) -> str:
    return _level_of(message)

def split_area(message: str, fallback: str) -> tuple[str, str]:
    return _split_area(message, fallback)

def _now_stamp() -> str:
    now = datetime.datetime.now()
    return now.strftime("%Y-%m-%d %H:%M:%S") + f".{now.microsecond // 1000:03d}"

def palette(enabled: bool = True):
    return PALETTE if enabled else None

def _paint(text: str, code: str | None, palette_map: dict | None) -> str:
    if not palette_map or not code:
        return text
    return f"{code}{text}{PALETTE['reset']}"

def _color(text: str, style: str | None, palette_map: dict | None) -> str:
    if not palette_map or not style:
        return text
    return _paint(text, palette_map.get(style), palette_map)

def build_line(message: str, *,
               site: tuple[str, int, str] | None = None,
               level: str | None = None,
               palette_map: dict | None = None,
               stamp: str | None = None) -> str:
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
    lines = message.rstrip("\r\n").split("\n")
    if not lines:
        return ""
    rendered = [build_line(lines[0], palette_map=palette_map)]
    rendered.extend(lines[1:])
    return "\n".join(rendered)

_STAMP_DATE_RE = re.compile(
    r"^((?:\x1b\[[0-9;]*m)*)\[\d{4}-\d{2}-\d{2} (\d{2}:\d{2}:\d{2})(\.\d{3})?\]")

def short_stamp(line: str, *, keep_ms: bool = False) -> str:
    if keep_ms:
        return _STAMP_DATE_RE.sub(r"\1[\2\3]", line, count=1)
    return _STAMP_DATE_RE.sub(r"\1[\2]", line, count=1)
