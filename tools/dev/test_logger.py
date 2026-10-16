# -*- coding: utf-8 -*-
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from functions.base import console_log, logger, log_manager  # noqa: E402

class Sink:
    def __init__(self):
        self.lines = []

    def write(self, text):
        self.lines.append(text)
        return len(text)

    def flush(self):
        pass

    def isatty(self):
        return False

    def fileno(self):
        raise OSError("no fileno")

    @property
    def encoding(self):
        return "utf-8"

    @property
    def errors(self):
        return "replace"

def strip_ansi(text):
    import re
    return re.sub(r"\x1b\[[0-9;]*m", "", text)

raw = Sink()
old = sys.stdout
sys.stdout = raw
try:
    console_log._installed = True
    console_log._color_ok = False
    sys.stdout = console_log._ConsoleStream(raw, "stdout")
    logger.debug("明细: 缓存命中 %d 条", 12)
    logger.info("普通流程消息, 内容里带错误二字也不该变级")
    logger.warn("跳过载入插件 MotionBlur")
    logger.error("复制汉化文件失败: %s", "permission denied")
    print("这是老式 print, 应归 INFO")
    print("插件 X 被禁用, 跳过载入")
finally:
    sys.stdout = old

for line in raw.lines:
    print(strip_ansi(line).rstrip())
print("--- 级别校验 ---")
for line in raw.lines:
    t = strip_ansi(line)
    if "[" in t and "]" in t:
        parts = t.split("]")
        if len(parts) >= 3:
            print(parts[2].strip().lstrip("[") + "  <-  " + parts[-1].strip()[:42])
