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

_CACHE_SUFFIX = "_icon.png"


def _safe_name(item_name):
    """item 名 → 文件名里可用的部分 (去掉 Windows 非法字符)。"""
    name = str(item_name or "unknown").strip() or "unknown"
    for ch in '\\/:*?"<>|':
        name = name.replace(ch, "_")
    return name.replace(" ", "_")


def _name_of_file(filename):
    """缓存文件名 → 它属于哪个 item (``<名字>_<url摘要>_icon.png``)。"""
    base = os.path.basename(filename)
    if base.endswith(_CACHE_SUFFIX):
        base = base[:-len(_CACHE_SUFFIX)]
    return base.rsplit("_", 1)[0] if "_" in base else base


def _files_for_name(item_name, cache_dir=DEFAULT_ICON_CACHE_DIR):
    """同一个 item 名下的所有缓存文件 (可能有多份历史遗留)。"""
    prefix = _safe_name(item_name) + "_"
    out = []
    try:
        for filename in os.listdir(cache_dir):
            if filename.endswith(_CACHE_SUFFIX) and filename.startswith(prefix):
                out.append(os.path.join(cache_dir, filename))
    except OSError:
        pass
    return out


def _file_md5(path):
    try:
        with open(path, "rb") as fh:
            return hashlib.md5(fh.read()).hexdigest()
    except OSError:
        return ""


def icon_cache_path(icon_url, item_name, cache_dir=DEFAULT_ICON_CACHE_DIR):
    if not icon_url:
        return ""
    digest = hashlib.md5(icon_url.encode("utf-8")).hexdigest()[:12]
    name = _safe_name(item_name)
    return os.path.join(cache_dir, "%s_%s_icon.png" % (name, digest))

def looks_like_image(data):
    if not data:
        return False
    head = bytes(data[:64])
    return any(head.startswith(magic) for magic in _IMAGE_MAGIC)

def find_cached_icon(icon_url, item_name, cache_dir=DEFAULT_ICON_CACHE_DIR):
    """找出已缓存的图标文件路径；没有缓存时返回空字符串。

    查找顺序: ①``<名字>_<url摘要>_icon.png`` 精确命中; ②按 ``_<url摘要>`` 后缀
    扫一遍 (云端条目改名后仍能命中同一张图); ③按 item 名兜底取最新的一份。

    第 ③ 步是关键: 云端每次下发的 ``icon_url`` 常带签名/换了解析域名,
    url 一变摘要就变, 只按摘要找等于每个 url 都重新下载一份新文件 ——
    缓存目录里会攒出一堆同一张图的副本。
    """
    if not icon_url:
        return ""
    exact = icon_cache_path(icon_url, item_name, cache_dir)
    if exact and os.path.exists(exact):
        return exact
    digest = hashlib.md5(icon_url.encode("utf-8")).hexdigest()[:12]
    suffix = "_%s_icon.png" % digest
    same_url = []
    try:
        for filename in os.listdir(cache_dir):
            if filename.endswith(suffix):
                same_url.append(os.path.join(cache_dir, filename))
    except OSError:
        pass
    if same_url:
        return max(same_url, key=lambda p: _mtime(p))
    if _safe_name(item_name) != "unknown":
        same_name = _files_for_name(item_name, cache_dir)
        if same_name:
            return max(same_name, key=lambda p: _mtime(p))
    return ""


def _mtime(path):
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


def save_icon(data, icon_url, item_name, cache_dir=DEFAULT_ICON_CACHE_DIR,
              max_edge=None):
    """落盘一张图标，**同一个 item 只保留一份**；返回最终路径（失败返回 ""）。

    写之前先把数据缩略成要保存的字节，再和该 item 已有的缓存比 md5：
    · 内容相同 → 直接复用那份文件（必要时改名为当前 url 对应的规范名）；
    · 内容不同 → 写新文件，然后删掉这个 item 的其它旧文件。
    这样即使 ``icon_url`` 每次都不一样，磁盘上也不会越攒越多。
    """
    if not data:
        return ""
    from functions.base.common import icon_fetch

    target = icon_cache_path(icon_url, item_name, cache_dir)
    if not target:
        return ""
    try:
        payload = icon_fetch.shrink_image(
            data, max_edge=max_edge if max_edge is not None else icon_fetch.MAX_EDGE)
    except Exception:  # noqa: BLE001 - 缩略失败就存原图
        payload = data
    digest = hashlib.md5(payload).hexdigest()

    others = _files_for_name(item_name, cache_dir)
    for old in others:
        if _file_md5(old) != digest:
            continue
        if old != target:
            try:
                os.replace(old, target)
            except OSError:
                return old
        _remove_files(others, keep=target)
        return target

    # 另一个条目已经存过一模一样的图: 建硬链接共享同一份数据, 磁盘只占一次
    twin = _find_same_content(cache_dir, digest, exclude=target)
    if twin:
        try:
            if os.path.exists(target):
                os.remove(target)
            os.link(twin, target)
            _remove_files(others, keep=target)
            return target
        except OSError:
            pass

    tmp = "%s.%d.%d.tmp" % (target, os.getpid(), threading.get_ident())
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
    _remove_files(others, keep=target)
    return target


def _remove_files(paths, keep=""):
    for path in paths:
        if path == keep:
            continue
        try:
            os.remove(path)
        except OSError:
            pass


def _find_same_content(cache_dir, digest, exclude=""):
    """缓存里是否已有内容完全相同的图标 (不同条目共用同一张图)。"""
    exclude = os.path.abspath(exclude) if exclude else ""
    try:
        names = os.listdir(cache_dir)
    except OSError:
        return ""
    for filename in names:
        if not filename.endswith(_CACHE_SUFFIX):
            continue
        path = os.path.join(cache_dir, filename)
        if exclude and os.path.abspath(path) == exclude:
            continue
        if _file_md5(path) == digest:
            return path
    return ""

def icon_failed_recently(icon_url):
    """_失败兜底策略，这个url没有接受到的缓存_

    Args:
        icon_url (_type_): _description_

    Returns:
        _type_: _成功？_
    """
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

def dedupe_icons(cache_dir=DEFAULT_ICON_CACHE_DIR, log=None):
    """同一个 item 只留最新的一份图标，返回 (删除数, 保留数)。

    历史版本按 url 摘要命名，云端每换一次 ``icon_url`` 就多一份文件，
    清理时保留最近写入的那份即可（内容以最新一次下载为准）。
    """
    try:
        names = [f for f in os.listdir(cache_dir) if f.endswith(_CACHE_SUFFIX)]
    except OSError:
        return (0, 0)
    groups = {}
    for filename in names:
        groups.setdefault(_name_of_file(filename), []).append(filename)
    removed = 0
    kept = 0
    for group in groups.values():
        kept += 1
        if len(group) < 2:
            continue
        group.sort(key=lambda f: _mtime(os.path.join(cache_dir, f)), reverse=True)
        for filename in group[1:]:
            try:
                os.remove(os.path.join(cache_dir, filename))
                removed += 1
            except OSError:
                pass
    if removed and log:
        log("图标缓存去重: 删除 %d 个重复文件, 保留 %d 个图标" % (removed, kept))
    return (removed, kept)


def dedupe_content(cache_dir=DEFAULT_ICON_CACHE_DIR, log=None):
    """不同条目共用同一张图时，把内容相同的文件改成硬链接，磁盘只存一份。

    只替换文件本身，文件名不动 —— 每个条目仍能按自己的名字找到图标。
    返回 (改成硬链接的数量, 不同内容的数量)。
    """
    try:
        names = [f for f in os.listdir(cache_dir) if f.endswith(_CACHE_SUFFIX)]
    except OSError:
        return (0, 0)
    by_digest = {}
    linked = 0
    for filename in names:
        path = os.path.join(cache_dir, filename)
        digest = _file_md5(path)
        if not digest:
            continue
        src = by_digest.get(digest)
        if not src:
            by_digest[digest] = path
            continue
        tmp = path + ".lnk"
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
            os.link(src, tmp)
            os.replace(tmp, path)
            linked += 1
        except OSError:
            try:
                os.remove(tmp)
            except OSError:
                pass
    if linked and log:
        log("图标缓存合并: %d 个文件改为硬链接, 共 %d 张不同的图" % (linked, len(by_digest)))
    return (linked, len(by_digest))


def prune_icon_cache(cloud_lists, cache_dir=DEFAULT_ICON_CACHE_DIR, log=None):
    """清掉云端列表里已经不存在的条目图标。

    只比 item 名，不比完整文件名 —— ``icon_url`` 每次下发可能都不一样，
    按 url 算出来的文件名会一天一个，那样每天都会把还在用的图标删掉、
    再重新下一遍。
    """
    if not os.path.isdir(cache_dir):
        return (0, 0)
    keep = set()
    for item in iter_cloud_items(cloud_lists):
        if item.get("icon_url"):
            keep.add(_safe_name(item.get("name")))
    if not keep:
        return (0, 0)

    removed = 0
    for filename in os.listdir(cache_dir):
        if not filename.endswith(_CACHE_SUFFIX) or _name_of_file(filename) in keep:
            continue
        try:
            os.remove(os.path.join(cache_dir, filename))
            removed += 1
        except OSError:
            pass
    if removed and log:
        log("图标缓存清理: 删除 %d 个已不用的图标, 保留 %d 个条目" % (removed, len(keep)))
    return (removed, len(keep))


_migrate_lock = threading.Lock()
_migrate_started = False


def shrink_cached_icons(cache_dir=DEFAULT_ICON_CACHE_DIR, log=None):
    """把缓存目录里的大图就地缩略，返回 (处理数, 节省字节)。

    早期版本把上传时的原图（1 MB 级）直接当缓存存下来，前端却只显示几十像素，
    既占磁盘又让每次 base64 传输膨胀几十倍。这里做一次性的瘦身迁移：以
    ``force=True`` 调 :func:`functions.base.common.icon_fetch.shrink_file`，
    连「体积不到 96 KB 但像素尺寸仍超标」（例如 536px / 80 KB）的历史文件也
    一并缩到 ``MAX_EDGE``；``shrink_file`` 内部有幂等判断，已合格的文件不会被
    反复改写。
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
        try:
            changed = icon_fetch.shrink_file(path, force=True)
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
    """在后台线程里跑一次缓存维护（去重 + 瘦身，同一进程只跑一次）。"""
    global _migrate_started
    with _migrate_lock:
        if _migrate_started:
            return False
        _migrate_started = True

    def _work():
        try:
            dedupe_icons(cache_dir, log=log)
        except Exception as exc:  # noqa: BLE001 - 清理失败不该影响启动
            print("[icon_cache] 图标去重失败: %s" % exc)
        try:
            dedupe_content(cache_dir, log=log)
        except Exception as exc:  # noqa: BLE001 - 合并失败不该影响启动
            print("[icon_cache] 图标合并失败: %s" % exc)
        try:
            shrink_cached_icons(cache_dir, log=log)
        except Exception as exc:  # noqa: BLE001 - 迁移失败不该影响启动
            print("[icon_cache] 图标瘦身失败: %s" % exc)

    threading.Thread(target=_work, daemon=True).start()
    return True
