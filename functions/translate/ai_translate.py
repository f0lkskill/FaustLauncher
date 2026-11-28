"""translate 子模块：<ai_translate>（具体职责见函数文档）。"""

import requests
from functions.base.settings_manager import get_settings_manager


class AITranslator:
    """AITranslator类。"""
    def __init__(self):
        """初始化对象状态。"""
        self.appid:str = get_settings_manager().get_setting("ai_app_key") # type: ignore
        self.prompt:str = get_settings_manager().get_setting("ai_prompt") # type: ignore
        self.userid = "user"

    def translate(self, text: str):
        """翻译相关处理。"""
        text = self.prompt.replace("{text}", text)
        sess = requests.get(f'https://api.sizhi.com/chat?appid={self.appid}&userid={self.userid}&spoken={text}')
        answer = sess.json()
        return answer