"""成就解锁弹窗 (仿 Steam 成就通知)。

设计:
- 右下角弹出, 深色渐变圆角卡片 (PIL 绘背景/图标, 圆角外 key 抠图)
- 文字全部用 tk.Label + **tk 字体名** (Microsoft YaHei UI) 渲染
- 标题 "解锁成就" 颜色与边框 = 成就稀有度色 (白/绿/蓝/紫/金/红)
- 无时间戳; 多成就队列 + 垂直堆叠 (最多 MAX_SHOW 同时)
- 线程安全: show_toast_async() 仅入队; ToastController.pump() 驱动
"""

import os
import queue
import threading
import tkinter as tk
import tkinter.font as tkfont

from PIL import Image, ImageDraw, ImageTk

# ============ 常量 ============
CARD_W = 356
CARD_MIN_H = 94            # 单/两行描述时的卡片高度（保持原有观感）
RADIUS = 10                 # 圆角
PAD_RIGHT = 18
PAD_BOTTOM = 10            # 避开任务栏
MAX_SHOW = 4
GAP = 8
HOLD_FRAMES = 190          # ~3.1s @60fps
SLIDE_FRAMES = 20
FADE_FRAMES = 16
EASE_IN = 2.0

# 文字区布局（描述自动换行，行数多了卡片就变高）
TITLE_SIZE = 15
DESC_SIZE = 11
TEXT_X = 84
TEXT_PAD_R = 14
TITLE_Y = 18
TITLE_H = 24
DESC_Y = 44                # 描述第一行的 y
DESC_BOTTOM_PAD = 14
MAX_DESC_LINES = 4         # 超过就用省略号收尾

COL_KEY = "#ff00fe"
BG_MID = (32, 36, 46)          # 卡片/文字区统一底色

# tk 字体 (微软雅黑 UI, 由 tkinter 按字体族名解析)
FONT_FAMILY = "Microsoft YaHei UI"

# 稀有度 → 标题色/边框色
RARITY_TITLE_COLORS = {
    "common":    (222, 222, 222),
    "uncommon":  (96, 200, 110),
    "rare":      (80, 150, 255),
    "epic":      (180, 110, 255),
    "legendary": (255, 200, 60),
    "mythic":    (255, 80, 70),
}
RARITY_BORDER_COLORS = {
    "common":    (150, 150, 150), # 白
    "uncommon":  (60, 140, 72),   # 绿
    "rare":      (48, 100, 200),  # 蓝
    "epic":      (120, 68, 190),  # 紫
    "legendary": (190, 145, 32),  # 金
    "mythic":    (200, 50, 44),   # 红
}

_ICON_PATH = None

# 渲染好的卡片背景缓存：同一 (稀有度, 高度) 多个弹窗直接复用，
# 避免每弹一个成就都重画一遍（PIL 合成 + 图标缩放也要几 ms）。
_BG_CACHE: dict[tuple[str, int], Image.Image] = {}
_BG_CACHE_MAX = 12

# 描述字体缓存（按 root 复用，避免每次弹窗都新建一个 Tcl 字体）
_DESC_FONTS: dict[int, "tkfont.Font"] = {}


def desc_font(root: tk.Tk) -> "tkfont.Font":
    """取（并缓存）描述用的 tk 字体 —— 量行宽与实际渲染必须是同一条字体。"""
    key = id(root)
    font = _DESC_FONTS.get(key)
    if font is None:
        font = tkfont.Font(root=root, family=FONT_FAMILY, size=DESC_SIZE)
        _DESC_FONTS[key] = font
    return font


def _resolve_icon_path() -> str | None:
    """定位项目图标 assets/images/icon/icon.png。"""
    global _ICON_PATH
    if _ICON_PATH:
        return _ICON_PATH
    base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    cands = [
        os.path.join(base, "assets", "images", "icon", "icon.png"),
        os.path.join(base, "assets", "images", "icon", "icon.ico"),
    ]
    for c in cands:
        if os.path.exists(c):
            _ICON_PATH = c
            return c
    return None


def _rounded_icon(src_path: str, size: int = 60, radius: int = 10) -> Image.Image:
    """加载图标并圆角裁剪为正方形 RGBA (无边框)。"""
    with Image.open(src_path) as im:
        im = im.convert("RGBA")
        pad = 4
        inner = size - pad * 2
        im = im.resize((inner, inner), Image.LANCZOS)  # type: ignore
        canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        canvas.paste(im, (pad, pad))
        mask = Image.new("L", (size, size), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, size - 1, size - 1),
                                               radius=radius, fill=255)
        out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        out.paste(canvas, (0, 0), mask)
        return out


def render_toast_bg(rarity: str = "common", height: int = CARD_MIN_H) -> Image.Image:
    """渲染卡片背景: 单一深色底 + 稀有度边框 + 圆角图标 (无文字)。

    ``height`` 由描述行数决定（自动换行后卡片会变高）；图标垂直居中。
    文字由 tk.Label 叠加, Label 底色与卡片底色一致 → 无缝融合。
    """
    border_col = RARITY_BORDER_COLORS.get(rarity, RARITY_BORDER_COLORS["common"])
    bg_col = BG_MID  # 单一底色 (与 Label 文字区一致)
    h = max(CARD_MIN_H, int(height))
    cached = _BG_CACHE.get((rarity, h))
    if cached is not None:
        return cached

    im = Image.new("RGBA", (CARD_W, h), (0, 0, 0, 0))
    mask = Image.new("L", (CARD_W, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, CARD_W - 1, h - 1),
                                           radius=RADIUS, fill=255)

    # 纯色填充
    fill = Image.new("RGBA", (CARD_W, h), bg_col + (255,))
    im.paste(fill, (0, 0), mask)

    # 边框 (稀有度色)
    ImageDraw.Draw(im).rounded_rectangle(
        (1, 1, CARD_W - 2, h - 2), radius=RADIUS - 1,
        outline=border_col, width=1)

    # 图标 (圆角, 无边框, 垂直居中)
    icon_path = _resolve_icon_path()
    if icon_path:
        icon = _rounded_icon(icon_path, size=70, radius=10)
        ic_x, ic_y = 12, max(2, (h - 70) // 2)
        im.paste(icon, (ic_x, ic_y), icon)

    # key 色抠圆角外：用 Image.composite 一步完成（mask=255 → 卡片，0 → key 色）。
    # 以前这里是逐像素 Python 双层循环，356×138 就要 ~49k 次迭代 → 单张卡片就是几十 ms，
    # 连续弹几个时那几帧就会明显卡（本次「动画卡顿」的直接来源）。
    im = im.convert("RGB")
    key = tuple(int(COL_KEY[i:i + 2], 16) for i in (1, 3, 5))
    out = Image.composite(im, Image.new("RGB", (CARD_W, h), key), mask)
    if len(_BG_CACHE) >= _BG_CACHE_MAX:
        _BG_CACHE.clear()
    _BG_CACHE[(rarity, h)] = out
    return out


def _hex(col) -> str:
    return "#%02x%02x%02x" % col


def wrap_text(text: str, font, max_width: int,
              max_lines: int = MAX_DESC_LINES) -> list[str]:
    """按**像素宽度**自动换行（中英文混排都按实际渲染宽度算）。

    - 显式 ``\n`` 强制换行；
    - 行满时优先回退到最近的空格（英文单词不劈开），中文逐字断；
    - 超过 ``max_lines`` 行时，最后一行用 “…” 收尾（不再像旧版那样 24 字就砍）。
    """
    if not text:
        return []
    lines: list[str] = []
    for paragraph in str(text).split("\n"):
        if not paragraph:
            lines.append("")
            continue
        cur = ""
        for ch in paragraph:
            if not cur or font.measure(cur + ch) <= max_width:
                cur += ch
                continue
            cut = cur.rfind(" ")
            if cut > 0:
                lines.append(cur[:cut])
                cur = cur[cut + 1:] + ch
            else:
                lines.append(cur)
                cur = ch
        if cur:
            lines.append(cur)
    if len(lines) <= max_lines:
        return lines
    kept = lines[:max_lines]
    tail = kept[-1]
    while tail and font.measure(tail + "…") > max_width:
        tail = tail[:-1]
    kept[-1] = (tail + "…") if tail else "…"
    return kept


_toast_q: "queue.Queue[tuple[str, str, str]]" = queue.Queue()


def show_toast_async(name: str, desc: str, rarity: str = "common"):
    """线程安全: 入队一个成就弹窗。"""
    try:
        _toast_q.put_nowait((name, desc, rarity))
    except Exception:
        pass


class _ToastWindow:
    """单个成就弹窗 (PIL 背景 + tk.Label 文字, 透明 Toplevel)。"""

    def __init__(self, root: tk.Tk, name: str, desc: str, rarity: str = "common"):
        self.root = root
        self.done = False
        self._alive = True

        # 先用同一条字体把描述量好行数（像素级，与 Label 实际渲染一致）
        self._desc_font = desc_font(root)
        text_w = CARD_W - TEXT_X - TEXT_PAD_R
        self._lines = wrap_text(desc, self._desc_font, text_w) if desc else []
        line_h = max(1, int(self._desc_font.metrics("linespace")))
        self._line_h = line_h
        # 单/两行保持原来观感（CARD_MIN_H），行数再多就把卡片长高
        needed = DESC_Y + len(self._lines) * line_h + DESC_BOTTOM_PAD
        self._h = max(CARD_MIN_H, needed)

        bg = render_toast_bg(rarity, self._h)
        self._bg_img = ImageTk.PhotoImage(bg)
        title_col = RARITY_TITLE_COLORS.get(rarity, RARITY_TITLE_COLORS["common"])

        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.configure(bg=COL_KEY)
        try:
            self.win.attributes("-transparentcolor", COL_KEY)
        except tk.TclError:
            pass

        bg_label = tk.Label(self.win, image=self._bg_img, bg=COL_KEY, bd=0)
        bg_label.place(x=0, y=0)

        # 文字 Label 底色与卡片底色一致 (单色, 无渐变冲突)
        mid_col = "#20242e"

        tk.Label(self.win, text=name,
                 font=(FONT_FAMILY, TITLE_SIZE, "bold"),
                 fg=_hex(title_col), bg=mid_col, bd=0, anchor="w").place(
            x=TEXT_X, y=TITLE_Y, width=text_w, height=TITLE_H)

        if self._lines:
            # 已按宽度量好，直接用 "\n" 拼（justify=left 左对齐，不再截断）
            tk.Label(self.win, text="\n".join(self._lines),
                     font=self._desc_font, justify="left",
                     fg="#969ca6", bg=mid_col, bd=0, anchor="nw").place(
                x=TEXT_X, y=DESC_Y, width=text_w, height=len(self._lines) * line_h)

        sw = self.win.winfo_screenwidth()
        sh = self.win.winfo_screenheight()
        self._screen_h = sh
        self._screen_w = sw
        self._target_x = sw - CARD_W - PAD_RIGHT
        self._target_y = sh - PAD_BOTTOM - self._h

        self.win.geometry(f"{CARD_W}x{self._h}+{sw}+{self._target_y}")
        try:
            self.win.attributes("-alpha", 0.0)
        except tk.TclError:
            pass
        self.win.deiconify()

        self._slide_from_x = sw
        self._frame = 0
        self._frames_total = 0
        self._state = "in"
        self._y = self._target_y
        self._last_geom: tuple[int, int] | None = None
        self._last_alpha = -1.0

    def set_slot(self, idx_from_bottom: int):
        ty = self._screen_h - PAD_BOTTOM - self._h - idx_from_bottom * (self._h + GAP)
        if ty < 40:
            ty = 40
        self._target_y = ty

    def tick(self) -> bool:
        try:
            self._frames_total += 1
            # 安全网：状态机万一被卡住（destroy 失败/事件风暴），到时强拆，
            # 不会留一张永远不消失的卡片在屏幕上。
            if self._frames_total > HOLD_FRAMES + SLIDE_FRAMES + FADE_FRAMES * 4:
                self._destroy()
                return False

            dy = self._target_y - self._y
            if abs(dy) > 1:
                self._y += dy * 0.12
                if abs(self._target_y - self._y) < 1:
                    self._y = self._target_y

            x = self._target_x
            alpha = 1.0

            if self._state == "in":
                self._frame += 1
                k = min(1.0, self._frame / SLIDE_FRAMES)
                ease = 1 - (1 - k) ** EASE_IN
                x = self._target_x + int((self._slide_from_x - self._target_x) * (1 - ease))
                alpha = min(1.0, k * 1.6)
                if k >= 1.0:
                    self._state = "hold"
                    self._frame = 0
            elif self._state == "hold":
                self._frame += 1
                if self._frame >= HOLD_FRAMES:
                    self._state = "out"
                    self._frame = 0
            elif self._state == "out":
                self._frame += 1
                k = min(1.0, self._frame / FADE_FRAMES)
                alpha = max(0.0, 1.0 - k)
                self._y += 0.8
                if k >= 1.0:
                    self._destroy()
                    return False

            self._apply_geometry(int(x), int(self._y), alpha)
            return True
        except Exception:
            self._destroy()
            return False

    def _apply_geometry(self, x: int, y: int, alpha: float) -> None:
        """只写**变化了的**属性：geometry/alpha 每帧无脑重设会让 Tk 反复重排，
        淡化尾部尤其容易看出拖影/卡顿。
        """
        if (x, y) != self._last_geom:
            self._last_geom = (x, y)
            self.win.geometry(f"{CARD_W}x{self._h}+{x}+{y}")
        if abs(alpha - self._last_alpha) > 0.02 or alpha in (0.0, 1.0):
            self._last_alpha = alpha
            try:
                self.win.attributes("-alpha", alpha)
            except tk.TclError:
                pass

    def _destroy(self):
        if not self._alive:
            return
        self._alive = False
        try:
            self.win.withdraw()      # 先隐，再毁：即便 destroy 偶尔抛错，也不会留在屏幕上
        except Exception:
            pass
        try:
            self.win.destroy()
        except Exception:
            pass


class ToastController:
    """Toast 控制器: 必须在持有 Tk 主循环的线程中创建与 pump。"""

    def __init__(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.overrideredirect(True)
        self._active: list[_ToastWindow] = []
        self._prewarm_img = None
        self._prewarm()

    def _prewarm(self):
        """预热：首次建 Toplevel / 建 ImageTk 图片 / 建 Tk 字体都是**一次性**开销
        （实测第一个弹窗那一帧 ~50ms），放在启动时先做一遍，
        之后每个弹窗都是平滑的 —— 不会再看到「第一张卡片一顿」。
        """
        try:
            img = render_toast_bg("common", CARD_MIN_H)     # 顺便填上背景缓存
            self._prewarm_img = ImageTk.PhotoImage(img)
            probe = tk.Toplevel(self.root)
            probe.withdraw()
            tk.Label(probe, image=self._prewarm_img, bd=0).place(x=0, y=0)
            tk.Label(probe, text="warm-up", font=desc_font(self.root)).place(x=0, y=0)
            probe.destroy()
        except Exception:
            pass

    def _spawn(self, name: str, desc: str, rarity: str = "common"):
        try:
            w = _ToastWindow(self.root, name, desc, rarity)
            self._active.append(w)
        except Exception:
            pass

    def _relayout(self):
        n = len(self._active)
        for i in range(n):
            self._active[i].set_slot(n - 1 - i)

    def pump(self):
        try:
            # 一帧最多新建 1 个卡片：同时解锁好几个时不会把某一帧撑到几十毫秒
            # （Tk 建窗 + 图片对象），视觉上就是连续弹出，更自然。
            if len(self._active) < MAX_SHOW:
                try:
                    name, desc, rarity = _toast_q.get_nowait()
                except queue.Empty:
                    pass
                else:
                    self._spawn(name, desc, rarity)
            if self._active:
                self._relayout()
                remain = []
                for w in self._active:
                    if w.tick():
                        remain.append(w)
                self._active = remain
            self.root.update()
        except tk.TclError:
            pass
        except Exception:
            pass

    def destroy(self):
        try:
            self.root.destroy()
        except Exception:
            pass


def demo():
    """演示: python toast.py 观看多稀有度/自动换行弹窗效果。"""
    import time
    ctrl = ToastController()
    show_toast_async("初次战斗", "完成1场战斗", "common")
    show_toast_async("无伤通关", "完成至少1场战斗且没有角色死亡", "legendary")
    show_toast_async("神也会受伤吗？",
                     "脑叶公司E.G.O::狐雨-希斯克里夫 在战斗中受到一次伤害。",
                     "uncommon")
    show_toast_async("魔法少女的悲剧",
                     "让任意一位魔法少女陷入负理智状态。\n（负理智 = 陷入恐慌）",
                     "uncommon")
    show_toast_async("长描述压力测试",
                     "这是一段非常长的描述文本，用来验证自动换行会不会把卡片撑坏、"
                     "行数超限时是不是用省略号收尾，以及文本是否右对齐/超出边界。",
                     "mythic")
    time.sleep(2)
    show_toast_async("天选之手", "累计点击 100000 次", "mythic")
    end = time.time() + 22
    while time.time() < end:
        ctrl.pump()
        time.sleep(1 / 60)
    ctrl.destroy()


def preview(out_png: str = "toast_preview.png", rarity: str = "legendary"):
    """仅渲染背景 (预览用; 文字由 tk 渲染, PNG 预览不含文字)。"""
    im = render_toast_bg(rarity)
    im.save(out_png)
    print("saved:", out_png)


if __name__ == "__main__":
    import sys
    if "--preview" in sys.argv:
        rarity = "legendary"
        out = "toast_preview.png"
        if len(sys.argv) > 2:
            rarity = sys.argv[2]
        if len(sys.argv) > 3:
            out = sys.argv[3]
        preview(out, rarity)
    else:
        demo()
