"""cmd 控制台输出美化：给每行加上 ``[时间] [区域] [级别] [文件:行]`` 前缀并着色。

为什么要包一层 ``sys.stdout`` 而不是改几百处 ``print``：启动器里的输出是**散落**的
（``print`` / ``rich`` / 第三方库 / 子模块），逐个改既不现实、也覆盖不全。包一层之后
所有输出自动获得统一格式，调用点一行都不用动。

排版（模仿常见的那种带模块出处的日志）::

    [2026-10-11 11:21:28.291] [hook] [INFO] [updater:314]: 偏移索引已是最新

    [时间]  精确到毫秒 —— 一回合的伤害/收尾事件全挤在同一秒里，只有毫秒能看清先后
    [区域]  消息自带的 ``[xxx]`` 前缀（如 ``[成就监测]``）优先当作区域，没有就取该文件
            所在的板块目录名（``functions/hook/updater.py`` → ``hook``）——
            顺带把消息开头那个重复的 ``[xxx]`` 收掉，不再出现 ``[hook] ... [成就监测] ...``
    [级别]  由内容推断（失败/错误/异常→ERROR，警告/跳过/未找到→WARN，其余 INFO）
    [文件:行]  真正发起这次输出的 py 文件与行号（跳过本模块与两个重定向器自己的帧）

区域名按名字取稳定的颜色，便于一眼区分是哪个板块在说话。

**和 UI 终端/日志文件的关系**（重要，别搞坏）：
``TerminalRedirector``（旧版界面）与 ``WebLogRedirector``（Web 界面）都会把消息
**原样**送进 UI 与 logs/*.log，只把 "转发到真实控制台" 那一步交给构造时捕获的
``sys.stdout``。所以只要在它们之前 ``install()``，就正好只影响 cmd，UI 与日志文件
拿到的东西一点没变（UI 终端本来就自己解析 ANSI、自己加时间戳）。

多行输出（启动横幅这类一次 write 带多个换行，``print`` 还会把结尾换行拆成第二次 write）
只给**第一行**加前缀，同一笔 write 的其余内容原样透传，免得把 ASCII art 的排版切碎。
带 ``\\r`` 的输出（进度条）整笔原样透传，不加前缀。
"""

from __future__ import annotations

import os
import re
import sys
import threading
import time

__all__ = ["install", "uninstall", "is_installed"]

# --------------------------------------------------------------------------- 常量

# 真实发起输出的栈帧：跳过这些"只是转发"的文件
_SKIP_FRAMES = {
    ("console_log.py", None),
    ("terminal_redirect.py", None),
    ("log_manager.py", None),
    ("stdio.py", None),
    # traceback.print_exc() 是从 stdlib 的 traceback.py 里逐行写出来的：不跳过它，
    # 每一帧的出处都会记成 `[traceback] [traceback.py:1574]`，真正的出错位置反而看不到。
    ("traceback.py", None),
    ("app_web.py", "write"),        # WebLogRedirector.write
    ("app_web.py", "flush"),
    ("app_core.py", "add_terminal_message"),
}

# 消息自带的区块前缀：`[成就监测] 正文` → 区域=成就监测，正文=去掉前缀的内容
_TAG_RE = re.compile(r"^\[([^\[\]\r\n]{1,16})\][ \t]+(\S.*)$", re.S)

_LEVEL_RULES = (
    ("ERROR", ("失败", "错误", "异常", "无法", "不存在", "崩溃", "error", "failed",
               "traceback", "❌", "⛔")),
    # ⚠ 别往里加短而常见的词（"注意" 会命中 "注意力"、整行被误判成 WARN 并被染色）
    ("WARN", ("警告", "跳过", "未找到", "缺少", "不完整", "已禁用", "回退",
              "warning", "warn", "⚠")),
)
_OK_WORDS = ("成功", "完成", "已更新", "已写入", "已注入", "已启用", "已就绪", "✅")
_ACT_WORDS = ("正在", "开始", "尝试", "加载中", "更新中", "🔄", "🚀", "📦")

# 语义色（只用 30-37/90-97 + 1/2，UI 终端自己的 ANSI 解析器也认得这些）
_C = {
    "reset": "\x1b[0m",
    "dim": "\x1b[90m",
    "time": "\x1b[90m",
    "sep": "\x1b[90m",
    "file": "\x1b[96m",
    "line": "\x1b[96m",
    "INFO": "\x1b[94m",
    "WARN": "\x1b[93m",
    "ERROR": "\x1b[91m",
    "ok": "\x1b[92m",
    "act": "\x1b[95m",
    "warnword": "\x1b[93m",
    "errword": "\x1b[91m",
    "num": "\x1b[96m",
    "path": "\x1b[35m",
}
# 区域名 → 颜色，按名字哈希取（同一个板块永远同色）
_AREA_COLORS = ("\x1b[96m", "\x1b[92m", "\x1b[95m", "\x1b[93m", "\x1b[94m", "\x1b[97m")

_HEX_RE = re.compile(r"\b0x[0-9A-Fa-f]+\b")
_PATH_RE = re.compile(r"[A-Za-z]:[\\/][^\s\"'<>|*?\r\n]*|(?:[\w.\-]+[\\/])+[\w.\-]+")

_installed = False
_lock = threading.RLock()
_color_ok = False


# --------------------------------------------------------------------------- 颜色

def _enable_ansi() -> bool:
    """尽量让 cmd 认 ANSI；做不到就返回 False（调用方会退化成无色输出）。"""
    if os.name != "nt":
        return True
    try:
        import colorama                                   # requirements 里有
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


def _paint(text: str, *styles: str) -> str:
    if not _color_ok or not text:
        return text
    prefix = "".join(_C.get(s, "") for s in styles)
    return f"{prefix}{text}{_C['reset']}" if prefix else text


# --------------------------------------------------------------------------- 出处判定

def _area_of(filename: str) -> str:
    """``functions/hook/updater.py`` → ``hook``；顶层脚本 → 文件名。"""
    parts = re.split(r"[\\/]", os.path.abspath(filename))
    if "functions" in parts:
        idx = len(parts) - 1 - parts[::-1].index("functions")
        if idx + 2 < len(parts):                          # functions/<板块>/.../x.py
            return parts[idx + 1]
    return os.path.splitext(parts[-1])[0]


def _caller_site():
    """返回 (模块文件名, 行号, 区域名)；找不到就返回占位。"""
    frame = sys._getframe(1)
    while frame is not None:
        code = frame.f_code
        name = os.path.basename(code.co_filename)
        if not any(name == f and (func is None or func == code.co_name)
                   for f, func in _SKIP_FRAMES):
            return name, frame.f_lineno, _area_of(code.co_filename)
        frame = frame.f_back
    return "?", 0, "?"


def _level_of(message: str) -> str:
    low = message.lower()
    for level, words in _LEVEL_RULES:
        if any(w in message or w in low for w in words):
            return level
    return "INFO"


# --------------------------------------------------------------------------- 正文着色

def _highlight(message: str, level: str) -> str:
    """关键字着色：结果词 / 进行词 / 0x 偏移 / 路径。已经带 ANSI 的文本原样放过。"""
    if not _color_ok or "\x1b[" in message:
        return message
    hits = []
    for match in _HEX_RE.finditer(message):
        hits.append((match.start(), match.end(), "num"))
    for match in _PATH_RE.finditer(message):
        text = match.group(0)
        # 必须含字母：否则 "19/19"、"1/2" 这类分数/比例会被当成路径染成紫色
        if len(text) > 3 and ("\\" in text or "/" in text) and re.search(r"[A-Za-z]", text):
            hits.append((match.start(), match.end(), "path"))
    for words, style in ((_OK_WORDS, "ok"), (_ACT_WORDS, "act"),
                         (_LEVEL_RULES[0][1], "errword"), (_LEVEL_RULES[1][1], "warnword")):
        for word in words:
            start = message.find(word)
            while start != -1:
                hits.append((start, start + len(word), style))
                start = message.find(word, start + len(word))
    # 长的优先、重叠的丢掉，保证区间互不覆盖
    hits.sort(key=lambda item: (item[0], -(item[1] - item[0])))
    selected = []
    for start, end, style in hits:
        if any(start < s_end and end > s_start for s_start, s_end, _ in selected):
            continue
        selected.append((start, end, style))
    out = []
    pos = 0
    for start, end, style in sorted(selected):
        if start < pos:
            continue
        out.append(message[pos:start])
        out.append(_paint(message[start:end], style))
        pos = end
    out.append(message[pos:])
    return "".join(out)


# --------------------------------------------------------------------------- 流代理

class _ConsoleStream:
    """把写进来的文本按行加上前缀，再交给真正的控制台流。

    ``print("a\\nb\\nc")`` 会拆成两次 write（正文一次、结尾的换行一次），所以这里按
    "**一次 write 里只有第一行算新日志行，其余部分原样透传**"处理，并用 ``_raw_tail``
    记住"上一笔以未换行结尾"，让紧跟的那一个换行直接透传 —— 否则启动横幅的最后一行
    会被补上一个前缀。
    """

    def __init__(self, raw, name: str):
        self._raw = raw
        self._name = name
        self._buf = ""
        self._raw_tail = False
        self._lock = threading.RLock()

    # ---- 供第三方库探测的常规属性（缺一个都可能让它们炸）
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

    def reconfigure(self, **kwargs):                        # noqa: D401
        func = getattr(self._raw, "reconfigure", None)
        if func:
            func(**kwargs)

    # ---- 真正的写入
    def write(self, text):
        if not text:
            return 0
        if not isinstance(text, str):
            text = str(text)
        if "\r" in text:                                    # 进度条：原样透传
            return self._raw.write(text)
        with self._lock:
            if self._raw_tail and text.startswith("\n"):
                # 上一笔以未换行结尾（多行输出的尾巴），这个换行只是补上它
                self._raw_tail = False
                return self._raw.write(text)
            self._buf += text
            if "\n" not in self._buf:
                return len(text)
            first, rest = self._buf.split("\n", 1)
            self._buf = ""
        out = self._format(first)
        if rest:
            # 同一笔 write 的后续行（横幅 / traceback 文本 / 结构化 dump）：原样透传，
            # 免得把 ASCII art 的缩进和排版切碎
            self._raw_tail = not rest.endswith("\n")
            out += rest
        return self._raw.write(out)

    def _format(self, line: str) -> str:
        name, lineno, area = _caller_site()
        level = _level_of(line)
        # 消息自带的 [xxx] 前缀：当作区域，顺便从正文里去掉（避免 [hook] 后面又跟一个 [成就监测]）
        match = _TAG_RE.match(line)
        if match:
            area, line = match.group(1), match.group(2)
        head = (f"{_paint('[' + _stamp() + ']', 'time')} "
                f"{_paint('[' + area + ']', _area_color(area))} "
                f"{_paint('[' + level + ']', level)} "
                f"{_paint('[' + name, 'file')}{_paint(':' + str(lineno) + ']', 'line')}: ")
        return head + _highlight(line, level) + "\n"

    def flush(self):
        try:
            self._raw.flush()
        except Exception:
            pass


def _stamp() -> str:
    now = time.time()
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)) + \
        f".{int(now * 1000) % 1000:03d}"


def _area_color(area: str) -> str:
    return _AREA_COLORS[sum(area.encode("utf-8")) % len(_AREA_COLORS)]


# --------------------------------------------------------------------------- 安装

def is_installed() -> bool:
    return _installed


def install() -> bool:
    """把 sys.stdout / sys.stderr 包一层（幂等）。返回是否已生效。

    ⚠ 只在**面向用户控制台**的入口调用：成就监测子进程的 stdout 会被父进程接到
    成就日志文件上，那里不需要（也不该有）这套前缀。
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
        # ⚠ 顺序：先让 colorama/SetConsoleMode 处理好真实流，再取它作为底层 ——
        #   这样在"控制台不支持 ANSI"的机器上，颜色会被 colorama 翻译/剥掉，而不是打出乱码。
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
