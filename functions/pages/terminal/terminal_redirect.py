
import re
import sys
import threading

import tkinter as tk

class TerminalRedirector:

    ANSI_COLOR_MAP = {
        '30': '#000000',
        '31': '#ff6b6b',
        '32': '#4bff4e',
        '33': '#f9ca24',
        '34': '#4ecbff',
        '35': '#a29bfe',
        '36': '#00cec9',
        '37': '#ffffff',
        '90': '#636e72',
        '91': '#ff7675',
        '92': '#55efc4',
        '93': '#ffeaa7',
        '94': '#74b9ff',
        '95': '#a29bfe',
        '96': '#81ecec',
        '97': '#ffffff',
    }

    _ANSI_RE = re.compile(r'(\x1b\[[0-9;]*m|\033\[[0-9;]*m)')
    _LEVEL_RE = re.compile(r'\[(ERROR|WARN|DEBUG|INFO)\]')
    _ANSI_CODE_RE = re.compile(r'\[([0-9;]+)m')

    def __init__(self, text_widget):
        self.text_widget = text_widget
        self.current_color = None
        self.is_typing = False
        self.enable_type = False
        self.typing_queue = []
        self.initialized = False
        self._line_buffer = []
        self._buffer_lock = threading.Lock()
        self._flush_scheduled = False
        self._hooked = False
        self._active = False
        self._pending_after = None

    def _line_hook(self, line):
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
        try:
            self.text_widget.after(0, func)
        except Exception:
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

    def _enqueue(self, text):
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
        try:
            self.text_widget.config(state=tk.NORMAL)
            self._insert_with_ansi(message + "\n")
            self.text_widget.see(tk.END)
            self.text_widget.config(state=tk.DISABLED)
            self.text_widget.update_idletasks()
        except Exception as e:
            print(f"_direct_output error: {e}", file=sys.__stdout__)

    def _start_typing(self, force: bool = False):
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

        total_chars = sum(len(part['text']) for part in parts)
        base_delay = 10
        min_delay = 1
        delay = max(min_delay, base_delay - min(base_delay - min_delay, total_chars * 0.5))
        self._type_next_char(parts, 0, 0, delay)

    def _prepare_typing_parts(self, message):
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
        m = TerminalRedirect._LEVEL_RE.search(text)
        if m:
            return {"ERROR": "error", "WARN": "warning",
                    "DEBUG": "wait"}.get(m.group(1), "info")
        return "info"

    def _type_next_char(self, parts, part_idx, char_idx, delay):
        if not self.is_typing:
            return

        try:
            if part_idx >= len(parts):
                self.text_widget.see(tk.END)
                self.text_widget.config(state=tk.DISABLED)
                self.text_widget.update_idletasks()
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
            self.is_typing = False
            self._active = False
            self._start_typing()

    def _insert_with_ansi(self, message):
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
        match = self._ANSI_CODE_RE.search(code)
        if not match:
            return
        for c in match.group(1).split(';'):
            if c == '0':
                self.current_color = None
            elif c in self.ANSI_COLOR_MAP:
                self.current_color = self.ANSI_COLOR_MAP[c]

    def flush(self):
        try:
            self._flush_buffer()
        except Exception:
            pass

    def start_redirect(self, debug: bool = False):
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
