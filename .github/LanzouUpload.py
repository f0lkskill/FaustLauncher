import os
import sys
from pathlib import Path

project_root = Path(os.path.dirname(__file__)).parent
sys.path.append(project_root.as_posix())

from functions.web_update.lanzou_utils import LoginByCookie, UploadFile

# 蓝奏云 LLC_lang 文件夹 id
LLC_LANG_FOLDER_ID = 13813177
# lz.qaiu.top 直链解析服务
PARSER_BASE = "https://lz.qaiu.top/parser?url="


class LanzouUploader:
    """
    蓝奏云上传封装，供工作流脚本（UpdatePackage.py）使用
    登录凭据从环境变量读取：
        LANZOU_YLOGIN       -- 浏览器 cookie 中的 ylogin（必填）
        LANZOU_PHPDISK_INFO -- 浏览器 cookie 中的 phpdisk_info（必填）
        LANZOU_YLOGINS      -- 可选
    cookie 会在网页端过期后失效，届时需更新对应的环境变量/secrets
    """

    def __init__(self):
        cookie = {}
        ylogin = os.getenv("LANZOU_YLOGIN")
        if ylogin:
            cookie["ylogin"] = ylogin
        ylogins = os.getenv("LANZOU_YLOGINS")
        if ylogins:
            cookie["ylogins"] = ylogins
        phpdisk_info = os.getenv("LANZOU_PHPDISK_INFO")
        if phpdisk_info:
            cookie["phpdisk_info"] = phpdisk_info
        self.cookie = cookie
        self.session = None

    def login(self):
        """登录蓝奏云，成功返回 True"""
        if not self.cookie:
            print("错误: 未配置 LANZOU_YLOGIN / LANZOU_PHPDISK_INFO 环境变量")
            return False
        self.session = LoginByCookie(self.cookie)
        return self.session is not False

    def upload(self, file_path, folder_id=LLC_LANG_FOLDER_ID):
        """
        上传文件到指定文件夹
        :return: {"success": bool, "share_url": 蓝奏云分享链接, "parse_url": lz.qaiu.top 解析链接, "error": 错误信息}
        """
        if not self.session:
            if not self.login():
                return {"success": False, "share_url": None, "parse_url": None, "error": "蓝奏云登录失败"}
        result = UploadFile(self.session, file_path, folder_id=folder_id)
        if result.get("status") != 1:
            return {"success": False, "share_url": None, "parse_url": None, "error": result.get("msg")}
        share_url = result.get("share_url") or ""
        parse_url = PARSER_BASE + share_url
        return {"success": True, "share_url": share_url, "parse_url": parse_url, "error": None}


if __name__ == "__main__":
    uploader = LanzouUploader()
    if not uploader.login():
        sys.exit(1)
    file = sys.argv[1] if len(sys.argv) > 1 else None
    if not file:
        print("用法: python .github/LanzouUpload.py <文件路径>")
        sys.exit(1)
    print(uploader.upload(file))
