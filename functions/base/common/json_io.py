"""JSON 与文本的容错读写工具。

统一处理 BOM、UTF-16、GB18030 等编码，并记住每个文件上次读到的编码/BOM，
写回时尽量保持原格式（``write_json`` 默认复用 :func:`last_meta`）。所有写入
都先落同目录临时文件再 ``os.replace``，避免中途失败留下半截 JSON。

读文件分两档：:func:`read_json` 解析失败就抛异常，适合必须成功的场景；
:func:`try_read_json` 失败时返回默认值，适合缓存/可选配置。
"""

import codecs
import json
import os
import threading

__all__ = [
    "read_text", "read_json", "read_json_meta", "try_read_json",
    "write_text", "write_json", "sniff_encoding", "last_meta",
]

_BOMS = (
    (codecs.BOM_UTF32_LE, "utf-32-le"),
    (codecs.BOM_UTF32_BE, "utf-32-be"),
    (codecs.BOM_UTF8, "utf-8"),
    (codecs.BOM_UTF16_LE, "utf-16-le"),
    (codecs.BOM_UTF16_BE, "utf-16-be"),
)

_FALLBACK_ENCODINGS = ("utf-8", "gb18030")

_meta_cache = {}
_meta_lock = threading.Lock()
_META_CACHE_MAX = 256

def sniff_encoding(raw):
    """识别 BOM，返回 ``(编码名, BOM 字节)``；没有 BOM 时返回 ``(None, b'')``。"""
    if not isinstance(raw, (bytes, bytearray)):
        raw = bytes(raw)
    for bom, codec in _BOMS:
        if raw.startswith(bom):
            return codec, bytes(bom)
    return None, b""

def _decode(raw):
    """把字节流解成文本，按 BOM → UTF-8/GB18030 → charset_normalizer 兜底。"""
    codec, bom = sniff_encoding(raw)
    if codec:
        try:
            return raw.decode(codec), {"encoding": codec, "bom": bom}
        except UnicodeDecodeError:
            pass

    text = None
    for enc in _FALLBACK_ENCODINGS:
        try:
            text = raw.decode(enc)
            codec = enc
            break
        except UnicodeDecodeError:
            continue

    if text is None:
        guess = None
        try:
            from charset_normalizer import from_bytes      # type: ignore
            best = from_bytes(raw).best()
            if best is not None:
                guess = str(best)
                text = str(best)
                codec = best.encoding or "utf-8"
        except Exception:
            guess = None
        if guess is None:
            text = raw.decode("latin-1")
            codec = "latin-1"

    if "\x00" in text[:4096]: # type: ignore
        for enc, b in (("utf-16-le", codecs.BOM_UTF16_LE), ("utf-16-be", codecs.BOM_UTF16_BE)):
            try:
                cand = raw.decode(enc)
            except UnicodeDecodeError:
                continue
            if "\x00" not in cand[:4096]:
                return cand, {"encoding": enc, "bom": b""}

    return text, {"encoding": codec, "bom": b""}

def read_text(path):
    """读文本文件，返回 ``(文本, 元信息)``；元信息会被 :func:`_remember` 记住。"""
    with open(path, "rb") as f:
        raw = f.read()
    text, meta = _decode(raw)
    assert text is not None
    meta["newline"] = "\n" if text.endswith("\n") else ""
    meta["compact"] = "\n" not in text.strip()
    return text, meta

def _remember(path, meta):
    """记录文件的编码/BOM/换行风格，供下次写回时保持原格式。"""
    if not meta:
        return
    key = os.path.abspath(path)
    with _meta_lock:
        if len(_meta_cache) >= _META_CACHE_MAX:
            _meta_cache.pop(next(iter(_meta_cache)))
        _meta_cache[key] = dict(meta)

def last_meta(path):
    """取出之前 :func:`read_text` 记下的文件元信息；没有返回 None。"""
    with _meta_lock:
        meta = _meta_cache.get(os.path.abspath(path))
    return dict(meta) if meta else None

def read_json_meta(path, **kwargs):
    """读 JSON，同时返回文件元信息；解析失败抛 ``json.JSONDecodeError``。"""
    text, meta = read_text(path)
    data = json.loads(text.lstrip("\ufeff"), **kwargs)
    _remember(path, meta)
    return data, meta

def read_json(path, **kwargs):
    """读 JSON 文件；``**kwargs`` 透传给 ``json.loads``。"""
    data, _meta = read_json_meta(path, **kwargs)
    return data

def try_read_json(path, default=None, **kwargs):
    """读 JSON 失败时返回 ``default``，适合可选配置/缓存的容错读取。"""
    try:
        return read_json(path, **kwargs)
    except (OSError, ValueError, UnicodeDecodeError):
        return default

def write_text(path, text, meta=None, fsync=False):
    """原子写文本文件；编码/BOM 取自 ``meta``，装不下时自动降级 UTF-8。

    ``meta`` 省略时复用 :func:`last_meta` 的结果（如果有）。
    """
    if meta is None:
        meta = last_meta(path)
    meta = meta or {}
    codec = meta.get("encoding") or "utf-8"
    bom = meta.get("bom") or b""
    text = text + (meta.get("newline") or "")

    try:
        payload = bom + text.encode(codec)
    except (UnicodeEncodeError, LookupError):
        print(f"  提示: {os.path.basename(path)} 原编码 {codec} 放不下新内容, 已改用 UTF-8 写入")
        codec, bom = "utf-8", b""
        payload = text.encode(codec)

    tmp = path + ".tmp"
    try:
        with open(tmp, "wb") as f:
            f.write(payload)
            if fsync:
                f.flush()
                os.fsync(f.fileno())
        os.replace(tmp, path)
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass
        with open(path, "wb") as f:
            f.write(payload)

    _remember(path, {"encoding": codec, "bom": bom,
                     "newline": meta.get("newline", ""), "compact": meta.get("compact", False)})

def write_json(path, data, indent=4, meta=None, ensure_ascii=False, fsync=False):
    """把对象写成 JSON；默认保持原文件的缩进/紧凑风格与编码。"""
    if meta is None:
        meta = last_meta(path) or {}
    if indent is None or meta.get("compact"):
        text = json.dumps(data, ensure_ascii=ensure_ascii, separators=(",", ":"))
    else:
        text = json.dumps(data, ensure_ascii=ensure_ascii, indent=indent)
    write_text(path, text, meta, fsync=fsync)
