import os
import sys
import urllib.request

from PIL import Image, ImageChops, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
SKIN_DIR = os.path.dirname(HERE)
SRC_DIR = os.path.join(SKIN_DIR, "source")
BG_DIR = os.path.join(SKIN_DIR, "assets", "launcher", "background")
ICON_DIR = os.path.join(SKIN_DIR, "assets", "web", "icon")

BG_SIZE = (1920, 1080)
PROFILE_SIZE = (700, 977)
ICON_SIZE = 256
SRC_MAX = 2560

WALLPAPERS = [
    ("wallpaper-01.jpg", "奶蛙-4K-捶头大笑-01.jpg", "捶头大笑"),
    ("wallpaper-02.jpg", "奶蛙-4K-抱头震惊-02.jpg", "抱头震惊"),
    ("wallpaper-03.jpg", "奶蛙-4K-叉腰指点-03.jpg", "叉腰指点"),
    ("wallpaper-04.jpg", "奶蛙-4K-托腮沉思-04.jpg", "托腮沉思"),
    ("wallpaper-05.jpg", "奶蛙-4K-张臂平衡-05.jpg", "张臂平衡"),
]
PROFILE_SRC = "wallpaper-05.jpg"
ICON_POSE_SRC = "icon-pose.png"

REPO = "Nailong-Studio/wallpaper"
BRANCH = "main"
PROXY = "https://gh-proxy.com/https://raw.githubusercontent.com/%s/%s/" % (REPO, BRANCH)

def content_bbox(im, tol=28, floor=215):
    small = im.convert("RGB")
    w, h = small.size
    if w > 256:
        small = small.resize((256, max(1, int(h * 256 / w))), Image.BILINEAR)
    px = small.load()
    w, h = small.size
    col_hit = [0] * w
    row_hit = [0] * h
    for y in range(h):
        for x in range(w):
            r, g, b = px[x, y]
            is_bg = min(r, g, b) > floor and (max(r, g, b) - min(r, g, b)) < tol
            if not is_bg:
                col_hit[x] += 1
                row_hit[y] += 1
    def span(hits, total, keep=0.02):
        thr = max(2, int(total * keep))
        idx = [i for i, v in enumerate(hits) if v >= thr]
        return (idx[0], idx[-1] + 1) if idx else None
    cs = span(col_hit, h)
    rs = span(row_hit, w)
    if not cs or not rs:
        return (0, 0, im.width, im.height)
    sx, sy = im.width / w, im.height / h
    return (int(cs[0] * sx), int(rs[0] * sy), int(cs[1] * sx), int(rs[1] * sy))

def crop_to_ratio(im, ratio, center):
    w, h = im.size
    if w / h > ratio:
        cw, ch = int(round(h * ratio)), h
    else:
        cw, ch = w, int(round(w / ratio))
    cx, cy = center
    x = int(round(cx - cw / 2.0))
    y = int(round(cy - ch / 2.0))
    x = max(0, min(w - cw, x))
    y = max(0, min(h - ch, y))
    return im.crop((x, y, x + cw, y + ch))

def fit(im, size, resample=Image.LANCZOS):
    tw, th = size
    k = max(tw / im.width, th / im.height)
    nw, nh = max(tw, int(round(im.width * k))), max(th, int(round(im.height * k)))
    im = im.resize((nw, nh), resample)
    return im.crop(((nw - tw) // 2, (nh - th) // 2, (nw - tw) // 2 + tw, (nh - th) // 2 + th))

def load_src(name):
    p = os.path.join(SRC_DIR, name)
    if not os.path.isfile(p):
        raise SystemExit("缺少素材: %s (先跑 python tools/make_assets.py fetch)" % p)
    return Image.open(p)

def _ramp_h(w, edge):
    im = Image.new("L", (w, 1), 0)
    px = im.load()
    for x in range(w):
        d = min(x, w - 1 - x)
        px[x, 0] = 255 if d >= edge else int(255.0 * d / edge)
    return im

def _ramp_v(h, edge):
    im = Image.new("L", (1, h), 0)
    px = im.load()
    for y in range(h):
        d = min(y, h - 1 - y)
        px[0, y] = 255 if d >= edge else int(255.0 * d / edge)
    return im

def feather_mask(size, ratio=0.06):
    w, h = size
    rx = _ramp_h(w, max(1, int(w * ratio))).resize((w, h), Image.BILINEAR)
    ry = _ramp_v(h, max(1, int(h * ratio))).resize((w, h), Image.BILINEAR)
    return ImageChops.multiply(rx, ry)

def backdrop_column(fg, th):
    w, h = fg.size
    px = fg.load()
    xs = [int(round(i * (w - 1) / 23.0)) for i in range(24)]

    def score(c):
        return c[0] * 299 + c[1] * 587 + c[2] * 114 - (max(c) - min(c)) * 342

    col = Image.new("RGB", (1, th))
    o = col.load()
    for y in range(th):
        top = sorted((px[x, y] for x in xs), key=score, reverse=True)[:4]
        o[0, y] = tuple(sum(c[k] for c in top) // len(top) for k in range(3))
    return col

def compose_background(im, size=BG_SIZE):
    tw, th = size
    fg = im.resize((max(1, int(round(im.width * th / float(im.height)))), th),
                   Image.LANCZOS).convert("RGB")
    if fg.width >= tw:
        x = (fg.width - tw) // 2
        return fg.crop((x, 0, x + tw, th))
    pad = tw - fg.width
    left, right = pad // 2, pad - pad // 2
    edge = max(12, int(fg.width * 0.04))
    band = backdrop_column(fg, th).filter(ImageFilter.GaussianBlur(max(3.0, th * 0.012)))
    out = Image.new("RGB", size)
    out.paste(band.resize((left + edge, th), Image.NEAREST), (0, 0))
    out.paste(band.resize((right + edge, th), Image.NEAREST), (tw - right - edge, 0))
    out.paste(fg, (left, 0), _ramp_h(fg.width, edge).resize((fg.width, th), Image.BILINEAR))
    return out

def make_backgrounds():
    os.makedirs(BG_DIR, exist_ok=True)
    print("背景图 (1920x1080, 16:9, 保留完整角色):")
    for i, (src, _orig, label) in enumerate(WALLPAPERS, 1):
        im = load_src(src).convert("RGB")
        out = compose_background(im, BG_SIZE)
        name = "naiwa_%d.jpg" % i
        dst = os.path.join(BG_DIR, name)
        out.save(dst, "JPEG", quality=88, optimize=True, progressive=True)
        print("  %-14s %-6s 源 %s -> %s  %.0fKB"
              % (name, label, im.size, out.size, os.path.getsize(dst) / 1024))

def make_profile():
    im = load_src(PROFILE_SRC).convert("RGB")
    bx0, by0, bx1, by1 = content_bbox(im)
    center = ((bx0 + bx1) / 2.0, (by0 + by1) / 2.0)
    crop = crop_to_ratio(im, PROFILE_SIZE[0] / PROFILE_SIZE[1], center)
    out = fit(crop, PROFILE_SIZE)
    dst = os.path.join(SKIN_DIR, "profile.jpg")
    out.save(dst, "JPEG", quality=90, optimize=True, progressive=True)
    print("卡片图:")
    print("  %-14s %s  %.0fKB" % ("profile.jpg", out.size, os.path.getsize(dst) / 1024))

def make_icon():
    im = load_src(ICON_POSE_SRC).convert("RGBA")
    box = im.getchannel("A").getbbox()
    if box:
        im = im.crop(box)
    side = int(round(max(im.size) * 1.16))
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.paste(im, ((side - im.width) // 2, (side - im.height) // 2), im)
    out = canvas.resize((ICON_SIZE, ICON_SIZE), Image.LANCZOS)
    os.makedirs(ICON_DIR, exist_ok=True)
    dst = os.path.join(ICON_DIR, "icon.png")
    out.save(dst, "PNG", optimize=True)
    print("启动器图标:")
    print("  %-14s %s  %.0fKB" % ("icon.png", out.size, os.path.getsize(dst) / 1024))

def fetch():
    os.makedirs(SRC_DIR, exist_ok=True)
    jobs = [("4k/" + orig, dst, SRC_MAX, 92) for dst, orig, _ in WALLPAPERS]
    jobs.append(("emotes/奶蛙-姿态-露肚.png", ICON_POSE_SRC, 900, None))
    for remote, dst, limit, q in jobs:
        target = os.path.join(SRC_DIR, dst)
        url = PROXY + urllib.parse.quote(remote)
        print("  下载 %s ..." % remote, flush=True)
        req = urllib.request.Request(url, headers={"User-Agent": "faustlauncher-skin"})
        with urllib.request.urlopen(req, timeout=120) as r:
            data = r.read()
        tmp = target + ".download"
        with open(tmp, "wb") as f:
            f.write(data)
        im = Image.open(tmp)
        if max(im.size) > limit:
            k = limit / float(max(im.size))
            im = im.resize((int(round(im.width * k)), int(round(im.height * k))), Image.LANCZOS)
        if q is None:
            im.save(target, "PNG", optimize=True)
        else:
            im.convert("RGB").save(target, "JPEG", quality=q, optimize=True)
        os.remove(tmp)
        print("    -> %-20s %s  %.0fKB" % (dst, im.size, os.path.getsize(target) / 1024))

if __name__ == "__main__":
    import urllib.parse  # noqa: E402  (仅 fetch 需要)
    targets = set(a.lower() for a in sys.argv[1:]) or {"all"}
    if "fetch" in targets:
        print("从 %s 拉取素材:" % REPO)
        fetch()
    if targets & {"all", "bg", "background"}:
        make_backgrounds()
    if targets & {"all", "profile"}:
        make_profile()
    if targets & {"all", "icon"}:
        make_icon()
    print("完成")
