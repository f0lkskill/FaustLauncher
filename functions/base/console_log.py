
from __future__ import annotations

import os
import sys
import threading

from functions.base import log_format
from functions.base.log_format import LogRecord

__all__ = ["install", "uninstall", "is_installed",
           "add_line_hook", "remove_line_hook"]

_installed = False
_lock = threading.RLock()
_color_ok = False
_line_hooks: list = []
_hooks_lock = threading.RLock()
_explicit = threading.local()

def _take_level():
    level = getattr(_explicit, "level", None)
    _explicit.level = None
    return level

def add_line_hook(hook) -> None:
    with _hooks_lock:
        if hook not in _line_hooks:
            _line_hooks.append(hook)

def remove_line_hook(hook) -> None:
    with _hooks_lock:
        try:
            _line_hooks.remove(hook)
        except ValueError:
            pass

def _emit_line(line: str) -> None:
    with _hooks_lock:
        hooks = list(_line_hooks)
    for hook in hooks:
        try:
            hook(line)
        except Exception:
            pass

def _enable_ansi() -> bool:
    if os.name != "nt":
        return True
    try:
        import colorama
        colorama.just_fix_windows_console()
        return True
    except Exception:
        pass
    try:
        import ctypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        for handle_id in (-11, -12):
            handle = kernel32.GetStdHandle(handle_id)
            mode = ctypes.c_uint32()
            if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                kernel32.SetConsoleMode(handle, mode.value | 0x0004)
        return True
    except Exception:
        return False

def _mirror_to_log(line: str) -> None:
    try:
        from functions.base.log_manager import write_line
        write_line(line)
    except Exception:
        pass

class _ConsoleStream:

    def __init__(self, raw, name: str):
        self._raw = raw
        self._name = name
        self._buf = ""
        self._raw_tail = False
        self._lock = threading.RLock()

    def __getattr__(self, item):
        return getattr(self._raw, item)

    def isatty(self):
        try:
            return bool(self._raw.isatty())
        except Exception:
            return False

    def fileno(self):
        return self._raw.fileno()

    @property
    def encoding(self):
        return getattr(self._raw, "encoding", "utf-8")

    @property
    def errors(self):
        return getattr(self._raw, "errors", "replace")

    def writable(self):
        return True

    def readable(self):
        return False

    def reconfigure(self, **kwargs):
        func = getattr(self._raw, "reconfigure", None)
        if func:
            func(**kwargs)

    def write(self, text):
        if not text:
            return 0
        if not isinstance(text, str):
            text = str(text)
        if "\r" in text:
            return self._raw.write(text)
        with self._lock:
            if self._raw_tail and text.startswith("\n"):
                self._raw_tail = False
                return self._raw.write(text)
            self._buf += text
            if "\n" not in self._buf:
                return len(text)
            first, rest = self._buf.split("\n", 1)
            self._buf = ""
        if rest:
            block = first + "\n" + rest
            self._raw_tail = not rest.endswith("\n")
            self._mirror_block(block)
            return self._raw.write(block)
        out = self._format(first)
        return self._raw.write(out)

    def _mirror_block(self, block: str) -> None:
        for line in block.split("\n"):
            if not line.strip():
                continue
            _mirror_to_log(line)
            if not line.startswith("|"):
                _emit_line(line)

    def _format(self, line: str) -> str:
        if not line.strip():
            return "\n"
        level = _take_level()
        if level is None and getattr(_explicit, "rendered", False):
            _explicit.rendered = False
            _mirror_to_log(line)
            if not line.startswith("|"):
                _emit_line(line)
            return line + "\n"
        rendered = log_format.build_line(
            line, level=level, palette_map=log_format.palette(_color_ok))
        _mirror_to_log(rendered)
        if not line.startswith("|"):
            _emit_line(rendered)
        return rendered + "\n"

    def flush(self):
        try:
            self._raw.flush()
        except Exception:
            pass

def is_installed() -> bool:
    return _installed

def install() -> bool:
    global _installed, _color_ok
    with _lock:
        if _installed:
            return True
        out, err = sys.stdout, sys.stderr
        if out is None or isinstance(out, _ConsoleStream):
            return False
        if err is None or isinstance(err, _ConsoleStream):
            return False
        _color_ok = _enable_ansi()
        sys.stdout = _ConsoleStream(sys.stdout, "stdout")
        sys.stderr = _ConsoleStream(sys.stderr, "stderr")
        _installed = True
        return True

def uninstall() -> None:
    global _installed
    with _lock:
        if not _installed:
            return
        for name in ("stdout", "stderr"):
            stream = getattr(sys, name, None)
            if isinstance(stream, _ConsoleStream):
                setattr(sys, name, stream._raw)
        _installed = False
