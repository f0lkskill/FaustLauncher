
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
    if not isinstance(raw, (bytes, bytearray)):
        raw = bytes(raw)
    for bom, codec in _BOMS:
        if raw.startswith(bom):
            return codec, bytes(bom)
    return None, b""

def _decode(raw):
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
    with open(path, "rb") as f:
        raw = f.read()
    text, meta = _decode(raw)
    assert text is not None
    meta["newline"] = "\n" if text.endswith("\n") else ""
    meta["compact"] = "\n" not in text.strip()
    return text, meta

def _remember(path, meta):
    if not meta:
        return
    key = os.path.abspath(path)
    with _meta_lock:
        if len(_meta_cache) >= _META_CACHE_MAX:
            _meta_cache.pop(next(iter(_meta_cache)))
        _meta_cache[key] = dict(meta)

def last_meta(path):
    with _meta_lock:
        meta = _meta_cache.get(os.path.abspath(path))
    return dict(meta) if meta else None

def read_json_meta(path, **kwargs):
    text, meta = read_text(path)
    data = json.loads(text.lstrip("\ufeff"), **kwargs)
    _remember(path, meta)
    return data, meta

def read_json(path, **kwargs):
    data, _meta = read_json_meta(path, **kwargs)
    return data

def try_read_json(path, default=None, **kwargs):
    try:
        return read_json(path, **kwargs)
    except (OSError, ValueError, UnicodeDecodeError):
        return default

def write_text(path, text, meta=None, fsync=False):
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
    if meta is None:
        meta = last_meta(path) or {}
    if indent is None or meta.get("compact"):
        text = json.dumps(data, ensure_ascii=ensure_ascii, separators=(",", ":"))
    else:
        text = json.dumps(data, ensure_ascii=ensure_ascii, indent=indent)
    write_text(path, text, meta, fsync=fsync)
