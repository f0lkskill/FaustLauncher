"""成就日志的**唯一落点**与**唯一格式**登记处。

以前成就子系统要写好几份日志：``logs/achievement_hook.log``（成就生命周期）、
``logs/achievement_hook_child.log``（子进程 stdout/stderr）、``logs/battle_watch.log``
（DLL 全量事件流），外加 ``cache/achievement/`` 下的启动面包屑与 faulthandler 文件 ——
出问题时要跨好几个文件对时间，用户也反馈"日志太散"。

现在统一成一份 ``logs/achievement_hook.log``：

  · 父进程负责清空 + 写 BOM，并把子进程的 stdout/stderr **逐行格式化后追加**到同一个文件；
  · 子进程的 ``hook._LogSink`` 也写它（O_APPEND），并把自己的写函数登记到本模块；
  · 战斗观测、启动面包屑通过 :func:`write` 写同一份，不再各开各的文件。

**行格式**（本模块是唯一实现处，凡写成就日志的行都必须过 :func:`format_line`）::

    [12:06:28.770] [BattleWatch] [INFO] 注入成功 PID=19432 dll=...
    [12:06:28.771] [OffsetProbe] [WARN] 对不上的钩子 19/26 条

即 ``[时:分:秒.毫秒] [区域] [级别] 正文`` —— 与启动器主日志同一风格，但**不带日期**
（这份日志每次启动都会清空，只服务本次会话，日期是噪声）。

区域取正文开头的 ``[标签]``；没有就用调用方给的默认区域。级别复用启动器主日志的
关键字规则（:func:`functions.base.log_format.level_of`），这样"跳过/失败/异常"这些词
在两份日志里含义一致。

没有登记时 :func:`write` 返回 ``False``，调用方回退到自己的文件 ——
``python -m functions.achievement.battle_watch`` 这类离线自查仍然能单独出日志。
"""

from __future__ import annotations

import datetime as _datetime
import re
import threading

from functions.base.log_format import level_of as _level_of
from functions.base.log_format import split_area as _split_area

__all__ = ["install", "clear", "installed", "write", "format_line", "DEFAULT_AREA"]

_LOCK = threading.Lock()
_SINK = None                      # Callable[[str, str | None], None]

# 解析不到 ``[区域]`` 标签时用哪个区域名
DEFAULT_AREA = "AchMonitor"

# 已有时间戳前缀：``[12:06:09] `` / ``12:06:28.770 `` / ``[12:06:28.770] ``
_TS_PREFIX_RE = re.compile(r"^\[?\d{2}:\d{2}:\d{2}(?:\.\d{1,3})?\]?[ \t]+")


def _now_stamp() -> str:
    """``HH:MM:SS.mmm`` —— 毫秒用 ``microsecond // 1000`` 而不是浮点 ``time()*1000``。"""
    now = _datetime.datetime.now()
    return now.strftime("%H:%M:%S") + f".{now.microsecond // 1000:03d}"


def format_line(message: str, *, area: str | None = None,
                stamp: str | None = None) -> str:
    """把一行（或一段多行）成就日志渲染成统一格式。

    · 空白行 → 空字符串（调用方写一行空行，不做任何装饰）；
    · 首行：先剥掉可能已经存在的时间戳，再把开头的 ``[标签]`` 提升为区域列，
      最后补 ``[时间] [区域] [级别]``；
    · 续行原样保留（成就日志里多行消息都是缩进的小表格，缩进本身就是可读性）。
    """
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
    """登记当前进程的日志写函数（子进程启动时由 hook 调用）。

    *sink* 形如 ``callable(message, area=None)``；只接受一个参数的老式写函数也能用。
    """
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
    """把一行写进统一日志；没有登记时返回 ``False``（调用方自行回退）。"""
    with _LOCK:
        sink = _SINK
    if sink is None:
        return False
    try:
        try:
            sink(message, area)
        except TypeError:
            # 兼容只接受一个参数的老式写函数（格式仍由 _LogSink 统一处理）
            sink(message)
        return True
    except Exception:  # noqa: BLE001
        return False
