"""FaustLauncher 日志系统

- 每次实例运行生成一个日志文件: logs/YYYY-MM-DD_HHMMSS.log
- 最多保留 3 天内的日志文件
- 同一天(同一天内多次实例运行)最多保留 7 个日志文件, 超出删除最早的
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
    """清理过期日志: 超过 3 天的删除; 同一天超过 7 个的删除最早的文件"""
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
    """初始化日志系统(每次实例运行调用一次)"""
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
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
    _logger.addHandler(handler)

    _cleanup_logs()
    
    from functions.base.terminal_banner import get_banner
    print(get_banner("FaustLauncher"))
    _logger.info(get_banner("\nFaustLauncher"))
    _logger.info("Faust Launcher 实例启动")
    _logger.info("日志文件: %s", fname)
    return _logger


def get_logger():
    """获取全局 logger"""
    global _logger
    if _logger is None:
        init_logger()
    return _logger


def log_message(message):
    """写入一行日志(自动去除 ANSI 转义序列)"""
    try:
        text = re.sub(r"\x1b\[[0-9;]*m", "", message).rstrip("\n")
        if text:
            get_logger().info("%s", text) # type: ignore
    except Exception:
        pass
