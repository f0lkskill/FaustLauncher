
import json
import os
import sys
from functions.base.common.json_io import read_json

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
_config_source = ""

def _embedded_dict() -> dict:
    if not EMBEDDED_CONFIG:
        return {}
    try:
        data = json.loads(EMBEDDED_CONFIG)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}

def _warn_if_webnote_differs(local: dict, embedded: dict) -> None:
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
            print("[Cloud] 本地 config/web_config.json 与内嵌配置的笔记地址不一致: " + " | ".join(diffs))
            print("[Cloud] 若本地配置是旧版本残留, 建议删除 exe 同目录的 config/web_config.json (将自动改用内嵌配置)")
    except Exception:
        pass

def get_web_config() -> dict:
    global _config_cache, _config_source
    if _config_cache is not None:
        return _config_cache
    data = None
    embedded = _embedded_dict()
    try:
        data = read_json(CONFIG_PATH)
        _config_source = "本地文件"
        if embedded:
            _warn_if_webnote_differs(data if isinstance(data, dict) else {}, embedded)
    except FileNotFoundError:
        pass
    except Exception as e:
        print(f"[Warning] 读取 {CONFIG_PATH} 失败: {e} (相关云端功能将不可用)")
    if data is None and embedded:
        data = embedded
        _config_source = "内嵌配置"
    _config_cache = data if isinstance(data, dict) else {}
    return _config_cache

def get_config_source() -> str:
    get_web_config()
    return _config_source or "未知"

def get_embedded_webnote_address(key: str) -> str:
    item = (_embedded_dict().get("webnote") or {}).get(key)
    if isinstance(item, dict):
        return str(item.get("address") or "")
    if isinstance(item, str):
        return item
    return ""

def _get_webnote_item(key: str):
    data = get_web_config().get('webnote', {})
    if not isinstance(data, dict):
        return None
    return data.get(key)

def get_webnote_address(key: str) -> str:
    item = _get_webnote_item(key)
    if isinstance(item, dict):
        return item.get('address', '') or ''
    if isinstance(item, str):
        return item
    return ''

def get_webnote(key: str) -> tuple[str, str]:
    item = _get_webnote_item(key)
    if isinstance(item, dict):
        return (item.get('address', '') or '', item.get('pwd', '') or '')
    if isinstance(item, str):
        return (item, '')
    return ('', '')

def get_api_base() -> str:
    data = get_web_config()
    base = data.get('api_base')
    if isinstance(base, str) and base.strip():
        return base.strip().rstrip('/')
    bases = data.get('webnote_bases')
    if isinstance(bases, str):
        bases = [bases]
    if isinstance(bases, (list, tuple)):
        from urllib.parse import urlsplit
        for item in bases:
            text = str(item or '').strip()
            if not text:
                continue
            try:
                parts = urlsplit(text)
            except Exception:
                continue
            if parts.scheme and parts.netloc:
                return f"{parts.scheme}://{parts.netloc}"
    return ''

def get_lanzou_config() -> dict:
    data = get_web_config().get('lanzou', {})
    return data if isinstance(data, dict) else {}
