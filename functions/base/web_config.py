"""web 配置加载器 — 从 config/web_config.json 读取 webnote 等云端地址/凭据。

config/web_config.json 已被 .gitignore 排除，不会随源码上传 GitHub。
文件缺失或读取失败时相关云端功能将自动降级（打印警告并返回空值），
避免打包/开发环境缺少该文件时崩溃。
"""

import json
import os

CONFIG_PATH = os.path.join('config', 'web_config.json')

_config_cache = None


def get_web_config() -> dict:
    """读取完整 web 配置（带缓存），失败时返回空 dict。"""
    global _config_cache
    if _config_cache is not None:
        return _config_cache
    try:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        _config_cache = data if isinstance(data, dict) else {}
    except Exception as e:
        print(f"[警告] 读取 {CONFIG_PATH} 失败: {e} (相关云端功能将不可用)")
        _config_cache = {}
    return _config_cache


def _get_webnote_item(key: str):
    """获取指定用途的 webnote 配置项，支持 dict 或字符串两种写法。"""
    data = get_web_config().get('webnote', {})
    if not isinstance(data, dict):
        return None
    return data.get(key)


def get_webnote_address(key: str) -> str:
    """获取指定用途的 webnote 笔记地址（如 'version_info'），不存在时返回空字符串。"""
    item = _get_webnote_item(key)
    if isinstance(item, dict):
        return item.get('address', '') or ''
    if isinstance(item, str):
        return item
    return ''


def get_webnote(key: str) -> tuple[str, str]:
    """获取指定用途的 webnote 配置，返回 (address, pwd)。"""
    item = _get_webnote_item(key)
    if isinstance(item, dict):
        return (item.get('address', '') or '', item.get('pwd', '') or '')
    if isinstance(item, str):
        return (item, '')
    return ('', '')
