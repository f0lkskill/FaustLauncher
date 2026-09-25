"""云端笔记 (Webnote) 读写

**读与写是两条独立链路**:

- 读取: `config/web_config.json → webnote_bases` (模板列表, 含 `{key}`), 即 `/note/<key>`
- 写回: `config/web_config.json → webnote_update_url`, 即 `/update/` (下载计数/排序上传)
  写回固定用 **POST** (`key` 在 query, `value` 在表单体): 实测 `/update/` 用 GET 时 value 进 URL,
  真实笔记(20KB+) 会被 openresty **414 Request-URI Too Large** 拒绝, GET 仅作小内容兜底。

读取侧针对国内复杂线路做了加固。此前"南方部分用户云端数据全部获取失败"的典型原因:
单域名 + 无超时 + 不区分错误类型, 跨境线路一抖动 / DNS 被污染 / IPv6 半通 就整段失败,
而浏览器自带 DoH、Happy Eyeballs(IPv6 自动回落) 等机制, 所以看起来"浏览器正常"。

加固点:
  1. 多源兜底: webnote_bases 模板列表依次尝试
  2. 超时 + 重试: 不再出现无超时的长时间挂死 (连接类错误会换协议栈/退避重试)
  3. IPv4 优先: Python 不会像浏览器那样自动回落 IPv4, 线路 IPv6 半通时会直接失败
  4. DoH 兜底: 常规线路失败时用 223.5.5.5 / doh.pub 解析, 再按原域名 SNI 直连 IP (绕过 DNS 污染)
  5. 本地缓存兜底: 全部源失败时用 cache/webnote/<key>.txt, 启动器仍可用 (可能过期)
  6. 明确日志: 打印每个源的 URL/状态/耗时/异常, 失败不再被静默吞掉

**笔记名规则**: 就用 `config/web_config.json`(打包后是构建时内嵌)里写死的那个名字,
不加也不减任何后缀; 内嵌名与本地配置名不同时(残留旧配置)才依次尝试, 供旧配置自动迁移。
"""

import json
import os
import re
import socket
import sys
import time
from contextlib import contextmanager, nullcontext

import requests

# 路径 / 常量
if getattr(sys, "frozen", False):
    _PROJECT_ROOT = os.path.dirname(os.path.abspath(sys.executable))
else:
    _PROJECT_ROOT = os.path.abspath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

CACHE_DIR = os.path.join(_PROJECT_ROOT, "cache", "webnote")

# 默认笔记读取源 (config/web_config.json 的 webnote_bases 可覆盖, 支持 {key} 占位符)
DEFAULT_BASES = (
    "https://folkskill.pythonanywhere.com/note/{key}",
)
# 默认写回地址 (与读取源分开配置; value 走表单体, 不用 GET 避免 414)
DEFAULT_UPDATE_URL = "https://folkskill.pythonanywhere.com/update/"

CONNECT_TIMEOUT = 15        # 建连超时 (秒)
READ_TIMEOUT = 15          # 读取超时 (秒)
BUDGET_NO_CACHE = 45       # 无本地缓存时的总尝试预算 (秒)
BUDGET_WITH_CACHE = 14     # 有本地缓存时快速失败, 尽早回退到缓存 (秒)
# 新鲜度策略 (重要):
#   磁盘缓存 (cache/webnote) 仅作为"网络失败时的兜底", 不做跨重启快速命中 ——
#   否则发布新版本/新 Mod 后重启启动器仍会看到旧内容 (曾经就是这样把更新吞掉的)。
#   同一次启动内的重复请求由进程内记忆合并, 重启即失效; 手动刷新会强制联网。
MEMO_TTL = 30              # 进程内记忆时长 (秒), 0 = 关闭

# 备用 DNS (DoH): 系统 DNS 被污染 / 解析失败时用, 解析到 IP 后按原域名 SNI 直连
DOH_ENDPOINTS = (
    "https://223.5.5.5/resolve",       # 阿里公共 DNS (国内可达)
    "https://doh.pub/dns-query",       # 腾讯 DNSPod
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
# note_key -> 最近一次失败原因 (诊断用)


# 配置
def get_note_bases():
    """读取笔记源模板列表 (config/web_config.json → webnote_bases)"""
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
    """读取写回地址 (config/web_config.json → webnote_update_url)

    读取 (/note/) 与写回 (/update/) 是两套独立配置, 互不影响。
    """
    try:
        from functions.base.web_config import get_web_config
        url = (get_web_config() or {}).get("webnote_update_url")
        if isinstance(url, str) and url.strip():
            return url.strip()
    except Exception:
        pass
    return DEFAULT_UPDATE_URL


def _build_url(template, key):
    """模板 → 完整地址: 支持 {key} 占位符, 否则按 base/key 拼接"""
    t = str(template).strip()
    if "{key}" in t:
        return t.replace("{key}", str(key))
    return t.rstrip("/") + "/" + str(key)


# 本地缓存 (断网/线路故障时兜底, 保证启动器仍可用)
def _cache_path(key):
    safe = re.sub(r"[^0-9A-Za-z._\-]", "_", str(key))[:80] or "note"
    return os.path.join(CACHE_DIR, safe + ".txt")


def cache_read(key):
    """返回 (内容, 缓存时长秒); 无缓存返回 ('', None)"""
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


# 进程内记忆: 同一次启动里同一条笔记只请求一次 (重启即失效)
_MEMO = {}
# key -> (text, ts)


def memo_get(keys, ttl):
    """命中进程内记忆时返回 (text, used_key, age), 否则 None"""
    if ttl <= 0:
        return None
    now = time.time()
    for k in keys:
        item = _MEMO.get(k)
        if item and now - item[1] < ttl:
            return item[0], k, now - item[1]
    return None


def memo_put(key, text):
    if key:
        _MEMO[key] = (text, time.time())


def memo_clear():
    _MEMO.clear()


# ============================================================
# 网络请求 (IPv4 优先 + 超时 + 多源)
# ============================================================
@contextmanager
def _prefer_ipv4():
    """临时让 DNS 只返回 IPv4 地址 (浏览器有 Happy Eyeballs 自动回落, Python 没有)"""
    def _ipv4_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
        return _orig_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)

    socket.getaddrinfo = _ipv4_getaddrinfo
    try:
        yield
    finally:
        socket.getaddrinfo = _orig_getaddrinfo


def _is_conn_error(exc):
    """是否为连接/超时/握手类错误 (这类错误换协议栈(IPv6)重试才有意义)"""
    text = f"{type(exc).__name__}: {exc}".lower()
    keys = ("timeout", "timed out", "connection", "ssl", "eof", "reset", "refused",
            "unreachable", "getaddrinfo", "socket", "proxy", "handshake", "aborted")
    return any(k in text for k in keys)


_DOH_HEADERS = dict(_HEADERS, Accept="application/dns-json")


def resolve_via_doh(host):
    """通过 DoH 解析 A 记录; 失败返回 [] (用于绕过系统 DNS 污染/解析失败)"""
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
    """按指定 IP 连接, 但 TLS SNI / Host 仍用原域名 (绕过 DNS 污染, 不破 SNI 路由)"""
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
    """按候选笔记名依次尝试获取 (超时/IPv4 优先/DoH/预算控制)。

    每个候选名最多两次: 第 1 次强制 IPv4, 连接类错误时第 2 次放开 IPv6。
    返回 200 但内容为空 (说明该笔记名不存在) 时会自动换下一个候选名。

    Returns:
        (text, source_url, used_key, error)
    """
    if isinstance(keys, str):
        keys = [keys]
    bases = get_note_bases()
    cached_text = ""
    for k in keys:
        c, _age = cache_read(k)
        if c:
            cached_text = c
            break
    deadline = time.time() + (BUDGET_WITH_CACHE if cached_text else BUDGET_NO_CACHE)
    # 有本地缓存时不值得等太久: 尽早失败并回退缓存 (南方线路卡顿时体验更好)
    conn_to = 3 if cached_text else CONNECT_TIMEOUT
    last_err = ""

    for key in keys:
        http_level_fail = False       # 该笔记名是否属于"不存在/为空"而不是线路问题
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
                        print(f"[云端] {key} 获取成功: ({len(text)} 字节, {cost:.2f}s)")
                    cache_write(key, text)
                    return text, url, key, ""
                except Exception as e:
                    cost = time.time() - t0
                    reason = f"{type(e).__name__}: {str(e)[:140]}"
                    last_err = f"[{key}] {reason}"
                    # HTTP 层/内容为空属于"笔记名问题", 与线路无关, 不值得再跑 DoH
                    if isinstance(e, RuntimeError):
                        http_level_fail = True
                    if verbose:
                        print(f"[云端] {key} 第 {attempt} 次失败"
                              f"{' (IPv4)' if use_ipv4 else ' (IPv6 放开)'}: "
                              f"{reason} ({cost:.2f}s)")
                    if attempt == 1 and _is_conn_error(e):
                        continue          # 换协议栈再试一次
                    break                 # HTTP 层错误或第 2 次失败: 换下一个源

            # 兜底: 系统 DNS 被污染 / 连接被卡 → 用 DoH 解析后按原域名直连 IP
            remain = deadline - time.time()
            if host and remain > 3 and not http_level_fail:
                ips = resolve_via_doh(host)
                if ips:
                    if verbose:
                        print(f"[云端] {key} 常规线路失败, 改用 DoH 解析直连: "
                              f"{host} -> {', '.join(ips[:3])}")
                    t0 = time.time()
                    text = _fetch_by_ip(url, host, ips,
                                        (min(conn_to, remain), min(READ_TIMEOUT, remain)))
                    if text:
                        if verbose:
                            print(f"[云端] {key} DoH 直连获取成功: ({len(text)} 字节, "
                                  f"{time.time() - t0:.2f}s)")
                        cache_write(key, text)
                        return text, url, key, ""
                    last_err = f"[{key}] DoH 直连仍失败"

    _last_error[keys[0]] = last_err or "未知错误"
    return "", "", "", last_err or "未知错误"


def _fetch_text(key, verbose=True):
    """单笔记名获取 (兼容旧调用, 供 diag/测试使用)"""
    text, url, _used, err = _fetch_note([key] if isinstance(key, str) else key, verbose)
    return text, url, err


def read_note_live(note_id: str, address: str, pwd: str = "") -> tuple:
    """**只走网络**读笔记 (不落本地缓存兜底), 供"读-改-写"型调用方使用。

    与 Note.fetch_note_info() 的区别: 后者在全部网络源失败时会回退本地缓存 (对读方更友好),
    但写方拿着**可能过期的旧内容**去覆盖云端会丢数据 (2026-09-25 build.py 上传版本信息就踩了:
    服务器抖动返回 200 + 0 字节, 还被当成"笔记是空的", 直接抹掉云端几十个版本历史)。

    Returns:
        (内容, 实际生效的笔记名, 错误信息): 内容为空即读取失败, 调用方应当放弃写回。
    """
    try:
        note = Note(note_id, address, pwd)
        keys = note._candidate_keys()
    except Exception as e:
        return "", str(address or ""), f"构造笔记失败: {e}"
    text, _source, used, err = _fetch_note(keys)
    return (text or ""), (used or str(address or "")), (err or "")


# 写回 (与读取完全分开的一条链路)
def parse_write_response(r):
    """解析 /update/ 响应, 返回 (是否成功, 信息字典)

    约定成功响应: {"status": 1, ...}; 失败可能是 HTML 错误页(如 414/502)或空响应。
    """
    text = (r.text or "").strip()
    if not text:
        return False, {"error": f"HTTP {r.status_code} 空响应"}
    if text.startswith("<"):
        m = re.search(r"<title>(.*?)</title>", text, re.S | re.I)
        title = (m.group(1).strip() if m else "")
        if re.match(r"^\d{3}\b", title):        # 如 414 Request-URI Too Large
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
    """写回笔记内容 (key 不变, value 覆盖)。

    - 优先 **POST** (`key` 在 query, `value` 在 form body): 不受 URL 长度限制
    - 内容很小时再补一个 GET 兜底 (老接口习惯写法)
    - 连接类错误退避重试一次 (跨境线路瞬时 RST 很常见)

    Returns:
        dict: {'status': 1/0, 'error': str|None, 'method': str, 'req_id': str|None}
    """
    url = update_url or get_update_url()
    key = str(key or "")
    value = "" if value is None else str(value)
    if not key:
        return {"status": 0, "error": "笔记名为空", "method": "", "req_id": None}

    methods = ["POST"]
    if len(value) <= 4000:
        # 大内容用 GET 会被 414, 只有小内容才兜底
        methods.append("GET")

    last_err = ""
    for method in methods:
        for attempt in (1, 2):
            t0 = time.time()
            try:
                if method == "POST":
                    r = requests.post(url, params={"key": key}, data={"value": value},
                                      headers=_HEADERS, verify=False,
                                      timeout=(CONNECT_TIMEOUT, 60))
                else:
                    r = requests.get(url, params={"key": key, "value": value},
                                     headers=_HEADERS, verify=False,
                                     timeout=(CONNECT_TIMEOUT, 60))
                ok, info = parse_write_response(r)
                cost = time.time() - t0
                if ok:
                    print(f"[云端] {key} 写回成功 ({method}, {len(value)} 字节, {cost:.2f}s)")
                    return {"status": 1, "error": None, "method": method,
                            "req_id": info.get("req_id") if isinstance(info, dict) else None}
                last_err = str(info.get("error"))
                print(f"[云端] {key} 写回失败 ({method}): {last_err} ({cost:.2f}s)")
                # HTTP 层错误: 换个方法, 不重试
                break               
            except Exception as e:
                cost = time.time() - t0
                last_err = f"{type(e).__name__}: {str(e)[:140]}"
                print(f"[云端] {key} 写回第 {attempt} 次失败 ({method}): {last_err} ({cost:.2f}s)")
                if attempt == 1 and _is_conn_error(e):
                    time.sleep(0.4)
                    continue
                break
    return {"status": 0, "error": last_err or "未知错误", "method": "", "req_id": None}


# Note: 对外接口 (保持与旧实现兼容)
class Note:
    """云端笔记

    Args:
        id_name: 笔记标识 (如 'addon_info'), 缺省时用 address
        address: 云端笔记地址/键名 (如 'FaustLauncher.mod.info.v2')
        pwd: 密码 (保留字段)
        read_only: 只读标记 (保留字段)
    """

    def __init__(self, id_name=None, address="", pwd="", read_only=False):
        self.note_id = id_name if id_name else address
        self._requested = str(address or "")     # 配置里写的笔记名 (可能已过期)
        self.note_name = self._requested          # 实际使用的笔记名 (成功后会被自动纠正)
        self.pwd = pwd
        self.note_url = _build_url(get_note_bases()[0], self.note_name) if self.note_name else ""
        self.read_only = read_only
        self.note_content = ""
        self.req_id = None
        self.has_get = False

    def _candidate_keys(self):
        """候选笔记名 —— **配置里写什么就用什么, 不做任何后缀猜测**

        顺序 (只有这两条, 不加也不减任何后缀):
          1. 当前配置里的名字 (config/web_config.json)
          2. 构建时内嵌配置里的同名笔记 (仅当与上面不同: exe 旁边残留旧配置时的兜底)

        以前这里还会自动增删 `.v2` 变体, 并把"纠正后"的名字记进 cache/webnote/_keymap.json ——
        结果 FaustLauncher.version_info 明明没有 .v2 后缀, 打包版的日志里也会凭空冒出
        "FaustLauncher.version_info.v2" 白跑一趟请求 (2026-09-25 用户要求彻底去掉)。
        """
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
        """记下实际生效的笔记名 (后续读写都用它) """
        key = str(key or "").strip()
        if not key:
            return
        if key != self._requested:
            print(f"[云端] {self.note_id} 使用内嵌配置里的笔记名: {key} "
                  f"(本地配置写的是 {self._requested})")
        self.note_name = key

    def fetch_note_info(self, allow_refresh=False):
        """读取笔记内容 (多源 + 超时 + 笔记名自动纠正 + 本地缓存兜底)

        Returns:
            dict: {'note_content': str, 'note_id': str}
        """
        if not allow_refresh and self.has_get and self.note_content:
            return {"note_content": self.note_content, "note_id": self.note_name}

        keys = self._candidate_keys()

        # 同一次启动内复用 (进程内记忆): 重启一定重新请求, 不会看到过期内容
        if not allow_refresh:
            hit = memo_get(keys, MEMO_TTL)
            if hit:
                text, used, age = hit
                self._use_key(used)
                self.note_content = text
                self.has_get = True
                if age >= 2:
                    print(f"[云端] {self.note_id} 命中本次启动已有的内容 ({age:.0f}s 前, 不重复请求)")
                return {"note_content": self.note_content, "note_id": self.note_name}

        if self.has_get and not self.note_content:
            print(f"[云端] 尝试重新获取 {self.note_id} 内容…")

        text, source, used, err = _fetch_note(keys)
        if text:
            self._use_key(used)
            self.note_content = text
            self.note_url = source
            self.has_get = True
            memo_put(used, text)
            return {"note_content": self.note_content, "note_id": self.note_name}

        # 全部候选名 + 全部源都失败: 回退本地缓存 (取最新的一份; 磁盘缓存只在这里发挥作用)
        best = None
        for k in keys:
            cached, age = cache_read(k)
            if cached and (best is None or (age is not None and age < best[2])):
                best = (cached, k, age if age is not None else 1e18)
        if best:
            self._use_key(best[1])
            print(f"[云端] {self.note_id} 云端获取失败, 使用本地缓存 "
                  f"({_fmt_age(best[2])}前, 可能过期) | 原因: {err}")
            self.note_content = best[0]
            self.has_get = True
            memo_put(best[1], best[0])      # 避免同一次启动里反复等待超时
            return {"note_content": self.note_content, "note_id": self.note_name}

        print(f"[云端] {self.note_id} 获取失败, 无可用缓存 | 尝试过: {', '.join(keys)} | 原因: {err}")
        self.note_content = ""
        return {"note_content": "", "note_id": self.note_name}

    def update_note_content(self, new_content):
        """写回笔记内容 (下载计数 / 排序上传), 走独立的写回地址 (/update/, POST)"""
        result = write_note(self.note_name, new_content)
        self.note_content = new_content      # 内存保持最新, 后续排序/计数继续基于它
        memo_put(self.note_name, new_content)   # 同步进程内记忆, 避免后续读取又拿到旧内容
        if result.get("status") == 1:
            self.req_id = result.get("req_id")
            cache_write(self.note_name, new_content)
        else:
            print(f"[云端] {self.note_id} 写回未成功 (仅本地生效): {result.get('error')}")
        return result

    def delete_note(self):
        """清空笔记 (写回空内容)"""
        result = write_note(self.note_name, "")
        if result.get("status") == 1:
            cache_write(self.note_name, "")
        memo_clear()
        return result
