"""启动器日志接口: 显式级别 (debug / info / warn / error)。

为什么要有这一层
----------------
行布局早已统一在 :mod:`functions.base.log_format`，但**级别**一直是靠正文里的关键词
猜出来的 (``失败`` -> ERROR、``跳过`` -> WARN)。猜错的地方很多：一句话里提到"错误
处理"就不再是错误，而真正该报警的英文消息又匹配不上中文词表。级别是记录方的意图，
只能由调用方给出，不该在事后从文本里倒推。

用法::

    from functions.base import logger

    logger.debug("偏移索引命中缓存 %d 条", n)
    logger.info("启动游戏流水线作业开始")
    logger.warn("插件 %s 被禁用, 跳过载入", name)
    logger.error("复制汉化文件失败: %s", exc)

``print()`` 依然可用，它走同一条渲染管道并被记为 **INFO**。

输出格式 (与 log_format 一致)::

    [2026-10-11 11:21:28.291] [hook] [ERROR] [updater.py:314]: 偏移索引更新失败

各出口的分工
------------
本模块只负责"决定级别 + 渲染整行"，然后把已经带好前缀的文本交给
:func:`functions.base.log_manager.write_line` 与 UI 钩子；控制台流
(:mod:`functions.base.console_log`) 仍然服务 ``print``。两边的行格式完全一致。
"""

from __future__ import annotations

import sys

from functions.base import log_format

__all__ = ["debug", "info", "warn", "error", "log", "LEVELS"]

# 级别顺序: 与 log_format.LEVELS 保持一致 (DEBUG 最详细)。
LEVELS = ("DEBUG", "INFO", "WARN", "ERROR")

# 级别 -> 函数名别名, 方便调用方写 logger.fatal 这类习惯名。
_ALIASES = {"warning": "WARN", "fatal": "ERROR", "critical": "ERROR",
            "verbose": "DEBUG"}


def log(message, level: str = "INFO") -> str:
    """按 *level* 记录一行，返回渲染好的整行文本。"""
    level = _normalize(level)
    text = _coerce(message)
    _emit(text, level)
    return log_format.build_line(text, level=level)


def _coerce(message) -> str:
    """把 message 与其格式化参数拼成最终文本。"""
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
    """DEBUG: 排查用的细节，默认不刷屏。"""
    _write("DEBUG", message, args)


def info(message, *args) -> None:
    """INFO: 正常流程的关键节点。"""
    _write("INFO", message, args)


def warn(message, *args) -> None:
    """WARN: 还能继续，但值得看一眼。"""
    _write("WARN", message, args)


def error(message, *args) -> None:
    """ERROR: 该动作失败或关键前提不成立。"""
    _write("ERROR", message, args)


def _write(level: str, message, args: tuple) -> None:
    text = _format_args(message, args)
    _emit(text, level)


def _format_args(message, args: tuple):
    """``logger.error("失败: %s", e)`` 这类调用在这里完成占位符替换。"""
    if not args:
        return message
    if isinstance(message, str):
        try:
            return message % args
        except Exception:
            return message + " " + " ".join(str(a) for a in args)
    return " ".join(str(a) for a in (message,) + args)


def _emit(text: str, level: str) -> None:
    """把正文交给控制台管道，级别通过线程局部通道传递。

    渲染只做一次：管道 (_ConsoleStream) 会用 build_line 补上前缀，并负责落盘与
    UI 上报。所以这里传的是**正文**，不是带好前缀的整行——否则管道再套一层就会
    出现两份时间戳。控制台管道尚未装好时退化为直接输出整行，绝不抛异常。
    """
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
