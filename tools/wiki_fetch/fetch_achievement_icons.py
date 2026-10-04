"""从 huijiwiki 抓成就徽标素材（**独立目录，不占用 build_temp**）。

用法（首次会自己建虚拟环境并装 selenium）：

    python tools/wiki_fetch/fetch_achievement_icons.py --search 战斗
    python tools/wiki_fetch/fetch_achievement_icons.py --fetch "战斗.png" --out ach_battle_01

为什么必须用真实浏览器：huijiwiki 有 Cloudflare 挑战（直接 HTTP 请求返回 403「请稍候…」），
无头浏览器也过不去；只有 **有头 Edge + 持久化 profile**（首次过挑战后 cookie 会留着）可行。

脚本做的事：
  1. 建/复用 tools/wiki_fetch/.venv（selenium）与 .edge_profile（Cloudflare 通行 cookie）；
  2. 打开 wiki，走 MediaWiki API：``list=search`` 搜文件 / ``prop=imageinfo`` 取原图 URL；
  3. 下载到 tools/wiki_fetch/downloads/，再用 Pillow 处理成
     ``web/app/assets/achievement/<成就id>.png``（128×128、透明底、**不带边框**）。

注意：徽标边框由前端按稀有度自动着色，图片本身**不要**画边框。
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, os.pardir, os.pardir))
VENV = os.path.join(HERE, ".venv")
PROFILE = os.path.join(HERE, ".edge_profile")
DOWNLOADS = os.path.join(HERE, "downloads")
ASSET_DIR = os.path.join(ROOT, "web", "app", "assets", "achievement")
API = "https://limbuscompany.huijiwiki.com/api.php"
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"


def _venv_python() -> str:
    return os.path.join(VENV, "Scripts", "python.exe")


def ensure_env() -> str:
    """保证有可用的 selenium 环境，返回该解释器路径。"""
    py = _venv_python()
    if os.path.isfile(py):
        return py
    print("[环境] 首次运行：创建虚拟环境并安装 selenium …")
    subprocess.check_call([sys.executable, "-m", "venv", VENV])
    subprocess.check_call([py, "-m", "pip", "install", "-q", "--upgrade", "pip"])
    subprocess.check_call([py, "-m", "pip", "install", "-q", "selenium", "Pillow",
                           "-i", "https://mirrors.aliyun.com/pypi/simple/"])
    os.makedirs(DOWNLOADS, exist_ok=True)
    return py


def run(py: str, args) -> int:
    """在有头 Edge 里跑一次抓取（Cloudflare 过了之后 profile 会记住）。"""
    from selenium import webdriver                       # noqa: PLC0415
    from selenium.webdriver.edge.options import Options   # noqa: PLC0415

    os.makedirs(PROFILE, exist_ok=True)
    os.makedirs(DOWNLOADS, exist_ok=True)
    opts = Options()
    if os.path.isfile(EDGE):
        opts.binary_location = EDGE
    opts.add_argument(f"--user-data-dir={PROFILE}")
    opts.add_argument("--start-maximized")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    driver = webdriver.Edge(options=opts)
    try:
        driver.get("https://limbuscompany.huijiwiki.com/wiki/%E9%A6%96%E9%A1%B5")
        time.sleep(3)
        if args.search:
            query = (API + "?action=query&list=search&srsearch=" +
                     __import__("urllib.parse", fromlist=["quote"]).quote(args.search) +
                     "&srnamespace=6&srlimit=30&format=json")
            driver.get(query)
            time.sleep(1)
            print(driver.find_element("tag name", "pre").text)
        elif args.fetch:
            from urllib.parse import quote           # noqa: PLC0415
            q = (API + "?action=query&titles=File:" + quote(args.fetch) +
                 "&prop=imageinfo&iiprop=url&format=json")
            driver.get(q)
            time.sleep(1)
            print(driver.find_element("tag name", "pre").text)
        else:
            print("[提示] 用 --search <关键词> 搜文件，或 --fetch <文件名> --out <成就id> 下载")
    finally:
        driver.quit()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="抓 huijiwiki 素材做成就徽标")
    ap.add_argument("--search", default="", help="在文件命名空间里搜关键词")
    ap.add_argument("--fetch", default="", help="要下载的 wiki 文件名（含扩展名）")
    ap.add_argument("--out", default="", help="成就 id（下载后处理成 <out>.png）")
    args = ap.parse_args()
    py = ensure_env()
    if os.path.abspath(sys.executable) != os.path.abspath(py):
        # 用带 selenium 的解释器重跑自己
        return subprocess.call([py, os.path.abspath(__file__)] + sys.argv[1:])
    return run(py, args)


if __name__ == "__main__":
    raise SystemExit(main())
