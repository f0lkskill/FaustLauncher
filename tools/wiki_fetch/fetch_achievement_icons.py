"""从 huijiwiki 抓成就徽标素材并处理成启动器用的 PNG（**独立目录，不占用 build_temp**）。

用法：

    # 搜文件（看有哪些素材）
    python tools/wiki_fetch/fetch_achievement_icons.py --search 战斗

    # 抓一张并做成成就徽标（<成就id>.png 落到 web/app/assets/achievement/）
    python tools/wiki_fetch/fetch_achievement_icons.py --make "地牢-普通战斗.png:ach_battle_01"

    # 一次做多张（可重复 --make）
    python tools/wiki_fetch/fetch_achievement_icons.py \
        --make "地牢-普通战斗.png:ach_battle_01" \
        --make "地牢-精英战斗.png:ach_battle_02"

为什么必须用真实浏览器：huijiwiki 有 Cloudflare 挑战（直接 HTTP 请求 403「请稍候…」，
无头浏览器也过不去），只有 **有头 Edge + 持久化 profile** 可行。图片字节也在浏览器里
用 fetch 取（同源、带 cookie），不另外发 HTTP 请求，避免再撞一次挑战。

徽标处理规则（与现有素材一致）：
  · 输出 128×128 PNG、透明底、**不带边框**（边框由前端按稀有度自动着色）；
  · 等比缩放留边，不裁剪（保留原图完整内容）。
"""

from __future__ import annotations

import argparse
import base64
import json
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
WIKI = "https://limbuscompany.huijiwiki.com/wiki/"
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"

# 浏览器里用 fetch 取图片字节，回传 dataURL（同源 + 带 Cloudflare cookie）
_JS_FETCH_IMAGE = """
const url = arguments[0], done = arguments[arguments.length - 1];
fetch(url).then(r => r.blob()).then(b => {
    const fr = new FileReader();
    fr.onload = () => done(fr.result);
    fr.readAsDataURL(b);
}).catch(e => done("ERR:" + e));
"""


def _venv_python() -> str:
    return os.path.join(VENV, "Scripts", "python.exe")


def ensure_env() -> str:
    """保证有可用的 selenium 环境，返回该解释器路径。"""
    py = _venv_python()
    if os.path.isfile(py):
        return py
    print("[环境] 首次运行：创建虚拟环境并安装 selenium + Pillow …")
    subprocess.check_call([sys.executable, "-m", "venv", VENV])
    subprocess.check_call([py, "-m", "pip", "install", "-q", "--upgrade", "pip"])
    subprocess.check_call([py, "-m", "pip", "install", "-q", "selenium", "Pillow",
                           "-i", "https://mirrors.aliyun.com/pypi/simple/"])
    return py


def _api_json(driver, url: str) -> dict:
    driver.get(url)
    time.sleep(0.8)
    try:
        return json.loads(driver.find_element("tag name", "pre").text)
    except Exception:
        return {}


def _image_url(driver, filename: str) -> str:
    """取 wiki 文件的原始 URL。"""
    from urllib.parse import quote
    data = _api_json(driver, API + "?action=query&titles=File:" + quote(filename) +
                     "&prop=imageinfo&iiprop=url&format=json")
    pages = (data.get("query") or {}).get("pages") or {}
    for page in pages.values():
        info = (page.get("imageinfo") or [{}])[0]
        if info.get("url"):
            return str(info["url"])
    return ""


def _download(driver, url: str, dest: str) -> bool:
    """在浏览器里 fetch 图片字节（绕开 Cloudflare），落盘到 dest。"""
    data_url = driver.execute_async_script(_JS_FETCH_IMAGE, url)
    if not isinstance(data_url, str) or not data_url.startswith("data:"):
        print(f"[下载] 失败: {data_url}")
        return False
    raw = base64.b64decode(data_url.split(",", 1)[1])
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "wb") as fh:
        fh.write(raw)
    print(f"[下载] {os.path.basename(dest)}  {len(raw):,} B")
    return True


def _to_badge(src: str, dest: str, size: int = 128) -> bool:
    """处理成徽标：等比缩放居中贴到 size×size 透明画布（不裁剪、不描边）。"""
    from PIL import Image
    with Image.open(src) as im:
        im = im.convert("RGBA")
        w, h = im.size
        if not w or not h:
            return False
        scale = min(size / w, size / h)
        new = (max(1, int(round(w * scale))), max(1, int(round(h * scale))))
        im = im.resize(new, Image.LANCZOS)
        canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        canvas.paste(im, ((size - new[0]) // 2, (size - new[1]) // 2), im)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        canvas.save(dest)
    print(f"[徽标] {os.path.basename(dest)}  {size}×{size} 透明底（无边框）")
    return True


def run(args) -> int:
    from selenium import webdriver                        # noqa: PLC0415
    from selenium.webdriver.edge.options import Options    # noqa: PLC0415

    os.makedirs(PROFILE, exist_ok=True)
    os.makedirs(DOWNLOADS, exist_ok=True)
    opts = Options()
    if os.path.isfile(EDGE):
        opts.binary_location = EDGE
    opts.add_argument(f"--user-data-dir={PROFILE}")
    opts.add_argument("--start-maximized")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    driver = webdriver.Edge(options=opts)
    made = 0
    try:
        driver.get(WIKI)                     # 先过 Cloudflare 挑战
        time.sleep(3)
        if args.search:
            from urllib.parse import quote
            data = _api_json(driver, API + "?action=query&list=search&srsearch=" +
                             quote(args.search) + "&srnamespace=6&srlimit=30&format=json")
            for hit in ((data.get("query") or {}).get("search") or []):
                print("  " + str(hit.get("title", "")).replace("文件:", ""))
        for spec in (args.make or []):
            if ":" not in spec:
                print(f"[跳过] --make 需要 <wiki文件名>:<成就id>，收到 {spec!r}")
                continue
            filename, ach_id = spec.split(":", 1)
            url = _image_url(driver, filename)
            if not url:
                print(f"[跳过] wiki 上找不到文件: {filename}")
                continue
            raw_path = os.path.join(DOWNLOADS, filename)
            if _download(driver, url, raw_path):
                if _to_badge(raw_path, os.path.join(ASSET_DIR, ach_id.strip() + ".png")):
                    made += 1
    finally:
        driver.quit()
    print(f"[完成] 生成 {made} 张徽标")
    return 0 if made or args.search else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="抓 huijiwiki 素材做成就徽标")
    ap.add_argument("--search", default="", help="在文件命名空间里搜关键词")
    ap.add_argument("--make", action="append",
                    help="抓取并处理：<wiki文件名>:<成就id>（可重复）")
    args = ap.parse_args()
    if not args.search and not args.make:
        ap.print_help()
        return 0
    py = ensure_env()
    if os.path.abspath(sys.executable) != os.path.abspath(py):
        return subprocess.call([py, os.path.abspath(__file__)] + sys.argv[1:])
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
