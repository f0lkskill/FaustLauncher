"""控制台输出包装与日志镜像。

包装 sys.stdout/stderr，把 print 输出按行加上日志头，同时写日志文件并通过
行钩子推给前端终端。单行走 :meth:`_ConsoleStream._format`；含回车或多行的
块直接透传，避免把进度条/表格拆坏。颜色由 ANSI 控制，Windows 下借 colorama
或内核模式开启。
"""


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
    """取出一次性的显式级别并清空，供 logger 给当前行着色。"""
    level = getattr(_explicit, "level", None)
    _explicit.level = None
    return level

def add_line_hook(hook) -> None:
    """注册行钩子：每条日志行写出后回调，用于前端终端展示。"""
    with _hooks_lock:
        if hook not in _line_hooks:
            _line_hooks.append(hook)

def remove_line_hook(hook) -> None:
    """注销行钩子；没注册过就静默忽略。"""
    with _hooks_lock:
        try:
            _line_hooks.remove(hook)
        except ValueError:
            pass

def _emit_line(line: str) -> None:
    """把格式化后的行分发给所有行钩子，单个钩子出错不影响其他。"""
    with _hooks_lock:
        hooks = list(_line_hooks)
    for hook in hooks:
        try:
            hook(line)
        except Exception:
            pass

def _enable_ansi() -> bool:
    """尝试开启 Windows 控制台的 ANSI 颜色；失败返回 False。"""
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
    """把一行同步写入日志文件；失败静默忽略。"""
    try:
        from functions.base.log_manager import write_line
        write_line(line)
    except Exception:
        pass

class _ConsoleStream:

    """内部ConsoleStream类。"""
    def __init__(self, raw, name: str):
        """包装原始输出流，缓存未满行并持有锁。"""
        self._raw = raw
        self._name = name
        self._buf = ""
        self._raw_tail = False
        self._lock = threading.RLock()

    def __getattr__(self, item):
        """未定义的属性直接转发给原始流。"""
        return getattr(self._raw, item)

    def isatty(self):
        """转发原始流的 isatty 判断。"""
        try:
            return bool(self._raw.isatty())
        except Exception:
            return False

    def fileno(self):
        """转发原始流的文件描述符。"""
        return self._raw.fileno()

    @property
    def encoding(self):
        """转发原始流编码，缺省 utf-8。"""
        return getattr(self._raw, "encoding", "utf-8")

    @property
    def errors(self):
        """转发原始流错误处理策略，缺省 replace。"""
        return getattr(self._raw, "errors", "replace")

    def writable(self):
        """本流只写。"""
        return True

    def readable(self):
        """本流不可读。"""
        return False

    def reconfigure(self, **kwargs):
        """把 reconfigure 调用转发给原始流（如果它支持）。"""
        func = getattr(self._raw, "reconfigure", None)
        if func:
            func(**kwargs)

    def write(self, text):
        """按行缓冲写入：普通单行加日志头，含回车/多行的块直接透传并镜像。"""
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
        """把多行块逐行写日志并发给行钩子（以 | 开头的表格行不推送）。"""
        for line in block.split("\n"):
            if not line.strip():
                continue
            _mirror_to_log(line)
            if not line.startswith("|"):
                _emit_line(line)

    def _format(self, line: str) -> str:
        """给单行加日志头（时间/模块/级别/位置），再镜像并推送钩子。"""
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
        """刷新原始流；失败静默忽略。"""
        try:
            self._raw.flush()
        except Exception:
            pass

def is_installed() -> bool:
    """控制台输出流是否已被包装。"""
    return _installed

def install() -> bool:
    """把 sys.stdout/stderr 换成带日志格式的包装流；幂等。"""
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
    """把 stdout/stderr 还原成原始流。"""
    global _installed
    with _lock:
        if not _installed:
            return
        for name in ("stdout", "stderr"):
            stream = getattr(sys, name, None)
            if isinstance(stream, _ConsoleStream):
                setattr(sys, name, stream._raw)
        _installed = False
