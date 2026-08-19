import os
import re
from typing import List, Dict, Tuple
from functions.base.settings_manager import get_settings_manager
from functions.base.window_utils import center_window
from functions.base.color_scheme import C, darken_color
from functions.base.common.color_utils import hex_to_rgb, rgb_to_hex, interpolate_color, is_white_color
from functions.base.common.json_io import read_json, write_json


def extract_text_and_tags(text: str) -> List[Dict]:
    """提取文本和标签，将文本字符和HTML标签分开处理"""
    # 匹配HTML标签的正则表达式
    tag_pattern = r'(<[^>]+>)'
    parts = []
    
    # 分割文本和标签
    segments = re.split(tag_pattern, text)
    
    for segment in segments:
        if not segment:
            continue
        if segment.startswith('<') and segment.endswith('>'):
            # 这是HTML标签
            parts.append({'type': 'tag', 'content': segment})
        else:
            # 这是文本内容，需要区分普通字符和特殊字符
            for char in segment:
                # 检查是否为特殊字符（换行符、制表符、回车符等）
                if char in ['\n', '\t', '\r']:
                    parts.append({'type': 'special', 'content': char})
                else:
                    parts.append({'type': 'char', 'content': char})
    
    return parts

def apply_color_gradient_custom(text: str, start_color: str, end_color: str, gradient_rate: float = 2.0) -> str:
    """对文本应用颜色渐变效果（支持自定义起始和结束颜色）
    Args:
        text: 要处理的文本
        start_color: 起始颜色
        end_color: 结束颜色
        gradient_rate: 渐变度，越大渐变越快（默认2.0）
    """
    if not text:
        return text
    
    # 提取文本和标签
    parts = extract_text_and_tags(text)
    
    # 计算需要渐变的字符数量（不包括标签和特殊字符）
    char_count = sum(1 for part in parts if part['type'] == 'char')
    
    if char_count == 0:
        return f"<color={start_color}>{text}</color>"
    
    # 转换颜色
    start_rgb = hex_to_rgb(start_color)
    end_rgb = hex_to_rgb(end_color)
    
    # 构建渐变后的文本
    result_parts = []
    char_index = 0
    
    for part in parts:
        if part['type'] == 'tag' or part['type'] == 'special':
            # 直接添加标签和特殊字符
            result_parts.append(part['content'])
        else:
            # 对普通字符应用渐变
            if char_count > 1:
                # 使用指数函数控制渐变速度，gradient_rate越大渐变越快
                linear_ratio = char_index / char_count
                # 应用渐变度参数：gradient_rate越大，ratio增长越快
                ratio = 1 - (1 - linear_ratio) ** gradient_rate
            else:
                ratio = 0  # 只有一个字符时使用起始颜色
            
            # 计算当前字符的颜色
            current_rgb = interpolate_color(start_rgb, end_rgb, ratio)
            current_color = rgb_to_hex(current_rgb)
            
            # 为每个字符单独包装颜色标签
            result_parts.append(f"<color={current_color}>{part['content']}</color>")
            char_index += 1
    
    # 合并所有部分
    return ''.join(result_parts)

def apply_color_gradient(text: str, start_color: str, gradient_rate: float = 2.0) -> str:
    """对文本应用颜色渐变效果（默认渐变到白色）
    Args:
        text: 要处理的文本
        start_color: 起始颜色
        gradient_rate: 渐变度，越大渐变越快（默认2.0）
    """
    return apply_color_gradient_custom(text, start_color, "#ffffff", gradient_rate)

def process_dlg_text(dlg_text: str, gradient_rate: float = 2.0) -> str:
    """处理dlg文本，提取颜色并应用渐变
    Args:
        dlg_text: 要处理的dlg文本
        gradient_rate: 渐变度，越大渐变越快（默认2.0）
    """
    # 匹配颜色标签 - 使用re.DOTALL标志来支持跨行匹配
    color_pattern = r'<color=#([a-fA-F0-9]{3,6})>(.*?)</color>'
    match = re.search(color_pattern, dlg_text, re.DOTALL)  # 添加re.DOTALL标志
    
    if not match:
        return dlg_text  # 没有颜色标签，直接返回
    
    color_code = match.group(1)
    text_content = match.group(2)
    
    # 应用颜色渐变
    processed_text = apply_color_gradient(text_content, color_code, gradient_rate)
    
    # 替换原始文本中的对应部分
    return dlg_text.replace(match.group(0), processed_text)

def create_gradient_test_gui(window, root):
    """创建渐变文本测试GUI界面"""
    import tkinter as tk
    from tkinter import scrolledtext, colorchooser, font
    import os
    
    # 颜色选择函数（与main.py保持一致）
    def choose_start_color():
        color = colorchooser.askcolor(title="选择起始颜色", initialcolor=start_color_var.get())[1]
        if color:
            start_color_var.set(color)
            start_color_canvas.configure(bg=color)
            update_preview()
    
    def choose_end_color():
        color = colorchooser.askcolor(title="选择结束颜色", initialcolor=end_color_var.get())[1]
        if color:
            end_color_var.set(color)
            end_color_canvas.configure(bg=color)
            update_preview()
    
    # 更新预览函数
    def update_preview(event=None):
        try:
            text_content = text_entry.get("1.0", tk.END).strip()
            if not text_content:
                return
                
            start_color = start_color_var.get()
            end_color = end_color_var.get()
            gradient_rate = gradient_scale.get()
            
            # 应用渐变处理
            processed_text = apply_color_gradient_custom(text_content, start_color, end_color, gradient_rate)
            
            # 更新HTML显示
            html_text.config(state=tk.NORMAL)
            html_text.delete("1.0", tk.END)
            html_text.insert("1.0", processed_text)
            html_text.config(state=tk.DISABLED)
        except Exception as e:
            print(f"更新预览时出错: {e}")
    
    # 复制功能
    def copy_html():
        try:
            html_content = html_text.get("1.0", tk.END).strip()
            if html_content:
                root.clipboard_clear()
                root.clipboard_append(html_content)
        except Exception as e:
            pass
    
    # 重置功能
    def reset_settings():
        start_color_var.set(C.CYAN)
        end_color_var.set(C.TEXT_WHITE)
        start_color_canvas.configure(bg=C.TEXT_WHITE)
        end_color_canvas.configure(bg=C.TEXT_WHITE)
        gradient_scale.set(2.0)
        gradient_value_label.config(text="0.1")
        text_entry.delete("1.0", tk.END)
        text_entry.insert("1.0", "你也将安息, 化作哀蝶消散吧...")
        update_preview()
    
    # 创建主窗口
    root = tk.Toplevel(root)
    root.withdraw()
    root.title("渐变文本生成工具")
    root.geometry("600x750")
    root.resizable(True, True)

    center_window(root)
    
    # 设置窗口图标（与main.py保持一致）
    try:
        if os.path.exists("assets/images/icon/icon.ico"):
            root.iconbitmap("assets/images/icon/icon.ico")
    except:
        pass
    
    # 设置样式（与main.py保持一致）
    # style = ttk.Style()
    # style.theme_use('clam')
    
    # # 配置样式（使用main.py的颜色方案）
    # style.configure("TFrame", background=window.bg_color)
    # style.configure("TLabel", background=window.bg_color, foreground='white', font=('Microsoft YaHei UI', 10))
    # style.configure("TButton", background='#3498db', foreground='white', font=('Microsoft YaHei UI', 9, 'bold'))
    # style.configure("TLabelframe", background='#f8f9fa', foreground=window.lighten_bg_color)
    # style.configure("TLabelframe.Label", background='#f8f9fa', foreground=window.lighten_bg_color, font=('Microsoft YaHei UI', 11, 'bold'))
    # style.configure("TScale", background=window.bg_color)
    
    # 创建变量
    start_color_var = tk.StringVar(value=C.CYAN)
    end_color_var = tk.StringVar(value=C.TEXT_WHITE)
    
    # 创建主容器（使用main.py的深蓝色背景）
    main_frame = tk.Frame(root, bg=window.bg_color, padx=20, pady=20)
    main_frame.pack(fill=tk.BOTH, expand=True)
    
    # 配置网格权重
    root.columnconfigure(0, weight=1)
    root.rowconfigure(0, weight=1)
    main_frame.columnconfigure(0, weight=1)
    main_frame.rowconfigure(3, weight=1)
    main_frame.rowconfigure(5, weight=1)
    
    # 颜色选择区域（使用卡片式设计）
    color_frame = tk.Frame(main_frame, bg='#f8f9fa', relief='raised', borderwidth=2, padx=15, pady=15)
    color_frame.grid(row=1, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=(0, 15)) # type: ignore
    color_frame.columnconfigure(1, weight=1)
    color_frame.columnconfigure(3, weight=1)
    
    # 区域标题
    color_title = tk.Label(color_frame, text="🎨 颜色设置", bg='#f8f9fa', fg=window.lighten_bg_color, 
                          font=('Microsoft YaHei UI', 12, 'bold'))
    color_title.grid(row=0, column=0, columnspan=6, sticky=tk.W, pady=(0, 10))
    
    # 起始颜色
    tk.Label(color_frame, text="起始颜色:", bg='#f8f9fa', fg=window.lighten_bg_color, 
            font=('Microsoft YaHei UI', 10)).grid(row=1, column=0, sticky=tk.W, padx=(0, 10))
    start_color_canvas = tk.Canvas(color_frame, width=30, height=30, bg=start_color_var.get(), 
                                  relief="solid", borderwidth=1, highlightthickness=0)
    start_color_canvas.grid(row=1, column=1, sticky=tk.W, padx=(0, 15))
    
    start_color_btn = tk.Button(color_frame, text="选择颜色", command=choose_start_color,
                               bg=C.LEGACY_BLUE, fg=C.TEXT_WHITE, font=('Microsoft YaHei UI', 9, 'bold'),
                               relief='flat', padx=10, pady=3, cursor='hand2')
    start_color_btn.grid(row=1, column=2, padx=(0, 30))
    
    # 结束颜色
    tk.Label(color_frame, text="结束颜色:", bg='#f8f9fa', fg=window.lighten_bg_color, 
            font=('Microsoft YaHei UI', 10)).grid(row=1, column=3, sticky=tk.W, padx=(0, 10))
    end_color_canvas = tk.Canvas(color_frame, width=30, height=30, bg=end_color_var.get(), 
                                relief="solid", borderwidth=1, highlightthickness=0)
    end_color_canvas.grid(row=1, column=4, sticky=tk.W, padx=(0, 15))
    
    end_color_btn = tk.Button(color_frame, text="选择颜色", command=choose_end_color,
                             bg='#3498db', fg='white', font=('Microsoft YaHei UI', 9, 'bold'),
                             relief='flat', padx=10, pady=3, cursor='hand2')
    end_color_btn.grid(row=1, column=5)
    
    # 渐变度设置区域（卡片式设计）
    gradient_frame = tk.Frame(main_frame, bg='#f8f9fa', relief='raised', borderwidth=2, padx=15, pady=15)
    gradient_frame.grid(row=2, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=(0, 15)) # type: ignore
    gradient_frame.columnconfigure(1, weight=1)
    
    # 区域标题
    gradient_title = tk.Label(gradient_frame, text="📊 渐变度设置", bg='#f8f9fa', fg=window.lighten_bg_color, 
                             font=('Microsoft YaHei UI', 12, 'bold'))
    gradient_title.grid(row=0, column=0, columnspan=3, sticky=tk.W, pady=(0, 10))
    
    tk.Label(gradient_frame, text="渐变度 (值越大渐变越快):", bg='#f8f9fa', fg=window.lighten_bg_color, 
            font=('Microsoft YaHei UI', 10)).grid(row=1, column=0, sticky=tk.W)
    
    gradient_scale = tk.Scale(gradient_frame, from_=0.1, to=5.0, resolution=0.1,orient=tk.HORIZONTAL,
                             command=update_preview, bg='#f8f9fa', fg=window.lighten_bg_color, 
                             highlightbackground='#bdc3c7', troughcolor='#ecf0f1')
    gradient_scale.grid(row=1, column=1, sticky=(tk.W, tk.E), padx=(10, 10)) # type: ignore

    gradient_value_label = tk.Label(gradient_frame, text="0.1", bg='#f8f9fa', fg=window.lighten_bg_color, 
                                   font=('Microsoft YaHei UI', 10, 'bold'))
    gradient_value_label.grid(row=1, column=2)
    
    # 更新渐变度显示
    def update_gradient_label(event):
        gradient_value_label.config(text=f"{gradient_scale.get():.1f}")
    
    gradient_scale.configure(command=lambda e: [update_gradient_label(e), update_preview()])
    
    # 文本输入区域（卡片式设计）
    text_frame = tk.Frame(main_frame, bg='#f8f9fa', relief='raised', borderwidth=2, padx=15, pady=15)
    text_frame.grid(row=3, column=0, columnspan=3, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(0, 15)) # type: ignore
    text_frame.columnconfigure(0, weight=1)
    text_frame.rowconfigure(1, weight=1)
    
    # 区域标题
    text_title = tk.Label(text_frame, text="📝 输入文本", bg='#f8f9fa', fg=window.lighten_bg_color, 
                         font=('Microsoft YaHei UI', 12, 'bold'))
    text_title.grid(row=0, column=0, sticky=tk.W, pady=(0, 10))
    
    text_entry = scrolledtext.ScrolledText(text_frame, width=60, height=6, wrap=tk.WORD, 
                                          bg='white', fg=window.lighten_bg_color, font=('Microsoft YaHei UI', 10),
                                          relief='solid', borderwidth=1)
    text_entry.grid(row=1, column=0, sticky=(tk.W, tk.E, tk.N, tk.S)) # type: ignore
    text_entry.insert("1.0", "你也将安息, 化作哀蝶消散吧...")
    text_entry.bind("<KeyRelease>", update_preview)
    
    # Unity富文本区域（卡片式设计）
    html_frame = tk.Frame(main_frame, bg='#f8f9fa', relief='raised', borderwidth=2, padx=15, pady=15)
    html_frame.grid(row=4, column=0, columnspan=3, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(0, 15)) # type: ignore
    html_frame.columnconfigure(0, weight=1)
    html_frame.rowconfigure(1, weight=1)
    
    # 区域标题
    html_title = tk.Label(html_frame, text="🎯 生成的 Unity 富文本", bg='#f8f9fa', fg=window.lighten_bg_color, 
                         font=('Microsoft YaHei UI', 12, 'bold'))
    html_title.grid(row=0, column=0, sticky=tk.W, pady=(0, 10))
    
    html_text = scrolledtext.ScrolledText(html_frame, width=60, height=4, wrap=tk.WORD, state=tk.DISABLED,
                                         bg='#f5f5f5', fg=window.lighten_bg_color, font=('Consolas', 9),
                                         relief='solid', borderwidth=1)
    html_text.grid(row=1, column=0, sticky=(tk.W, tk.E, tk.N, tk.S)) # type: ignore
    
    # 按钮区域
    button_frame = tk.Frame(main_frame, bg=window.bg_color)
    button_frame.grid(row=5, column=0, columnspan=3, pady=(20, 0))
    
    # 按钮样式（与main.py保持一致）
    button_style = {'bg': '#3498db', 'fg': 'white', 'font': ('Microsoft YaHei UI', 10, 'bold'),
                   'relief': 'flat', 'padx': 15, 'pady': 8, 'cursor': 'hand2'}
    
    copy_btn = tk.Button(button_frame, text="📋 复制 Unity 富文本", command=copy_html, **button_style)
    copy_btn.pack(side=tk.LEFT, padx=(0, 10))
    
    reset_btn = tk.Button(button_frame, text="🔄 重置设置", command=reset_settings, **button_style)
    reset_btn.pack(side=tk.LEFT, padx=(0, 10))
    
    close_btn = tk.Button(button_frame, text="❌ 关闭", command=root.destroy, 
                         bg='#e74c3c', fg='white', font=('Microsoft YaHei UI', 10, 'bold'),
                         relief='flat', padx=15, pady=8, cursor='hand2')
    close_btn.pack(side=tk.LEFT)
    
    # 添加按钮悬停效果
    def on_enter(btn, original_color):
        btn.configure(bg=darken_color(original_color))
    
    def on_leave(btn, original_color):
        btn.configure(bg=original_color)
    
    # 应用悬停效果
    copy_btn.bind("<Enter>", lambda e: on_enter(copy_btn, '#3498db'))
    copy_btn.bind("<Leave>", lambda e: on_leave(copy_btn, '#3498db'))
    
    reset_btn.bind("<Enter>", lambda e: on_enter(reset_btn, '#3498db'))
    reset_btn.bind("<Leave>", lambda e: on_leave(reset_btn, '#3498db'))
    
    close_btn.bind("<Enter>", lambda e: on_enter(close_btn, '#e74c3c'))
    close_btn.bind("<Leave>", lambda e: on_leave(close_btn, '#e74c3c'))
    
    # 初始更新预览
    update_preview()
    
    return root

def test_color_gradient_gui(UI):
    """启动渐变文本测试GUI"""
    try:
        root = create_gradient_test_gui(UI, UI.root)
        root.mainloop()
        return True
    except Exception as e:
        print(f"GUI启动失败: {e}")
        return False

def test_color_gradient(gradient_rate: float = 2.0):
    """测试颜色渐变功能
    Args:
        gradient_rate: 渐变度，越大渐变越快（默认2.0）
    """
    test_cases = [
        {
            'input': '<color=#6e44a6>呼，洗盘子的家伙们\n也会捅刀过来。</color>',
            'description': '包含换行符的文本'
        },
        {
            'input': '<color=#6e44a6>凯瑟琳……？！是我，希斯克利夫……！\n求求你再一次接受我吧！！！</color>',
            'description': '包含换行符和标点符号的文本'
        },
        {
            'input': '<color=#ff0000>Hello <i>World</i>!</color>',
            'description': '包含HTML标签的文本'
        },
        {
            'input': '<color=#ffffff>已经是白色的文本</color>',
            'description': '已经是白色的文本'
        }
    ]
    
    print("测试颜色渐变功能:")
    print(f"渐变度设置: {gradient_rate}")
    print("=" * 60)
    
    for i, test_case in enumerate(test_cases, 1):
        print(f"\n测试用例 {i}: {test_case['description']}")
        print(f"输入: {test_case['input']}")
        
        processed = process_dlg_text(test_case['input'], gradient_rate)
        print(f"输出: {processed}")
        
        # 检查是否发生了变化（除了白色文本）
        if test_case['input'] != processed:
            print("处理成功 - 文本已被渐变处理")
        else:
            print("ℹ️  未处理 - 文本保持原样（可能是白色或特殊情况）")
        
        print("-" * 40)

def process_json_file(file_path: str, gradient_rate: float = 2.0) -> bool:
    """处理单个JSON文件
    Args:
        file_path: JSON文件路径
        gradient_rate: 渐变度，越大渐变越快（默认2.0）
    """
    try:
        # 读取JSON文件
        data = read_json(file_path)
        
        # 检查数据结构
        if 'dataList' not in data or not isinstance(data['dataList'], list):
            print(f"文件 {file_path} 格式不正确")
            return False
        
        processed_count = 0
        total_count = len(data['dataList'])
        
        # 处理每个条目
        for item in data['dataList']:
            if 'dlg' in item and item['dlg']:
                original_dlg = item['dlg']
                processed_dlg = process_dlg_text(original_dlg, gradient_rate)
                
                if processed_dlg != original_dlg:
                    item['dlg'] = processed_dlg
                    processed_count += 1
        
        # 保存处理后的文件
        write_json(file_path, data, indent=2)
        
        print(f"文件 {os.path.basename(file_path)} 处理完成")
        print(f"  处理了 {processed_count}/{total_count} 个条目")
        return True
        
    except Exception as e:
        print(f"处理文件 {file_path} 时出错: {e}")
        return False

def process_all_json_files(game_path: str, gradient_rate: float = 2.0) -> bool:
    """处理游戏目录下的所有JSON文件
    Args:
        game_path: 游戏目录路径
        gradient_rate: 渐变度，越大渐变越快（默认2.0）
    """
    # 目标目录
    from functions.web_update.translation_source import get_game_lang_dir
    target_dir = get_game_lang_dir(game_path)
    
    if not os.path.exists(target_dir):
        print(f"目标目录不存在: {target_dir}")
        return False
    
    # 要处理的JSON文件列表
    json_files = []

    # 搜索所有前缀带有 'BattleSpeechBubbleDlg' 的文件
    for file in os.listdir(target_dir):
        if file.startswith('BattleSpeechBubbleDlg'):
            json_files.append(file)
    
    success_count = 0
    
    for json_file in json_files:
        file_path = os.path.join(target_dir, json_file)
        
        if os.path.exists(file_path):
            if process_json_file(file_path, gradient_rate):
                success_count += 1
        else:
            print(f"⚠️ 文件不存在: {file_path}")
    
    print(f"\n处理完成: {success_count}/{len(json_files)} 个文件成功处理")
    print(f"渐变度设置: {gradient_rate}")
    return success_count > 0

def process_temp_json_files(gradient_rate: float = 2.0) -> bool:
    """处理temp目录下的JSON文件（用于测试）
    Args:
        gradient_rate: 渐变度，越大渐变越快（默认2.0）
    """
    temp_dir = os.path.join(os.path.dirname(__file__), '..', 'temp')
    temp_dir = os.path.abspath(temp_dir)
    
    if not os.path.exists(temp_dir):
        print(f"temp目录不存在: {temp_dir}")
        return False
    
    # 要处理的JSON文件列表
    json_files = []

    # 搜寻所有前缀带有 'BattleSpeechBubbleDlg' 的文件
    json_files.extend([f for f in os.listdir(temp_dir) if f.startswith('BattleSpeechBubbleDlg')])
       
    success_count = 0
    
    for json_file in json_files:
        file_path = os.path.join(temp_dir, json_file)
        
        if os.path.exists(file_path):
            if process_json_file(file_path, gradient_rate):
                success_count += 1
        else:
            print(f"⚠️ 文件不存在: {file_path}")
    
    print(f"\n处理完成: {success_count}/{len(json_files)} 个文件成功处理")
    print(f"渐变度设置: {gradient_rate}")
    return success_count > 0

def main():
    """主函数入口点"""
    print("气泡文本 JSON 颜色渐变处理器")
    try:
        gradient_rate = get_settings_manager().get_setting('bubble_text_gradient_rate')
        game_path = get_settings_manager().get_setting('game_path')
        
        if not game_path:
            print("气泡渐变色：未配置游戏路径")
            return False
        if not gradient_rate:
            gradient_rate = 0.5
        
        return process_all_json_files(game_path, gradient_rate) # type: ignore
    
    except Exception as e:
        print(f"读取配置文件失败: {e}")
        return False

def maint():
    """命令行入口点"""
    print("=" * 50)
    print("气泡文本 JSON 颜色渐变处理器")
    print("=" * 50)
    
    print("1. 处理游戏目录下的JSON文件")
    print("2. 处理temp目录下的JSON文件（测试）")
    print("3. 命令行测试渐变效果")
    print("4. GUI测试渐变效果（自定义颜色）")
    
    choice = input("请选择操作 (1-4): ").strip()
    
    if choice == "1":
        # 从配置文件获取游戏路径
        try:
            main()
            
        except Exception as e:
            print(f"读取配置文件失败: {e}")
            return False
    
    elif choice == "2":
        gradient_rate = float(input("请输入渐变度 (默认2.0): ") or "2.0")
        return process_temp_json_files(gradient_rate)
    
    elif choice == "3":
        gradient_rate = float(input("请输入渐变度 (默认2.0): ") or "2.0")
        test_color_gradient(gradient_rate)
        return True
    
    elif choice == "4":
        pass
        # return test_color_gradient_gui()
    
    else:
        print("无效选择")
        return False

if __name__ == "__main__":
    success = maint()
    if success:
        print("\n 操作成功完成!")
    else:
        print("\n 操作失败!")