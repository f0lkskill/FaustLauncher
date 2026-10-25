"""资源图标下载：全局连接复用 + Range 多连接并发 + 本地缩略。

背景（为什么要有这个模块）
--------------------------
资源管理里的 addon / mod 图标来自蓝奏分享链接，并被 ``lz.qaiu.top`` 解析器包
了一层（形如 ``https://lz.qaiu.top/parser?url=<分享链接>``）。实测这条链路有
三个「慢」的来源：

1. 单连接极慢：同一 CDN 单连接只有 ~26 KB/s，一个 470 KB 的图标要十几秒；
   而把同一个文件拆成 4 段 ``Range`` 并发，0.17 秒就能拿全 ——
   CDN 是按单连接限速，不是按总量。
2. 解析链路多余：``lanzou_utils.GetWithDirectLink`` 会把这种 URL 当作蓝奏
   分享链接去做完整解析（抓页面 + WAF + POST + 跟随 file 页），而解析器本身
   就会 302 到文件，直接 GET 更快；解析失败还会让图标整块丢掉。
3. 缓存的是原图：历史上的缓存直接存 1 MB 级原图（724×724 / 904×951），
   而界面上只显示几十像素。前端拿到的是 base64 字符串，体积因此被放大
   ``4/3`` 倍并完整穿过 pywebview 的 JS 桥。

对应做法：直接 GET（解析器会 302），拿到响应头后如果支持 Range 就把正文拆成
几段并发拉；拿到图片先缩到 :data:`MAX_EDGE` 再落盘；命中老缓存时顺手瘦身。

这个模块只负责「把图标弄到磁盘上并且足够小」，缓存命名 / 负缓存 / 清理仍然
交给 :mod:`functions.base.common.icon_cache`。
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

#: 小于这个体积就不折腾多连接了，拆包开销比省下的时间还多。
PARALLEL_MIN_BYTES = 64 * 1024

#: 单个文件最多拆成几段。并发太高反而会被 CDN 判成异常请求。
PARALLEL_PARTS = 4

#: 单段少于这个字节数就别拆了，一段一个请求不划算。
PARALLEL_MIN_PART = 24 * 1024

#: 图标不可能这么大。超过就判定 URL 指错了（例如误传成资源包下载链接），
#: 直接放弃，别把几十 MB 的东西拉进内存。
MAX_ICON_BYTES = 6 * 1024 * 1024

CONNECT_TIMEOUT = 10
READ_TIMEOUT = 20

#: 已经是缩略图的文件不会再被反复打开（避免每次读都走一遍 PIL）。
_SHRUNK_MARK = "\x00icon_fetch_shrunk"

_session = None
_session_lock = threading.Lock()
_shrink_lock = threading.Lock()


def _http() -> requests.Session:
    """返回全局复用的 Session。

    必须全局复用而不是线程局部：pywebview 的每个 ``js_api`` 调用都在新线程里
    跑（``webview/util.py`` 里 ``Thread(target=_call).start()``），线程局部的
    Session 等于每次请求都重新握手 TCP + TLS，几十个图标就是几十次握手。
    """
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
                # 图片本身已经压过，让 CDN 再 gzip 一遍只是白费 CPU
                "Accept-Encoding": "identity",
            })
            _session = sess
        return _session


def reset_session() -> None:
    """丢掉缓存的 Session（切换代理或测试时使用）。"""
    global _session
    with _session_lock:
        _session = None


def _content_length(resp: requests.Response) -> int:
    try:
        return int(resp.headers.get("content-length") or 0)
    except (TypeError, ValueError):
        return 0


def _supports_ranges(resp: requests.Response) -> bool:
    return str(resp.headers.get("accept-ranges", "")).strip().lower() == "bytes"


def _fetch_range(url: str, headers: dict, start: int, end: int) -> Optional[bytes]:
    """取 ``[start, end]`` 闭区间的一段；失败返回 None。"""
    merged = dict(headers)
    merged["Range"] = "bytes=%d-%d" % (start, end)
    merged["Accept-Encoding"] = "identity"
    try:
        resp = _http().get(url, headers=merged, timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
                           verify=False)
    except Exception:  # noqa: BLE001 - 网络异常一律当失败，由上层回退
        return None
    try:
        if resp.status_code not in (200, 206):
            return None
        data = resp.content
    except Exception:  # noqa: BLE001
        return None
    finally:
        try:
            resp.close()
        except Exception:  # noqa: BLE001
            pass
    expected = end - start + 1
    # 服务端忽略 Range 时会整份返回 200，此时只要够覆盖这一段就算成功
    if resp.status_code == 200:
        return data[start:end + 1] if len(data) >= expected else None
    return data if len(data) == expected else None


def _download_parallel(url: str, headers: dict, size: int) -> Optional[bytes]:
    """把 ``size`` 字节拆成若干段并发拉取并拼回；任何一段失败返回 None。"""
    parts = min(PARALLEL_PARTS, max(2, size // PARALLEL_MIN_PART))
    step = (size + parts - 1) // parts
    ranges = [(i * step, min(size - 1, (i + 1) * step - 1)) for i in range(parts)]
    chunks: list = [None] * len(ranges)
    error: list = []

    def _work(index: int, start: int, end: int) -> None:
        data = _fetch_range(url, headers, start, end)
        if data is None:
            error.append(index)
        else:
            chunks[index] = data

    threads = [threading.Thread(target=_work, args=(i, s, e), daemon=True)
               for i, (s, e) in enumerate(ranges)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=READ_TIMEOUT + CONNECT_TIMEOUT + 5)
    if error or any(c is None for c in chunks):
        return None
    return b"".join(chunks)  # type: ignore[arg-type]


def download_image(url: str, timeout: float = 15.0) -> Optional[bytes]:
    """下载一张图片，返回正文；失败返回 None。

    先发一次普通 GET（解析器会 302 到真正的文件），从响应头里读出总大小与
    Range 支持情况；条件合适就把正文改走多连接并发。
    """
    if not url:
        return None
    headers = {"Accept": "image/avif,image/webp,image/png,image/*,*/*;q=0.8"}
    try:
        probe = _http().get(url, headers=headers, stream=True,
                            timeout=(CONNECT_TIMEOUT, min(READ_TIMEOUT, timeout)),
                            verify=False)
    except Exception:  # noqa: BLE001
        return None

    try:
        if probe.status_code != 200:
            return None
        size = _content_length(probe)
        if size > MAX_ICON_BYTES:
            # 明显不是图标（常见于 icon_url 被误填成资源包下载链接）
            return None
        final_url = probe.url or url
        if size >= PARALLEL_MIN_BYTES and _supports_ranges(probe):
            # 先把这个探测连接关掉，别占着连接池；正文交给并发段
            probe.close()
            data = _download_parallel(final_url, headers, size)
            if data is not None and len(data) == size:
                return data
            # 并发失败就退回单连接再拉一次，别让图标因为加速策略反而丢掉
            return _download_simple(final_url, headers, timeout)
        return _read_capped(probe)
    except Exception:  # noqa: BLE001
        return None
    finally:
        try:
            probe.close()
        except Exception:  # noqa: BLE001
            pass


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
    except Exception:  # noqa: BLE001
        return None
    return b"".join(chunks) or None


def _download_simple(url: str, headers: dict, timeout: float) -> Optional[bytes]:
    """单连接整份下载（并发失败时的兜底），同样带体积上限。"""
    try:
        resp = _http().get(url, headers=headers, stream=True,
                           timeout=(CONNECT_TIMEOUT, min(READ_TIMEOUT, timeout)),
                           verify=False)
    except Exception:  # noqa: BLE001
        return None
    try:
        if resp.status_code != 200:
            return None
        return _read_capped(resp)
    finally:
        try:
            resp.close()
        except Exception:  # noqa: BLE001
            pass


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


def shrink_file(path: str, max_edge: int = MAX_EDGE) -> bool:
    """把磁盘上的大图标就地缩小；返回是否真的改写了文件。"""
    try:
        size = os.path.getsize(path)
    except OSError:
        return False
    if size <= 96 * 1024:
        # 体积已经不大，再打开一次不值得（1 MB 级原图才会走到下面）
        return False
    with _shrink_lock:
        try:
            with open(path, "rb") as f:
                raw = f.read()
        except OSError:
            return False
        shrunk = shrink_image(raw, max_edge=max_edge)
        if shrunk is raw or len(shrunk) >= len(raw):
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
