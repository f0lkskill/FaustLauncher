# -*- coding: utf-8 -*-
"""warphook 诊断日志 —— C 侧引擎到底在干什么，一眼可见。

与 :mod:`warphook.host` 的关系：host 负责把事件读出来，这里负责把
「读到了什么、翻成了什么、引擎状态如何」原样落到磁盘。落盘位置与
:mod:`warphook.base` 相同 —— **整个 WarpHook 只有 ``addons/WarpHook/warp.log``
一个文件**，C 侧宿主 DLL 的事件同样写进这个文件，行首用
``[event]`` / ``[host]`` 区分类型。

三层结构，全部单行、带时间戳、可 grep：

``CFG``  钩子表安装快照
    push 之后立刻写。每条钩子一行：槽号、目标方法、参数个数、事件号、
    读链条数、when/ret——配置有没有真的写进共享内存，看这里。
``EVT``  事件流水
    每读一条事件写一行：事件号、来源槽与方法名、十二个槽位原始值、
    翻译出的行。C 报了什么、Python 翻成了什么，逐条对得上。
``ST``   周期状态（5 秒节流，只有变化才写）
    引擎挂接状态、钩子安装数、事件环水位、累计丢弃、最近错误，
    以及「自上次状态行以来命中数有变化的钩子」——哪个钩子在动，
    一眼定位。

所有函数绝不抛异常：诊断日志挂了不能拖死事件泵。环境变量
``WARP_DIAG=0`` 可整体关闭。
"""

import ctypes
import logging
import os
import threading
import time

from .base import _LOGGER as _SHARED_LOGGER
from .base import _LOG_LOCK as _SHARED_LOCK
from .base import _start_block as _shared_start
from .host import (
    HOST_ACT_EVENT,
    HOST_EVENT_SLOTS,
    HOST_HOOK_OFFSET,
    HOST_HOOK_SIZE,
    HOST_MAX_HOOKS,
    HostHeader,
    HostHook,
)

_Lock = threading.Lock()
_logger = None
_last_state_at = 0.0
_state_interval = 5.0          # ST 行的节流窗口（秒）
_last_counters = {}            # slot -> (hits, blocked)，ST 只报增量
_last_evt_total = 0            # 上次 ST 看到的 header.evt_count

_SLOT_KEYS = ("a", "b", "c", "d", "e", "f", "g", "h", "i", "j", "k", "l")


def _enabled():
    from .base import is_debug_enabled
    return is_debug_enabled() and os.environ.get("WARP_DIAG", "1") != "0"


def _log():
    """与 :mod:`warphook.base` 共用同一个 logger / 同一个文件（``warp.log``）。

    以前这里自己开 ``warp_events.log``（2MB×3 轮转），和 base 的
    ``warp_python.log`` 各写一份、再叠加宿主 DLL 的 ``warp_host.log`` ——
    一次调试产出一堆文件和 ``.log.1/.2/.3`` 备份，日志类型还分不清谁是谁。
    现在只有 ``warp.log`` 一个文件，类型靠 ``[event]`` / ``[host]`` 前缀区分。
    """
    global _logger
    with _Lock:
        if _logger is not None:
            return _logger
        base_logger = _SHARED_LOGGER
        if base_logger is None:
            # 让 base 先把 handler 建好（用一条最小的 host 行触发），再复用。
            try:
                from .base import log as _base_log
                _base_log("事件流水开始", tag="host")
            except Exception:                # noqa: BLE001
                pass
            base_logger = _SHARED_LOGGER
        _logger = base_logger or logging.getLogger("warphook.runtime")
        return _logger


def _emit(line):
    if not _enabled():
        return
    try:
        _log().info("[event] %s", line)
    except Exception:                        # noqa: BLE001
        pass


# --------------------------------------------------------------------------
# CFG —— 钩子表安装快照
# --------------------------------------------------------------------------

def config_snapshot(source):
    """attach/push 之后调用：把本插件的钩子表逐条落盘。

    ``source`` 是 :class:`functions.achievement.warp_source.WarpSource`，
    需要 ``_hooks``（build_hooks 的产物）与 ``_host``。
    """
    try:
        hooks = getattr(source, "_hooks", None) or []
        host = getattr(source, "_host", None)
        _emit("CFG ==== push %d hooks (engine hooked=%s) ====" % (
            len(hooks), _engine_on(host)))
        for i, hook in enumerate(hooks):
            reads = hook.get("reads") or []
            extras = []
            if hook.get("cache_arg") is not None and hook.get("cache_arg") >= 0:
                extras.append("cache=arg%d->slot%s" % (
                    hook.get("cache_arg"), hook.get("cache_slot")))
            when = "post" if hook.get("when") == 1 else "pre"
            ret = hook.get("ret_kind")
            ret = "-" if ret in (None, 0) else str(ret)
            _emit("CFG slot=%02d %s::%s argc=%s ev=%s when=%s ret=%s reads=%d "
                  "kind=%s %s" % (
                      i, hook.get("klass"), hook.get("method"),
                      hook.get("argc"), hook.get("event"), when, ret,
                      len(reads), hook.get("kind"), " ".join(extras)))
    except Exception:                        # noqa: BLE001
        pass


def _engine_on(host):
    """引擎挂接状态：True/False/未知。"""
    try:
        block = host.block()
        if block is None:
            return "no-map"
        hdr = ctypes.cast(block.address, ctypes.POINTER(HostHeader)).contents
        return "hooked" if hdr.hooked else "not-hooked"
    except Exception:                        # noqa: BLE001
        return "?"


# --------------------------------------------------------------------------
# EVT —— 事件流水
# --------------------------------------------------------------------------

def event(source, ev, hook, lines):
    """pump 每读到一条事件调用一次。

    ``ev`` 是 host.events() 的 dict（十二格），``hook`` 是命中的钩子
    spec，``lines`` 是翻译出的行列表（即使为空也记——空说明翻译层
    没接住这个 kind，正是要抓的）。
    """
    try:
        vals = ",".join(str(int(ev.get(key, 0))) for key in _SLOT_KEYS)
        text = " | ".join(lines) if lines else "-"
        _emit("EVT ev=%s slot=%02d %s out=[%s] -> %s" % (
            ev.get("id"), ev.get("hook", -1), hook.get("method"), vals, text))
    except Exception:                        # noqa: BLE001
        pass


def dropped(source, lost_delta):
    """host.events() 报告了新的丢弃数：单独一行，醒目。"""
    try:
        _emit("DROP +%d (累计丢失 %s)" % (lost_delta, lost_delta))
    except Exception:                        # noqa: BLE001
        pass


# --------------------------------------------------------------------------
# ST —— 周期状态
# --------------------------------------------------------------------------

def state(source, force=False):
    """pump 轮末调用；5 秒节流，值没变化就不写。"""
    global _last_state_at, _last_counters, _last_evt_total
    now = time.time()
    if not force and now - _last_state_at < _state_interval:
        return
    _last_state_at = now
    try:
        host = getattr(source, "_host", None)
        block = host.block() if host else None
        if block is None:
            _emit("ST engine=no-map")
            return
        hdr = ctypes.cast(block.address, ctypes.POINTER(HostHeader)).contents
        hooks = getattr(source, "_hooks", None) or []
        base = block.address + HOST_HOOK_OFFSET

        moved = []
        for i in range(min(len(hooks), HOST_MAX_HOOKS)):
            slot = base + i * HOST_HOOK_SIZE
            hits = ctypes.c_int32.from_address(
                slot + HostHook.hits.offset).value
            blocked = ctypes.c_int32.from_address(
                slot + HostHook.blocked.offset).value
            prev = _last_counters.get(i)
            if prev != (hits, blocked):
                name = (hooks[i].get("method") or "?")[:24]
                if prev is None:
                    moved.append("%s=%d/%d" % (name, hits, blocked))
                else:
                    d_hits = hits - prev[0]
                    d_blk = blocked - prev[1]
                    if d_hits or d_blk:
                        moved.append("%s=+%d/%+d" % (name, d_hits, d_blk))
            _last_counters[i] = (hits, blocked)

        evt_total = int(hdr.evt_count)
        evt_delta = ""
        if evt_total != _last_evt_total:
            evt_delta = " evtΔ=%+d" % (evt_total - _last_evt_total)
        _last_evt_total = evt_total

        lost = int(getattr(source, "events_lost", 0) or 0)
        tail = hdr.log_tail.decode("utf-8", "replace").strip()[:48] \
            if hdr.log_tail else ""
        _emit("ST %s inst=%d/%d evt=%d%s lost=%d err=%d fired=%d%s%s" % (
            _engine_on(host), int(hdr.hook_installed), int(hdr.hook_total),
            evt_total, evt_delta, lost, int(hdr.last_error), int(hdr.fired),
            " tail=\"" + tail + "\"" if tail else "",
            " Δ" + ",".join(moved) if moved else ""))
    except Exception:                        # noqa: BLE001
        pass


def reset():
    """跨引擎重启清增量基线（下次 ST 全量报一遍）。"""
    global _last_counters, _last_evt_total, _last_state_at
    _last_counters = {}
    _last_evt_total = 0
    _last_state_at = 0.0
