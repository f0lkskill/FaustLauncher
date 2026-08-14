"""web 配置加载器 — 从 config/web_config.json 读取 webnote 等云端地址/凭据。

config/web_config.json 已被 .gitignore 排除，不会随源码上传 GitHub。
构建产物中同样携带该文件 (build.py 会复制 config 目录)，保证打包版云端功能可用。
路径解析: 打包版按 exe 所在目录, 源码版按项目根目录 (与 cwd 无关)。
文件缺失时静默降级（返回空值，不打印警告）；文件存在但格式错误时打印警告。
"""

import json
import os
import sys

if getattr(sys, "frozen", False):
    _PROJECT_ROOT = os.path.dirname(os.path.abspath(sys.executable))
else:
    _PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

CONFIG_PATH = os.path.join(_PROJECT_ROOT, "config", "web_config.json")

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
    except FileNotFoundError:
        _config_cache = {}
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


def get_lanzou_config() -> dict:
    """获取蓝奏云上传配置 (phpdisk_info/ylogin/文件夹名)，未配置时返回空 dict。"""
    data = get_web_config().get('lanzou', {})
    return data if isinstance(data, dict) else {}
