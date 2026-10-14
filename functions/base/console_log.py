"""控制台输出管道：给 cmd 的每行加统一前缀，并原样镜像进日志文件。

为什么包 ``sys.stdout`` 而不是去改几百处 ``print``：启动器的输出散落在
``print`` / ``rich`` / 第三方库 / 子模块里，逐个调用点改既不现实也改不全。
包一层就能让每一行都套上统一布局，而不用动任何调用点。

布局本身在 :mod:`functions.base.log_format`，这里只负责搬运字节：

    [2026-10-11 11:21:28.291] [hook] [INFO] [updater.py:314]: offset index up to date

本模块保留的职责：

* 包装 ``sys.stdout`` / ``sys.stderr``，让控制台的行都经过
  :func:`functions.base.log_format.build_line`；
* 把**同一份**文本镜像进滚动日志文件，这正是日志文件和控制台能对上的原因
  （见 :mod:`functions.base.log_manager`）；
* 多行写入保持原样。带内嵌换行的 ``print``（启动横幅、ASCII 图、回溯）只有首行
  会加前缀，``print`` 随后单独写出的换行直接透传，于是图案排版不被破坏；含 ``\\r``
  的写入（进度条）也原样转发。

与 UI 终端的关系：日志文件归本模块所有，一行文本也只在这里渲染一次。Tk 终端和 Web
终端通过 :func:`add_line_hook` 订阅，直接绘制拿到的文本（连 ANSI 颜色一起，由各自的
解析器上色），因此任何 UI 都不再自己加前缀、加时间戳或另写一遍日志文件。
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


def add_line_hook(hook) -> None:
    """注册 ``hook(text)``，接收控制台每一条完整的行。

    ``text`` 不含结尾换行，但**带 ANSI 颜色**——用什么颜色由
    :mod:`functions.base.log_format` 一次定好，钩子拿到的就是 cmd 上显示的那一份。
    钩子调用时不持有调用方可见的锁；钩子内部抛异常会被吞掉，坏掉的 UI 绝不能拖垮
    控制台。
    """
    with _hooks_lock:
        if hook not in _line_hooks:
            _line_hooks.append(hook)


def remove_line_hook(hook) -> None:
    """撤销 :func:`add_line_hook`；未知的钩子直接忽略。"""
    with _hooks_lock:
        try:
            _line_hooks.remove(hook)
        except ValueError:
            pass


def _emit_line(line: str) -> None:
    """把一条完成的行分发给所有已注册的 UI 钩子。"""
    with _hooks_lock:
        hooks = list(_line_hooks)
    for hook in hooks:
        try:
            hook(line)
        except Exception:
            pass


# --------------------------------------------------------------------------- 颜色

def _enable_ansi() -> bool:
    """尽力为经典 cmd 打开 ANSI 支持；返回 False 表示放弃着色。"""
    if os.name != "nt":
        return True
    try:
        import colorama                                   # requirements 里已声明
        colorama.just_fix_windows_console()
        return True
    except Exception:
        pass
    try:
        import ctypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        for handle_id in (-11, -12):                      # stdout / stderr
            handle = kernel32.GetStdHandle(handle_id)
            mode = ctypes.c_uint32()
            if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                kernel32.SetConsoleMode(handle, mode.value | 0x0004)
        return True
    except Exception:
        return False


def _mirror_to_log(line: str) -> None:
    """把一条已格式化的行抄进滚动日志文件。

    文本原样写入：时间戳、区域、级别、来源它都已经带了，日志文件不需要自己的
    formatter。写失败绝不能影响调用方的 print，所以整个函数被兜底保护。
    """
    try:
        from functions.base.log_manager import write_line
        write_line(line)
    except Exception:
        pass


# --------------------------------------------------------------------------- 输出流代理

class _ConsoleStream:
    """给写进控制台流的行加前缀，并把它们镜像到日志文件。

    ``print("a\\nb\\nc")`` 会以两次写入到达这里（正文、然后是结尾换行），所以规则是：
    **一次写入里只有第一行算新的日志行，其余原样透传**。``_raw_tail`` 记住上一次
    写入没有以换行结束，于是紧随其后的那个换行会被直接转发，而不是给横幅的最后
    一行加上前缀。
    """

    def __init__(self, raw, name: str):
        self._raw = raw
        self._name = name
        self._buf = ""
        self._raw_tail = False
        self._lock = threading.RLock()

    # ---- 第三方库会探测这些属性，缺一个就可能把它们弄崩
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

    # ---- 真正的写入
    def write(self, text):
        if not text:
            return 0
        if not isinstance(text, str):
            text = str(text)
        if "\r" in text:                                  # 进度条：原样透传
            return self._raw.write(text)
        with self._lock:
            if self._raw_tail and text.startswith("\n"):
                # 上一次写入停在一行中途（多行块的尾部），这个换行只是收尾。
                self._raw_tail = False
                return self._raw.write(text)
            self._buf += text
            if "\n" not in self._buf:
                return len(text)
            first, rest = self._buf.split("\n", 1)
            self._buf = ""
        out = self._format(first)
        if rest:
            # 同一次写入里剩下的行（横幅 / 回溯 / 打印块）原样透传，
            # 这样缩进和图案排版不会被破坏。
            self._raw_tail = not rest.endswith("\n")
            out += rest
        return self._raw.write(out)

    def _format(self, line: str) -> str:
        if not line.strip():
            # 空白行（``print("")`` 之类）不进日志、也不上报 UI：生成一条只有前缀、
            # 没有内容的记录毫无意义。三处都按普通空行处理，才谈得上一致。
            return "\n"
        rendered = log_format.build_line(
            line, palette_map=log_format.palette(_color_ok))
        _mirror_to_log(rendered)
        # UI 终端拿到的是 cmd 打印的同一份文本，**连颜色一起**：着色只在 log_format
        # 里决定一次，前端与 Tk 各自把转义序列解析成自己的颜色，这样就不会出现
        # “cmd 有颜色、面板没颜色”的偏差。以 `|` 开头的是启动器的“内部管道”标记，
        # 屏幕终端一律过滤掉。
        if not line.startswith("|"):
            _emit_line(rendered)
        return rendered + "\n"

    def flush(self):
        try:
            self._raw.flush()
        except Exception:
            pass


# --------------------------------------------------------------------------- 安装

def is_installed() -> bool:
    return _installed


def install() -> bool:
    """用带前缀的代理包住 ``sys.stdout`` / ``sys.stderr``（幂等）。

    只在真正拥有用户可见控制台的入口调用：成就监测子进程的 stdout 被父进程接到
    成就日志文件上，那里不该出现这个前缀。
    """
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
        # 顺序有讲究：先让 colorama/SetConsoleMode 把真实流准备好，再抓住它作为
        # 落点。不支持 ANSI 的主机上，转义序列随后会被翻译或剥掉，而不是原样打印。
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
