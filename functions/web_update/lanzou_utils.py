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
    origin = "{0.scheme}://{0.netloc}".format(urlparse(share_url))
    sess = session or _http_session()

    resp = _RequestWithWaf(sess, share_url, timeout=timeout)
    if resp.status_code != 200 or "html" not in (resp.headers.get("Content-Type") or "").lower():
        print("GetDirectLink 失败：分享页不可用(%s)" % resp.status_code)
        return None
    info = _ParseSharePage(resp.text, origin)
    if not info:
        print("GetDirectLink 失败：分享页结构未匹配(可能是文件夹/新页面格式)")
        return None

    data = {"action": "downprocess", "sign": info["sign"], "kd": info["kd"]}
    if pwd:
        data["p"] = pwd
    payload = _PostDownProcess(sess, info["api"], data, share_url, timeout)
    if not isinstance(payload, dict) or str(payload.get("zt")) != "1":
        # 部分链接不接受 p 字段, 或密码写错; 再试一次不带 p
        if "p" in data:
            payload = _PostDownProcess(sess, info["api"],
                                       {k: v for k, v in data.items() if k != "p"},
                                       share_url, timeout)
    if not isinstance(payload, dict) or str(payload.get("zt")) != "1":
        print("GetDirectLink 失败：%s" % (payload.get("inf") if isinstance(payload, dict) else payload))
        return None

    dom = str(payload.get("dom") or "").rstrip("/")
    path = str(payload.get("url") or "")
    if not dom or not path:
        print("GetDirectLink 失败：未取到 dom/url")
        return None
    file_url = dom + "/file/" + path.lstrip("/")
    return _FollowToFile(sess, file_url, share_url, timeout)


def ResolveDownloadUrl(url, pwd=None, session=None, log=None):
    """下载前预处理: 蓝奏云链接解析成直链, 其他链接原样返回

    解析失败时返回原链接 (历史数据里的解析服务链接仍然可用), 永不抛异常。
    注意返回的是时效性直链, 拿到后应立刻下载。
    """
    if not url:
        return url
    try:
        if not IsLanzouUrl(url):
            return url
        if log:
            log("正在解析蓝奏云直链...")
        direct = GetDirectLink(url, pwd=pwd, session=session)
        if direct:
            if log:
                log("蓝奏云直链解析成功")
            return direct
        if log:
            log("蓝奏云直链解析失败, 回退原始链接")
    except Exception as e:
        print("ResolveDownloadUrl 异常：%s" % e)
    return url


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

_thread_local = threading.local()
_acw_cache = {}
_acw_lock = threading.Lock()


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


def _RequestWithWaf(session, url, **kwargs):
    """GET, 命中阿里云 WAF 的 acw_sc__v2 挑战时自动求解并重试"""
    host = urlparse(url).hostname or ""
    cached = _RecallAcw(host)
    if cached and not session.cookies.get("acw_sc__v2", domain=host):
        session.cookies.set("acw_sc__v2", cached, domain=host, path="/")
    resp = session.get(url, **kwargs)
    for _ in range(3):
        arg1 = _ChallengeArg1(resp)
        if not arg1:
            break
        value = _AcwScV2(arg1)
        if not value:
            break
        _RememberAcw(host, value)
        session.cookies.set("acw_sc__v2", value, domain=host, path="/")
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


def _ParseSharePage(html, origin):
    """从分享页提取 {接口地址, sign, kd}"""
    match = (re.search(r"url\s*:\s*['\"]([^'\"]*(?:ajaxfile|ajaxm)\.php[^'\"]*)['\"]", html)
             or re.search(r"['\"]([^'\"]*(?:ajaxfile|ajaxm)\.php\?file=\d+[^'\"]*)['\"]", html))
    if not match:
        return None
    api = match.group(1)
    if api.startswith("//"):
        api = "https:" + api
    elif api.startswith("/"):
        api = origin.rstrip("/") + api

    sign = None
    literal = re.search(r"['\"]sign['\"]\s*:\s*['\"]([^'\"]+)['\"]", html)
    if literal:
        sign = literal.group(1)
    else:
        var_ref = re.search(r"['\"]sign['\"]\s*:\s*([A-Za-z_$][\w$]*)", html)
        if var_ref:
            name = re.escape(var_ref.group(1))
            var_value = (re.search(r"var\s+%s\s*=\s*'([^']*)'" % name, html)
                         or re.search(r'var\s+%s\s*=\s*"([^"]*)"' % name, html))
            if var_value:
                sign = var_value.group(1)
    if not sign:
        return None

    kd = 1
    kd_ref = re.search(r"['\"]kd['\"]\s*:\s*([A-Za-z_$][\w$]*|\d+)", html)
    if kd_ref:
        raw = kd_ref.group(1)
        if raw.isdigit():
            kd = int(raw)
        else:
            var_value = re.search(r"var\s+%s\s*=\s*(\d+)" % re.escape(raw), html)
            if var_value:
                kd = int(var_value.group(1))
    return {"api": api, "sign": sign, "kd": kd}


def _PostDownProcess(session, api, data, referer, timeout):
    """POST downprocess, 返回解析后的 JSON (失败返回 None)"""
    try:
        resp = session.post(api, data=data, timeout=timeout,
                            headers={"Referer": referer, "X-Requested-With": "XMLHttpRequest"})
    except requests.RequestException as e:
        print("_PostDownProcess 请求失败：%s" % e)
        return None
    if _ChallengeArg1(resp):
        resp = _RequestWithWaf(session, api, timeout=timeout, data=data,
                               headers={"Referer": referer,
                                        "X-Requested-With": "XMLHttpRequest"})
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
                subs = GetFolderList(session, f.get("id"))
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

    # filelists=GetAllFileListByUrl("https://wwyi.lanzoub.com/b014wpn02j",'fib6')
    # print(filelists)

    # 上传示例（先登录，推荐使用浏览器 cookie 登录）：
    # session = LoginByCookie({"phpdisk_info": "...", "ylogin": "..."})
    # if not session:
    #     os._exit(1)
    # result = UploadFile(session, r"D:\path\to\file.zip", folder_id=-1)
    # print(result)
