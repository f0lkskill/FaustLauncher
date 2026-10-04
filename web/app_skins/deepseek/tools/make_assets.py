"""DeepSeek 皮肤素材生成 (PIL 程序化合成, 可重复运行)。

素材: source/whale-girl-transparent.png (CC BY-NC-SA 4.0, 见 CREDITS.md)
产出:
  assets/launcher/background/deepseek_1..3.jpg   全屏背景 (cover, 1600x900)
  profile.jpg                                    玻璃窗卡片图 (700x977)
  assets/web/icon/icon.png                       启动器图标 (256x256, 透明底)

调色板取自立绘本身 + DeepSeek 官方蓝:
  深海藏青 #0C1122 / #1A2340   主蓝紫 #54609C   亮蓝 #789CCC
  冰白     #FCF0F0             官方蓝 #4D6BFE

用法 (在本目录下执行):
  python tools/make_assets.py           # 全部重新生成
  python tools/make_assets.py icon      # 只生成启动器图标 (不动已入库的背景图)
"""
import os
import sys
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps

HERE = os.path.dirname(os.path.abspath(__file__))
SKIN = os.path.dirname(HERE)
SRC = os.path.join(SKIN, "source", "whale-girl-transparent.png")
BG_DIR = os.path.join(SKIN, "assets", "launcher", "background")

DEEP = (12, 17, 34)          # 深藏青
MID = (26, 35, 64)           # 中间调
INK = (8, 11, 24)            # 近黑
BLUE = (77, 107, 254)        # DeepSeek 官方蓝
ICE = (120, 156, 204)        # 亮蓝
WHITE = (252, 240, 240)      # 冰白


def vgrad(size, stops):
    """垂直渐变。stops=[(0.0,(r,g,b)), (1.0,(r,g,b))] 按位置线性插值"""
    w, h = size
    col = Image.new("RGB", (1, h))
    px = col.load()
    for y in range(h):
        t = y / max(1, h - 1)
        for i in range(len(stops) - 1):
            p0, c0 = stops[i]
            p1, c1 = stops[i + 1]
            if p0 <= t <= p1 or i == len(stops) - 2:
                k = 0.0 if p1 == p0 else max(0.0, min(1.0, (t - p0) / (p1 - p0)))
                px[0, y] = tuple(int(c0[j] + (c1[j] - c0[j]) * k) for j in range(3))
                break
    return col.resize((w, h), Image.BILINEAR)


_RADIAL_CACHE = {}


def radial_mask(size=256, power=2.0):
    """严格圆形的径向渐变 mask: 中心 255 -> 边缘 0, 圆外恒 0。

    不用 PIL 的 Image.radial_gradient: 它按**对角线**归一化, 画布边缘中点仍有
    ~74/255 的亮度 (实测 中心=0 / 边缘中点=181 / 角=255), resize 放大后用 screen
    叠加, 会在图上留下一块方形硬边亮块。
    """
    key = (size, power)
    if key not in _RADIAL_CACHE:
        m = Image.new("L", (size, size), 0)
        px = m.load()
        c = (size - 1) / 2.0
        for y in range(size):
            dy = y - c
            for x in range(size):
                d = (((x - c) ** 2 + dy * dy) ** 0.5) / c
                px[x, y] = 0 if d >= 1 else int(255 * ((1 - d) ** power))
        _RADIAL_CACHE[key] = m
    return _RADIAL_CACHE[key]


def glow(size, center, radius, color, peak=1.0):
    """径向光斑 (screen 叠加用)"""
    d = max(16, int(radius * 2))
    m = radial_mask(256, 2.0).resize((d, d), Image.LANCZOS)
    m = m.filter(ImageFilter.GaussianBlur(d * 0.05))
    if peak != 1.0:
        m = m.point(lambda v: int(max(0, min(255, v * peak))))
    layer = Image.new("RGB", size, (0, 0, 0))
    layer.paste(Image.new("RGB", (d, d), color),
                (int(center[0] - radius), int(center[1] - radius)), m)
    return layer


def light_shafts(size, color=ICE, alpha=30):
    """斜向柔光带: 深海光柱意象, 用来填充大片空白"""
    w, h = size
    out = Image.new("RGBA", size, (0, 0, 0, 0))
    for i in range(3):
        band = Image.new("L", size, 0)
        d = ImageDraw.Draw(band)
        x0 = int(w * (0.10 + 0.20 * i))
        bw = int(w * 0.075)
        lean = int(w * 0.13)
        d.polygon([(x0, 0), (x0 + bw, 0), (x0 + bw + lean, h), (x0 + lean, h)],
                  fill=int(alpha * (1.0 - 0.22 * i)))
        out = Image.alpha_composite(out, Image.merge("RGBA", (
            Image.new("L", size, color[0]), Image.new("L", size, color[1]),
            Image.new("L", size, color[2]), band)))
    return out.filter(ImageFilter.GaussianBlur(w * 0.018))


def bubbles(size, count=30, seed=7, color=ICE):
    """悬浮微粒: 让深海背景不至于太空"""
    import random
    rnd = random.Random(seed)
    w, h = size
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for _ in range(count):
        r = rnd.randint(2, 9)
        x = rnd.randint(0, w)
        y = rnd.randint(0, h)
        a = rnd.randint(16, 62)
        d.ellipse([x - r, y - r, x + r, y + r], fill=color + (a,))
        d.ellipse([x - r, y - r, x + r, y + r], outline=(255, 255, 255, min(255, a + 34)), width=1)
    return layer


def grid(size, step=44, color=ICE, alpha=13):
    g = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(g)
    for x in range(0, size[0], step):
        d.line([(x, 0), (x, size[1])], fill=color + (alpha,))
    for y in range(0, size[1], step):
        d.line([(0, y), (size[0], y)], fill=color + (alpha,))
    return g


def edge_shade(size, top_ratio=0.0, bottom_ratio=0.0, color=INK, max_alpha=200, power=1.7):
    """顶部/底部压暗 (小图拉伸成大图, 避免逐像素循环)"""
    w, h = size
    mask = Image.new("L", (1, h), 0)
    mp = mask.load()
    top_px = int(h * top_ratio)
    bot_start = h - int(h * bottom_ratio)
    for y in range(h):
        a = 0
        if top_px and y < top_px:
            a = int(max_alpha * ((1 - y / top_px) ** power))
        if bottom_ratio and y >= bot_start:
            t = (y - bot_start) / max(1, h - bot_start)
            a = max(a, int(max_alpha * (t ** power)))
        mp[0, y] = a
    layer = Image.new("RGBA", size, color + (255,))
    layer.putalpha(mask.resize((w, h), Image.BILINEAR))
    return layer


def place_char(base, height, x_ratio, flip=False, glow_color=BLUE, glow_alpha=120,
               glow_blur=34, shadow=True, y_shift=0):
    """把鲸鱼娘立绘合到 base 上 (阴影 + 蓝色外发光 + 本体)"""
    char = Image.open(SRC).convert("RGBA")
    if flip:
        char = ImageOps.mirror(char)
    th = int(height)
    tw = int(char.width * th / char.height)
    char = char.resize((tw, th), Image.LANCZOS)
    x = int(base.width * x_ratio - tw / 2)
    y = base.height - th + int(y_shift)
    alpha = char.split()[3]

    if shadow:
        sh = Image.new("RGBA", base.size, (0, 0, 0, 0))
        sh.paste(Image.new("RGBA", char.size, (0, 0, 0, 160)),
                 (x, y + 14), alpha.filter(ImageFilter.GaussianBlur(24)))
        base = Image.alpha_composite(base, sh)

    gl = Image.new("RGBA", base.size, (0, 0, 0, 0))
    gl.paste(Image.new("RGBA", char.size, glow_color + (glow_alpha,)),
             (x, y), alpha.filter(ImageFilter.GaussianBlur(glow_blur)))
    base = Image.alpha_composite(base, gl)

    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    layer.paste(char, (x, y), char)
    return Image.alpha_composite(base, layer)


def base_canvas(size, hot=(0.80, -0.06), cool=(0.06, 1.06), hot_peak=0.95, cool_peak=0.5,
                shafts=True):
    """深蓝渐变底 + 光斑 + 细网格 + 深海光柱 + 微粒"""
    img = vgrad(size, [(0.0, DEEP), (0.45, MID), (1.0, INK)]).convert("RGB")
    for center, radius, color, peak in (
        (hot, size[0] * 0.62, BLUE, hot_peak),
        (cool, size[0] * 0.40, ICE, cool_peak),
        ((0.5, 0.42), size[0] * 0.34, BLUE, 0.28),
    ):
        img = ImageChops.screen(img, glow(size, (size[0] * center[0], size[1] * center[1]),
                                          radius, color, peak))
    gr = grid(size)
    ui = Image.new("RGB", size, (0, 0, 0))
    ui.paste(gr, (0, 0), gr)
    img = ImageChops.screen(img, ui)
    out = img.convert("RGBA")
    if shafts:
        out = Image.alpha_composite(out, light_shafts(size))
    return Image.alpha_composite(out, bubbles(size))


def write_bg(name, canvas, quality=90):
    os.makedirs(BG_DIR, exist_ok=True)
    out = os.path.join(BG_DIR, name)
    canvas.convert("RGB").save(out, "JPEG", quality=quality, optimize=True)
    print("  %-22s %s  %.0fKB" % (name, canvas.size, os.path.getsize(out) / 1024))


def make_backgrounds():
    W, H = 1600, 900
    print("背景图:")

    # 1) 角色居右: 主视觉
    c = base_canvas((W, H))
    c = place_char(c, H * 0.96, 0.73)
    c = Image.alpha_composite(c, edge_shade((W, H), top_ratio=0.22, bottom_ratio=0.34, max_alpha=205))
    write_bg("deepseek_1.jpg", c)

    # 2) 角色居左 (镜像): 换一侧的观感
    c = base_canvas((W, H), hot=(0.18, -0.06), cool=(0.96, 1.06))
    c = place_char(c, H * 0.94, 0.26, flip=True)
    c = Image.alpha_composite(c, edge_shade((W, H), top_ratio=0.22, bottom_ratio=0.34, max_alpha=205))
    write_bg("deepseek_2.jpg", c)

    # 3) 角色稍小 + 蓝雾更重: 氛围向
    c = base_canvas((W, H), hot=(0.70, 0.10), cool=(0.20, 0.95), hot_peak=0.8)
    c = ImageChops.screen(c.convert("RGB"),
                          glow((W, H), (W * 0.55, H * 0.62), W * 0.78, ICE, 0.30)).convert("RGBA")
    c = place_char(c, H * 0.88, 0.74, glow_alpha=150, glow_blur=44)
    c = Image.alpha_composite(c, edge_shade((W, H), top_ratio=0.24, bottom_ratio=0.30, max_alpha=200))
    write_bg("deepseek_3.jpg", c)


def make_profile():
    W, H = 700, 977
    c = base_canvas((W, H), hot=(0.62, 0.06), cool=(0.10, 0.98), hot_peak=0.9, cool_peak=0.55)
    c = place_char(c, H * 0.80, 0.52, glow_alpha=110, glow_blur=30, shadow=False)
    c = Image.alpha_composite(c, edge_shade((W, H), top_ratio=0.16, bottom_ratio=0.30, max_alpha=210))
    out = os.path.join(SKIN, "profile.jpg")
    c.convert("RGB").save(out, "JPEG", quality=90, optimize=True)
    print("卡片图:")
    print("  %-22s %s  %.0fKB" % ("profile.jpg", c.size, os.path.getsize(out) / 1024))


def make_icon():
    """取立绘头部做启动器图标 (透明底)。

    裁切框要涵盖"头饰 + 整张脸 + 两侧鲸鱼耳": 只到眼睛上半的话,
    缩到标题栏 20px 就完全看不出是角色了。比例按立绘 910x941 量的:
    头饰顶 y≈2%, 下巴/脖子 y≈72%, 脸中心 x≈50%, 左右各让 36%。
    """
    char = Image.open(SRC).convert("RGBA")
    w, h = char.size
    box = (int(w * 0.135), int(h * 0.020), int(w * 0.865), int(h * 0.725))
    head = char.crop(box)
    side = max(head.size)
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.paste(head, ((side - head.width) // 2, (side - head.height) // 2), head)
    icon = canvas.resize((256, 256), Image.LANCZOS)
    out_dir = os.path.join(SKIN, "assets", "web", "icon")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, "icon.png")
    icon.save(out, "PNG", optimize=True)
    print("启动器图标:")
    print("  %-22s %s  %.0fKB" % ("icon.png", icon.size, os.path.getsize(out) / 1024))


if __name__ == "__main__":
    if not os.path.isfile(SRC):
        raise SystemExit("缺少素材: " + SRC)
    targets = set(a.lower() for a in sys.argv[1:]) or {"all"}
    if "all" in targets or "bg" in targets or "background" in targets:
        make_backgrounds()
    if "all" in targets or "profile" in targets:
        make_profile()
    if "all" in targets or "icon" in targets:
        make_icon()
    print("完成")
