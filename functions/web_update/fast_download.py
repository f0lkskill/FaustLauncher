"""下载加速层：连接池 / 大块读 / 断点续传 / 多连接分块。

云端接口、文件布局都不动，纯客户端优化：

* 全局 ``requests.Session`` 复用 TCP/TLS 连接 —— 原来每次 ``requests.get``
  都要重新握手，失败重试几次光握手就白等几百毫秒到数秒。
* 读块 8KB -> 256KB，系统调用减少一个数量级。
* 单线程失败写 ``<dest>.part`` 并用 ``Range`` 续传，不再从 0 字节重来。
* 服务端回 ``Accept-Ranges: bytes`` 且文件够大时，分块多连接并发；
  探测不通过自动回退单线程 —— 不赌服务端一定支持。

只给 ``zeroasso_download`` 的直链下载用，不参与蓝奏解析本身。
"""

from __future__ import annotations

import os
import threading
from typing import Callable, Dict, Optional

import requests

CHUNK_SIZE = 256 * 1024
PART_SUFFIX = ".part"
MIN_PARALLEL_BYTES = 8 * 1024 * 1024
# 实测（9.6MB 蓝奏直链，本机 3MB/s）：1 连接 3.17s / 2 连接 3.13s /
# 4 连接 3.57s / 8 连接 4.31s —— 该 CDN 按来源限速，并发越多反而越慢。
# 所以默认只开 2 条，遇到换 CDN 或对方按连接限速时可通过参数调大。
DEFAULT_THREADS = 2
CONNECT_TIMEOUT = 15
READ_TIMEOUT = 90

_session = None
_session_lock = threading.Lock()


def session() -> requests.Session:
    """返回全局复用的 Session（连接池 16/32，不自动重试）。"""
    global _session
    with _session_lock:
        if _session is None:
            sess = requests.Session()
            adapter = requests.adapters.HTTPAdapter(
                pool_connections=16, pool_maxsize=32, max_retries=0, pool_block=False)
            sess.mount("http://", adapter)
            sess.mount("https://", adapter)
            sess.headers.update({
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                # 7z / zip 本身已经压过，让 CDN 再压一遍只是白费 CPU 还可能拖慢
                "Accept-Encoding": "identity",
            })
            _session = sess
        return _session


def reset_session() -> None:
    """丢掉缓存的 Session（测试或切换代理后使用）。"""
    global _session
    with _session_lock:
        _session = None


def _request_headers(resp: Optional[requests.Response]) -> Dict[str, str]:
    """从已有响应里捞出请求头，供分块请求复用。"""
    headers: Dict[str, str] = {}
    if resp is not None:
        try:
            for key, value in resp.request.headers.items():
                if key.lower() in ("range", "accept-encoding", "content-length"):
                    continue
                headers[key] = value # type: ignore
        except Exception:  # noqa: BLE001 - 请求对象可能是替身
            headers = {}
    headers.setdefault("Accept-Encoding", "identity")
    return headers


def _content_size(resp: Optional[requests.Response]) -> int:
    if resp is None:
        return 0
    try:
        return int(resp.headers.get("content-length") or 0)
    except (TypeError, ValueError):
        return 0


def _supports_ranges(resp: Optional[requests.Response]) -> bool:
    if resp is None:
        return False
    return str(resp.headers.get("accept-ranges", "")).strip().lower() == "bytes"


def _probe(url: str, headers: Dict[str, str]):
    """没有现成响应时探一下总大小与 Range 支持（一次 1 字节的 GET）。"""
    try:
        with session().get(url, headers={**headers, "Range": "bytes=0-0"},
                           stream=True, timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
                           verify=False) as resp:
            if resp.status_code == 206:
                total = 0
                content_range = str(resp.headers.get("content-range", ""))
                if "/" in content_range:
                    try:
                        total = int(content_range.rsplit("/", 1)[1])
                    except ValueError:
                        total = 0
                return total, True
            if resp.status_code == 200:
                return _content_size(resp), False
    except Exception:  # noqa: BLE001 - 探测失败就当不支持
        pass
    return 0, False


def _parallel(url, part, size, headers, threads, progress, cancel) -> bool:
    """分块并发写入同一个预分配文件；任一失败返回 False 由调用方回退。"""
    seg = size // threads
    if seg <= 0:
        return False

    done = 0
    lock = threading.Lock()
    failed = threading.Event()

    try:
        fd = os.open(part, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o666)
        os.ftruncate(fd, size)
    except OSError:
        return False

    def worker(index: int) -> None:
        nonlocal done
        start = index * seg
        end = size - 1 if index == threads - 1 else start + seg - 1
        if start > end:
            return
        try:
            with session().get(url, headers={**headers, "Range": f"bytes={start}-{end}"},
                               stream=True, timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
                               verify=False) as resp:
                if resp.status_code not in (200, 206):
                    resp.raise_for_status()
                # 服务端无视 Range 直接回 200 的话，分块会互相覆盖，必须放弃
                if resp.status_code == 200:
                    raise RuntimeError("服务端未接受 Range 请求")
                position = start
                for chunk in resp.iter_content(chunk_size=CHUNK_SIZE):
                    if failed.is_set():
                        return
                    if cancel is not None and not cancel():
                        failed.set()
                        return
                    if not chunk:
                        continue
                    os.pwrite(fd, chunk, position)
                    position += len(chunk)
                    with lock:
                        done += len(chunk)
                        snapshot = done
                    if progress is not None:
                        progress(snapshot, size)
        except Exception:  # noqa: BLE001 - 任何异常都回退单线程
            failed.set()

    workers = [threading.Thread(target=worker, args=(i,), daemon=True)
               for i in range(threads)]
    try:
        for item in workers:
            item.start()
        for item in workers:
            item.join()
    finally:
        try:
            os.close(fd)
        except OSError:
            pass

    if failed.is_set():
        return False
    try:
        return os.path.getsize(part) == size
    except OSError:
        return False


def _serial(url, part, headers, progress, cancel, resume,
            resp: Optional[requests.Response] = None) -> bool:
    """单连接下载，支持 .part 断点续传。

    传入 ``resp`` 时直接读它（调用方刚建立好的流，零额外请求）；需要从
    ``.part`` 续传时那个响应是从 0 字节开始的，没法接续，必须重开。
    """
    start = 0
    if resume and os.path.exists(part):
        try:
            start = os.path.getsize(part)
        except OSError:
            start = 0

    if start > 0 and resp is not None:
        try:
            resp.close()
        except Exception:  # noqa: BLE001
            pass
        resp = None

    if resp is None:
        request_headers = dict(headers)
        if start > 0:
            request_headers["Range"] = f"bytes={start}-"
        resp = session().get(url, headers=request_headers, stream=True,
                             timeout=(CONNECT_TIMEOUT, READ_TIMEOUT), verify=False)

    with resp:
        if start > 0 and resp.status_code == 200:
            start = 0  # 服务端不认 Range，只能重来
        resp.raise_for_status()

        total = _content_size(resp)
        total = start + total if total else 0
        done = start
        if progress is not None:
            progress(done, total)

        mode = "ab" if start > 0 else "wb"
        with open(part, mode) as handle:
            for chunk in resp.iter_content(chunk_size=CHUNK_SIZE):
                if cancel is not None and not cancel():
                    return False
                if not chunk:
                    continue
                handle.write(chunk)
                done += len(chunk)
                if progress is not None:
                    progress(done, total)
    return True


def download(url: str, dest: str, *, resp: Optional[requests.Response] = None,
             progress: Optional[Callable[[int, int], None]] = None,
             cancel: Optional[Callable[[], bool]] = None,
             threads: int = DEFAULT_THREADS,
             allow_parallel: bool = True,
             resume: bool = True) -> bool:
    """把 ``url`` 下到 ``dest``。

    ``resp`` 可以是调用方已经建立好的流式响应（用来复用它的请求头、总大小与
    Range 能力判断），传了就不额外发探测请求。成功返回 True，被取消或失败返回
    False；失败时 ``<dest>.part`` 会保留，下次同 URL 可以续传。
    """
    if not url:
        raise ValueError("下载链接为空")

    dest = os.path.normpath(dest)
    folder = os.path.dirname(dest)
    if folder:
        os.makedirs(folder, exist_ok=True)
    part = dest + PART_SUFFIX

    headers = _request_headers(resp)
    final_url = getattr(resp, "url", None) or url
    size = _content_size(resp)
    ranges = _supports_ranges(resp)

    usable_threads = max(1, min(int(threads), DEFAULT_THREADS))
    if resp is None and allow_parallel and usable_threads > 1:
        # 调用方只给了链接，自己探一次 Range 能力
        size, ranges = _probe(final_url, headers)

    if resp is not None:
        try:
            resp.close()
        except Exception:  # noqa: BLE001
            pass
        resp = None

    if (allow_parallel and ranges and size >= MIN_PARALLEL_BYTES
            and usable_threads > 1):
        if _parallel(final_url, part, size, headers, usable_threads, progress, cancel):
            os.replace(part, dest)
            return True
        # 分块失败：清掉残片，退回单线程从头来（part 里是稀疏数据，不能续传）
        try:
            os.remove(part)
        except OSError:
            pass
        resume = False

    ok = _serial(final_url, part, headers, progress, cancel, resume=resume, resp=resp)
    if not ok:
        return False
    os.replace(part, dest)
    return True


def __main__() -> int:  # pragma: no cover - 手工测速入口
    import sys
    import time

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass

    target = sys.argv[1] if len(sys.argv) > 1 else "https://lz.qaiu.top/parser?url=https://folkskill.lanzouc.com/irAGt3iha71c"
    out = os.path.join(os.getcwd(), "test", "_speed_dl.7z")

    begin = time.time()
    with requests.get(target, stream=True, verify=False, timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
                      headers={"User-Agent": "Mozilla/5.0"}) as probe:
        probe.raise_for_status()
        print(f"直链: {probe.url[:90]}")
        print(f"Ranges: {_supports_ranges(probe)}  大小: {_content_size(probe)}")
        ok = download(probe.url, out, resp=probe)
    elapsed = time.time() - begin
    if os.path.isfile(out):
        size = os.path.getsize(out)
        print(f"结果 {ok}  {size} 字节  {elapsed:.2f}s  {size/1024/max(elapsed,0.01):.0f} KB/s")
    else:
        print(f"结果 {ok}  未落盘")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(__main__())
