import os
import re
import json
import requests
import time

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
UPLOAD_URL = "https://pc.woozooo.com/fileup.php"

# 蓝奏云官方允许上传的文件格式
ALLOW_UP_TYPES = [
    'doc', 'docx', 'zip', 'rar', 'apk', 'ipa', 'txt', 'exe', '7z', 'e', 'z', 'ct', 'ke',
    'cetrainer', 'db', 'tar', 'pdf', 'w3x', 'epub', 'mobi', 'azw', 'azw3', 'osk', 'osz',
    'xpa', 'cpk', 'lua', 'jar', 'dmg', 'ppt', 'pptx', 'xls', 'xlsx', 'mp3',
    'iso', 'img', 'gho', 'ttf', 'ttc', 'txf', 'dwg', 'bat', 'imazingapp', 'dll', 'crx',
    'xapk', 'conf', 'deb', 'rp', 'rpm', 'rplib', 'mobileconfig', 'appimage', 'lolgezi',
    'fla'
]

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
    定位上传的目标文件夹（蓝奏云靠 cookie 中的 folder_id_c 记录当前目录）
    :return: 成功返回 True，失败返回 False
    """
    data = {'task': '47', 'folder_id': str(folder_id)}
    try:
        response = session.post(DO_LOAD_URL, data=data, headers=headers, timeout=(10, 30))
    except requests.RequestException as e:
        print("_SetFolderID 请求失败：%s" % e)
        return False
    try:
        j = json.loads(response.text)
    except (ValueError, TypeError) as e:
        print("_SetFolderID 响应解析失败：%s" % e)
        return False
    if j.get("zt") != 1:
        print("_SetFolderID 失败：%s" % j.get("info"))
        return False
    session.cookies.set("folder_id_c", str(folder_id))
    return True

def UploadFile(session, file_path, folder_id=-1):
    """
    上传单个文件到蓝奏云指定文件夹（需先调用 Login / LoginByCookie）
    :param session: 已登录的 requests.Session
    :param file_path: 本地文件路径（建议绝对路径）
    :param folder_id: 目标文件夹 id，默认 -1（根目录）
    :return: {"status": 1, "msg": "success", "f_id": 文件id} 成功；
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
    if size > 100 * 1024 * 1024:
        ret["msg"] = "单个文件不能超过 100MB"
        return ret
    if not _SetFolderID(session, folder_id):
        ret["msg"] = "无法定位上传文件夹"
        return ret

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
        f = open(file_path, "rb")
    except OSError as e:
        ret["msg"] = "无法打开文件：%s" % e
        return ret
    try:
        files = {"upload_file": (filename, f, "application/octet-stream")}
        response = session.post(UPLOAD_URL, data=data, files=files, headers=upload_headers, timeout=(30, 600))
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
        ret["f_id"] = j["text"][0]["id"]
    except (KeyError, IndexError, TypeError):
        ret["f_id"] = None
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