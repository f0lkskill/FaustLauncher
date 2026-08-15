"""web 配置加载器 — 从 config/web_config.json 读取 webnote 等云端地址/凭据。

config/web_config.json 已被 .gitignore 排除，不会随源码上传 GitHub。
打包版: 配置由 FaustLauncher.spec 在构建时内嵌进 exe (PYZ 内的 web_config_data
模块)，不以独立文件随构建产物分发；exe 目录存在 config/web_config.json 时
优先读取（本地覆盖/调试用），否则回退到内嵌配置。
源码版: 按项目根目录读取 (与 cwd 无关)。
文件缺失时静默降级（返回空值，不打印警告）；文件存在但格式错误时打印警告。
"""

import json
import os
import sys

# 打包版: 构建时内嵌的配置 (编译进 PYZ, 非独立文件)
EMBEDDED_CONFIG = None
try:
    from web_config_data import EMBEDDED_CONFIG  # type: ignore
except ImportError:
    pass

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
    data = None
    try:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except FileNotFoundError:
        pass
    except Exception as e:
        print(f"[警告] 读取 {CONFIG_PATH} 失败: {e} (相关云端功能将不可用)")
    if data is None and EMBEDDED_CONFIG:
        try:
            data = json.loads(EMBEDDED_CONFIG)
        except Exception as e:
            print(f"[警告] 解析内嵌云端配置失败: {e} (相关云端功能将不可用)")
            data = None
    _config_cache = data if isinstance(data, dict) else {}
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
