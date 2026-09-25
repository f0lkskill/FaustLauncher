"""图标缓存: 路径生成、内容校验、失败短暂封堵、过期清理。

下载中心与网页端共用 `cache/icons`。文件名规则:
    <条目名>_<icon_url 的 md5 前 12 位>_icon.png
icon_url 一变更 (换图标 / 重新上传) 文件名就不同, 旧图标的缓存会一直留着,
所以需要按当前云端列表主动清理。
"""
import hashlib
import os
import threading
import time

DEFAULT_ICON_CACHE_DIR = "cache/icons"

# 下载失败后这段时间内不再重试同一个图标 (页面反复重绘时不必反复请求)
NEGATIVE_TTL = 60.0
_NEGATIVE_MAX = 512

_IMAGE_MAGIC = (
    b"\x89PNG\r\n\x1a\n",   # PNG
    b"\xff\xd8\xff",         # JPEG
    b"GIF87a", b"GIF89a",    # GIF
    b"RIFF",                 # WEBP (RIFF....WEBP)
    b"BM",                   # BMP
    b"<svg", b"<?xml",       # SVG
)

_failed_lock = threading.Lock()
_failed_until = {}


def icon_cache_path(icon_url, item_name, cache_dir=DEFAULT_ICON_CACHE_DIR):
    """图标缓存路径; 文件名为 URL 哈希 + 名称, URL 变更后自动失效"""
    if not icon_url:
        return ""
    digest = hashlib.md5(icon_url.encode("utf-8")).hexdigest()[:12]
    name = str(item_name or "unknown").replace(" ", "_")
    return os.path.join(cache_dir, "%s_%s_icon.png" % (name, digest))


def looks_like_image(data):
    """内容像不像图片 (解析失败回退到第三方解析服务时会拿到 JSON/HTML 错误页)"""
    if not data:
        return False
    head = bytes(data[:64])
    return any(head.startswith(magic) for magic in _IMAGE_MAGIC)


def find_cached_icon(icon_url, item_name, cache_dir=DEFAULT_ICON_CACHE_DIR):
    """找已经缓存好的图标: 先按标准命名, 找不到再只按 icon_url 的哈希兜底

    文件名里的条目名可能因调用方不同而不同 (云端显示名 / 本地目录名 / 改名后的名字),
    甚至同一条目在不同页面用不同名字 —— 只按 icon_url 哈希兜底, 就不会出现
    "缓存里明明有却当成没有, 又去下载一遍" 的情况。
    """
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
    """该图标刚失败过吗 (期间不必再试)"""
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
    """记一次失败, 短时间内不再重试"""
    if not icon_url:
        return
    with _failed_lock:
        if len(_failed_until) >= _NEGATIVE_MAX:
            _failed_until.clear()
        _failed_until[icon_url] = time.time() + NEGATIVE_TTL


def note_icon_success(icon_url):
    """成功一次就清掉封堵"""
    if not icon_url:
        return
    with _failed_lock:
        _failed_until.pop(icon_url, None)


def iter_cloud_items(cloud_lists):
    """把云端数据摊平成条目 dict

    支持 [总信息, 页1, 页2...] 或 [该类列表, 另一类列表] 两种套法。
    """
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
    """清理云端列表里已经不存在的图标缓存, 返回 (删除数, 保留数)

    只删自己生成的 `<名字>_<哈希>_icon.png`, 其它文件不动;
    云端列表为空/异常时直接返回, 避免误删整套缓存。
    """
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
