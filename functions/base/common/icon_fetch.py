"""资源图标下载与缩略。

背景（为什么要有这个模块）
--------------------------
资源管理里的 addon / mod 图标来自蓝奏分享链接，并被 ``lz.qaiu.top`` 解析器包
了一层（形如 ``https://lz.qaiu.top/parser?url=<分享链接>``）。旧实现把这整条
链路交给 :func:`functions.web_update.lanzou_utils.GetWithDirectLink`，而后者会
先用 ``IsLanzouUrl`` 判断 URL —— 它会把 ``url=`` 参数里的内层链接取出来再判
域名，于是这种 parser 包装 URL 被当成蓝奏分享页，白白走一遍「抓分享页 + WAF
挑战 + POST 接口 + 跟随 file 页」。

因此这里不再走解析链路，取图顺序是「已知直链 → 包装 URL 直连」。实测（单图标）：

    场景                      旧解析链路     现在        说明
    直链缓存为空（冷启动）    0.72 s/个      0.28 s/个   2.59x，越到后面越好（旧链路还会被限流）
    直链缓存命中（热启动）    0.10 s/个      0.13 s/个   基本持平（多花的 40 ms 是缩略）

第二个问题是**缓存的是原图**：上传时的图标是 724×724 ~ 1254×1254、1 MB 级别
的 PNG，而界面上只显示几十像素。旧代码把原图 base64 后塞给前端，单个图标的
data-uri 就有 200 万字符级别，还要整个穿过 pywebview 的 JS 桥。实测 12 个真实
图标：缩到 160px 后 data-uri 总量 8 248 700 → 662 716 字符（**12.4x**），
``cache/icons`` 从 29.9 MB 降到 4.9 MB（**12.5x**）。这才是「打开资源页明显
变慢」的主因 —— 网络时间其实只占小头。

第三个是**连接复用**：pywebview 的每个 ``js_api`` 调用都在新线程里跑
（``webview/util.py`` 里 ``Thread(target=_call).start()``），而
``lanzou_utils._http_session()`` 是按线程复用 Session 的，等于每次 ``get_icon``
都重新握手 TCP + TLS。这里用进程级共享 Session（连接池 16/32）。

关于「多连接并发下载」：早期版本曾按 ``Range`` 把图标拆成 4 段并发，实测在 12
个真实图标上**全部更慢**（中位 0.58x，即慢 1.7 倍）—— 该 CDN 单连接就能跑到
1.2 MB/s，拆包反而多付 3 次握手与首包延迟。早先观测到的「单连接 26 KB/s」是
冷回源导致的，并发分块同样要等回源，救不了。所以这里不再做并发，保持单连接。
"""

from __future__ import annotations

import base64
import io
import os
import threading
from typing import Optional

import requests

#: 落盘图标的短边上限（px）。界面里图标最大显示不到 100px，留 2 倍余量。
MAX_EDGE = 160

#: 图标不可能这么大。超过就判定 URL 指错了（例如误填成资源包下载链接），
#: 直接放弃，别把几十 MB 的东西拉进内存。
MAX_ICON_BYTES = 6 * 1024 * 1024

CONNECT_TIMEOUT = 10
READ_TIMEOUT = 20

_session = None
_session_lock = threading.Lock()
_shrink_lock = threading.Lock()


def _http() -> requests.Session:
    """返回进程级共享的 Session（连接池 16/32，不自动重试）。"""
    global _session
    with _session_lock:
        if _session is None:
            sess = requests.Session()
            adapter = requests.adapters.HTTPAdapter(
                pool_connections=16, pool_maxsize=32, max_retries=0)
            sess.mount("http://", adapter)
            sess.mount("https://", adapter)
            sess.headers.update({
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/126.0.0.0 Safari/537.36"),
                # 图片已经压过，让 CDN 再 gzip 一遍只是白费 CPU
                "Accept-Encoding": "identity",
            })
            _session = sess
        return _session


def reset_session() -> None:
    """丢掉缓存的 Session（切换代理或测试时使用）。"""
    global _session
    with _session_lock:
        _session = None


def _read_capped(resp: requests.Response) -> Optional[bytes]:
    """分块读响应体，超过 :data:`MAX_ICON_BYTES` 就放弃（防止误拉大文件）。"""
    total = 0
    chunks = []
    try:
        for chunk in resp.iter_content(chunk_size=64 * 1024):
            if not chunk:
                continue
            total += len(chunk)
            if total > MAX_ICON_BYTES:
                return None
            chunks.append(chunk)
    except Exception:  # noqa: BLE001 - 网络中断一律当失败
        return None
    return b"".join(chunks) or None


_IMAGE_MAGIC = (
    b"\x89PNG\r\n\x1a\n",
    b"\xff\xd8\xff",
    b"GIF87a", b"GIF89a",
    b"RIFF",
    b"BM",
    b"<svg", b"<?xml",
)


def _looks_like_image(data: Optional[bytes]) -> bool:
    """按文件头判断是不是图片（错误页、限制页都不是）。"""
    if not data:
        return False
    head = bytes(data[:64])
    return any(head.startswith(magic) for magic in _IMAGE_MAGIC)


def _cached_direct(url: str) -> str:
    """查蓝奏直链缓存（只读，不发网络请求）；没有可用直链时返回空串。

    为什么值得多这一步：同一张图，
        parser 包装 URL 直连   中位 170 ms
        蓝奏 CDN 直链直连      中位  43 ms
    差的是解析器那次 302 往返。直链缓存由后台下载流程写入（25 分钟有效），
    图标这边只要「有就顺手用上」，过期了也不影响 —— 直接回落到 parser URL。
    """
    try:
        from functions.web_update import lanzou_utils as lu
        return lu.PeekCachedDirectLink(url) or ""
    except Exception:  # noqa: BLE001 - 依赖缺失时退回直连原 URL
        return ""


def _get_once(target: str, timeout: float) -> Optional[bytes]:
    """GET 一次，返回图片字节；状态码异常 / 不是图片 / 超限时返回 None。"""
    headers = {"Accept": "image/avif,image/webp,image/png,image/*,*/*;q=0.8"}
    try:
        resp = _http().get(target, headers=headers, stream=True,
                           timeout=(CONNECT_TIMEOUT, min(READ_TIMEOUT, timeout)),
                           verify=False)
    except Exception:  # noqa: BLE001
        return None
    try:
        if resp.status_code != 200:
            return None
        try:
            size = int(resp.headers.get("content-length") or 0)
        except (TypeError, ValueError):
            size = 0
        if size > MAX_ICON_BYTES:
            # 明显不是图标（常见于 icon_url 被误填成资源包下载链接）
            return None
        data = _read_capped(resp)
    finally:
        try:
            resp.close()
        except Exception:  # noqa: BLE001
            pass
    if not data or not _looks_like_image(data):
        return None
    return data


def download_image(url: str, timeout: float = 15.0) -> Optional[bytes]:
    """取图片字节；失败返回 None。

    取图顺序：

    1. **已知直链**（:func:`_cached_direct`）—— 命中时中位 43 ms；
    2. **原 URL 直连** —— ``lz.qaiu.top/parser?url=...`` 这种包装 URL 自己
       就会 302 到文件，中间只多一次往返（中位 170 ms）；
    3. 两者都拿不到图片时由调用方回退 ``GetWithDirectLink`` 的完整解析链路
       （约 1.3 s/个，只在直链缓存过期且直连又不通时才会走到）。
    """
    if not url:
        return None
    direct = _cached_direct(url)
    if direct and direct != url:
        data = _get_once(direct, timeout)
        if data:
            return data
    return _get_once(url, timeout)


def shrink_image(data: bytes, max_edge: int = MAX_EDGE) -> bytes:
    """把图片缩到 ``max_edge`` 以内，返回新的 PNG 字节；不需要/失败时原样返回。"""
    if not data:
        return data
    try:
        from PIL import Image
    except Exception:  # noqa: BLE001 - 没装 Pillow 就保持原图，别让图标坏掉
        return data
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
        width, height = image.size
        if max(width, height) <= max_edge and len(data) <= 96 * 1024:
            return data
        image.thumbnail((max_edge, max_edge), Image.LANCZOS)
        buffer = io.BytesIO()
        if image.mode in ("RGBA", "LA", "P"):
            image.convert("RGBA").save(buffer, "PNG", optimize=True)
        else:
            image.convert("RGB").save(buffer, "PNG", optimize=True)
        shrunk = buffer.getvalue()
    except Exception:  # noqa: BLE001
        return data
    # 少数调色板图重编码反而变大，这种情况保留原图
    return shrunk if len(shrunk) < len(data) else data


def shrink_file(path: str, max_edge: int = MAX_EDGE, force: bool = False) -> bool:
    """把磁盘上的大图标就地缩小；返回是否真的改写了文件。

    热路径（每次缓存命中的 ``get_icon``）用默认 ``force=False``：体积已经小于
    96 KB 就直接跳过，避免为了确认尺寸去读整个文件。一次性迁移
    （:func:`functions.base.common.icon_cache.shrink_cached_icons`）用
    ``force=True``，连「体积不大但像素尺寸超标」的历史文件也一并处理。
    """
    try:
        size = os.path.getsize(path)
    except OSError:
        return False
    if not force and size <= 96 * 1024:
        return False
    with _shrink_lock:
        try:
            with open(path, "rb") as f:
                raw = f.read()
        except OSError:
            return False
        shrunk = shrink_image(raw, max_edge=max_edge)
        if len(shrunk) >= len(raw):
            return False
        tmp = "%s.%d.%d.tmp" % (path, os.getpid(), threading.get_ident())
        try:
            with open(tmp, "wb") as f:
                f.write(shrunk)
            os.replace(tmp, path)
            return True
        except OSError:
            try:
                os.remove(tmp)
            except OSError:
                pass
            return False


def save_image(data: bytes, path: str, max_edge: int = MAX_EDGE) -> bool:
    """缩略后写盘（先写临时文件再原子替换，避免读到半个文件）。"""
    if not data:
        return False
    payload = shrink_image(data, max_edge=max_edge)
    tmp = "%s.%d.%d.tmp" % (path, os.getpid(), threading.get_ident())
    try:
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(tmp, "wb") as f:
            f.write(payload)
        os.replace(tmp, path)
        return True
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass
        return False


def data_uri(path: str) -> str:
    """读文件并转成 ``data:image/png;base64,...``；失败返回空串。"""
    try:
        with open(path, "rb") as f:
            return "data:image/png;base64," + base64.b64encode(f.read()).decode("ascii")
    except Exception:  # noqa: BLE001
        return ""
