"""极简日志门面：按级别输出一行文本到终端。

``debug/info/warn/error`` 接受 printf 风格的 ``%`` 参数；实际行格式（时间、
模块、级别、文件行号）由 :mod:`functions.base.log_format` 负责。这里还兼容
控制台的彩色流：检测到自定义 ``_ConsoleStream`` 时直接写裸文本，由流自己
按 ``level`` 上色；否则写完整的单行格式。
"""

from __future__ import annotations

import sys

from functions.base import log_format

__all__ = ["debug", "info", "warn", "error", "log", "LEVELS"]

LEVELS = ("DEBUG", "INFO", "WARN", "ERROR")

_ALIASES = {"warning": "WARN", "fatal": "ERROR", "critical": "ERROR",
            "verbose": "DEBUG"}

def log(message, level: str = "INFO") -> str:
    """输出一条日志并返回最终写出的那一行（便于复用/测试）。

    Args:
        message: 文本或可 ``str()`` 的对象。
        level: DEBUG/INFO/WARN/ERROR；别名会归一化，非法值当 INFO。

    Returns:
        str: 带时间戳/级别等前缀的完整行。
    """
    level = _normalize(level)
    text = _coerce(message)
    _emit(text, level)
    return log_format.build_line(text, level=level)

def _coerce(message) -> str:
    """把非字符串消息转成字符串，字符串本身原样返回。"""
    if isinstance(message, str):
        return message
    return str(message)

def _normalize(level) -> str:
    """把级别别名（warning/fatal/verbose 等）归一到四级，非法值当 INFO。"""
    if not isinstance(level, str):
        return "INFO"
    up = level.strip().upper()
    up = _ALIASES.get(up.lower(), up)
    return up if up in LEVELS else "INFO"

def debug(message, *args) -> None:
    """输出 DEBUG 级日志；``message % args`` 可用 printf 风格占位。"""
    _write("DEBUG", message, args)

def info(message, *args) -> None:
    """输出 INFO 级日志；``message % args`` 可用 printf 风格占位。"""
    _write("INFO", message, args)

def warn(message, *args) -> None:
    """输出 WARN 级日志；``message % args`` 可用 printf 风格占位。"""
    _write("WARN", message, args)

def error(message, *args) -> None:
    """输出 ERROR 级日志；``message % args`` 可用 printf 风格占位。"""
    _write("ERROR", message, args)

def _write(level: str, message, args: tuple) -> None:
    """按级别格式化参数并写到输出流。"""
    text = _format_args(message, args)
    _emit(text, level)

def _format_args(message, args: tuple):
    """优先 ``message % args``；格式不匹配时退化为空格拼接。"""
    if not args:
        return message
    if isinstance(message, str):
        try:
            return message % args
        except Exception:
            return message + " " + " ".join(str(a) for a in args)
    return " ".join(str(a) for a in (message,) + args)

def _emit(text: str, level: str) -> None:
    """写终端：自定义控制台流写裸文本并带级别，否则写带前缀的完整行。"""
    try:
        from functions.base import console_log
        stream = sys.stdout
        if isinstance(stream, console_log._ConsoleStream):
            console_log._explicit.level = level
            stream.write(text + "\n")
            return
    except Exception:
        pass
    try:
        raw = getattr(sys.stdout, "_raw", sys.stdout)
        raw.write(log_format.build_line(text, level=level) + "\n")
    except Exception:
        pass
