import os
import re
import datetime
import logging

LOG_DIR = "logs"
MAX_KEEP_DAYS = 3
MAX_KEEP_PER_DAY = 7
LEVEL_DIRS = ("DEBUG", "WARN", "ERROR")

_logger = None

def _ensure_dir():
    os.makedirs(LOG_DIR, exist_ok=True)

def _cleanup_logs():
    try:
        today = datetime.date.today()
        cutoff = today - datetime.timedelta(days=MAX_KEEP_DAYS - 1)
        for folder in [LOG_DIR] + [os.path.join(LOG_DIR, d) for d in LEVEL_DIRS]:
            if not os.path.isdir(folder):
                continue
            _cleanup_folder(folder, cutoff)
    except Exception:
        pass

def _cleanup_folder(folder: str, cutoff: datetime.date) -> None:
    by_day = {}
    for fname in os.listdir(folder):
        path = os.path.join(folder, fname)
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
                    os.remove(os.path.join(folder, fname))
                except OSError:
                    pass

def init_logger():
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
    handler.setFormatter(logging.Formatter("%(message)s"))
    _logger.addHandler(handler)

    _cleanup_logs()

    from functions.base.terminal_banner import get_banner, get_random_font, get_random_color
    font = get_random_font()
    color = get_random_color()
    print(get_banner("FaustLauncher", font=font, colors=color))

    _announce(f"Faust Launcher 开始运行... ({fname})")
    return _logger

def _announce(message: str) -> None:
    try:
        from functions.base import log_format
        write_line(log_format.build_line(message, site=("log_manager.py", 0, "logs")))
    except Exception:
        pass

def get_logger():
    global _logger
    if _logger is None:
        init_logger()
    return _logger

def _current_log_file() -> str:
    if _logger is None:
        return ""
    for handler in list(_logger.handlers):
        base = getattr(handler, "baseFilename", "")
        if base:
            return base
    return ""

def _mirror_level(line: str) -> None:
    level = parse_level(line)
    if level == "INFO" or level not in LEVEL_DIRS:
        return
    main = _current_log_file()
    if not main:
        return
    folder = os.path.join(LOG_DIR, level)
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, os.path.basename(main))
    with open(path, "a", encoding="utf-8") as fp:
        fp.write(re.sub(r"\x1b\[[0-9;]*m", "", line).rstrip("\r\n") + "\n")

def parse_level(line: str) -> str:
    try:
        text = re.sub(r"\x1b\[[0-9;]*m", "", line)
        for level in ("ERROR", "WARN", "DEBUG", "INFO"):
            if "] [" + level + "]" in text:
                return level
    except Exception:
        pass
    return "INFO"

def write_line(line: str) -> None:
    try:
        text = re.sub(r"\x1b\[[0-9;]*m", "", line).rstrip("\r\n")
        if not text:
            return
        get_logger().info("%s", text)  # type: ignore
        _mirror_level(text)
    except Exception:
        pass

def flush() -> None:
    if _logger is None:
        return
    for handler in list(_logger.handlers):
        try:
            handler.flush()
        except Exception:
            pass

def log_message(message) -> None:
    try:
        from functions.base import log_format
        write_line(log_format.format_message(str(message)))
    except Exception:
        pass
