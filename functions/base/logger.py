
from __future__ import annotations

import sys

from functions.base import log_format

__all__ = ["debug", "info", "warn", "error", "log", "LEVELS"]

LEVELS = ("DEBUG", "INFO", "WARN", "ERROR")

_ALIASES = {"warning": "WARN", "fatal": "ERROR", "critical": "ERROR",
            "verbose": "DEBUG"}

def log(message, level: str = "INFO") -> str:
    level = _normalize(level)
    text = _coerce(message)
    _emit(text, level)
    return log_format.build_line(text, level=level)

def _coerce(message) -> str:
    if isinstance(message, str):
        return message
    return str(message)

def _normalize(level) -> str:
    if not isinstance(level, str):
        return "INFO"
    up = level.strip().upper()
    up = _ALIASES.get(up.lower(), up)
    return up if up in LEVELS else "INFO"

def debug(message, *args) -> None:
    _write("DEBUG", message, args)

def info(message, *args) -> None:
    _write("INFO", message, args)

def warn(message, *args) -> None:
    _write("WARN", message, args)

def error(message, *args) -> None:
    _write("ERROR", message, args)

def _write(level: str, message, args: tuple) -> None:
    text = _format_args(message, args)
    _emit(text, level)

def _format_args(message, args: tuple):
    if not args:
        return message
    if isinstance(message, str):
        try:
            return message % args
        except Exception:
            return message + " " + " ".join(str(a) for a in args)
    return " ".join(str(a) for a in (message,) + args)

def _emit(text: str, level: str) -> None:
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
