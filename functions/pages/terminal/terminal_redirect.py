import sys
import tkinter as tk
import re
from functions.base.settings_manager import get_settings_manager

class TerminalRedirector:
    """重定向print输出到文本组件的类（支持ANSI转义序列解析）"""
    
    # ANSI颜色代码到Tkinter颜色的映射
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
    
    def __init__(self, text_widget):
        self.text_widget = text_widget
        self.original_stdout = sys.stdout
        self.original_stderr = sys.stderr
        self.buffer = ""  # 缓冲区用于处理部分消息
        self.current_color = None  # 当前颜色状态
        self.is_typing = False  # 是否正在打字
        self.enable_type = False
        self.typing_queue = []  # 打字队列
        self.initialized = False  # 组件是否已初始化
    
    def write(self, message):
        """重定向write方法"""
        if message:
            # 同时转发到原始控制台（cmd/终端），保证两边都能看到输出
            self._forward_to_console(message)
            # 写入日志系统
            self._write_log(message)
            
            # 添加到缓冲区
            self.buffer += message
            
            # 如果缓冲区以换行符结尾，处理完整消息
            if self.buffer.endswith('\n'):
                # 移除结尾的换行符
                full_message = self.buffer.rstrip('\n')
                if full_message:  # 只处理非空消息
                    self._add_message_to_terminal(full_message)
                # 清空缓冲区
                self.buffer = ""
    
    def _forward_to_console(self, message):
        """转发消息到原始控制台输出"""
        try:
            self.original_stdout.write(message)
            self.original_stdout.flush()
        except UnicodeEncodeError:
            try:
                self.original_stdout.write(message.encode(
                    'utf-8', errors='replace').decode('utf-8'))
                self.original_stdout.flush()
            except Exception:
                pass
        except Exception:
            pass
    
    def _write_log(self, message):
        """写入日志文件"""
        # 若原始 stdout 仍是重定向器(链式), 交由链路末端的重定向器记录, 避免重复
        if isinstance(self.original_stdout, TerminalRedirector):
            return
        try:
            from functions.base.log_manager import log_message
            log_message(message)
        except Exception:
            pass
    
    def _add_message_to_terminal(self, message):
        """添加格式化消息到终端（支持ANSI转义序列和打字机效果）"""
        # 组件未初始化或已过滤的消息: 已转发到控制台, 不再输出到GUI
        if not self.initialized or not self.text_widget:
            return
            
        # 过滤以 | 开头的消息（调试信息）
        if message.startswith('|'):
            return
            
        message = self.process_message(message)

        try:
            if '\r' in message:
                return
            
            enable_typing_effect:bool = get_settings_manager().get_setting('enable_terminal_typing_effect') # type: ignore
            # 超过阈值直接输出，不使用打字机效果
            if len(message) > 30 or not enable_typing_effect:
                # 如果正在打字，先暂停并清空当前输出，然后直接输出
                if self.is_typing:
                    self.is_typing = False
                    self.typing_queue = []  # 清空队列
                self._direct_output(message)
                return
            
            # 添加到打字队列
            self.typing_queue.append(message)
            
            # 如果当前没有在打字，开始打字
            if not self.is_typing:
                self._start_typing()
        
        except Exception as e:
            print(f"_add_message_to_terminal error: {e}", file=self.original_stdout)
            pass
    
    def _direct_output(self, message):
        """直接输出消息（不使用打字机效果）"""
        try:
            # 添加时间戳
            import datetime
            timestamp = datetime.datetime.now().strftime("%H:%M:%S")
            timestamp_str = f'[{timestamp}]' if '[INFO]' not in message else ''
            
            self.text_widget.config(state=tk.NORMAL)
            
            # 插入带时间戳
            self.text_widget.insert(tk.END, timestamp_str, "info")
            
            # 解析ANSI转义序列并插入带样式的文本
            self._insert_with_ansi(message + "\n")
            
            # 自动滚动到底部
            self.text_widget.see(tk.END)
            
            # 禁用文本编辑
            self.text_widget.config(state=tk.DISABLED)
            
            # 立即更新显示
            self.text_widget.update_idletasks()
        except Exception as e:
            print(f"_direct_output error: {e}", file=self.original_stdout)
            pass
    
    def _start_typing(self):
        """开始打字机效果输出"""
        if not self.typing_queue:
            self.is_typing = False
            return
        
        self.is_typing = True
        message = self.typing_queue.pop(0)
        
        # 添加时间戳
        import datetime
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        timestamp_str = f'[{timestamp}]' if '[INFO]' not in message else ''
        
        # 处理消息，解析ANSI转义序列
        processed_parts = self._prepare_typing_parts(message + "\n", timestamp_str)
        
        # 计算打字速度：文字越多，间隔越短
        total_chars = sum(len(part['text']) for part in processed_parts)
        base_delay = 10  # 基础间隔时间（毫秒）
        min_delay = 1   # 最短间隔时间
        # 根据消息长度动态调整间隔时间
        # 如果太长，直接为最小
        delay = max(min_delay, base_delay - min(base_delay - min_delay, total_chars * 0.5))
        
        # 开始逐字输出
        self._type_next_char(processed_parts, 0, 0, delay)
    
    def _prepare_typing_parts(self, message, timestamp_str):
        """准备打字的内容片段（包含样式信息）"""
        parts = []
        
        # 添加时间戳
        if timestamp_str:
            parts.append({'text': timestamp_str, 'tag': 'info', 'color': None})
        
        # 先为路径添加引号和紫色标记
        message = self._quote_paths(message)
        
        # 匹配ANSI转义序列
        ansi_pattern = re.compile(r'(\x1b\[[0-9;]*m|\033\[[0-9;]*m)')
        message_parts = ansi_pattern.split(message)
        
        current_color = None
        
        for part in message_parts:
            if not part:
                continue
            
            # 检查是否为ANSI转义序列
            if ansi_pattern.match(part):
                # 解析ANSI代码 - 不输出转义序列本身，只更新颜色状态
                match = re.search(r'\[([0-9;]+)m', part)
                if match:
                    codes = match.group(1).split(';')
                    for c in codes:
                        if c == '0':
                            current_color = None
                        elif c in self.ANSI_COLOR_MAP:
                            current_color = self.ANSI_COLOR_MAP[c]
            else:
                # 根据消息内容确定级别
                level = "info"
                if "❌" in part:
                    level = "error"
                elif "✅" in part:
                    level = "success"
                elif "⚠️" in part:
                    level = "warning"
                elif ("🔄" in part) or ("📦" in part):
                    level = "wait"
                
                # 使用颜色或级别
                if current_color:
                    parts.append({'text': part, 'tag': None, 'color': current_color})
                else:
                    parts.append({'text': part, 'tag': level, 'color': None})
                
        return parts
    
    def _type_next_char(self, parts, part_idx, char_idx, delay):
        """递归输出下一个字符"""
        # 如果已经停止打字，直接返回
        if not self.is_typing:
            return
            
        try:
            if part_idx >= len(parts):
                # 所有内容输出完毕
                self.text_widget.see(tk.END)
                self.text_widget.config(state=tk.DISABLED)
                self.text_widget.update_idletasks()
                
                # 继续处理队列中的下一条消息
                root = self.text_widget.winfo_toplevel()
                root.after(0, self._start_typing)
                return
            
            current_part = parts[part_idx]
            
            if char_idx >= len(current_part['text']):
                # 当前片段已输出完毕，处理下一个片段
                self._type_next_char(parts, part_idx + 1, 0, delay)
                return
            
            # 输出单个字符
            self.text_widget.config(state=tk.NORMAL)
            
            char = current_part['text'][char_idx]
            tag = current_part['tag']
            color = current_part['color']
            
            # 根据颜色或标签插入字符
            if color:
                # 使用自定义颜色
                color_tag = f"color_{color.replace('#', '')}"
                if color_tag not in self.text_widget.tag_names():
                    self.text_widget.tag_config(color_tag, foreground=color)
                self.text_widget.insert(tk.END, char, color_tag)
            elif tag:
                # 使用预定义标签
                self.text_widget.insert(tk.END, char, tag)
            else:
                # 无样式
                self.text_widget.insert(tk.END, char)
            
            self.text_widget.see(tk.END)
            self.text_widget.update_idletasks()
            
            # 继续输出下一个字符
            # 通过text_widget获取根窗口
            root = self.text_widget.winfo_toplevel()
            root.after(int(delay), lambda: self._type_next_char(parts, part_idx, char_idx + 1, delay))
            
        except Exception as e:
            print(f"_type_next_char error: {e}", file=self.original_stdout)
            # 继续处理，避免卡住
            self.is_typing = False
            self._start_typing()
            
    def _insert_with_ansi(self, message):
        """解析ANSI转义序列并插入文本（支持路径添加引号和紫色）"""
        # 先为路径添加引号和紫色标记
        message = self._quote_paths(message)
        
        # 匹配ANSI转义序列：\x1b[...m 或 \033[...m
        ansi_pattern = re.compile(r'(\x1b\[[0-9;]*m|\033\[[0-9;]*m)')
        parts = ansi_pattern.split(message)
        
        for part in parts:
            if not part:
                continue
            
            # 检查是否为ANSI转义序列
            if ansi_pattern.match(part):
                # 解析ANSI代码
                self._parse_ansi_code(part)
            else:
                # 根据消息内容确定级别
                level = "info"
                if "❌" in part:
                    level = "error"
                elif "✅" in part:
                    level = "success"
                elif "⚠️" in part:
                    level = "warning"
                elif ("🔄" in part) or ("📦" in part):
                    level = "wait"
                
                # 插入普通文本，使用当前颜色或级别
                if self.current_color:
                    # 使用ANSI颜色
                    tag_name = f"ansi_{self.current_color}"
                    if tag_name not in self.text_widget.tag_names():
                        self.text_widget.tag_config(tag_name, foreground=self.current_color)
                    self.text_widget.insert(tk.END, part, tag_name)
                else:
                    # 使用默认级别颜色
                    self.text_widget.insert(tk.END, part, level)
        
        # 重置颜色状态
        self.current_color = None

    def _quote_paths(self, text):
        """为文本中的路径添加引号和紫色效果"""
        if not text:
            return text
        
        # 匹配路径模式：
        # 1. Windows路径：C:\xxx\yyy 或 C:/xxx/yyy
        # 2. 包含路径分隔符的路径（支持包含空格但不包含换行）
        # 3. 相对路径如 mods/xxx 或 extra_files
        path_pattern = re.compile(
            r'(?<!")'  # 前面没有引号
            r'(|^)'  # 前面是空格或行首
            r'([A-Za-z]:[/\\][^"\n<>|*?]*|[^\s"\n<>|*?]*[/\\][^"\n<>|*?]*)'  # 路径（排除换行符）
            r'(?=(\s|$))'  # 后面是空白或行尾
        )
        
        def replace_match(match):
            prefix = match.group(1)
            path = match.group(2)
            # 如果路径已经有引号则不处理
            if path.startswith('"') and path.endswith('"'):
                return prefix + path
            # 添加紫色ANSI转义序列和引号
            return f'{prefix}\x1b[35m"{path}"\x1b[0m'
        
        return path_pattern.sub(replace_match, text)
    
    def _parse_ansi_code(self, code):
        """解析ANSI转义序列"""
        # 提取数字代码（如：\x1b[33m -> 33）
        match = re.search(r'\[([0-9;]+)m', code)
        if match:
            codes = match.group(1).split(';')
            for c in codes:
                if c == '0':
                    # 重置样式
                    self.current_color = None
                elif c in self.ANSI_COLOR_MAP:
                    # 设置前景色
                    self.current_color = self.ANSI_COLOR_MAP[c]

    @staticmethod
    def process_message(message:str) -> str: # type: ignore
        """根据消息内容添加表情符号"""
        emoji_dict = {
            "🚀": [
                "启动"
            ],
            "💡": [
                "提示",
                "提示信息",
            ],
            "⚠️": [
                "警告",
                "不存在",
                "warning",
            ],
            "❌": [
                "错误",
                "失败",
                "异常"
            ],
            "✅": [
                "成功",
                "完成",
                "已经"
            ],
            "🔄": [
                "正在",
                "加载中",
                "更新中"
            ],
            "📦": [
                "安装",
                "下载",
                "解压"
            ],
        }
        # 遍历字典，检查消息中是否包含关键字
        for emoji, keywords in emoji_dict.items():
            for keyword in keywords:
                if keyword in message:
                    return f"{emoji} {message}"
        return message
        
    def flush(self):
        """重定向flush方法"""
        # 处理缓冲区中剩余的消息
        if self.buffer:
            self._add_message_to_terminal(self.buffer)
            self.buffer = ""
    
    def start_redirect(self, debug:bool = False):
        """开始重定向"""
        if not debug:
            sys.stdout = self
            sys.stderr = self
            self.initialized = True  # 标记为已初始化
    
    def stop_redirect(self):
        """停止重定向"""
        # 刷新缓冲区
        self.flush()
        sys.stdout = self.original_stdout
        sys.stderr = self.original_stderr