import os
import json
import concurrent.futures
from functions.translate.ai_translate import AITranslator

import unicodedata
from functions.base.common.json_io import read_json, write_json

def is_all_punctuation(sentence):
    """检测句子是否完全由标点符号组成（允许包含空白字符）"""
    if not sentence:
        return False
    
    for char in sentence:
        # 跳过空白字符
        if char.isspace():
            continue
        # 检查字符是否为标点符号（Unicode 类别以 'P' 开头）
        if not unicodedata.category(char).startswith('P'):
            return False
    return True

class AutoTranslator:
    def __init__(self, window):
        self.window = window
        self.translator = AITranslator()
        self.target_keys = {'content', 'teller', 'dlg', 'desc', 'dialog', 'abName', 'name', 'place'}
        self.is_running = True
    
    def set_running_state(self, state):
        """设置运行状态"""
        self.is_running = state
    
    def _get_json_files(self, source_path):
        """获取源路径下的所有 json 文件"""
        json_files = []
        for root, dirs, files in os.walk(source_path):
            for file in files:
                if file.endswith('.json'):
                    json_files.append(os.path.join(root, file))
        return json_files
    
    def _translate_value(self, value):
        """翻译单个值"""
        if not value or not isinstance(value, str):
            return value
        
        if is_all_punctuation(value):
            self.window.log_message(f"⏩ 跳过纯标点符号的值: {value}")
            return value
        
        try:
            result = self.translator.translate(value)
            if result['status'] == 0:
                text:str = result['data']['info']['text']
                text = text.replace('“','').replace('”','')

                self.window.log_message(f" 翻译成功: {value} -> {text}")
                return text
            else:
                self.window.log_message(f"⚠️ 翻译失败: {result}")
                return value
        except Exception as e:
            self.window.log_message(f"⚠️ 翻译异常: {e}")
            return value
    
    def _process_file(self, source_file, target_file, is_skill=False):
        """处理单个 json 文件"""
        if not self.is_running:
            return False
        
        try:
            # 读取源文件
            data = read_json(source_file)
            
            # 翻译文件
            if is_skill:
                # 处理技能文件
                if isinstance(data, list):
                    for item in data:
                        if not self.is_running:
                            return False
                        if isinstance(item, dict):
                            for key in item:
                                if key in self.target_keys:
                                    item[key] = self._translate_value(item[key])
            else:
                # 处理普通文件
                if isinstance(data, dict):
                    for key in data:
                        if not self.is_running:
                            return False
                        if key in self.target_keys:
                            data[key] = self._translate_value(data[key])
                        elif isinstance(data[key], dict):
                            # 递归处理嵌套字典
                            for sub_key in data[key]:
                                if not self.is_running:
                                    return False
                                if sub_key in self.target_keys:
                                    data[key][sub_key] = self._translate_value(data[key][sub_key])
                        elif isinstance(data[key], list):
                            # 处理列表
                            for i, item in enumerate(data[key]):
                                if not self.is_running:
                                    return False
                                if isinstance(item, dict):
                                    for sub_key in item:
                                        if not self.is_running:
                                            return False
                                        if sub_key in self.target_keys:
                                            item[sub_key] = self._translate_value(item[sub_key])
            
            # 保存目标文件
            write_json(target_file, data, indent=2)
            
            return True
        except Exception as e:
            self.window.log_message(f"❌ 处理文件失败 {source_file}: {e}")
            return False
    
    def translate(self, source_path, target_path, blacklist_files=None, progress_callback=None, is_skill=False):
        """主方法，用于启动翻译任务"""
        if blacklist_files is None:
            blacklist_files = []
        
        self.is_running = True
        
        # 获取源路径下的所有 json 文件
        source_files = self._get_json_files(source_path)
        total_files = len(source_files)
        
        if total_files == 0:
            self.window.log_message(f"⚠️ 在源路径 {source_path} 下没有找到 json 文件")
            return False
        
        self.window.log_message(f"📁 找到 {total_files} 个 json 文件")
        
        # 过滤掉黑名单文件
        filtered_files = []
        for file in source_files:
            filename = os.path.basename(file)
            if filename not in blacklist_files:
                filtered_files.append(file)
        
        if filtered_files != source_files:
            self.window.log_message(f"🚫 跳过了 {total_files - len(filtered_files)} 个黑名单文件")
        
        total_files = len(filtered_files)
        processed_files = 0
        success_files = 0
        
        # 确保目标路径存在
        os.makedirs(target_path, exist_ok=True)
        
        # 使用线程池处理文件
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            # 提交所有任务
            futures = []
            filtered_files.reverse()

            for source_file in filtered_files:
                # 构建目标文件路径
                target_file = os.path.join(target_path, os.path.basename(str(source_file).replace("EN_", '')))
                file_name = os.path.basename(target_file)

                if os.path.exists(target_file):
                    # self.window.log_message(f"⚠️ 目标文件已存在，跳过: {file_name}")
                    processed_files += 1
                    if progress_callback:
                        progress_callback(processed_files, total_files, f"已处理 {processed_files}/{total_files} 个文件")
                    continue

                self.window.log_message(f"🔄 开始处理文件: {file_name}")
                
                # 确保目标文件的父目录存在
                os.makedirs(os.path.dirname(target_file), exist_ok=True)
                
                # 提交任务
                futures.append(executor.submit(self._process_file, source_file, target_file, is_skill))
            
            # 处理任务结果
            for future in concurrent.futures.as_completed(futures):
                if not self.is_running:
                    break
                
                processed_files += 1
                
                if future.result():
                    success_files += 1
                
                # 更新进度
                if progress_callback:
                    progress_callback(processed_files, total_files, f"已处理 {processed_files}/{total_files} 个文件")
        
        if self.is_running:
            self.window.log_message(f" 翻译完成，成功处理 {success_files}/{total_files} 个文件")
            return True
        else:
            self.window.log_message(f"⏹️ 翻译任务被取消，已处理 {processed_files}/{total_files} 个文件")
            return False

def auto_translate(window, source_path, target_path, blacklist_files=None, progress_callback=None, is_skill=False):
    """入口函数，用于调用 AutoTranslator 类"""
    # 创建一个临时的窗口对象，用于输出日志
    translator = AutoTranslator(window)
    translator.translate(source_path, target_path, blacklist_files, progress_callback, is_skill)