"""图标缓存。

缓存策略只有一条：

    一个资源只保留一份图标，文件名 = <资源名>__<URL哈希>_icon.png

- URL 未变化：文件名相同，直接命中缓存。
- URL 变化：文件名变化，find 不会命中，调用方重新下载；
  save 写入新文件后删除该资源旧的图标文件。
- 旧版 <资源名>_<12位md5>_icon.png 只在 URL 精确匹配时迁移一次。
- 无哈希文件名、旧版 .url.json 等无法识别的缓存，在去重/清理时删除。

这里不使用 sidecar JSON，也不按资源名猜测“最新文件”。
"""

import hashlib
import os
import re
import threading
import time

DEFAULT_ICON_CACHE_DIR = "cache/icons"

# 失败退避：同一个坏 URL 在窗口期内不重复请求。
NEGATIVE_TTL = 60.0
_NEGATIVE_MAX = 512

# 用于快速判断下载内容是不是图片，避免把错误页写进缓存。
_IMAGE_MAGIC = (
    b"\x89PNG\r\n\x1a\n",
    b"\xff\xd8\xff",
    b"GIF87a",
    b"GIF89a",
    b"RIFF",
    b"BM",
    b"<svg",
    b"<?xml",
)

_failed_lock = threading.Lock()
_failed_until = {}

# 新文件名格式：资源名 + 双下划线 + 24 位 URL SHA256。
_CACHE_SUFFIX = "_icon.png"
_URL_HEX = 24
_NEW_RE = re.compile(
    r"^(.*)__([0-9a-f]{%d})_icon\.png$" % _URL_HEX,
    re.IGNORECASE,
)

# 旧版文件名格式：资源名 + 单下划线 + 12 位 URL MD5。
_LEGACY_RE = re.compile(
    r"^(.*)_([0-9a-f]{12})_icon\.png$",
    re.IGNORECASE,
)

# save_icon 写文件时串行化，避免同一资源被两个线程同时覆盖。
_save_lock = threading.Lock()


def _safe_name(item_name):
    """把资源名转成 Windows 可用的文件名。"""
    name = str(item_name or "unknown").strip() or "unknown"
    for ch in '\\/:*?"<>|':
        name = name.replace(ch, "_")
    return name.replace(" ", "_")


def _url_digest(icon_url):
    """URL 的稳定摘要，直接写进文件名。"""
    raw = str(icon_url).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:_URL_HEX]


def _legacy_digest(icon_url):
    """旧版文件名使用的前 12 位 MD5，仅用于一次迁移。"""
    raw = str(icon_url).encode("utf-8")
    return hashlib.md5(raw).hexdigest()[:12]


def icon_cache_path(icon_url, item_name=None, cache_dir=DEFAULT_ICON_CACHE_DIR):
    """返回资源当前 URL 对应的缓存路径；URL/资源名为空时返回空串。"""
    url = str(icon_url or "").strip()
    name = str(item_name or "").strip()
    if not url or not name:
        return ""
    filename = "%s__%s_icon.png" % (_safe_name(name), _url_digest(url))
    return os.path.join(cache_dir, filename)


def _legacy_path(icon_url, item_name, cache_dir):
    """旧版精确缓存路径：<资源名>_<12位MD5>_icon.png。"""
    filename = "%s_%s_icon.png" % (
        _safe_name(item_name),
        _legacy_digest(icon_url),
    )
    return os.path.join(cache_dir, filename)


def _resource_of_file(filename):
    """从缓存文件名还原资源名。

    新格式取双下划线前的部分，旧格式取 12 位 MD5 前的部分。
    无法识别的文件返回空串，由清理逻辑删除。
    """
    if not filename.endswith(_CACHE_SUFFIX):
        return ""

    match = _NEW_RE.match(filename)
    if match:
        return match.group(1)

    match = _LEGACY_RE.match(filename)
    if match:
        return match.group(1)

    return ""


def _files_for_resource(item_name, cache_dir):
    """列出某个资源名下的所有缓存文件（新格式和旧格式）。"""
    name = _safe_name(item_name)
    result = []
    try:
        filenames = os.listdir(cache_dir)
    except OSError:
        return result

    for filename in filenames:
        if _resource_of_file(filename) == name:
            result.append(os.path.join(cache_dir, filename))
    return result


def _file_md5(path):
    """读取文件内容摘要；用于跨资源内容合并，不参与 URL 判断。"""
    try:
        with open(path, "rb") as fh:
            return hashlib.md5(fh.read()).hexdigest()
    except OSError:
        return ""


def _mtime(path):
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


def looks_like_image(data):
    """按文件头快速判断图片，避免缓存错误页。"""
    if not data:
        return False
    head = bytes(data[:64])
    return any(head.startswith(magic) for magic in _IMAGE_MAGIC)


def find_cached_icon(icon_url, item_name=None, cache_dir=DEFAULT_ICON_CACHE_DIR):
    """查找当前 URL 的缓存；URL 变了就返回空串。

    不再按资源名取“最新文件”，也不扫描 URL 后缀。文件名里已经包含
    当前 URL 的哈希，所以命中/未命中是完全确定的。
    """
    url = str(icon_url or "").strip()
    path = icon_cache_path(url, item_name, cache_dir)
    if not url or not path:
        return ""

    if os.path.isfile(path):
        return path

    # 旧版文件名只在 URL 摘要精确匹配时迁移，避免升级后全部重新下载。
    legacy = _legacy_path(url, item_name, cache_dir)
    if not os.path.isfile(legacy):
        return ""

    try:
        os.replace(legacy, path)
    except OSError:
        # 文件被占用时仍可安全使用：旧文件名里的摘要就是当前 URL。
        return legacy

    # 迁移后清理同资源的其它旧文件，保证“一个资源一份”。
    for old in _files_for_resource(item_name, cache_dir):
        if os.path.abspath(old) == os.path.abspath(path):
            continue
        try:
            os.remove(old)
        except OSError:
            pass

    return path


def save_icon(data, icon_url, item_name=None, cache_dir=DEFAULT_ICON_CACHE_DIR,
              max_edge=None):
    """按当前 URL 保存资源图标，并删除该资源的其它旧文件。"""
    if not data:
        return ""

    from functions.base.common import icon_fetch

    target = icon_cache_path(icon_url, item_name, cache_dir)
    if not target:
        return ""

    try:
        payload = icon_fetch.shrink_image(
            data,
            max_edge=max_edge if max_edge is not None else icon_fetch.MAX_EDGE,
        )
    except Exception:  # noqa: BLE001 - 缩略失败就保存原图
        payload = data

    tmp = "%s.%d.%d.tmp" % (
        target,
        os.getpid(),
        threading.get_ident(),
    )

    with _save_lock:
        try:
            os.makedirs(cache_dir, exist_ok=True)
            with open(tmp, "wb") as fh:
                fh.write(payload)
            os.replace(tmp, target)
        except OSError:
            try:
                os.remove(tmp)
            except OSError:
                pass
            return ""

        # URL 变化后，旧 URL 的文件也在这里被删除。
        for old in _files_for_resource(item_name, cache_dir):
            if os.path.abspath(old) == os.path.abspath(target):
                continue
            try:
                os.remove(old)
            except OSError:
                pass

    return target


def icon_failed_recently(icon_url):
    """该 URL 是否处于失败退避窗口。"""
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
    """记录一次失败，短期内不再请求。"""
    if not icon_url:
        return

    with _failed_lock:
        if len(_failed_until) >= _NEGATIVE_MAX:
            _failed_until.clear()
        _failed_until[icon_url] = time.time() + NEGATIVE_TTL


def note_icon_success(icon_url):
    """成功后清除失败记录。"""
    if not icon_url:
        return

    with _failed_lock:
        _failed_until.pop(icon_url, None)


def iter_cloud_items(cloud_lists):
    """遍历云端列表里的条目，兼容 dict / 分页 list 两种结构。"""
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


def dedupe_icons(cache_dir=DEFAULT_ICON_CACHE_DIR, log=None):
    """同一资源只留最新一份，并删除无法识别的缓存文件。

    - 旧版 .url.json：删除。
    - 有 _icon.png 但没有资源名/URL 哈希的文件：删除。
    - 同一资源多个 URL 哈希：保留修改时间最新的一个。
    """
    try:
        all_names = os.listdir(cache_dir)
    except OSError:
        return (0, 0)

    removed = 0
    icon_names = []

    for filename in all_names:
        full_path = os.path.join(cache_dir, filename)

        # 早期尝试过 sidecar JSON，现已废弃，直接清理。
        if filename.endswith(".url.json"):
            try:
                os.remove(full_path)
                removed += 1
            except OSError:
                pass
            continue

        if filename.endswith(_CACHE_SUFFIX):
            icon_names.append(filename)

    groups = {}
    for filename in icon_names:
        resource = _resource_of_file(filename)
        if not resource:
            try:
                os.remove(os.path.join(cache_dir, filename))
                removed += 1
            except OSError:
                pass
            continue

        groups.setdefault(resource, []).append(filename)

    for group in groups.values():
        # 新格式文件名带 URL 哈希，优先保留；只有全是旧格式时才按时间取最新。
        new_format = [name for name in group if _NEW_RE.match(name)]
        candidates = new_format or group
        keep = max(
            candidates,
            key=lambda name: _mtime(os.path.join(cache_dir, name)),
        )
        for filename in group:
            if filename == keep:
                continue
            try:
                os.remove(os.path.join(cache_dir, filename))
                removed += 1
            except OSError:
                pass

    if removed and log:
        log(
            "图标缓存去重: 删除 %d 个重复/无法识别的文件, 保留 %d 个资源"
            % (removed, len(groups))
        )
    return (removed, len(groups))


def dedupe_content(cache_dir=DEFAULT_ICON_CACHE_DIR, log=None):
    """不同资源使用同一张图时改为硬链接，磁盘只保留一份内容。"""
    try:
        names = [
            name for name in os.listdir(cache_dir)
            if name.endswith(_CACHE_SUFFIX)
        ]
    except OSError:
        return (0, 0)

    by_digest = {}
    linked = 0

    for filename in names:
        path = os.path.join(cache_dir, filename)
        digest = _file_md5(path)
        if not digest:
            continue

        source = by_digest.get(digest)
        if not source:
            by_digest[digest] = path
            continue

        tmp = path + ".lnk"
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
            os.link(source, tmp)
            os.replace(tmp, path)
            linked += 1
        except OSError:
            try:
                os.remove(tmp)
            except OSError:
                pass

    if linked and log:
        log(
            "图标缓存合并: %d 个文件改为硬链接, 共 %d 张不同的图"
            % (linked, len(by_digest))
        )
    return (linked, len(by_digest))


def prune_icon_cache(cloud_lists, cache_dir=DEFAULT_ICON_CACHE_DIR, log=None):
    """只保留云端当前“资源名 + URL”精确对应的图标。

    URL 变化后旧文件名不再出现在 keep 集合里，会被一起删除；
    无哈希文件名、旧版 sidecar JSON 也在这里清掉。
    """
    if not os.path.isdir(cache_dir):
        return (0, 0)

    keep = set()
    for item in iter_cloud_items(cloud_lists):
        name = item.get("name")
        url = item.get("icon_url")
        if not name or not url:
            continue

        keep.add(os.path.basename(icon_cache_path(url, name, cache_dir)))
        # 保留旧版精确文件，等 find_cached_icon 访问时迁移。
        keep.add(os.path.basename(_legacy_path(url, name, cache_dir)))

    if not keep:
        return (0, 0)

    removed = 0
    for filename in os.listdir(cache_dir):
        if filename in keep:
            continue

        # 只处理图标和旧版 sidecar，不碰缓存目录里的其它文件。
        if not filename.endswith(_CACHE_SUFFIX) and not filename.endswith(".url.json"):
            continue

        try:
            os.remove(os.path.join(cache_dir, filename))
            removed += 1
        except OSError:
            pass

    if removed and log:
        log(
            "图标缓存清理: 删除 %d 个已失效/无法识别的文件, 保留 %d 个"
            % (removed, len(keep))
        )
    return (removed, len(keep))


_migrate_lock = threading.Lock()
_migrate_started = False


def shrink_cached_icons(cache_dir=DEFAULT_ICON_CACHE_DIR, log=None):
    """把历史大图就地缩略；已经合格的文件不会被反复改写。"""
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
        if not filename.endswith(_CACHE_SUFFIX):
            continue

        path = os.path.join(cache_dir, filename)
        try:
            before = os.path.getsize(path)
        except OSError:
            continue

        try:
            changed = icon_fetch.shrink_file(path, force=True)
        except Exception:  # noqa: BLE001 - 单个坏文件不影响其它图标
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
        log(
            "图标缓存瘦身: 处理 %d 个, 节省 %.1f MB"
            % (count, saved / 1024.0 / 1024.0)
        )
    return (count, saved)


def ensure_icons_shrunk(cache_dir=DEFAULT_ICON_CACHE_DIR, log=None):
    """后台执行一次缓存维护：去重、内容合并、瘦身。"""
    global _migrate_started

    with _migrate_lock:
        if _migrate_started:
            return False
        _migrate_started = True

    def work():
        try:
            dedupe_icons(cache_dir, log=log)
        except Exception as exc:  # noqa: BLE001 - 清理失败不影响启动
            print("[icon_cache] 图标去重失败: %s" % exc)

        try:
            dedupe_content(cache_dir, log=log)
        except Exception as exc:  # noqa: BLE001 - 合并失败不影响启动
            print("[icon_cache] 图标合并失败: %s" % exc)

        try:
            shrink_cached_icons(cache_dir, log=log)
        except Exception as exc:  # noqa: BLE001 - 瘦身失败不影响启动
            print("[icon_cache] 图标瘦身失败: %s" % exc)

    threading.Thread(target=work, daemon=True).start()
    return True
