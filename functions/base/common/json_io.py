"""JSON 读写兼容层 —— 容忍"不干净的 UTF-8"

游戏自带的 Lang JSON、汉化包/mod 作者给出的 JSON 经常不是标准 UTF-8：

* **UTF-8 BOM**（记事本/部分编辑器另存为 UTF-8 会加 BOM）：
  用 ``encoding='utf-8'`` 读会在第 1 个字符就炸 ——
  ``Unexpected UTF-8 BOM (decode using utf-8-sig): line 1 column 1 (char 0)``；
* **UTF-16 LE/BE**（带 BOM，或没 BOM 但全是 NUL 间隔）；
* **GBK / GB18030**（老工具、中文 Windows 默认编码）。

这里统一做「按字节嗅探 + 解码回退」，并且**写回时默认沿用该文件原本的编码与 BOM** ——
否则把游戏原本 GBK 的文本改写成 UTF-8，游戏可能整篇读成乱码。

用法（保持旧签名，老调用方无需改动）::

    from functions.base.common.json_io import read_json, write_json

    data = read_json(path)            # 容忍 BOM / UTF-16 / GBK
    write_json(path, data)            # 自动沿用读它时探测到的编码/BOM
    write_json(path, data, indent=2)  # 新建文件时按 UTF-8 无 BOM 写

需要显式控制时用 ``read_json_meta`` / ``write_json(..., meta=meta)``。
只依赖标准库；``charset_normalizer`` 存在时作为最后兜底（可选）。
"""

import codecs
import json
import os
import threading

__all__ = [
    "read_text", "read_json", "read_json_meta", "try_read_json",
    "write_text", "write_json", "sniff_encoding", "last_meta",
]

# BOM 前缀必须"长的先测": UTF-32LE 的前 2 字节与 UTF-16LE 相同
_BOMS = (
    (codecs.BOM_UTF32_LE, "utf-32-le"),
    (codecs.BOM_UTF32_BE, "utf-32-be"),
    (codecs.BOM_UTF8, "utf-8"),
    (codecs.BOM_UTF16_LE, "utf-16-le"),
    (codecs.BOM_UTF16_BE, "utf-16-be"),
)

# 无 BOM 时的解码回退顺序（utf-8 严格 → gb18030 覆盖 GBK/GB2312 中文）
_FALLBACK_ENCODINGS = ("utf-8", "gb18030")

_meta_cache = {}                     # path -> meta（读过的文件，写回时沿用）
_meta_lock = threading.Lock()
_META_CACHE_MAX = 256


def sniff_encoding(raw):
    """按字节嗅探编码，返回 (codec, bom) —— codec 不含 BOM，bom 为要写回的字节"""
    if not isinstance(raw, (bytes, bytearray)):
        raw = bytes(raw)
    for bom, codec in _BOMS:
        if raw.startswith(bom):
            return codec, bytes(bom)
    return None, b""


def _decode(raw):
    """把字节解成文本，返回 (text, meta)；meta = {encoding, bom}"""
    codec, bom = sniff_encoding(raw)
    if codec:
        try:
            return raw.decode(codec), {"encoding": codec, "bom": bom}
        except UnicodeDecodeError:
            pass                                  # BOM 判断失误，继续走回退

    text = None
    for enc in _FALLBACK_ENCODINGS:
        try:
            text = raw.decode(enc)
            codec = enc
            break
        except UnicodeDecodeError:
            continue

    if text is None:
        # 标准回退都失败：交给 charset_normalizer 猜（可选依赖），再不行按 latin-1 保字节不丢
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

    # 无 BOM 的 UTF-16：上面的回退"解码成功"了但会掺进大量 NUL，按 UTF-16 重解一次
    if "\x00" in text[:4096]:
        for enc, b in (("utf-16-le", codecs.BOM_UTF16_LE), ("utf-16-be", codecs.BOM_UTF16_BE)):
            try:
                cand = raw.decode(enc)
            except UnicodeDecodeError:
                continue
            if "\x00" not in cand[:4096]:
                return cand, {"encoding": enc, "bom": b""}   # 原本就没有 BOM 就不要再加

    return text, {"encoding": codec, "bom": b""}


def read_text(path):
    """读文本，返回 (text, meta)；文件不存在等异常照旧抛出"""
    with open(path, "rb") as f:
        raw = f.read()
    text, meta = _decode(raw)
    meta["newline"] = "\n" if text.endswith("\n") else ""    # 保留原文件的行尾习惯
    meta["compact"] = "\n" not in text.strip()               # 压缩成一行的文件不要撑大
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
    """返回上次读该文件时探测到的编码信息（没读过返回 None）"""
    with _meta_lock:
        meta = _meta_cache.get(os.path.abspath(path))
    return dict(meta) if meta else None


def read_json_meta(path, **kwargs):
    """读 JSON，返回 (data, meta)；meta 可直接传给 write_json 保编码写回"""
    text, meta = read_text(path)
    data = json.loads(text.lstrip("\ufeff"), **kwargs)     # 双保险: 文本里残留的 BOM 也清掉
    _remember(path, meta)
    return data, meta


def read_json(path, **kwargs):
    """读 JSON（容忍 BOM / UTF-16 / GBK），返回解析结果"""
    data, _meta = read_json_meta(path, **kwargs)
    return data


def try_read_json(path, default=None, **kwargs):
    """读 JSON，任何失败都返回 default（用于"文件缺失/损坏就跳过"的场景）"""
    try:
        return read_json(path, **kwargs)
    except (OSError, ValueError, UnicodeDecodeError):
        return default


def write_text(path, text, meta=None, fsync=False):
    """写文本

    meta 为空时沿用「上次读这个文件」探测到的编码与 BOM（read_json 会自动记住），
    都没有则按 UTF-8 无 BOM 写。编码放不下时（例如往 GBK 文件里塞 emoji）
    自动退回 UTF-8 并打印提示，保证内容不丢。
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

    # 原子写: 先写临时文件再替换, 避免游戏/加载器读到半个文件
    tmp = path + ".tmp"
    try:
        with open(tmp, "wb") as f:
            f.write(payload)
            if fsync:                      # 断电安全场景(如 settings.json)要求刷盘后再替换
                f.flush()
                os.fsync(f.fileno())
        os.replace(tmp, path)
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass
        with open(path, "wb") as f:                  # 只读目录等场景退化为直接覆盖
            f.write(payload)

    _remember(path, {"encoding": codec, "bom": bom,
                     "newline": meta.get("newline", ""), "compact": meta.get("compact", False)})


def write_json(path, data, indent=4, meta=None, ensure_ascii=False, fsync=False):
    """写 JSON（默认沿用原文件编码/BOM；meta 可显式指定；indent=None 表示压缩成一行）"""
    if meta is None:
        meta = last_meta(path) or {}
    if indent is None or meta.get("compact"):
        text = json.dumps(data, ensure_ascii=ensure_ascii, separators=(",", ":"))
    else:
        text = json.dumps(data, ensure_ascii=ensure_ascii, indent=indent)
    write_text(path, text, meta, fsync=fsync)
