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


_migrate_lock = threading.Lock()
_migrate_started = False


def shrink_cached_icons(cache_dir=DEFAULT_ICON_CACHE_DIR, log=None):
    """把缓存目录里的大图就地缩略，返回 (处理数, 节省字节)。

    早期版本把上传时的原图（1 MB 级）直接当缓存存下来，前端却只显示几十像素，
    既占磁盘又让每次 base64 传输膨胀几十倍。这里做一次性的瘦身迁移：只碰
    体积超过 96 KB 的文件，`icon_fetch.shrink_file` 内部有幂等判断，重复调用
    不会反复处理。
    """
    if not os.path.isdir(cache_dir):
        return (0, 0)
    from functions.base.common import icon_fetch

    count = 0
    saved = 0
    try:
        names = os.listdir(cache_dir)
    except OSError:
        return (0, 0)
    for filename in names:
        if not filename.endswith("_icon.png"):
            continue
        path = os.path.join(cache_dir, filename)
        try:
            before = os.path.getsize(path)
        except OSError:
            continue
        if before <= 96 * 1024:
            continue
        try:
            changed = icon_fetch.shrink_file(path)
        except Exception:  # noqa: BLE001 - 单个文件坏掉不影响其它图标
            continue
        if not changed:
            continue
        try:
            after = os.path.getsize(path)
        except OSError:
            continue
        count += 1
        saved += max(0, before - after)
    if count and log:
        log("图标缓存瘦身: 处理 %d 个, 节省 %.1f MB" % (count, saved / 1024.0 / 1024.0))
    return (count, saved)


def ensure_icons_shrunk(cache_dir=DEFAULT_ICON_CACHE_DIR, log=None):
    """在后台线程里跑一次 `shrink_cached_icons`（同一进程只跑一次）。"""
    global _migrate_started
    with _migrate_lock:
        if _migrate_started:
            return False
        _migrate_started = True

    def _work():
        try:
            shrink_cached_icons(cache_dir, log=log)
        except Exception as exc:  # noqa: BLE001 - 迁移失败不该影响启动
            print("[icon_cache] 图标瘦身失败: %s" % exc)

    threading.Thread(target=_work, daemon=True).start()
    return True
