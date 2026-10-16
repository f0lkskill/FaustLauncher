
import os
import queue
import threading
import tkinter as tk
import tkinter.font as tkfont

from PIL import Image, ImageDraw, ImageTk

CARD_W = 356
CARD_MIN_H = 94
RADIUS = 10
PAD_RIGHT = 18
PAD_BOTTOM = 10
MAX_SHOW = 4
GAP = 8
HOLD_FRAMES = 190
SLIDE_FRAMES = 20
FADE_FRAMES = 16
EASE_IN = 2.0

TITLE_SIZE = 15
DESC_SIZE = 11
TEXT_X = 84
TEXT_PAD_R = 14
TITLE_Y = 18
TITLE_H = 24
DESC_Y = 44
DESC_BOTTOM_PAD = 14
MAX_DESC_LINES = 4

COL_KEY = "#ff00fe"
BG_MID = (32, 36, 46)

ICON_SIZE = 70
ICON_RADIUS = 16
ICON_X = 12

FONT_FAMILY = "Microsoft YaHei UI"

RARITY_TITLE_COLORS = {
    "common":    (222, 222, 222),
    "uncommon":  (96, 200, 110),
    "rare":      (80, 150, 255),
    "epic":      (180, 110, 255),
    "legendary": (255, 200, 60),
    "mythic":    (255, 80, 70),
}
RARITY_BORDER_COLORS = {
    "common":    (150, 150, 150),
    "uncommon":  (60, 140, 72),
    "rare":      (48, 100, 200),
    "epic":      (120, 68, 190),
    "legendary": (190, 145, 32),
    "mythic":    (200, 50, 44),
}

_ICON_PATH = None

_ACH_ICON_CACHE: dict[str, str | None] = {}
_ACH_ART_DIR: str | None = None

_BG_CACHE: dict[tuple, Image.Image] = {}
_BG_CACHE_MAX = 12

_DESC_FONTS: dict[int, "tkfont.Font"] = {}

def desc_font(root: tk.Tk) -> "tkfont.Font":
    key = id(root)
    font = _DESC_FONTS.get(key)
    if font is None:
        font = tkfont.Font(root=root, family=FONT_FAMILY, size=DESC_SIZE)
        _DESC_FONTS[key] = font
    return font

def _resolve_icon_path() -> str | None:
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

def _achievement_art_dir() -> str:
    global _ACH_ART_DIR
    if _ACH_ART_DIR is None:
        try:
            from functions.base.common.path_utils import get_web_root
            _ACH_ART_DIR = get_web_root("app", "assets", "achievement")
        except Exception:  # noqa: BLE001
            _ACH_ART_DIR = ""
    return _ACH_ART_DIR

def _resolve_achievement_icon(ach_id: str) -> str | None:
    aid = str(ach_id or "").strip()
    if not aid:
        return None
    if aid in _ACH_ICON_CACHE:
        return _ACH_ICON_CACHE[aid]
    path = None
    art_dir = _achievement_art_dir()
    if art_dir:
        for ext in (".png", ".webp", ".jpg", ".svg"):
            cand = os.path.join(art_dir, aid + ext)
            if os.path.isfile(cand):
                path = cand
                break
    _ACH_ICON_CACHE[aid] = path
    return path

def _rounded_icon(src_path: str, size: int = 60, radius: int = 10) -> Image.Image:
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

def render_toast_bg(rarity: str = "common", height: int = CARD_MIN_H,
                    ach_id: str = "") -> Image.Image:
    border_col = RARITY_BORDER_COLORS.get(rarity, RARITY_BORDER_COLORS["common"])
    bg_col = BG_MID
    h = max(CARD_MIN_H, int(height))
    cached = _BG_CACHE.get((rarity, h, ach_id))
    if cached is not None:
        return cached

    im = Image.new("RGBA", (CARD_W, h), (0, 0, 0, 0))
    mask = Image.new("L", (CARD_W, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, CARD_W - 1, h - 1),
                                           radius=RADIUS, fill=255)

    fill = Image.new("RGBA", (CARD_W, h), bg_col + (255,))
    im.paste(fill, (0, 0), mask)

    ImageDraw.Draw(im).rounded_rectangle(
        (1, 1, CARD_W - 2, h - 2), radius=RADIUS - 1,
        outline=border_col, width=1)

    icon_path = _resolve_achievement_icon(ach_id) or _resolve_icon_path()
    if icon_path:
        icon = _rounded_icon(icon_path, size=ICON_SIZE, radius=ICON_RADIUS)
        ic_x, ic_y = ICON_X, max(2, (h - ICON_SIZE) // 2)
        im.paste(icon, (ic_x, ic_y), icon)

    im = im.convert("RGB")
    key = tuple(int(COL_KEY[i:i + 2], 16) for i in (1, 3, 5))
    out = Image.composite(im, Image.new("RGB", (CARD_W, h), key), mask)
    if len(_BG_CACHE) >= _BG_CACHE_MAX:
        _BG_CACHE.clear()
    _BG_CACHE[(rarity, h, ach_id)] = out
    return out

def _hex(col) -> str:
    return "#%02x%02x%02x" % col

def wrap_text(text: str, font, max_width: int,
              max_lines: int = MAX_DESC_LINES) -> list[str]:
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

_toast_q: "queue.Queue[tuple[str, str, str, str]]" = queue.Queue()

def show_toast_async(name: str, desc: str, rarity: str = "common", ach_id: str = ""):
    try:
        _toast_q.put_nowait((name, desc, rarity, str(ach_id or "")))
    except Exception:
        pass

class _ToastWindow:

    def __init__(self, root: tk.Tk, name: str, desc: str, rarity: str = "common",
                 ach_id: str = ""):
        self.root = root
        self.done = False
        self._alive = True

        self._desc_font = desc_font(root)
        text_w = CARD_W - TEXT_X - TEXT_PAD_R
        self._lines = wrap_text(desc, self._desc_font, text_w) if desc else []
        line_h = max(1, int(self._desc_font.metrics("linespace")))
        self._line_h = line_h
        needed = DESC_Y + len(self._lines) * line_h + DESC_BOTTOM_PAD
        self._h = max(CARD_MIN_H, needed)

        bg = render_toast_bg(rarity, self._h, ach_id)
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

        mid_col = "#20242e"

        tk.Label(self.win, text=name,
                 font=(FONT_FAMILY, TITLE_SIZE, "bold"),
                 fg=_hex(title_col), bg=mid_col, bd=0, anchor="w").place(
            x=TEXT_X, y=TITLE_Y, width=text_w, height=TITLE_H)

        if self._lines:
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
            self.win.withdraw()
        except Exception:
            pass
        try:
            self.win.destroy()
        except Exception:
            pass

class ToastController:

    def __init__(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.overrideredirect(True)
        self._active: list[_ToastWindow] = []
        self._prewarm_img = None
        self._prewarm()

    def _prewarm(self):
        try:
            img = render_toast_bg("common", CARD_MIN_H)
            self._prewarm_img = ImageTk.PhotoImage(img)
            probe = tk.Toplevel(self.root)
            probe.withdraw()
            tk.Label(probe, image=self._prewarm_img, bd=0).place(x=0, y=0)
            tk.Label(probe, text="warm-up", font=desc_font(self.root)).place(x=0, y=0)
            probe.destroy()
        except Exception:
            pass

    def _spawn(self, name: str, desc: str, rarity: str = "common", ach_id: str = ""):
        try:
            w = _ToastWindow(self.root, name, desc, rarity, ach_id)
            self._active.append(w)
        except Exception:
            pass

    def _relayout(self):
        n = len(self._active)
        for i in range(n):
            self._active[i].set_slot(n - 1 - i)

    def has_work(self) -> bool:
        return bool(self._active) or not _toast_q.empty()

    def pump(self):
        try:
            if len(self._active) < MAX_SHOW:
                try:
                    name, desc, rarity, ach_id = _toast_q.get_nowait()
                except queue.Empty:
                    pass
                else:
                    self._spawn(name, desc, rarity, ach_id)
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
