import hashlib
import os
import threading
import time

DEFAULT_ICON_CACHE_DIR = "cache/icons"

NEGATIVE_TTL = 60.0
_NEGATIVE_MAX = 512

_IMAGE_MAGIC = (
    b"\x89PNG\r\n\x1a\n",
    b"\xff\xd8\xff",
    b"GIF87a", b"GIF89a",
    b"RIFF",
    b"BM",
    b"<svg", b"<?xml",
)

_failed_lock = threading.Lock()
_failed_until = {}

def icon_cache_path(icon_url, item_name, cache_dir=DEFAULT_ICON_CACHE_DIR):
    if not icon_url:
        return ""
    digest = hashlib.md5(icon_url.encode("utf-8")).hexdigest()[:12]
    name = str(item_name or "unknown").replace(" ", "_")
    return os.path.join(cache_dir, "%s_%s_icon.png" % (name, digest))

def looks_like_image(data):
    if not data:
        return False
    head = bytes(data[:64])
    return any(head.startswith(magic) for magic in _IMAGE_MAGIC)

def find_cached_icon(icon_url, item_name, cache_dir=DEFAULT_ICON_CACHE_DIR):
    if not icon_url:
        return ""
    exact = icon_cache_path(icon_url, item_name, cache_dir)
    if exact and os.path.exists(exact):
        return exact
    digest = hashlib.md5(icon_url.encode("utf-8")).hexdigest()[:12]
    suffix = "_%s_icon.png" % digest
    try:
        for filename in os.listdir(cache_dir):
            if filename.endswith(suffix):
                return os.path.join(cache_dir, filename)
    except OSError:
        pass
    return exact

def icon_failed_recently(icon_url):
    if not icon_url:
        return False
    with _failed_lock:
        until = _failed_until.get(icon_url)
        if until and until > time.time():
            return True
        if until:
            _failed_until.pop(icon_url, None)
    return False

def note_icon_failure(icon_url):
    if not icon_url:
        return
    with _failed_lock:
        if len(_failed_until) >= _NEGATIVE_MAX:
            _failed_until.clear()
        _failed_until[icon_url] = time.time() + NEGATIVE_TTL

def note_icon_success(icon_url):
    if not icon_url:
        return
    with _failed_lock:
        _failed_until.pop(icon_url, None)

def iter_cloud_items(cloud_lists):
    for data in cloud_lists:
        if isinstance(data, dict):
            yield data
            continue
        if not isinstance(data, (list, tuple)):
            continue
        for page in data:
            if isinstance(page, dict):
                yield page
                continue
            if not isinstance(page, (list, tuple)):
                continue
            for item in page:
                if isinstance(item, dict):
                    yield item

def prune_icon_cache(cloud_lists, cache_dir=DEFAULT_ICON_CACHE_DIR, log=None):
    if not os.path.isdir(cache_dir):
        return (0, 0)
    keep = set()
    for item in iter_cloud_items(cloud_lists):
        url = item.get("icon_url")
        if url:
            keep.add(os.path.basename(icon_cache_path(url, item.get("name"))))
    if not keep:
        return (0, 0)

    removed = 0
    for filename in os.listdir(cache_dir):
        if not filename.endswith("_icon.png") or filename in keep:
            continue
        try:
            os.remove(os.path.join(cache_dir, filename))
            removed += 1
        except OSError:
            pass
    if removed and log:
        log("图标缓存清理: 删除 %d 个已不用的图标, 保留 %d 个" % (removed, len(keep)))
    return (removed, len(keep))
