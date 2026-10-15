"""日志行布局的唯一出处。

所有要输出日志文本的地方都经过 :func:`build_line`：cmd 控制台
(:mod:`functions.base.console_log`)、滚动日志文件
(:mod:`functions.base.log_manager`)、旧版 Tk 终端
(:mod:`functions.pages.terminal.terminal_redirect`) 以及 Web 终端（它订阅
:mod:`functions.base.console_log` 暴露的行钩子）。把布局收敛到一个模块，
四处显示的内容才可能一致；在此之前每个出口都自己拼前缀，于是越走越偏。

行布局::

    [2026-10-11 11:21:28.291] [hook] [INFO] [updater.py:314]: 偏移索引已是最新
     ^------- 时间戳 --------^  ^区域^  ^级别^  ^---- 来源 ----^   ^-- 正文 --^

各列之间只留一个空格，**不做补齐对齐**：日志经常被复制进宽度不一的窗口、聊天框和
issue 里，靠空格撑出来的对齐换一处就散，单空格分隔在哪都稳。

消息自带区域标签时（例如 ``[AchMonitor] 检测完成``），标签会被提升到区域列并从正文中
去掉，所以不会出现 ``[hook] ... [AchMonitor] ...`` 这种区域写两遍的输出。

可选的 ANSI 配色（见 :data:`PALETTE`）用来给各列上色。**同一份渲染结果发给所有
出口**：cmd 直接显示转义序列，旧版 Tk 终端与 Web 终端各自把颜色解析出来，写日志
文件前用 :func:`strip_ansi` 去掉。着色只在这里决定一次，前端不再自己猜级别、
也不再补时间戳。
"""

from __future__ import annotations

import datetime
import os
import re
import sys
from dataclasses import dataclass

__all__ = [
    "LogRecord", "build_line", "format_message", "short_stamp", "resolve_site",
    "strip_ansi", "palette", "PALETTE",
]

# --------------------------------------------------------------------------- constants

# 只负责转发的栈帧。日志行的真正来源是第一个不在此列表中的栈帧，
# 所以重定向器打印出来的行仍然算在真正调用 print() 的业务代码头上。
SKIP_FRAMES = {
    ("log_format.py", None),
    ("console_log.py", None),
    ("terminal_redirect.py", None),
    ("log_manager.py", None),
    ("stdio.py", None),
    # traceback.print_exc() 的栈帧来自标准库 traceback 模块。不跳过它的话，
    # 每个回溯行都会被算到 `[traceback.py:1574]` 上，真正的出错位置就丢了。
    ("traceback.py", None),
    ("app_core.py", "add_terminal_message"),
}

# 正文标签：`[AchMonitor] 正文` -> 区域=成就监测, 正文=正文。
_TAG_RE = re.compile(r"^\[([^\[\]\r\n]{1,16})\][ \t]+(\S.*)$", re.S)

# 给各列上色用的 ANSI SGR 码。只有目标出口启用颜色时才会发出转义序列。
PALETTE = {
    "reset": "\x1b[0m",
    "time": "\x1b[90m",
    "area": "\x1b[96m",
    "INFO": "\x1b[94m",
    "WARN": "\x1b[93m",
    "ERROR": "\x1b[91m",
    "site": "\x1b[96m",
}
# 区域名 -> 颜色：按稳定哈希取色，同一个模块永远保持同一个颜色，便于纵向追踪。
AREA_COLORS = ("\x1b[96m", "\x1b[92m", "\x1b[95m", "\x1b[93m", "\x1b[94m", "\x1b[97m")

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

# 日志级别由正文推断。顺序有意义：先匹配到的组生效，所以宽泛的词要放在后面。
# 表情符号用 \uXXXX 转义写：字面量里的变体选择符（U+FE0F）会在某些工具链保存
# 文件时被剥掉，转义写法不依赖编辑器怎么存盘。
LEVEL_RULES = (
    ("ERROR", ("失败", "错误", "异常", "无法", "不存在", "崩溃", "error", "failed",
               "traceback", "\u274c", "\u26d4")),           # ❌ ⛔
    # 这里不要放短的常用词（"注意" 也会命中 "注意力"，把整行误标并改色）。
    ("WARN", ("警告", "跳过", "未找到", "缺少", "不完整", "已禁用", "回退",
              "failed", "warning", "warn", "\u26a0")),      # ⚠
)
LEVELS = ("INFO", "WARN", "ERROR")

_ANSI_OK = True


@dataclass(frozen=True)
class LogRecord:
    """解析后的一条日志：来自哪里、说了什么。"""

    timestamp: str
    level: str
    area: str
    filename: str
    lineno: int
    message: str


# --------------------------------------------------------------------------- 文本工具

def strip_ansi(text: str) -> str:
    """去掉 ANSI SGR 转义序列。

    写日志文件前会过一遍：文件要当纯文本读，转义序列留在里面只会碍事。
    """
    return _ANSI_RE.sub("", text)


# --------------------------------------------------------------------------- 来源与区域

def _area_of(filename: str) -> str:
    """``functions/hook/updater.py`` -> ``hook``；顶层脚本则用文件名主干。

    ``addons/<插件名>/scr.py`` 例外地取目录名当区域：插件脚本**一律**叫 scr.py，
    只看文件名的话所有插件都挤在同一个 ``scr`` 区域里，出了问题分不清是哪家在说话。
    """
    parts = re.split(r"[\\/]", os.path.abspath(filename))
    for marker in ("functions", "addons"):
        if marker not in parts:
            continue
        idx = len(parts) - 1 - parts[::-1].index(marker)
        if idx + 2 < len(parts):                          # <marker>/<区域>/.../x.py
            return parts[idx + 1]
    return os.path.splitext(parts[-1])[0]


def resolve_site() -> tuple[str, int, str]:
    """返回产生该行的 ``(文件名, 行号, 区域)``。

    :data:`SKIP_FRAMES` 里的栈帧只是转发层，不算来源，因此会继续往外走。找不到
    来源时返回占位符而不是抛异常——记录日志绝不能弄挂它正在观察的代码。
    """
    frame = sys._getframe(1)
    while frame is not None:
        code = frame.f_code
        name = os.path.basename(code.co_filename)
        if not any(name == skipped and (func is None or func == code.co_name)
                   for skipped, func in SKIP_FRAMES):
            return name, frame.f_lineno, _area_of(code.co_filename)
        frame = frame.f_back
    return "?", 0, "?"


# “异常 0 个”“跳过 0 次”这类统计只是在念计数，不是在报错。命中词后面紧跟零值时
# 就不算数，否则每一行统计都会被涂成 ERROR（用户报过这个）。
_ZERO_STAT_RE = re.compile(r"\s*[:：]?\s*0(?:\s*[个次条项分%])?")


def _mentions(message: str, word: str) -> bool:
    """*message* 里是否**真的**用到了 *word*（零值统计不算）。"""
    start = 0
    while True:
        idx = message.find(word, start)
        if idx < 0:
            return False
        if not _ZERO_STAT_RE.match(message, idx + len(word)):
            return True
        start = idx + len(word)


def _level_of(message: str) -> str:
    """按正文关键字推断级别，未命中即 INFO。"""
    lowered = message.lower()
    for level, words in LEVEL_RULES:
        if any(_mentions(message, word) or _mentions(lowered, word)
               for word in words):
            return level
    return "INFO"


def _split_area(message: str, fallback: str) -> tuple[str, str]:
    """把 *message* 开头的 ``[标签]`` 提升为区域列。"""
    match = _TAG_RE.match(message)
    if match:
        return match.group(1), match.group(2)
    return fallback, message


# --------------------------------------------------------------------------- 渲染

def _now_stamp() -> str:
    """毫秒精度的墙钟时间戳，格式 ``YYYY-mm-dd HH:MM:SS.mmm``。

    毫秒取自 ``datetime``（微秒 // 1000）而不是 ``time.time() * 1000``：浮点乘法
    会漂移一两毫秒，而日志恰恰用来排序同一秒内发生的事件。
    """
    now = datetime.datetime.now()
    return now.strftime("%Y-%m-%d %H:%M:%S") + f".{now.microsecond // 1000:03d}"


def palette(enabled: bool = True):
    """返回配色表；``enabled=False`` 时返回 ``None``（表示不着色）。"""
    return PALETTE if enabled else None


def _paint(text: str, code: str | None, palette_map: dict | None) -> str:
    """用**直接的 SGR 码**给 *text* 上色（``palette_map`` 为 None 表示不着色）。"""
    if not palette_map or not code:
        return text
    return f"{code}{text}{PALETTE['reset']}"


def _color(text: str, style: str | None, palette_map: dict | None) -> str:
    """用配色表里的**样式名**（time / INFO / site …）给 *text* 上色。

    区域列不吃这一套：它的颜色是按名字哈希出来的具体 SGR 码，所以走
    :func:`_paint`——先前这里拿码当名字去查表，查不到就返回原样，区域色因此在
    所有出口都没生效过。
    """
    if not palette_map or not style:
        return text
    return _paint(text, palette_map.get(style), palette_map)


def build_line(message: str, *,
               site: tuple[str, int, str] | None = None,
               level: str | None = None,
               palette_map: dict | None = None,
               stamp: str | None = None) -> str:
    """渲染一行日志（带统一前缀）。

    参数:
        message: 正文；开头的 ``[标签]`` 会被提升到区域列。
        site: ``(文件名, 行号, 区域)``；省略时取调用方栈帧。
        level: 显式级别；省略时由 *message* 推断。
        palette_map: :func:`palette` 返回的配色表；``None`` 表示不着色。
        stamp: 时间戳覆盖值，方便测试和批量回放。

    返回:
        格式化后的整行，**不含**结尾换行。各列只用单空格分隔，不做宽度补齐——
        日志会被复制到宽度不一的地方，空格式对齐在那里必然散掉。
    """
    if site is None:
        site = resolve_site()
    filename, lineno, fallback_area = site

    message = message.rstrip("\r\n")
    area, body = _split_area(message, fallback_area or "?")
    if level is None:
        level = _level_of(body)
    level = level.upper()
    if level not in LEVELS:
        level = "INFO"

    site_text = f"{filename}:{lineno}"
    area_color = AREA_COLORS[sum(area.encode("utf-8")) % len(AREA_COLORS)]
    head = " ".join((
        _color(f"[{stamp or _now_stamp()}]", "time", palette_map),
        _paint(f"[{area}]", area_color if palette_map else None, palette_map),
        _color(f"[{level}]", level, palette_map),
        _color(f"[{site_text}]:", "site", palette_map),
    ))
    return f"{head} {body}" if body else head


def format_message(message: str, *,
                   palette_map: dict | None = None) -> str:
    """格式化可能是多行的 *message*。

    只有第一行会带前缀（横幅和回溯必须保留自己的排版），结尾的空行会被丢掉。
    续行里原有 ANSI 转义序列原样保留。
    """
    lines = message.rstrip("\r\n").split("\n")
    if not lines:
        return ""
    rendered = [build_line(lines[0], palette_map=palette_map)]
    rendered.extend(lines[1:])
    return "\n".join(rendered)


# --------------------------------------------------------------------------- UI 裁剪

# 行首时间戳：允许前面先有若干 ANSI 序列（时间戳本身是灰色的），匹配时一起吃掉再
# 原样放回，否则裁剪会把颜色也削掉。毫秒是可选组，方便面板决定要不要它。
_STAMP_DATE_RE = re.compile(
    r"^((?:\x1b\[[0-9;]*m)*)\[\d{4}-\d{2}-\d{2} (\d{2}:\d{2}:\d{2})(\.\d{3})?\]")


def short_stamp(line: str, *, keep_ms: bool = False) -> str:
    """把行首时间戳压成 ``[HH:MM:SS]``（``keep_ms=True`` 时保留毫秒）。

    **只给窄面板用**（Web 终端）：那里能看到的只是最近一小段输出，年月日和毫秒都
    不解决任何问题，只占宽度。cmd 与滚动日志文件仍保留完整时间戳——日志要跨天回溯、
    要排序同一秒内的事件，这两样都不能省。
    行内没有可识别的时间戳时原样返回，多行消息的续行也不会被误伤。
    """
    if keep_ms:
        return _STAMP_DATE_RE.sub(r"\1[\2\3]", line, count=1)
    return _STAMP_DATE_RE.sub(r"\1[\2]", line, count=1)
