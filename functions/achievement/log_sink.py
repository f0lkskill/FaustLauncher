"""成就日志的**唯一落点**登记处。

以前成就子系统要写好几份日志：``logs/achievement_hook.log``（成就生命周期）、
``logs/achievement_hook_child.log``（子进程 stdout/stderr）、``logs/battle_watch.log``
（DLL 全量事件流），外加 ``cache/achievement/`` 下的启动面包屑与 faulthandler 文件 ——
出问题时要跨好几个文件对时间，用户也反馈"日志太散"。

现在统一成一份 ``logs/achievement_hook.log``：

  · 父进程负责清空 + 写 BOM，并把子进程的 stdout/stderr **追加**到同一个文件；
  · 子进程的 ``hook._LogSink`` 也写它（O_APPEND），并把自己的写函数登记到本模块；
  · 战斗观测、启动面包屑通过 :func:`write` 写同一份，不再各开各的文件。

没有登记时 :func:`write` 返回 ``False``，调用方回退到自己的文件 ——
``python -m functions.achievement.battle_watch`` 这类离线自查仍然能单独出日志。
"""

from __future__ import annotations

import threading

_LOCK = threading.Lock()
_SINK = None                      # Callable[[str], None]


def install(sink) -> None:
    """登记当前进程的日志写函数（子进程启动时由 hook 调用）。"""
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


def write(message: str) -> bool:
    """把一行写进统一日志；没有登记时返回 ``False``（调用方自行回退）。"""
    with _LOCK:
        sink = _SINK
    if sink is None:
        return False
    try:
        sink(message)
        return True
    except Exception:  # noqa: BLE001
        return False
