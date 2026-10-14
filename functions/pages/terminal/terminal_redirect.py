"""旧版 Tk 终端的绘制层。

Tk 窗口已经**不再**挂在 ``sys.stdout`` 链上了。到达控制台的每一行都先由
:mod:`functions.base.log_format` 渲染好，:mod:`functions.base.console_log` 再把
成品文本（无 ANSI、无结尾换行）交给注册过的钩子；本模块只注册这样一个钩子并负责
绘制：

* 颜色：取 ``log_format`` 已经嵌进行里的配色，经
  :data:`TerminalRedirector.ANSI_COLOR_MAP` 映射成 Tk 颜色；
* 打字机效果：设置项打开时才有。

改这里时请记住两点：

* 不再添加时间戳、级别或表情——行里已经带齐了，所以 Tk 终端、cmd 窗口和
  ``logs/*.log`` 显示的内容完全一致；
* 钩子可能来自任意打印线程，因此绘制一律通过 ``after`` 抛回 Tk 主循环；缓冲区
  和它的锁保证了跨线程交错也是安全的。
"""

import re
import sys
import threading

import tkinter as tk


class TerminalRedirector:
    """把控制台的行画进 Tk 文本框（ANSI 配色 + 打字机效果）。"""

    # ANSI 颜色码到 Tk 颜色的映射
    ANSI_COLOR_MAP = {
        '30': '#000000',  # 黑色
        '31': '#ff6b6b',  # 红色
        '32': '#4bff4e',  # 绿色
        '33': '#f9ca24',  # 黄色
        '34': '#4ecbff',  # 蓝色
        '35': '#a29bfe',  # 紫色
        '36': '#00cec9',  # 青色
        '37': '#ffffff',  # 白色
        '90': '#636e72',  # 亮黑色
        '91': '#ff7675',  # 亮红色
        '92': '#55efc4',  # 亮绿色
        '93': '#ffeaa7',  # 亮黄色
        '94': '#74b9ff',  # 亮蓝色
        '95': '#a29bfe',  # 亮紫色
        '96': '#81ecec',  # 亮青色
        '97': '#ffffff',  # 亮白色
    }

    _ANSI_RE = re.compile(r'(\x1b\[[0-9;]*m|\033\[[0-9;]*m)')
    _ANSI_CODE_RE = re.compile(r'\[([0-9;]+)m')

    def __init__(self, text_widget):
        self.text_widget = text_widget
        self.current_color = None       # 最近一条 ANSI 转义设定的颜色
        self.is_typing = False          # 打字流程正在占用控件
        self.enable_type = False        # 设置项决定是否启用打字机效果
        self.typing_queue = []          # 等待逐字打印的整行
        self.initialized = False        # 控件已就绪，可以接收内容
        self._line_buffer = []          # 已形成但还没绘制的行
        self._buffer_lock = threading.Lock()
        self._flush_scheduled = False
        self._hooked = False
        self._active = False            # 打字流程进行中（或已排期）
        self._pending_after = None

    # ------------------------------------------------------------------ 钩子

    def _line_hook(self, line):
        """接收一条控制台成品行（可能来自任意线程）。"""
        if not line or not self.initialized or not self.text_widget:
            return
        if line.startswith('|') or not line.strip():
            return
        with self._buffer_lock:
            self._line_buffer.append(line)
            if self._flush_scheduled:
                return
            self._flush_scheduled = True
        self._schedule(self._flush_buffer)

    def _schedule(self, func):
        """把 *func* 丢到 Tk 主循环执行，可从任意线程调用。"""
        try:
            self.text_widget.after(0, func)
        except Exception:
            # 窗口已经没了：直接丢弃，别从钩子里往上抛。
            with self._buffer_lock:
                self._flush_scheduled = False

    def _flush_buffer(self):
        with self._buffer_lock:
            self._flush_scheduled = False
            if not self._line_buffer:
                return
            text = "\n".join(self._line_buffer)
            self._line_buffer.clear()
        self._enqueue(text)

    # --------------------------------------------------------------- 绘制

    def _enqueue(self, text):
        """显示 *text*，或交给打字机。

        正在逐字打印的旧消息会先被丢弃：另一种做法是两行按字符交叉输出，看起来
        就像内容坏了。
        """
        if not self.initialized or not self.text_widget or not text:
            return
        try:
            self.enable_type = bool(
                get_settings_manager().get_setting('enable_terminal_typing_effect'))  # type: ignore
        except Exception:
            self.enable_type = False

        if not self.enable_type or len(text) > 30:
            self._cancel_pending_after()
            self._active = False
            self.is_typing = False
            self._insert_with_ansi(text + "\n")
            return

        self.typing_queue.append(text)
        self._start_typing(force=True)

    def _cancel_pending_after(self):
        after_id, self._pending_after = self._pending_after, None
        if after_id is None:
            return
        try:
            self.text_widget.after_cancel(after_id)
        except Exception:
            pass

    def _direct_output(self, message):
        """立即插入一行，不走打字机效果。"""
        try:
            self.text_widget.config(state=tk.NORMAL)
            self._insert_with_ansi(message + "\n")
            self.text_widget.see(tk.END)
            self.text_widget.config(state=tk.DISABLED)
            self.text_widget.update_idletasks()
        except Exception as e:
            print(f"_direct_output error: {e}", file=sys.__stdout__)

    def _start_typing(self, force: bool = False):
        """逐字打印队首的一条消息。

        ``force`` 会重启进行中的打字流程，新到的行就是这样抢占半截旧行的。
        """
        if force and self.is_typing:
            self._cancel_pending_after()
            self.is_typing = False

        if not self.typing_queue:
            self.is_typing = False
            self._active = False
            self._schedule(self._flush_buffer)
            return

        self._active = True
        self.is_typing = True
        message = self.typing_queue.pop(0)
        parts = self._prepare_typing_parts(message + "\n")

        # 内容越长打字越快，免得这个效果喧宾夺主。
        total_chars = sum(len(part['text']) for part in parts)
        base_delay = 10
        min_delay = 1
        delay = max(min_delay, base_delay - min(base_delay - min_delay, total_chars * 0.5))
        self._type_next_char(parts, 0, 0, delay)

    def _prepare_typing_parts(self, message):
        """把 *message* 切成 ``{'text', 'tag', 'color'}`` 片段，供逐字输出使用。"""
        parts = []
        for part in self._ANSI_RE.split(message):
            if not part:
                continue
            if self._ANSI_RE.match(part):
                self._parse_ansi_code(part)
                continue
            if self.current_color:
                parts.append({'text': part, 'tag': None, 'color': self.current_color})
            else:
                parts.append({'text': part, 'tag': self._tag_of(part), 'color': None})
        self.current_color = None
        return parts

    @staticmethod
    def _tag_of(text):
        """把一段文本映射到控件预定义的颜色标签上。

        这些符号一律用 ``\\uXXXX`` 转义写：字面量里的变体选择符（U+FE0F）在某些
        工具链保存文件时会被悄悄剥掉，变成无法匹配的裸字符；转义写法不依赖编辑器
        怎么存盘。
        """
        if "\u274c" in text:                                  # ❌
            return "error"
        if "\u2705" in text:                                  # ✅
            return "success"
        if "\u26a0" in text or "\ufe0f" in text:              # ⚠ / 残缺的变体选择符
            return "warning"
        if "\U0001f504" in text or "\U0001f4e6" in text:      # 🔄 / 📦
            return "wait"
        return "info"

    def _type_next_char(self, parts, part_idx, char_idx, delay):
        """输出一个字符，并排期下一个。"""
        if not self.is_typing:
            return

        try:
            if part_idx >= len(parts):
                self.text_widget.see(tk.END)
                self.text_widget.config(state=tk.DISABLED)
                self.text_widget.update_idletasks()
                # 这里跑在“本条消息打完”之后，所以不能走 _active 的提前返回；
                # 队列排空时 _start_typing 会负责清标志。
                root = self.text_widget.winfo_toplevel()
                self._pending_after = root.after(0, self._start_typing)
                return

            current_part = parts[part_idx]
            if char_idx >= len(current_part['text']):
                self._type_next_char(parts, part_idx + 1, 0, delay)
                return

            self.text_widget.config(state=tk.NORMAL)
            char = current_part['text'][char_idx]
            tag = current_part['tag']
            color = current_part['color']

            if color:
                color_tag = f"color_{color.replace('#', '')}"
                if color_tag not in self.text_widget.tag_names():
                    self.text_widget.tag_config(color_tag, foreground=color)
                self.text_widget.insert(tk.END, char, color_tag)
            elif tag:
                self.text_widget.insert(tk.END, char, tag)
            else:
                self.text_widget.insert(tk.END, char)

            self.text_widget.see(tk.END)
            self.text_widget.update_idletasks()

            root = self.text_widget.winfo_toplevel()
            self._pending_after = root.after(
                int(delay),
                lambda: self._type_next_char(parts, part_idx, char_idx + 1, delay))
        except Exception as e:
            print(f"_type_next_char error: {e}", file=sys.__stdout__)
            # 别让控件卡在“正在打字”的状态里。
            self.is_typing = False
            self._active = False
            self._start_typing()

    def _insert_with_ansi(self, message):
        """插入 *message*，按其中的 ANSI 转义给它上色。"""
        for part in self._ANSI_RE.split(message):
            if not part:
                continue

            if self._ANSI_RE.match(part):
                self._parse_ansi_code(part)
                continue

            if self.current_color:
                tag_name = f"ansi_{self.current_color}"
                if tag_name not in self.text_widget.tag_names():
                    self.text_widget.tag_config(tag_name, foreground=self.current_color)
                self.text_widget.insert(tk.END, part, tag_name)
            else:
                self.text_widget.insert(tk.END, part, self._tag_of(part))

        self.current_color = None

    def _parse_ansi_code(self, code):
        """按一条 ANSI SGR 序列更新 :attr:`current_color`。"""
        match = self._ANSI_CODE_RE.search(code)
        if not match:
            return
        for c in match.group(1).split(';'):
            if c == '0':
                self.current_color = None
            elif c in self.ANSI_COLOR_MAP:
                self.current_color = self.ANSI_COLOR_MAP[c]

    # --------------------------------------------------------------- 生命周期

    def flush(self):
        """把缓冲区里剩下的内容画出来（可重复调用）。"""
        try:
            self._flush_buffer()
        except Exception:
            pass

    def start_redirect(self, debug: bool = False):
        """挂上控制台行钩子。debug 模式下 Tk 窗口保持安静。"""
        if debug:
            return
        self.initialized = True
        try:
            from functions.base.console_log import add_line_hook
            add_line_hook(self._line_hook)
            self._hooked = True
        except Exception as e:
            print(f"终端重定向挂接失败: {e}", file=sys.__stdout__)

    def stop_redirect(self):
        """摘掉控制台行钩子，并丢弃缓冲中的行。"""
        if self._hooked:
            try:
                from functions.base.console_log import remove_line_hook
                remove_line_hook(self._line_hook)
            except Exception:
                pass
            self._hooked = False

        self.initialized = False
        self.is_typing = False
        self._active = False
        self.typing_queue.clear()
        with self._buffer_lock:
            self._line_buffer.clear()
            self._flush_scheduled = False

        self._cancel_pending_after()
