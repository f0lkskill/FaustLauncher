import os
import re
import json
import requests
import time
import threading
from urllib.parse import urljoin, urlparse, unquote

class RateLimiter:
    def __init__(self, rate_limit):
        """
        初始化速率限制器
        :param rate_limit: 速率限制，单位是秒（例如，每秒最多调用 1 次 API）
        """
        self.rate_limit = rate_limit
        self.last_request_time = 0  # 上一次调用 API 的时间

    def wait_if_needed(self):
        """
        检查是否需要等待，并暂停程序直到满足速率限制
        """
        current_time = time.time()  # 获取当前时间
        time_since_last_request = current_time - self.last_request_time

        # 如果时间间隔小于速率限制，就暂停等待
        if time_since_last_request < self.rate_limit:
            time.sleep(self.rate_limit - time_since_last_request)  # 暂停等待

        # 更新上一次调用 API 的时间
        self.last_request_time = time.time()

rate_limiter = RateLimiter(rate_limit=1)  # 每秒最多调用 1 次 API

headers = {
  'User-Agent': "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Mobile Safari/537.36",
}

LOGIN_URL = "https://pc.woozooo.com/account.php"
MYDISK_URL = "https://pc.woozooo.com/mydisk.php"
ACCOUNT_URL = "https://pc.woozooo.com/account.php"
DO_LOAD_URL = "https://pc.woozooo.com/doupload.php"
UPLOAD_URL = "https://pc.woozooo.com/html5up.php"
UPLOAD_TIMEOUT_SECONDS = 600

# 蓝奏云官方允许上传的文件格式
ALLOW_UP_TYPES = [
    'doc', 'docx', 'zip', 'rar', 'apk', 'ipa', 'txt', 'exe', '7z', 'e', 'z', 'ct', 'ke',
    'cetrainer', 'db', 'tar', 'pdf', 'w3x', 'epub', 'mobi', 'azw', 'azw3', 'osk', 'osz',
    'xpa', 'cpk', 'lua', 'jar', 'dmg', 'ppt', 'pptx', 'xls', 'xlsx', 'mp3',
    'iso', 'img', 'gho', 'ttf', 'ttc', 'txf', 'dwg', 'bat', 'imazingapp', 'dll', 'crx',
    'xapk', 'conf', 'deb', 'rp', 'rpm', 'rplib', 'mobileconfig', 'appimage', 'lolgezi',
    'fla', 'png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'ico', 'svg', 'psd'
]

# ============================================================
# 蓝奏云直链解析 (分享页 -> 可下载直链)
# ============================================================
# 云端数据库里的下载链接历史上写成第三方解析服务的地址:
#     https://lz.qaiu.top/parser?url=<分享链接>[&pwd=<密码>]
# 这里在本地把同一件事做掉, 不再依赖第三方解析服务:
#     1. 取分享页 —— 先过阿里云 WAF 的 acw_sc__v2 JS 挑战;
#     2. 从页面里读出 ajaxfile.php/ajaxm.php 接口、sign 与 kd;
#     3. POST downprocess 拿到 dom + url, 拼成 /file/<url> 直链;
#     4. 再请求该地址 (同样过 WAF), 拿到 302 后的真实文件直链 (时效性 URL)。
# 所有解析失败都只是退回原链接, 不影响已有下载流程。

def IsLanzouUrl(url):
    """判断是否蓝奏云分享链接, 或指向蓝奏云的解析服务链接"""
    if not url:
        return False
    inner, _ = ParseShareUrl(url)
    try:
        return bool(_lanzou_host_re.search(urlparse(inner).hostname or ""))
    except ValueError:
        return False


def ParseShareUrl(url, pwd=None):
    """把解析服务链接 (?url=<分享链接>&pwd=<密码>) 拆回 (分享链接, 密码)

    普通分享链接原样返回。
    """
    if not url:
        return url, pwd
    match = re.search(r"[?&](?:url|u)=([^&]+)", url)
    if not match:
        return url, pwd
    inner = unquote(match.group(1))
    if pwd:
        return inner, pwd
    pwd_match = re.search(r"[?&](?:pwd|p|password)=([^&]+)", url)
    return inner, (unquote(pwd_match.group(1)) if pwd_match else pwd)


def _ResolveOnce(session, share_url, pwd, timeout):
    """按给定密码解析一次 (失败返回 None)"""
    page_url = share_url
    resp = _RequestWithWaf(session, page_url, timeout=timeout)
    if resp.status_code != 200 or "html" not in (resp.headers.get("Content-Type") or "").lower():
        print("GetDirectLink 失败：分享页不可用(%s)" % resp.status_code)
        return None
    info = _ParseSharePage(resp.text, _OriginOf(page_url), pwd)
    if not info:
        # 无密码分享页把下载入口放在 <iframe src="/fn?..."> 里, 进去再找一次
        frame = _FindDownloadFrame(resp.text, _OriginOf(page_url))
        if frame:
            try:
                inner = _RequestWithWaf(session, frame, timeout=timeout,
                                        headers={"Referer": page_url})
            except requests.RequestException as e:
                print("GetDirectLink 失败：%s" % e)
                return None
            if inner.status_code == 200:
                page_url = frame
                info = _ParseSharePage(inner.text, _OriginOf(frame), pwd)
    if not info:
        print("GetDirectLink 失败：页面结构未匹配(可能是文件夹/新页面格式)")
        return None

    payload = _PostDownProcess(session, info["api"], info["data"], page_url, timeout)
    if not isinstance(payload, dict):
        if _CooldownRest() <= 0:
            print("GetDirectLink 失败：接口未返回数据")
        return None
    if str(payload.get("zt")) != "1":
        print("GetDirectLink 失败：%s" % (payload.get("inf") or payload.get("zt")))
        return None

    dom = str(payload.get("dom") or "").rstrip("/")
    path = str(payload.get("url") or "")
    if not dom or not path:
        print("GetDirectLink 失败：未取到 dom/url")
        return None
    return _FollowToFile(session, dom + "/file/" + path.lstrip("/"), page_url, timeout)


def GetDirectLink(url, pwd=None, session=None, timeout=(10, 30)):
    """把蓝奏云分享链接 (或指向它的解析服务链接) 解析成可下载直链

    :param url: 分享链接, 或 https://lz.qaiu.top/parser?url=<分享链接>&pwd=<密码>
    :param pwd: 分享密码 (可选; 解析服务链接里的 pwd 会自动取用)
    :param session: 可复用的 requests.Session (不传则用线程内默认会话)
    :return: 直链 (时效性 URL, 建议拿到后立刻下载); 解析失败返回 None
    """
    if not url or not IsLanzouUrl(url):
        return None
    share_url, pwd = ParseShareUrl(url, pwd)

    # 1) 持久缓存: 键就是调用方给的 url, 源 url 换了自然是新键 → 重新解析
    persisted = CachedDirectLink(url)
    if persisted:
        return persisted
    # 2) 本次会话的内存缓存
    cache_key = (share_url, pwd or "")
    cached = _CachedDirect(cache_key)
    if cached:
        return cached
    rest = _CooldownRest()
    if rest > 0:
        print("GetDirectLink 跳过：蓝奏云接口限流冷却中（约 %.0f 秒后恢复）" % rest)
        return None

    sess = session or _http_session()
    direct = _ResolveOnce(sess, share_url, pwd, timeout)
    if not direct and pwd and _CooldownRest() <= 0:
        # 条目里存的密码可能多余/已失效 (sign 一次性, 必须换一张新页面),
        # 不带密码再试一次
        direct = _ResolveOnce(sess, share_url, None, timeout)
        if direct:
            _CacheDirect((share_url, ""), direct)
    if direct:
        _CacheDirect(cache_key, direct)
        CacheDirectLink(url, direct)
    return direct


def ResolveDownloadUrl(url, pwd=None, session=None, log=None, retries=0, retry_wait=8.0):
    """下载前预处理: 蓝奏云链接解析成直链, 其他链接原样返回

    解析失败时返回原链接 (历史数据里的解析服务链接仍然可用), 永不抛异常。
    retries: 失败后的额外重试次数 (图标等可选项给 0, 用户主动点的下载给 2)
    注意返回的是时效性直链, 拿到后应立刻下载。
    """
    if not url:
        return url
    try:
        if not IsLanzouUrl(url):
            return url
        for attempt in range(retries + 1):
            if attempt:
                if log:
                    log("蓝奏云直链解析失败，%.0f 秒后重试（%d/%d）" % (retry_wait, attempt, retries))
                time.sleep(retry_wait)
            if log:
                # log("正在解析蓝奏云直链...")
                pass
            direct = GetDirectLink(url, pwd=pwd, session=session)
            if direct:
                if log:
                    log("蓝奏云直链解析成功")
                return direct
            rest = _CooldownRest()
            if rest > 0:
                # 接口限流: 重试只会白等, 直接回退原链接 (解析服务恢复时仍可用)
                if log:
                    log("蓝奏云接口限流中（约 %.0f 秒后恢复），请稍后再试" % rest)
                break
        if log:
            log("蓝奏云直链解析失败，回退原始链接")
    except Exception as e:
        print("ResolveDownloadUrl 异常：%s" % e)
    return url


# --- 解析结果持久化缓存 ---------------------------------------------
# 一次解析要打 4~5 个请求 (其中 downprocess 是最容易被频控的那个),
# 所以直链解析结果落盘保存:
#   * 键就是调用方给的原始 url —— 源 url 换了(重新上传/条目改链接) 自然是新键,
#     会重新解析, 不用靠 TTL 去猜链接还有没有效;
#   * 默认 25 分钟有效 (config/web_config.json -> lanzou.link_cache_ttl_sec, 0 = 永久);
#     蓝奏云直链约 30 分钟就失效, 所以过期即重新解析, 不会"先失败一次再重试";
#   * 蓝奏云的直链带签名, 过一段时间会失效 —— 那时下载会失败, 调用方调
#     InvalidateDirectLink(url) 丢掉这一条, 下一次立刻重新解析 (自愈)。
# 想整体重置: 删掉 cache/lanzou_links.json, 或调 ClearLinkCache()。

LINK_CACHE_FILE = os.path.join("cache", "lanzou_links.json")

_link_cache = {}
_link_cache_lock = threading.Lock()
_link_cache_save_lock = threading.Lock()
_link_cache_loaded = False


def _LinkCacheTTL():
    """直链缓存有效期(秒); 0 = 永久

    默认 25 分钟 —— 蓝奏云直链实测约 30 分钟失效, 提前一档自动刷新;
    可在 config/web_config.json -> lanzou.link_cache_ttl_sec 调。
    """
    try:
        from functions.base.web_config import get_lanzou_config
        raw = get_lanzou_config().get("link_cache_ttl_sec")
        if raw is not None:
            return max(float(raw), 0.0)
    except Exception:
        pass
    return DEFAULT_LINK_CACHE_TTL


def _LoadLinkCache():
    global _link_cache_loaded
    with _link_cache_lock:
        if _link_cache_loaded:
            return
        _link_cache_loaded = True
    try:
        with open(LINK_CACHE_FILE, encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception:
        return
    if not isinstance(data, dict):
        return
    cleaned = {}
    dropped = 0
    for key, item in data.items():
        if not isinstance(item, dict) or not item.get("direct"):
            dropped += 1
            continue
        age = _EntryAgeSeconds(item)
        if age is None or age > LINK_CACHE_KEEP_SEC:
            dropped += 1
            continue
        cleaned[key] = item
    with _link_cache_lock:
        _link_cache.update(cleaned)
    if dropped:
        print("蓝奏云直链缓存清理: 丢掉 %d 条无效/过旧条目" % dropped)
        _SaveLinkCache()


def _SaveLinkCache():
    """原子写: 先写临时文件再替换, 免得写到一半崩了把整个缓存弄坏

    临时文件名按线程区分(并发解析图标时多个线程各写各的), 替换再串行化 ——
    否则 Windows 上会出现 WinError 32 (另一个程序正在使用此文件)。
    """
    try:
        os.makedirs(os.path.dirname(LINK_CACHE_FILE) or ".", exist_ok=True)
        with _link_cache_lock:
            snapshot = dict(_link_cache)
        tmp = "%s.%d.tmp" % (LINK_CACHE_FILE, threading.get_ident())
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(snapshot, fh, ensure_ascii=False, indent=1)
        with _link_cache_save_lock:
            os.replace(tmp, LINK_CACHE_FILE)
    except Exception as e:
        print("蓝奏云直链缓存写入失败：%s" % e)


def _EntryAgeSeconds(item):
    """缓存条目的年龄(秒): 优先用写入时间 ts, 退而求其次用直链自带的 e (=签发时间)"""
    ts = item.get("ts")
    if ts:
        return max(time.time() - float(ts), 0.0)
    match = re.search(r"[?&]e=([0-9a-fA-F]{4,})", str(item.get("direct") or ""))
    if match:
        return max(time.time() - int(match.group(1), 16), 0.0)
    return None


def CachedDirectLink(url):
    """取持久缓存的直链; 超过有效期就丢掉并返回 None (调用方会自动重新解析)

    直链带签名, 约 30 分钟失效 —— 过期条目留着也没用, 顺手清掉。
    """
    if not url:
        return None
    _LoadLinkCache()
    with _link_cache_lock:
        item = _link_cache.get(url)
    if not isinstance(item, dict) or not item.get("direct"):
        return None
    ttl = _LinkCacheTTL()
    age = _EntryAgeSeconds(item)
    if age is None or (ttl and age > ttl):
        with _link_cache_lock:
            _link_cache.pop(url, None)
        _SaveLinkCache()
        return None
    return item["direct"]


def CacheDirectLink(url, direct):
    """把解析结果写进持久缓存 (源 url -> 直链)"""
    if not url or not direct:
        return
    _LoadLinkCache()
    with _link_cache_lock:
        _link_cache[url] = {"direct": direct, "ts": time.time()}
    _SaveLinkCache()


def InvalidateDirectLink(url):
    """丢掉某个源 url 的缓存 (下载发现直链失效时调用, 下次重新解析)

    持久缓存和本次会话的内存缓存都要清, 否则同一个失效直链会在进程内继续被命中。
    """
    if not url:
        return
    _LoadLinkCache()
    with _link_cache_lock:
        existed = _link_cache.pop(url, None)
    share_url, pwd = ParseShareUrl(url)
    with _acw_lock:
        _direct_cache.pop((share_url, pwd or ""), None)
        _direct_cache.pop((share_url, ""), None)
    if existed is not None:
        _SaveLinkCache()
        print("蓝奏云直链已失效，下次将重新解析：%s" % url[:90])


def ClearLinkCache():
    """清空全部直链缓存 (下次全部重新解析)"""
    _LoadLinkCache()
    with _link_cache_lock:
        count = len(_link_cache)
        _link_cache.clear()
    if count:
        _SaveLinkCache()
    print("蓝奏云直链缓存已清空 (%d 条)" % count)
    return count


def LinkCacheSize():
    _LoadLinkCache()
    with _link_cache_lock:
        return len(_link_cache)


def LooksLikeFileResponse(resp):
    """响应像"文件本体", 而不是解析服务回给我们的 JSON/HTML 错误页

    用于判断"解析服务链接直接下"的结果: 修复版解析服务 (lz0.qaiu.top) 会 302 到
    真文件 (requests 自动跟完, 拿到的就是文件); 老解析服务 (lz.qaiu.top) 已坏, 回
    200 + application/json 的 {"code":500,"msg":"解析异常"}。
    """
    if resp is None or resp.status_code != 200:
        return False
    ctype = (resp.headers.get("Content-Type") or "").lower()
    return not any(part in ctype for part in ("json", "html", "xml"))


def GetWithDirectLink(url, accept=None, timeout=(10, 30), session=None, **kwargs):
    """默认先本地解析成直链再 GET 取内容; 直链失效(或内容不合 accept) 时丢缓存重解析一次

    解析不出直链时 (ResolveDownloadUrl 把入参原样返回) 自动退回原链接 ——
    云端条目里的 lz0.qaiu.top 这类"修复版解析服务"链接本身就能下载 (GET 会 302
    到真文件), 所以解析失败也照样能拿到文件。

    :param accept: 可选回调 (response) -> bool, 返回 False 视为该直链不可用;
        不传时用 LooksLikeFileResponse 兜底判断 (JSON/HTML 错误页不算文件)
    :return: requests.Response (两次都不行时返回最后一次的响应, 可能为 None)
    """
    sess = session or _http_session()
    resolved = ResolveDownloadUrl(url, session=sess)
    resp = None
    for attempt in (1, 2):
        try:
            resp = sess.get(resolved, timeout=timeout, **kwargs)
        except requests.RequestException as e:
            print("GetWithDirectLink 请求失败：%s" % e)
            resp = None
        if resp is not None and (accept(resp) if accept else LooksLikeFileResponse(resp)):
            return resp
        if resp is not None:
            resp.close()
        if attempt == 2 or resolved == url:
            return resp
        # 直链可能已失效(过期/被顶掉): 丢掉缓存重新解析一次
        InvalidateDirectLink(url)
        resolved = ResolveDownloadUrl(url, session=sess)
    return resp


# --- 内部实现 --------------------------------------------------

# 阿里云 WAF acw_sc__v2 JS 挑战的固定置换表与异或密钥
_ACW_PERM = [0xf, 0x23, 0x1d, 0x18, 0x21, 0x10, 0x1, 0x26, 0xa, 0x9, 0x13, 0x1f, 0x28,
             0x1b, 0x16, 0x17, 0x19, 0xd, 0x6, 0xb, 0x27, 0x12, 0x14, 0x8, 0xe, 0x15,
             0x20, 0x1a, 0x2, 0x1e, 0x7, 0x4, 0x11, 0x5, 0x3, 0x1c, 0x22, 0x25, 0xc, 0x24]
_ACW_KEY = "3000176000856006061501533003690027800375"
_ACW_COOKIE_TTL = 1800

_DESKTOP_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

# 蓝奏云域名族 (lanzou/lanzoui/lanzoum/lanzout/lanzoub/lanzouw/lanzoux...)
_lanzou_host_re = re.compile(r"(^|\.)lanzou[\w-]*\.[a-z]{2,}$", re.I)

# --- 节流 / 限流冷却 / 解析结果缓存 ---------------------------------
# 蓝奏云 downprocess 接口有 IP 频控 (命中后返回 X-Tengine-Error:
# denied by http_ratelimit 与人机验证页)。这里统一节流, 一旦命中就进入冷却期,
# 期间不再继续撞墙, 避免把限流越撞越久。

_buckets = {}
_buckets_lock = threading.Lock()
_ratelimit_until = 0.0
_ratelimit_hits = 0
_direct_cache = {}

DEFAULT_MIN_INTERVAL = 1.5        # 额度用完后 downprocess 的补充间隔 (秒)
DEFAULT_BURST = 4                 # 一次允许的突发请求数 (一页 5 个图标可并行起步)
GET_BURST = 8                     # 分享页/下载页 GET: 基本放开
GET_INTERVAL = 0.1
RATELIMIT_COOLDOWN_BASE = 120.0   # 首次命中限流的冷却时长
RATELIMIT_COOLDOWN_MAX = 900.0    # 冷却时长上限 (连续命中会翻倍)
_COOLDOWN_FILE = os.path.join("cache", "lanzou_cooldown.json")  # 冷却状态跨重启保留
DIRECT_CACHE_TTL = 600.0          # 兜底: 未配置有效期时的会话内内存缓存时长
# 蓝奏云直链带签名, 实测约 30 分钟就失效(403)。所以缓存按 25 分钟有效:
# 用之前发现过期就自动重新解析, 不会"先失败一次再重试"。
DEFAULT_LINK_CACHE_TTL = 1500.0   # 25 分钟 (config -> lanzou.link_cache_ttl_sec)
LINK_CACHE_KEEP_SEC = 7 * 24 * 3600   # 缓存文件里最多保留 7 天没碰过的条目

_thread_local = threading.local()
_acw_cache = {}
_acw_lock = threading.Lock()


def _MinInterval():
    """蓝奏云请求最小间隔 (config/web_config.json → lanzou.min_interval_sec)"""
    try:
        from functions.base.web_config import get_lanzou_config
        raw = get_lanzou_config().get("min_interval_sec")
        if raw is not None:
            return max(float(raw), 0.0)
    except Exception:
        pass
    return DEFAULT_MIN_INTERVAL


class _TokenBucket:
    """令牌桶: 桶里先给 burst 个额度, 之后每 interval 秒回 1 个"""

    __slots__ = ("lock", "tokens", "last")

    def __init__(self, burst):
        self.lock = threading.Lock()
        self.tokens = float(burst)
        self.last = time.time()


def _Burst():
    """单次允许的突发请求数 (config/web_config.json -> lanzou.burst_requests)"""
    try:
        from functions.base.web_config import get_lanzou_config
        raw = get_lanzou_config().get("burst_requests")
        if raw is not None:
            return max(int(raw), 1)
    except Exception:
        pass
    return DEFAULT_BURST


def _BucketFor(host, burst):
    with _buckets_lock:
        bucket = _buckets.get(host)
        if bucket is None:
            bucket = _TokenBucket(burst)
            _buckets[host] = bucket
        return bucket


def _Throttle(host, burst=None, interval=None):
    """按 host 限速(令牌桶): 图标这类多线程解析能并行起步, 又不会持续冲击

    不同 host 各用一个桶, 互不阻塞; 桶里额度用完后按 interval 匀速补充。
    """
    if not host:
        return
    burst = float(_Burst() if burst is None else burst)
    interval = float(_MinInterval() if interval is None else interval)
    if burst < 1 and interval <= 0:
        return
    bucket = _BucketFor(host, burst)
    while True:
        with bucket.lock:
            now = time.time()
            bucket.tokens = (min(burst, bucket.tokens + (now - bucket.last) / interval)
                             if interval > 0 else burst)
            bucket.last = now
            if bucket.tokens >= 1:
                bucket.tokens -= 1
                return
            wait = (1 - bucket.tokens) * interval
        time.sleep(min(max(wait, 0.02), 0.25))


def _IsRateLimited(resp):
    """响应是不是蓝奏云的频控 / 人机验证页"""
    if "ratelimit" in (resp.headers.get("X-Tengine-Error") or ""):
        return True
    if resp.status_code == 407:
        return True
    if "html" not in (resp.headers.get("Content-Type") or "").lower():
        return False
    try:
        text = resp.text
    except Exception:
        return False
    return "aliyun_waf_aa" in text or "captchaV2.js" in text


def _NoteRateLimit():
    """记录一次限流, 进入(并逐步加长)冷却期"""
    global _ratelimit_until, _ratelimit_hits
    with _acw_lock:
        _ratelimit_hits += 1
        wait = min(RATELIMIT_COOLDOWN_BASE * _ratelimit_hits, RATELIMIT_COOLDOWN_MAX)
        _ratelimit_until = time.time() + wait
        _SaveCooldown()
    print("蓝奏云接口触发限流：%.0f 秒内不再尝试直链解析" % wait)


def _CooldownRest():
    """距冷却结束还有多少秒 (0 表示可以正常解析)"""
    return max(0.0, _ratelimit_until - time.time())


def _LoadCooldown():
    """读回上次的冷却状态: 启动器重启后不必重新撞一遍限流"""
    global _ratelimit_until, _ratelimit_hits
    try:
        with open(_COOLDOWN_FILE, encoding="utf-8") as fh:
            data = json.load(fh)
        until = float(data.get("until") or 0)
        if time.time() < until <= time.time() + RATELIMIT_COOLDOWN_MAX:
            _ratelimit_until = until
            _ratelimit_hits = int(data.get("hits") or 0)
            print("蓝奏云接口仍在限流冷却中（约 %.0f 秒后恢复）" % (until - time.time()))
    except Exception:
        pass


def _SaveCooldown():
    try:
        os.makedirs(os.path.dirname(_COOLDOWN_FILE), exist_ok=True)
        with open(_COOLDOWN_FILE, "w", encoding="utf-8") as fh:
            json.dump({"until": _ratelimit_until, "hits": _ratelimit_hits}, fh)
    except Exception:
        pass


def _CacheDirect(key, direct):
    ttl = _LinkCacheTTL() or DIRECT_CACHE_TTL
    with _acw_lock:
        _direct_cache[key] = (direct, time.time() + ttl)


def _CachedDirect(key):
    with _acw_lock:
        item = _direct_cache.get(key)
    if not item:
        return None
    direct, expire = item[0], item[1]
    if expire and expire < time.time():
        with _acw_lock:
            _direct_cache.pop(key, None)
        return None
    return direct


_LoadCooldown()


def _http_session():
    """线程内复用的 requests.Session (保留 WAF cookie, 少过一次挑战)"""
    sess = getattr(_thread_local, "session", None)
    if sess is None:
        sess = requests.Session()
        sess.headers.update({"User-Agent": _DESKTOP_UA, "Accept-Language": "zh-CN,zh;q=0.9"})
        _thread_local.session = sess
    return sess


def _AcwScV2(arg1):
    """由页面里的 arg1 算出 acw_sc__v2 cookie (置换 + 异或)"""
    ordered = [""] * len(_ACW_PERM)
    for index, ch in enumerate(arg1):
        for pos, value in enumerate(_ACW_PERM):
            if value == index + 1:
                ordered[pos] = ch
    shuffled = "".join(ordered)
    if len(shuffled) < len(_ACW_KEY):
        return None
    return "".join(format(int(shuffled[i:i + 2], 16) ^ int(_ACW_KEY[i:i + 2], 16), "02x")
                   for i in range(0, len(_ACW_KEY), 2))


def _RememberAcw(host, value):
    with _acw_lock:
        _acw_cache[host] = (value, time.time() + _ACW_COOKIE_TTL)


def _RecallAcw(host):
    with _acw_lock:
        item = _acw_cache.get(host)
    return item[0] if item and item[1] > time.time() else None


def _ApplyChallenge(session, resp, host):
    """响应是 WAF 挑战页时算出 cookie 写回会话, 返回是否命中挑战"""
    arg1 = _ChallengeArg1(resp)
    if not arg1:
        return False
    value = _AcwScV2(arg1)
    if not value:
        return False
    _RememberAcw(host, value)
    session.cookies.set("acw_sc__v2", value, domain=host, path="/")
    return True


def _RequestWithWaf(session, url, **kwargs):
    """GET, 命中阿里云 WAF 的 acw_sc__v2 挑战时自动求解并重试"""
    host = urlparse(url).hostname or ""
    cached = _RecallAcw(host)
    if cached and not session.cookies.get("acw_sc__v2", domain=host):
        session.cookies.set("acw_sc__v2", cached, domain=host, path="/")
    _Throttle(host, GET_BURST, GET_INTERVAL)
    resp = session.get(url, **kwargs)
    for _ in range(3):
        if _IsRateLimited(resp):
            _NoteRateLimit()
            return resp
        if not _ApplyChallenge(session, resp, host):
            break
        _Throttle(host, GET_BURST, GET_INTERVAL)
        resp = session.get(url, **kwargs)
    return resp


def _ChallengeArg1(resp):
    """响应是 WAF 挑战页时返回其中的 arg1, 否则 None"""
    if "html" not in (resp.headers.get("Content-Type") or "").lower():
        return None
    try:
        text = resp.text
    except Exception:
        return None
    if "acw_sc__v2" not in text:
        return None
    match = re.search(r"var\s+arg1\s*=\s*'([0-9A-Fa-f]{8,})'", text)
    return match.group(1) if match else None


def _Absolutize(target, origin):
    """把页面里的相对地址补成绝对地址"""
    if not target:
        return target
    if target.startswith("//"):
        return "https:" + target
    if target.startswith("/"):
        return (origin or "").rstrip("/") + target
    if target.startswith("http"):
        return target
    return urljoin((origin or "").rstrip("/") + "/", target)


def _OriginOf(url):
    """取 URL 的 scheme://host, 用于补全相对的接口地址"""
    return "{0.scheme}://{0.netloc}".format(urlparse(url))


def _LookupVar(html, name):
    """取页面里 var <name> = ... 的值

    字符串取最长的一次赋值 (页面常先声明空串再赋真值);
    数字取声明处的默认值 (后面的条件重赋值不参与)。
    """
    name_re = re.escape(name)
    strings = (re.findall(r"var\s+%s\s*=\s*'([^']*)'" % name_re, html)
               + re.findall(r'var\s+%s\s*=\s*"([^"]*)"' % name_re, html))
    if strings:
        return max(strings, key=len)
    numbers = re.findall(r"var\s+%s\s*=\s*(\d+)" % name_re, html)
    return int(numbers[0]) if numbers else None


def _ParseSubmitData(html, pwd=None):
    """还原页面 $.ajax 里 data 对象的提交字段 (逐个求值: 字面量 / var / pwd / 数字)

    蓝奏云会时不时在 data 里加减字段 (websignkey / signs / websign / ves ...),
    直接照页面自己的对象还原, 比只认 sign+kd 稳固得多。
    """
    block = re.search(r"data\s*:\s*\{(.*?)\}", html, re.S)
    if not block:
        return None
    pattern = (r"['\"]?([A-Za-z_$][\w$]*)['\"]?\s*:\s*"
               r"(?:'([^']*)'|\"([^\"]*)\"|\b(pwd)\b|([A-Za-z_$][\w$]*)|(\d+))")
    data = {}
    for item in re.finditer(pattern, block.group(1)):
        key = item.group(1)
        if item.group(2) is not None:
            data[key] = item.group(2)
        elif item.group(3) is not None:
            data[key] = item.group(3)
        elif item.group(4):        # 'p':pwd
            if pwd:
                data[key] = pwd
        elif item.group(5):        # 变量引用
            value = _LookupVar(html, item.group(5))
            if value is not None:
                data[key] = value
        elif item.group(6) is not None:
            data[key] = int(item.group(6))
    return data or None


def _FindDownloadFrame(html, origin):
    """无密码分享页把下载入口放在 <iframe src="/fn?..."> 里, 取出该地址"""
    match = re.search(r"<iframe[^>]+src=['\"]([^'\"]*?/fn\?[^'\"]*)['\"]", html)
    return _Absolutize(match.group(1), origin) if match else None


def _ParseSharePage(html, origin, pwd=None):
    """从分享页/下载页提取 {api: 提交地址, data: 提交字段}"""
    match = (re.search(r"url\s*:\s*['\"]([^'\"]*(?:ajaxfile|ajaxm)\.php[^'\"]*)['\"]", html)
             or re.search(r"['\"]([^'\"]*(?:ajaxfile|ajaxm)\.php\?file=\d+[^'\"]*)['\"]", html))
    if not match:
        return None
    api = _Absolutize(match.group(1), origin)

    data = _ParseSubmitData(html, pwd)
    if not data:
        data = _ParseSignKd(html, pwd)
    if not data:
        return None
    return {"api": api, "data": data}


def _ParseSignKd(html, pwd=None):
    """兜底: data 对象认不出时, 只按 sign/kd 拼一份提交字段"""
    sign = None
    literal = re.search(r"['\"]sign['\"]\s*:\s*['\"]([^'\"]+)['\"]", html)
    if literal:
        sign = literal.group(1)
    else:
        var_ref = re.search(r"['\"]sign['\"]\s*:\s*([A-Za-z_$][\w$]*)", html)
        if var_ref:
            sign = _LookupVar(html, var_ref.group(1))
    if not sign:
        return None
    kd = 1
    kd_ref = re.search(r"['\"]kd['\"]\s*:\s*([A-Za-z_$][\w$]*|\d+)", html)
    if kd_ref:
        raw = kd_ref.group(1)
        value = int(raw) if raw.isdigit() else _LookupVar(html, raw)
        if value is not None:
            kd = value
    data = {"action": "downprocess", "sign": sign, "kd": kd}
    if pwd:
        data["p"] = pwd
    return data


def _PostDownProcess(session, api, data, referer, timeout):
    """POST downprocess, 返回解析后的 JSON (失败返回 None)"""
    headers = {"Referer": referer, "X-Requested-With": "XMLHttpRequest"}
    host = urlparse(api).hostname or ""
    cached = _RecallAcw(host)
    if cached and not session.cookies.get("acw_sc__v2", domain=host):
        session.cookies.set("acw_sc__v2", cached, domain=host, path="/")
    try:
        _Throttle(host)          # downprocess: 最容易被频控, 用配置的间隔 + 突发额度
        resp = session.post(api, data=data, timeout=timeout, headers=headers)
        for _ in range(3):
            if _IsRateLimited(resp):
                _NoteRateLimit()
                return None
            # 挑战页必须用 POST 重放 (不能退回 GET)
            if not _ApplyChallenge(session, resp, host):
                break
            _Throttle(host)
            resp = session.post(api, data=data, timeout=timeout, headers=headers)
    except requests.RequestException as e:
        print("_PostDownProcess 请求失败：%s" % e)
        return None
    try:
        return json.loads(resp.text)
    except (ValueError, TypeError):
        return None


def _FollowToFile(session, file_url, referer, timeout):
    """请求 /file/ 地址, 取 302 后的真实文件直链 (200 直接返回该地址)"""
    try:
        resp = _RequestWithWaf(session, file_url, timeout=timeout, allow_redirects=False,
                               stream=True, headers={"Referer": referer})
    except requests.RequestException as e:
        print("_FollowToFile 请求失败：%s" % e)
        return None
    try:
        if resp.status_code in (301, 302, 303, 307, 308):
            location = resp.headers.get("Location")
            return urljoin(file_url, location) if location else None
        if resp.status_code == 200 and \
                "html" not in (resp.headers.get("Content-Type") or "").lower():
            # 直接返回文件本体: 该地址即直链 (但需要本次会话的 WAF cookie)
            return file_url
        return None
    finally:
        resp.close()


def PrepareData(url,pwd,pg=1):
    try:
        response = requests.get(url, headers=headers, timeout=(10, 30))
    except requests.RequestException as e:
        print("PrepareData 请求失败：%s" % e)
        return False
    # response = requests.get(url, headers=headers,verify=False)
    # script_content = '''
    # <script type="text/javascript">
            # var indwyr ='curl';
            # document.title = indwyr;
    # 　　        var pwd;
            # var pgs;
            # var ibh8v5 = '1739025066';
            # var _hfkwy = 'a74a9dfd4d87aacbfb613f957a4aa132';
            # pgs =1;
            # function file(){
                    # var pwd = document.getElementById('pwd').value;
            # $('#sub').val("提交中..."); 
                    # $.ajax({
                            # type : 'post',
                            # url : '/filemoreajax.php?file=10506909',
                            # data : { 
                            # 'lx':2,
                            # 'fid':10506909,
                            # 'uid':'3499274',
                            # 'pg':pgs,
                            # 'rep':'0',
                            # 't':ibh8v5,
                            # 'k':_hfkwy,
                            # 'up':1,
                                                    # 'ls':1,
                            # 'pwd':pwd                        }
    # '''
    script_content=response.text
    # print(response.text)
    t = None
    match = re.search(r"'t':([^,]+)", script_content)
    if match:
        t = match.group(1)
        # print(t)
        match = re.search(r"var "+t+r" = '([^']+)'", script_content)
        if match:
            t = match.group(1)
            # print(t)
        else:
            print("没有找到 t 的值")
            t = None
    else:
        print("没有找到 t(raw) 的值")

    k = None
    match = re.search(r"'k':([^,]+)", script_content)
    if match:
        k = match.group(1)
        # print(k)
        match = re.search(r"var "+k+r" = '([^']+)'", script_content)
        if match:
            k = match.group(1)
            # print(k)
        else:
            print("没有找到 k 的值")
            k = None
    else:
        print("没有找到 k(raw) 的值")

    fid = None
    match = re.search(r"'fid':(\d+)", script_content)
    if match:
        fid = match.group(1)
        # print(fid)
    else:
        print("没有找到 fid 的值")

    uid = None
    match = re.search(r"'uid':'([^']+)'", script_content)
    if match:
        uid = match.group(1)
        # print(uid)
    else:
        print("没有找到 uid 的值")

    lx = None
    match = re.search(r"'lx':(\d+)", script_content)
    if match:
        lx = match.group(1)
        # print(lx)
    else:
        print("没有找到 lx 的值")

    rep = None
    match = re.search(r"'rep':'([^']+)'", script_content)
    if match:
        rep = match.group(1)
        # print(rep)
    else:
        print("没有找到 rep 的值")

    up = None
    match = re.search(r"'up':(\d+)", script_content)
    if match:
        up = match.group(1)
        # print(up)
    else:
        print("没有找到 up 的值")

    _is = None
    match = re.search(r"'ls':(\d+)", script_content)
    if match:
        _is = match.group(1)
        # print(_is)
    else:
        print("没有找到 is 的值")

    if None in (t, k, fid, uid, lx, rep, up, _is):
        print("PrepareData 失败：页面结构未匹配（t/k/fid/uid/lx/rep/up/ls 中有缺失）")
        return False

    # 模拟的请求数据
    data = {
        'lx': lx,
        'fid': int(fid), # type: ignore
        'uid': uid,
        'pg': pg,
        'rep': rep,
        't': t,
        'k': k,
        'up': up,
        'ls': _is,
        'pwd': pwd
    }
    return data

def Get_final_link(_id):
    try:
        response = requests.get("https://wwjn.lanzout.com/tp/"+_id,headers=headers,timeout=(10, 30))
    except requests.RequestException as e:
        print("Get_final_link 请求失败：%s" % e)
        return None
    # response = requests.get("https://wwjn.lanzout.com/tp/"+_id,headers=headers,verify=False)
    # print("响应内容：", response.text)
    vkjxld = None
    match = re.search(r"var vkjxld = '([^']+)';", response.text)
    if match:
        vkjxld = match.group(1)
        # print(vkjxld)
    else:
        print("没有找到 vkjxld 的值")

    hyggid = None
    match = re.search(r"var hyggid = '([^']+)';", response.text)
    if match:
        hyggid = match.group(1)
        # print(hyggid)
    else:
        print("没有找到 hyggid 的值")

    if vkjxld is None or hyggid is None:
        return None

    try:
        response = requests.get(vkjxld+hyggid,headers=headers,timeout=(10, 30))
    except requests.RequestException as e:
        print("Get_final_link 请求失败：%s" % e)
        return None
    # response = requests.get(vkjxld+hyggid,headers=headers,verify=False)
    # print(response.text)

    match = re.search(r'<a href="(https?://[^"]+)"', response.text)

    if match:
        final_link = match.group(1)  # 提取捕获组的内容
        return final_link
        # print("提取到的链接为：")
        # print(final_link)
    else:
        print("没有找到链接")
        return None

def GetFileListByData(data,pg):
    url = 'https://wwjn.lanzout.com/filemoreajax.php?file='+str(data["fid"])
    data["pg"] = pg
    try:
        response = requests.post(url, data=data,headers=headers,timeout=(10, 30))
    except requests.RequestException as e:
        print("GetFileListByData 请求失败：%s" % e)
        return None
    if response.status_code==401:#因文件夹访问过频繁，蓝奏云会ban掉所有访问
        raise RuntimeError("401,请过段时间再试")
    try:
        j=json.loads(response.text)
    except (ValueError, TypeError) as e:
        print("GetFileListByData 响应解析失败：%s" % e)
        return None
    # print(response.text)
    if j["zt"]==1:
        return j["text"]
    elif j["zt"]==2:
        return []
    else:
        return None

def GetFileListByUrl(url,pwd='',pg=1):
    data=PrepareData(url, pwd,1)
    if data is False:
        print("GetFileListByUrl 失败：PrepareData 未返回有效数据")
        return []
    result = []
    for i in range(1,pg+1):
        for retry in range(0,3):  # 最多重试3次
            rate_limiter.wait_if_needed()  # 检查是否需要等待
            l=GetFileListByData(data,i)
            if l is not None:
                break
        if l is None:
            print(f"获取第 {i} 页失败（已重试3次）")
            break
        if isinstance(l, list):
            result += l
        else:
            print(f"获取第 {i} 页返回异常数据：{type(l).__name__}")
    return result

def GetAllFileListByUrl(url,pwd=''):
    lists=[]
    pg=1
    data=PrepareData(url, pwd)
    if data is False:
        print("GetAllFileListByUrl 失败：PrepareData 未返回有效数据")
        return []

    retry=0
    while retry<=3:
        rate_limiter.wait_if_needed()  # 检查是否需要等待
        l=GetFileListByData(data,pg)
        # print(f"pg={pg}")
        # print(f"API called at {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())}")

        if isinstance(l, list) and not l:#空列表，已经遍历完了
            return lists
        if l is None:#失败
            retry+=1
            print(f"获取第 {pg} 页失败（第 {retry} 次重试）")
            continue
        else:#成功
            lists+=l
            retry=0
            pg+=1
    print("获取文件列表失败：已重试 3 次")
    return []
def _CheckLogin(session):
    try:
        response = session.get(MYDISK_URL, headers=headers, timeout=(10, 30))
    except requests.RequestException:
        return False
    return "网盘用户登录" not in response.text

def Login(username, password):
    """
    使用账号密码登录蓝奏云 [已弃用]
    蓝奏云已取消密码登录，仅对部分老账号有效，建议改用 LoginByCookie
    :return: 登录成功的 requests.Session（含 cookie），失败返回 False
    """
    session = requests.Session()
    try:
        html = session.get(ACCOUNT_URL, headers=headers, timeout=(10, 30))
    except requests.RequestException as e:
        print("Login 请求失败：%s" % e)
        return False
    formhash = re.search(r'name="formhash" value="([^"]+)"', html.text)
    if not formhash:
        print("登录失败：页面未包含 formhash（密码登录可能已失效）")
        return False
    login_data = {
        "task": "3",
        "setSessionId": "",
        "setToken": "",
        "setSig": "",
        "setScene": "",
        "uid": username,
        "pwd": password,
        "formhash": formhash.group(1),
    }
    phone_headers = headers.copy()
    phone_headers["User-Agent"] = "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Mobile Safari/537.36"
    try:
        response = session.post(MYDISK_URL, data=login_data, headers=phone_headers, timeout=(10, 30))
    except requests.RequestException as e:
        print("Login 请求失败：%s" % e)
        return False
    try:
        j = json.loads(response.text)
    except (ValueError, TypeError) as e:
        print("Login 响应解析失败：%s" % e)
        return False
    if "成功" not in j.get("info", ""):
        print("登录失败：%s" % j.get("info"))
        return False
    print("登录成功")
    return session

def LoginByCookie(cookie):
    """
    使用浏览器登录后的 cookie 登录（推荐方式）
    :param cookie: dict，至少包含 phpdisk_info 与 ylogin（可选 PHPSESSID）
    :return: 登录成功的 requests.Session，失败返回 False
    """
    session = requests.Session()
    session.cookies.update(cookie)
    if not _CheckLogin(session):
        print("登录失败：cookie 已失效")
        return False
    print("登录成功")
    return session

def _SetFolderID(session, folder_id):
    """
    切换上传的目标文件夹：蓝奏云通过 cookie 中的 folder_id_c 指定上传目录，
    html5up.php 上传时即按该值写入对应文件夹。-1 表示根目录
    :return: 恒为 True
    """
    try:
        session.post(DO_LOAD_URL, data={'task': '47', 'folder_id': str(folder_id)}, headers=headers, timeout=(10, 30))
    except requests.RequestException as e:
        print("_SetFolderID 请求失败：%s" % e)
    session.cookies.set("folder_id_c", str(folder_id))
    return True

def GetFolderList(session, folder_id=-1):
    """
    获取指定文件夹下的子文件夹列表 (doupload.php task=47, 条目含 fol_id/name)
    :param session: 已登录的 requests.Session
    :param folder_id: 父文件夹 id，默认 -1（根目录）
    :return: [{'id': str, 'name': str}, ...]；失败返回 None
    """
    try:
        response = session.post(DO_LOAD_URL, data={'task': '47', 'folder_id': str(folder_id)},
                                headers=headers, timeout=(10, 30))
        j = json.loads(response.text)
    except (requests.RequestException, ValueError, TypeError) as e:
        print("GetFolderList 请求失败：%s" % e)
        return None
    if j.get("zt") == 1 and isinstance(j.get("text"), list):
        return [{"id": str(f.get("fol_id")), "name": f.get("name")} for f in j["text"]]
    if j.get("zt") == 2:  # 无子文件夹 (info 仅为面包屑)
        return []
    print("GetFolderList 返回异常：%s" % j)
    return None

def CreateFolder(session, folder_name, parent_id=-1):
    """
    创建文件夹 (task=2, 依次尝试 mydisk.php / doupload.php)
    :param session: 已登录的 requests.Session
    :param folder_name: 文件夹名称
    :param parent_id: 父文件夹 id，默认 -1（根目录）
    :return: 新文件夹 id (str)；失败返回 None
    """
    data = {'task': '2', 'folder_name': folder_name, 'folder_description': '', 'folder_id': str(parent_id)}
    last_err = None
    for url in (MYDISK_URL, DO_LOAD_URL):
        try:
            response = session.post(url, data=data, headers=headers, timeout=(10, 30))
            j = json.loads(response.text)
        except (requests.RequestException, ValueError, TypeError) as e:
            last_err = e
            continue
        if j.get("zt") == 1:
            text = j.get("text")
            if isinstance(text, dict) and text.get("id") is not None:
                return str(text["id"])
            if isinstance(text, (int, str)):
                return str(text)
            if isinstance(text, list) and text:
                return str(text[0].get("id"))
        last_err = "zt != 1: %s" % j
    print("CreateFolder 失败：%s" % last_err)
    return None

def GetOrCreateFolder(session, folder_name, parent_id=-1):
    """按名称查找文件夹 (根目录及其一级子目录), 不存在时才创建; 返回文件夹 id (str) 或 None"""
    folders = GetFolderList(session, parent_id)
    if folders:
        for f in folders:
            if f.get("name") == folder_name:
                return f.get("id")
        # 根目录下找不到时, 在一级子目录中继续找, 避免对已有子文件夹重复创建
        if str(parent_id) in ("-1", ""):
            for f in folders:
                subs = GetFolderList(session, f.get("id")) # type: ignore
                if subs:
                    for s in subs:
                        if s.get("name") == folder_name:
                            return s.get("id")
    return CreateFolder(session, folder_name, parent_id)

class _ProgressReader:
    """可计算进度的文件读取器 (requests 通过 read() 读取, len() 提供 Content-Length)"""

    def __init__(self, path, progress_callback=None):
        self.f = open(path, "rb")
        self.size = os.path.getsize(path)
        self.sent = 0
        self.cb = progress_callback

    def read(self, n=-1):
        data = self.f.read(n)
        self.sent += len(data)
        if self.cb:
            try:
                self.cb(min(self.sent / self.size, 1.0) if self.size else 0.0)
            except Exception:
                pass
        return data

    def __len__(self):
        return self.size

    def close(self):
        self.f.close()

def UploadFile(session, file_path, folder_id=-1, progress_callback=None, max_size_mb=66):
    """
    上传单个文件到蓝奏云指定文件夹（需先调用 Login / LoginByCookie）
    :param session: 已登录的 requests.Session
    :param file_path: 本地文件路径（建议绝对路径）
    :param folder_id: 目标文件夹 id，默认 -1（根目录）
    :param progress_callback: 可选回调(progress: float 0.0~1.0)，用于显示上传进度
    :param max_size_mb: 单文件大小上限 (MB)，默认 66（该账号实测上传上限，VIP 可在
                        web_config.json 的 lanzou.max_size_mb 调整）
    :return: {"status": 1, "msg": "success", "f_id": 文件id, "share_url": 分享链接} 成功；
             {"status": 0, "msg": 错误信息} 失败
    """
    ret = {"status": 0, "msg": "", "f_id": None}
    if not os.path.isfile(file_path):
        ret["msg"] = "%s 不是一个文件" % file_path
        return ret
    filename = os.path.basename(file_path)
    file_type = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if file_type not in ALLOW_UP_TYPES:
        ret["msg"] = "蓝奏云不支持上传该格式：%s" % file_type
        return ret
    size = os.path.getsize(file_path)
    if size == 0:
        ret["msg"] = "不能上传空文件"
        return ret
    limit = max(int(max_size_mb or 100), 1) * 1024 * 1024
    if size > limit:
        ret["msg"] = "文件 %.1f MB 超过蓝奏云单文件上限 %d MB（可在 web_config.json 的 lanzou.max_size_mb 调整）" \
                     % (size / 1024.0 / 1024.0, max_size_mb)
        return ret
    if not _SetFolderID(session, folder_id):
        ret["msg"] = "无法定位上传文件夹"
        return ret

    _SetFolderID(session, folder_id)

    upload_headers = headers.copy()
    upload_headers["Referer"] = "https://pc.woozooo.com/mydisk.php"
    upload_headers["Origin"] = "https://pc.woozooo.com"
    data = {
        "task": "1",
        "vie": "2",
        "ve": "2",
        "id": "WU_FILE_0",
        "folder_id_bb_n": str(folder_id),
        "name": filename,
    }

    try:
        f = _ProgressReader(file_path, progress_callback)
    except OSError as e:
        ret["msg"] = "无法打开文件：%s" % e
        return ret
    try:
        files = {"upload_file": (filename, f, "application/octet-stream")}
        # requests/urllib3 在发送请求体时可能沿用 connect timeout 作为 socket
        # 写超时。30 秒对几十 MB 的慢速上行太短，会在进度 100% 附近误报
        # "write operation timed out"。上传与服务端处理均允许最多 10 分钟。
        response = session.post(UPLOAD_URL, data=data, files=files,
                                headers=upload_headers,
                                timeout=(UPLOAD_TIMEOUT_SECONDS, UPLOAD_TIMEOUT_SECONDS))
    except requests.exceptions.ReadTimeout:
        ret["msg"] = "上传超时：长时间未收到服务器响应（网络过慢或文件过大，请重试；单文件上限 %d MB）" % max_size_mb
        return ret
    except requests.exceptions.ConnectionError as e:
        try:
            sent_mb = f.sent / 1024.0 / 1024.0
            total_mb = f.size / 1024.0 / 1024.0
            sent_hint = "已发送 %.1f/%.1f MB" % (sent_mb, total_mb)
        except Exception:
            sent_hint = "已发送部分数据"
        if size >= limit * 0.9:
            ret["msg"] = "上传被中断（%s）：%s。文件已接近账号上传上限 %d MB，蓝奏云可能拒收该文件" \
                         % (sent_hint, e, max_size_mb)
        else:
            ret["msg"] = "上传连接中断（%s）：%s。文件大小未达到配置上限 %d MB，通常是上行网络或蓝奏云响应超时，请稍后重试" \
                         % (sent_hint, e, max_size_mb)
        return ret
    except requests.RequestException as e:
        ret["msg"] = "UploadFile 请求失败：%s" % e
        return ret
    finally:
        f.close()

    try:
        j = json.loads(response.text)
    except (ValueError, TypeError) as e:
        ret["msg"] = "UploadFile 响应解析失败：%s" % e
        return ret
    if j.get("zt") != 1:
        ret["msg"] = j.get("info") or "上传失败"
        return ret
    try:
        first = j["text"][0]
        ret["f_id"] = first.get("id")
        ret["share_url"] = str(first.get("is_newd", "")).rstrip("/") + "/" + first.get("f_id", "")
    except (KeyError, IndexError, TypeError):
        ret["f_id"] = None
        ret["share_url"] = None
    ret["status"] = 1
    ret["msg"] = "success"
    return ret

if __name__ == "__main__":
    print('\n\n')

    # 直链解析示例 (不依赖第三方解析服务):
    # link = "https://lz.qaiu.top/parser?url=https://folkskill.lanzoum.com/irAGt3iha71c&pwd=3z4n"
    # print(GetDirectLink(link))
    # print(ResolveDownloadUrl(link))

    # filelists=GetAllFileListByUrl("https://wwyi.lanzoub.com/b014wpn02j",'fib6')
    # print(filelists)

    # 上传示例（先登录，推荐使用浏览器 cookie 登录）：
    # session = LoginByCookie({"phpdisk_info": "...", "ylogin": "..."})
    # if not session:
    #     os._exit(1)
    # result = UploadFile(session, r"D:\path\to\file.zip", folder_id=-1)
    # print(result)

    print(ResolveDownloadUrl("https://folkskill.lanzouc.com/iApEl49wry0h"))