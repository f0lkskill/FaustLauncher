"""云端笔记（webnote）的读取、缓存与写入。

公告正文、版本信息等文本都放在云端笔记里。读取走三档：进程内 memo（短
TTL）→ 磁盘缓存 ``cache/webnote/`` → 网络；网络失败时回退磁盘缓存，并在
:class:`Note` 上打 ``used_cache`` 标记，调用方据此知道这份内容可能过期，
不能拿它去做“云端已不存在”的清理。

DNS 解析异常时还会尝试 DoH + 固定 IPv4 兜底，避免在部分网络环境下彻底拿
不到笔记内容。写接口（:func:`write_note`）需要 web_config 里的
simplenote API key。
"""

import json
import os
import re
import socket
import sys
import time
from contextlib import contextmanager, nullcontext

import requests

if getattr(sys, "frozen", False):
    _PROJECT_ROOT = os.path.dirname(os.path.abspath(sys.executable))
else:
    _PROJECT_ROOT = os.path.abspath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

CACHE_DIR = os.path.join(_PROJECT_ROOT, "cache", "webnote")

DEFAULT_BASES = (
    "https://folkskill.pythonanywhere.com/note/{key}",
)
DEFAULT_UPDATE_URL = "https://folkskill.pythonanywhere.com/update/"

CONNECT_TIMEOUT = 15
READ_TIMEOUT = 15
BUDGET_NO_CACHE = 45
BUDGET_WITH_CACHE = 14
MEMO_TTL = 30

DOH_ENDPOINTS = (
    "https://223.5.5.5/resolve",
    "https://doh.pub/dns-query",
)
DOH_TIMEOUT = (3, 6)

_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"),
    "Accept": "*/*",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Cache-Control": "no-cache",
}

_orig_getaddrinfo = socket.getaddrinfo
_last_error = {}

def get_note_bases():
    """返回笔记 URL 模板列表，优先取 web_config，缺失时用内置默认地址。"""
    bases = []
    try:
        from functions.base.web_config import get_web_config
        raw = (get_web_config() or {}).get("webnote_bases")
        if isinstance(raw, str):
            raw = [raw]
        if isinstance(raw, (list, tuple)):
            bases = [str(x).strip() for x in raw if str(x).strip()]
    except Exception:
        bases = []
    return bases or list(DEFAULT_BASES)

def get_update_url():
    """返回版本信息接口的 URL，配置里没有则用内置地址。"""
    try:
        from functions.base.web_config import get_web_config
        url = (get_web_config() or {}).get("webnote_update_url")
        if isinstance(url, str) and url.strip():
            return url.strip()
    except Exception:
        pass
    return DEFAULT_UPDATE_URL

def _build_url(template, key):
    """把笔记 key 填进 URL 模板；模板没有 ``{key}`` 占位时直接拼到末尾。"""
    t = str(template).strip()
    if "{key}" in t:
        return t.replace("{key}", str(key))
    return t.rstrip("/") + "/" + str(key)

def _cache_stem(key):
    """把笔记名转成安全的文件名片段（非法字符替换为下划线，最长 80 字）。"""
    return re.sub(r"[^0-9A-Za-z._\-]", "_", str(key))[:80] or "note"

def _cache_path(key):
    """返回某个笔记名对应的磁盘缓存文件路径。"""
    return os.path.join(CACHE_DIR, _cache_stem(key) + ".txt")

def configured_note_names():
    """收集配置里出现过的所有笔记名（webnote 段 + lanzou 目录 + 内嵌地址）。

    Returns:
        list[str]: 去重后的笔记名，供缓存清理时保留白名单。
    """
    names = []

    def add(value):
        text = str(value or "").strip()
        if text and text not in names:
            names.append(text)

    try:
        from functions.base.web_config import get_embedded_webnote_address, get_web_config
    except Exception:
        return names
    data = get_web_config() or {}
    section = data.get("webnote")
    if isinstance(section, dict):
        for key, item in section.items():
            if str(key) == "simplenote_api_key":
                continue
            if isinstance(item, dict):
                add(item.get("address"))
            elif isinstance(item, str):
                add(item)
            try:
                add(get_embedded_webnote_address(str(key)))
            except Exception:
                pass
    lanzou = data.get("lanzou")
    if isinstance(lanzou, dict):
        for key in ("icons_folder", "mods_folder", "addons_folder"):
            add(lanzou.get(key))
    return names

def prune_cache(extra=()):
    """删掉不再被配置引用的旧笔记缓存文件。

    Args:
        extra: 额外的笔记名白名单，避免删掉调用方刚写入的缓存。
    """
    keep = {_cache_stem(name) for name in configured_note_names()}
    for item in (extra or ()):
        text = str(item or "").strip()
        if text:
            keep.add(_cache_stem(text))
    result = {"removed": 0, "kept": 0, "freed": 0, "names": sorted(keep)}
    if not keep:
        print("[Cloud] 读不到 web 配置的笔记名 → 跳过笔记缓存清理（不清空）")
        return result
    if not os.path.isdir(CACHE_DIR):
        return result
    for name in sorted(os.listdir(CACHE_DIR)):
        path = os.path.join(CACHE_DIR, name)
        if not os.path.isfile(path) or not name.lower().endswith(".txt"):
            continue
        if name[:-4] in keep:
            result["kept"] += 1
            continue
        try:
            size = os.path.getsize(path)
            os.remove(path)
            result["removed"] += 1
            result["freed"] += size
            print(f"[Cloud] 已清理废弃的笔记缓存: {name}（{size} 字节）")
        except OSError:
            pass
    if result["removed"]:
        print(f"[Cloud] 笔记缓存清理完成: 删除 {result['removed']} 份 / "
              f"释放 {result['freed'] / 1024:.1f} KB，保留 {result['kept']} 份")
    return result

_pruned = False

def _prune_once():
    global _pruned
    if _pruned:
        return
    _pruned = True
    try:
        prune_cache()
    except Exception as exc:  # noqa: BLE001
        print(f"[Cloud] 笔记缓存清理失败(忽略): {exc}")

def cache_read(key):
    """读磁盘缓存，返回 ``(内容, 距修改时间秒数)``；没有则返回 ``("", None)``。"""
    path = _cache_path(key)
    try:
        if not os.path.isfile(path):
            return "", None
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
        return text, max(0.0, time.time() - os.path.getmtime(path))
    except Exception:
        return "", None

def cache_write(key, text):
    """把笔记内容写到磁盘缓存，目录不存在时自动创建；失败静默忽略。"""
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(_cache_path(key), "w", encoding="utf-8") as f:
            f.write(text or "")
    except Exception:
        pass

def _fmt_age(seconds):
    if seconds is None:
        return "未知时间"
    if seconds < 60:
        return f"{int(seconds)} 秒"
    if seconds < 3600:
        return f"{seconds / 60:.0f} 分钟"
    if seconds < 86400:
        return f"{seconds / 3600:.1f} 小时"
    return f"{seconds / 86400:.1f} 天"

_MEMO = {}

def memo_get(keys, ttl):
    """查进程内短期缓存，返回 ``(内容, 使用的 key, 年龄秒)``；未命中返回 None。"""
    if ttl <= 0:
        return None
    now = time.time()
    for k in keys:
        item = _MEMO.get(k)
        if item and now - item[1] < ttl:
            return item[0], k, now - item[1]
    return None

def memo_put(key, text):
    """把内容放进进程内短期缓存；key 为空时什么都不做。"""
    if key:
        _MEMO[key] = (text, time.time())

def memo_clear():
    """清空进程内短期缓存，下次读取会重新走磁盘或网络。"""
    _MEMO.clear()

@contextmanager
def _prefer_ipv4():
    def _ipv4_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
        return _orig_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)

    socket.getaddrinfo = _ipv4_getaddrinfo
    try:
        yield
    finally:
        socket.getaddrinfo = _orig_getaddrinfo

def _is_conn_error(exc):
    text = f"{type(exc).__name__}: {exc}".lower()
    keys = ("timeout", "timed out", "connection", "ssl", "eof", "reset", "refused",
            "unreachable", "getaddrinfo", "socket", "proxy", "handshake", "aborted")
    return any(k in text for k in keys)

_DOH_HEADERS = dict(_HEADERS, Accept="application/dns-json")

def resolve_via_doh(host):
    for endpoint in DOH_ENDPOINTS:
        try:
            r = requests.get(endpoint, params={"name": host, "type": "A"},
                             headers=_DOH_HEADERS, verify=False, timeout=DOH_TIMEOUT)
            data = r.json()
            ips = []
            for ans in (data.get("Answer") or []):
                ip = str(ans.get("data", "")).strip()
                if re.match(r"^\d{1,3}(\.\d{1,3}){3}$", ip):
                    ips.append(ip)
            if ips:
                return ips
        except Exception:
            continue
    return []

def _fetch_by_ip(url, host, ips, timeout):
    try:
        import ssl
        import urllib3
        from urllib.parse import urlsplit
    except Exception:
        return None
    u = urlsplit(url)
    path = u.path + (("?" + u.query) if u.query else "")
    port = u.port or 443
    for ip in ips:
        pool = None
        try:
            pool = urllib3.HTTPSConnectionPool(
                ip, port=port, server_hostname=host, cert_reqs=ssl.CERT_NONE,
                timeout=urllib3.Timeout(connect=timeout[0], read=timeout[1]), retries=False)
            resp = pool.urlopen("GET", path, headers=dict(_HEADERS, **{"Host": host}),
                                preload_content=True, redirect=False)
            text = resp.data.decode("utf-8", "replace")
            if 200 <= int(resp.status) < 300 and text.strip():
                return text
        except Exception:
            continue
        finally:
            if pool is not None:
                try:
                    pool.close()
                except Exception:
                    pass
    return None

def _fetch_note(keys, verbose=True):
    """按候选笔记名/URL 模板逐个尝试网络读取，成功时顺手写磁盘缓存。

    总耗时受 ``BUDGET_*`` 限制：有缓存时预算更短。常规线路失败再尝试 DoH
    解析出的 IPv4 直连。

    Args:
        keys: 候选笔记名（字符串或列表）。
        verbose: 是否把每次尝试打到终端。

    Returns:
        tuple[str, str, str, str]: ``(内容, 来源 URL, 命中的 key, 错误说明)``；
        全部失败时内容为空、错误说明非空。
    """
    if isinstance(keys, str):
        keys = [keys]
    _prune_once()
    bases = get_note_bases()
    cached_text = ""
    for k in keys:
        c, _age = cache_read(k)
        if c:
            cached_text = c
            break
    deadline = time.time() + (BUDGET_WITH_CACHE if cached_text else BUDGET_NO_CACHE)
    conn_to = 3 if cached_text else CONNECT_TIMEOUT
    last_err = ""

    for key in keys:
        http_level_fail = False
        for template in bases:
            url = _build_url(template, key)
            host = ""
            try:
                from urllib.parse import urlsplit
                host = urlsplit(url).hostname or ""
            except Exception:
                host = ""
            for attempt in (1, 2):
                remain = deadline - time.time()
                if remain <= 1:
                    last_err = last_err or "总尝试时间超预算"
                    break
                use_ipv4 = (attempt == 1)
                t0 = time.time()
                try:
                    with (_prefer_ipv4() if use_ipv4 else nullcontext()):
                        r = requests.get(
                            url, headers=_HEADERS, verify=False,
                            timeout=(min(conn_to, remain), min(READ_TIMEOUT, remain)),
                        )
                    cost = time.time() - t0
                    text = r.text or ""
                    if r.status_code != 200:
                        raise RuntimeError(f"HTTP {r.status_code}")
                    if not text.strip():
                        raise RuntimeError("HTTP 200 但内容为空 (笔记名是否正确/是否已迁移?)")
                    if verbose:
                        print(f"[Cloud] {key} 获取成功: ({len(text)} 字节, {cost:.2f}s)")
                    cache_write(key, text)
                    return text, url, key, ""
                except Exception as e:
                    cost = time.time() - t0
                    reason = f"{type(e).__name__}: {str(e)[:140]}"
                    last_err = f"[{key}] {reason}"
                    if isinstance(e, RuntimeError):
                        http_level_fail = True
                    if verbose:
                        print(f"[Cloud] {key} 第 {attempt} 次失败"
                              f"{' (IPv4)' if use_ipv4 else ' (IPv6 放开)'}: "
                              f"{reason} ({cost:.2f}s)")
                    if attempt == 1 and _is_conn_error(e):
                        continue
                    break

            remain = deadline - time.time()
            if host and remain > 3 and not http_level_fail:
                ips = resolve_via_doh(host)
                if ips:
                    if verbose:
                        print(f"[Cloud] {key} 常规线路失败, 改用 DoH 解析直连: "
                              f"{host} -> {', '.join(ips[:3])}")
                    t0 = time.time()
                    text = _fetch_by_ip(url, host, ips,
                                        (min(conn_to, remain), min(READ_TIMEOUT, remain)))
                    if text:
                        if verbose:
                            print(f"[Cloud] {key} DoH 直连获取成功: ({len(text)} 字节, "
                                  f"{time.time() - t0:.2f}s)")
                        cache_write(key, text)
                        return text, url, key, ""
                    last_err = f"[{key}] DoH 直连仍失败"

    _last_error[keys[0]] = last_err or "未知错误"
    return "", "", "", last_err or "未知错误"

def _fetch_text(key, verbose=True):
    """_fetch_note 的简化版，只返回 ``(内容, 来源 URL, 错误说明)``。"""
    text, url, _used, err = _fetch_note([key] if isinstance(key, str) else key, verbose)
    return text, url, err

def read_note_live(note_id: str, address: str, pwd: str = "") -> tuple:
    """忽略缓存、直接走网络读一次笔记，给工具窗口预览用。

    Returns:
        tuple[str, str, str]: ``(内容, 实际使用的地址, 错误说明)``。
    """
    try:
        note = Note(note_id, address, pwd)
        keys = note._candidate_keys()
    except Exception as e:
        return "", str(address or ""), f"构造笔记失败: {e}"
    text, _source, used, err = _fetch_note(keys)
    return (text or ""), (used or str(address or "")), (err or "")

def parse_write_response(r):
    """解析写回接口的响应，返回 ``(是否成功, 详情字典)``；HTML 错误页也认。"""
    text = (r.text or "").strip()
    if not text:
        return False, {"error": f"HTTP {r.status_code} 空响应"}
    if text.startswith("<"):
        m = re.search(r"<title>(.*?)</title>", text, re.S | re.I)
        title = (m.group(1).strip() if m else "")
        if re.match(r"^\d{3}\b", title):
            return False, {"error": title}
        return False, {"error": f"HTTP {r.status_code} {title or 'HTML 错误页'}"}
    try:
        data = json.loads(text)
    except Exception:
        if r.status_code == 200:
            return True, {"status": 1, "raw": text[:200]}
        return False, {"error": f"HTTP {r.status_code} 非 JSON 响应: {text[:120]}"}
    if isinstance(data, dict) and data.get("status") == 1:
        return True, data
    return False, {"error": f"服务端返回失败: {str(data)[:160]}"}

def write_note(key, value, update_url=None):
    """把一段文本写回云端笔记；短文本走 GET，其余走 POST，各重试一次。

    Args:
        key: 笔记名。
        value: 新内容；None 视为空串。
        update_url: 可选的写入接口，缺省用 web_config/内置地址。

    Returns:
        dict: ``{'status': 1/0, 'error', 'method', 'req_id'}``。
    """
    url = update_url or get_update_url()
    key = str(key or "")
    value = "" if value is None else str(value)
    if not key:
        return {"status": 0, "error": "笔记名为空", "method": "", "req_id": None}

    methods = ["POST"]
    if len(value) <= 4000:
        methods.append("GET")

    last_err = ""
    for method in methods:
        for attempt in (1, 2):
            t0 = time.time()
            try:
                if method == "POST":
                    r = requests.post(url, params={"key": key},
                                      files={"value": (None, value.encode("utf-8"))},
                                      headers=_HEADERS, verify=False,
                                      timeout=(CONNECT_TIMEOUT, 60))
                else:
                    r = requests.get(url, params={"key": key, "value": value},
                                     headers=_HEADERS, verify=False,
                                     timeout=(CONNECT_TIMEOUT, 60))
                ok, info = parse_write_response(r)
                cost = time.time() - t0
                if ok:
                    print(f"[Cloud] {key} 写回成功 ({method}, {len(value)} 字节, {cost:.2f}s)")
                    return {"status": 1, "error": None, "method": method,
                            "req_id": info.get("req_id") if isinstance(info, dict) else None}
                last_err = str(info.get("error"))
                print(f"[Cloud] {key} 写回失败 ({method}): {last_err} ({cost:.2f}s)")
                break               
            except Exception as e:
                cost = time.time() - t0
                last_err = f"{type(e).__name__}: {str(e)[:140]}"
                print(f"[Cloud] {key} 写回第 {attempt} 次失败 ({method}): {last_err} ({cost:.2f}s)")
                if attempt == 1 and _is_conn_error(e):
                    time.sleep(0.4)
                    continue
                break
    return {"status": 0, "error": last_err or "未知错误", "method": "", "req_id": None}

class Note:
    """一个云端笔记的高层封装：记住 key、内容、来源和读取状态。

    典型用法是构造后调用 :meth:`fetch_note_info`，再从 ``note_content`` 拿
    文本。读取失败时 ``note_content`` 可能来自磁盘缓存，务必同时看
    ``used_cache``，不要把过期内容当成最新云端数据。
    """

    def __init__(self, id_name: str | None = None, address: str = "",
                 pwd: str = "", read_only: bool = False):
        """创建一个未读取的笔记对象。

        Args:
            id_name: 配置里的笔记名/键，用于查内嵌地址。
            address: 显式笔记地址；优先于 id_name。
            pwd: 缺省提取码（公告场景一般不用）。
            read_only: 只读标记，写接口可据此拒绝操作。
        """
        self.note_id = id_name if id_name else address
        self._requested = str(address or "")
        self.note_name = self._requested
        self.pwd = pwd
        self.note_url = _build_url(get_note_bases()[0], self.note_name) if self.note_name else ""
        self.read_only = read_only
        self.note_content = ""
        self.req_id = None
        self.has_get = False
        self.last_fetch_error = ""
        self.empty_note = False
        #: 本次内容是否来自本地缓存（云端没拿到）。调用方据此决定能不能拿
        #: 这份内容去做“云端已不存在”的清理，避免断网时误删本地记录。
        self.used_cache = False

    def _candidate_keys(self):
        """候选笔记名列表：显式地址在前，内嵌配置地址在后。"""
        keys = []

        def add(k):
            k = str(k or "").strip()
            if k and k not in keys:
                keys.append(k)

        add(self._requested)
        try:
            from functions.base.web_config import get_embedded_webnote_address
            add(get_embedded_webnote_address(self.note_id))
        except Exception:
            pass
        return keys or [self._requested]

    def _use_key(self, key):
        """记录本次实际命中的笔记名，配置名和得到的内嵌名不一致时打印提示。"""
        key = str(key or "").strip()
        if not key:
            return
        if key != self._requested:
            print(f"[Cloud] {self.note_id} 使用内嵌配置里的笔记名: {key} "
                  f"(本地配置写的是 {self._requested})")
        self.note_name = key

    def fetch_note_info(self, allow_refresh=False):
        """按 memo → 网络 → 磁盘缓存的顺序读取笔记内容。

        Args:
            allow_refresh: True 时跳过 memo 强制走网络；失败仍会回退磁盘缓存。

        Returns:
            dict: ``{'note_content': str, 'note_id': str}``。
        """
        if not allow_refresh and self.has_get and self.note_content:
            return {"note_content": self.note_content, "note_id": self.note_name}

        keys = self._candidate_keys()

        if not allow_refresh:
            hit = memo_get(keys, MEMO_TTL)
            if hit:
                text, used, age = hit
                self._use_key(used)
                self.note_content = text
                self.has_get = True
                if age >= 2:
                    print(f"[Cloud] {self.note_id} 命中本次启动已有的内容 ({age:.0f}s 前, 不重复请求)")
                return {"note_content": self.note_content, "note_id": self.note_name}

        if self.has_get and not self.note_content:
            print(f"[Cloud] 尝试重新获取 {self.note_id} 内容…")

        self.last_fetch_error = ""
        self.empty_note = False
        self.used_cache = False

        text, source, used, err = _fetch_note(keys)
        if text:
            self._use_key(used)
            self.note_content = text
            self.note_url = source
            self.has_get = True
            memo_put(used, text)
            return {"note_content": self.note_content, "note_id": self.note_name}

        best = None
        for k in keys:
            cached, age = cache_read(k)
            if cached and (best is None or (age is not None and age < best[2])):
                best = (cached, k, age if age is not None else 1e18)
        if best:
            self._use_key(best[1])
            print(f"[Cloud] {self.note_id} 云端获取失败, 使用本地缓存 "
                  f"({_fmt_age(best[2])}前, 可能过期) | 原因: {err}")
            self.note_content = best[0]
            self.has_get = True
            self.used_cache = True
            memo_put(best[1], best[0])
            return {"note_content": self.note_content, "note_id": self.note_name}

        print(f"[Cloud] {self.note_id} 获取失败, 无可用缓存 | 尝试过: {', '.join(keys)} | 原因: {err}")
        self.note_content = ""
        self.last_fetch_error = err or ""
        self.empty_note = "内容为空" in self.last_fetch_error
        return {"note_content": "", "note_id": self.note_name}

    def update_note_content(self, new_content):
        """写回新内容；云端失败时在内存/memo 里仍然生效，并打印警告。"""
        result = write_note(self.note_name, new_content)
        self.note_content = new_content
        memo_put(self.note_name, new_content)
        if result.get("status") == 1:
            self.req_id = result.get("req_id")
            cache_write(self.note_name, new_content)
        else:
            print(f"[Cloud] {self.note_id} 写回未成功 (仅本地生效): {result.get('error')}")
        return result

    def delete_note(self):
        """把云端笔记内容清空，并清掉磁盘缓存与进程内 memo。"""
        result = write_note(self.note_name, "")
        if result.get("status") == 1:
            cache_write(self.note_name, "")
        memo_clear()
        return result
