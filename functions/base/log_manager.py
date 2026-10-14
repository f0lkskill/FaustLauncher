"""日志文件生命周期：每次运行一个文件，保留数量有上限。

布局约定
--------
行通过 :func:`write_line` 进入本模块，此时文本已由
:mod:`functions.base.log_format` 渲染完毕（控制台、Tk 终端、Web 终端共用同一套
布局）。因此文件 handler **不再**添加任何前缀——再加一次就会打印两遍时间戳，并让
``logs/*.log`` 与 cmd 窗口对不上，而这正是本模块以前造成的问题。

命名与保留策略：

- 每次运行一个文件：``logs/YYYY-MM-DD_HH-MM-SS.log``
- 超过 :data:`MAX_KEEP_DAYS` 天的文件删除
- 每个自然日最多保留 :data:`MAX_KEEP_PER_DAY` 个文件，从最早的开始删
"""
import os
import re
import datetime
import logging

LOG_DIR = "logs"
MAX_KEEP_DAYS = 3
MAX_KEEP_PER_DAY = 7

_logger = None


def _ensure_dir():
    os.makedirs(LOG_DIR, exist_ok=True)


def _cleanup_logs():
    """删除超过 MAX_KEEP_DAYS 天的日志，并把每天的文件数压到 MAX_KEEP_PER_DAY。"""
    try:
        today = datetime.date.today()
        cutoff = today - datetime.timedelta(days=MAX_KEEP_DAYS - 1)
        by_day = {}
        for fname in os.listdir(LOG_DIR):
            path = os.path.join(LOG_DIR, fname)
            if not fname.endswith(".log") or not os.path.isfile(path):
                continue
            m = re.match(r"(\d{4}-\d{2}-\d{2})_", fname)
            if not m:
                continue
            try:
                day = datetime.datetime.strptime(m.group(1), "%Y-%m-%d").date()
            except ValueError:
                continue
            if day < cutoff:
                try:
                    os.remove(path)
                except OSError:
                    pass
                continue
            by_day.setdefault(day, []).append(fname)
        for day, files in by_day.items():
            if len(files) > MAX_KEEP_PER_DAY:
                files.sort()
                for fname in files[: len(files) - MAX_KEEP_PER_DAY]:
                    try:
                        os.remove(os.path.join(LOG_DIR, fname))
                    except OSError:
                        pass
    except Exception:
        pass


def init_logger():
    """创建本次运行的日志文件并把它装成唯一的 handler（每次运行调用一次）。"""
    global _logger
    _ensure_dir()
    fname = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S") + ".log"
    path = os.path.join(LOG_DIR, fname)

    _logger = logging.getLogger("FaustLauncher")
    _logger.setLevel(logging.INFO)
    for h in list(_logger.handlers):
        _logger.removeHandler(h)
        try:
            h.close()
        except Exception:
            pass
    handler = logging.FileHandler(path, encoding="utf-8")
    # formatter 里不带时间戳/级别：write_line() 收到的行已经由统一布局打好标记，
    # 这里再加前缀就会重复。
    handler.setFormatter(logging.Formatter("%(message)s"))
    _logger.addHandler(handler)

    _cleanup_logs()

    from functions.base.terminal_banner import get_banner, get_random_font, get_random_color
    font = get_random_font()
    color = get_random_color()
    print(get_banner("FaustLauncher", font=font, colors=color))

    # 横幅本身已经通过 print() -> 控制台流 -> write_line() 进了文件，这里只补一条
    # 运行头。以前把横幅再写一遍，正是日志文件与 cmd 窗口对不上（多一份、前缀还不
    # 一样）的原因。
    _announce(f"Faust Launcher instance started ({fname})")
    return _logger


def _announce(message: str) -> None:
    """按统一布局写一行启动信息。

    普通输出经控制台流进入文件；这里覆盖的是控制台流装好之前就存在的少数消息。
    """
    try:
        from functions.base import log_format
        write_line(log_format.build_line(message, site=("log_manager.py", 0, "logs")))
    except Exception:
        pass


def get_logger():
    """返回进程级 logger，首次使用时创建本次运行的日志文件。"""
    global _logger
    if _logger is None:
        init_logger()
    return _logger


def write_line(line: str) -> None:
    """把一条**已格式化**的行原样追加到日志文件。

    :mod:`functions.base.console_log` 用它写入与控制台完全相同的那份文本，这也是
    ``logs/*.log`` 能与 cmd 窗口逐字节一致的原因。文件要当纯文本读，所以 ANSI 颜色
    会被剥掉。
    """
    try:
        text = re.sub(r"\x1b\[[0-9;]*m", "", line).rstrip("\r\n")
        if text:
            get_logger().info("%s", text) # type: ignore
    except Exception:
        pass


def log_message(message) -> None:
    """用统一布局格式化 *message* 后追加到日志文件。

    留给手里只有未加前缀原文的调用方。经由 ``sys.stdout`` 的输出不需要它——控制台流
    已经记过一遍，再调一次就会出现重复行。
    """
    try:
        from functions.base import log_format
        write_line(log_format.format_message(str(message)))
    except Exception:
        pass
