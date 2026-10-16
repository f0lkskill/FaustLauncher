
from __future__ import annotations

import datetime as _datetime
import re
import threading

from functions.base.log_format import level_of as _level_of
from functions.base.log_format import split_area as _split_area

__all__ = ["install", "clear", "installed", "write", "format_line", "DEFAULT_AREA"]

_LOCK = threading.Lock()
_SINK = None

DEFAULT_AREA = "AchMonitor"

_TS_PREFIX_RE = re.compile(r"^\[?\d{2}:\d{2}:\d{2}(?:\.\d{1,3})?\]?[ \t]+")

def _now_stamp() -> str:
    now = _datetime.datetime.now()
    return now.strftime("%H:%M:%S") + f".{now.microsecond // 1000:03d}"

def format_line(message: str, *, area: str | None = None,
                stamp: str | None = None) -> str:
    text = str(message).replace("\r\n", "\n").rstrip("\n")
    if not text.strip():
        return ""
    head, _, tail = text.partition("\n")
    body = _TS_PREFIX_RE.sub("", head.lstrip(), count=1).rstrip()
    fallback = area or DEFAULT_AREA
    area_name, body = _split_area(body, fallback)
    head_out = f"[{stamp or _now_stamp()}] [{area_name}] [{_level_of(body)}]"
    if body:
        head_out += f" {body}"
    return head_out + (f"\n{tail}" if tail else "")

def install(sink) -> None:
    global _SINK
    with _LOCK:
        _SINK = sink

def clear() -> None:
    global _SINK
    with _LOCK:
        _SINK = None

def installed() -> bool:
    with _LOCK:
        return _SINK is not None

def write(message: str, area: str | None = None) -> bool:
    with _LOCK:
        sink = _SINK
    if sink is None:
        return False
    try:
        try:
            sink(message, area)
        except TypeError:
            sink(message)
        return True
    except Exception:  # noqa: BLE001
        return False
