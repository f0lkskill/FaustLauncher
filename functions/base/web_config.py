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
_config_source = ""      # 本次实际使用的配置来源 (诊断用)


def _embedded_dict() -> dict:
    """解析内嵌配置 (构建时由 spec 从 config/web_config.json 生成)"""
    if not EMBEDDED_CONFIG:
        return {}
    try:
        data = json.loads(EMBEDDED_CONFIG)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _warn_if_webnote_differs(local: dict, embedded: dict) -> None:
    """exe 旁的配置比内嵌配置旧时提醒 (残留的旧 config 会把笔记名指回旧值)"""
    try:
        a = (local.get("webnote") or {})
        b = (embedded.get("webnote") or {})
        if not isinstance(a, dict) or not isinstance(b, dict):
            return
        diffs = []
        for k in b:
            va = (a.get(k) or {}).get("address", "") if isinstance(a.get(k), dict) else (a.get(k) or "")
            vb = (b.get(k) or {}).get("address", "") if isinstance(b.get(k), dict) else (b.get(k) or "")
            if va and vb and str(va) != str(vb):
                diffs.append(f"{k}: 本地 {va} / 内嵌 {vb}")
        if diffs:
            print("[云端] 本地 config/web_config.json 与内嵌配置的笔记地址不一致: " + " | ".join(diffs))
            print("[云端] 若本地配置是旧版本残留, 建议删除 exe 同目录的 config/web_config.json (将自动改用内嵌配置)")
    except Exception:
        pass


def get_web_config() -> dict:
    """读取完整 web 配置（带缓存），失败时返回空 dict。

    优先级: exe 同目录的 config/web_config.json (本地覆盖/调试) → 构建时内嵌配置。
    会打印实际使用的来源, 并在两者笔记地址不一致时告警。
    """
    global _config_cache, _config_source
    if _config_cache is not None:
        return _config_cache
    data = None
    embedded = _embedded_dict()
    try:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        _config_source = "本地文件"
        print(f"[云端] 使用本地配置: {CONFIG_PATH}")
        if embedded:
            _warn_if_webnote_differs(data if isinstance(data, dict) else {}, embedded)
    except FileNotFoundError:
        pass
    except Exception as e:
        print(f"[警告] 读取 {CONFIG_PATH} 失败: {e} (相关云端功能将不可用)")
    if data is None and embedded:
        data = embedded
        _config_source = "内嵌配置"
        print("[云端] 使用内嵌配置 (exe 同目录无 config/web_config.json)")
    _config_cache = data if isinstance(data, dict) else {}
    return _config_cache


def get_config_source() -> str:
    """本次使用的配置来源描述 (诊断用)"""
    get_web_config()
    return _config_source or "未知"


def get_embedded_webnote_address(key: str) -> str:
    """从构建时内嵌配置里取笔记地址。

    用于纠正 exe 同目录里残留的旧配置 (旧笔记名会返回 200+空内容),
    调用方应把它的值作为备用笔记名一起尝试。
    """
    item = (_embedded_dict().get("webnote") or {}).get(key)
    if isinstance(item, dict):
        return str(item.get("address") or "")
    if isinstance(item, str):
        return item
    return ""


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
