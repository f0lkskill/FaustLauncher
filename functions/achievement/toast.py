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

from PIL import Image, ImageDraw, ImageTk

# ============ 常量 ============
CARD_W = 356
CARD_H = 94
RADIUS = 10                 # 圆角
PAD_RIGHT = 18
PAD_BOTTOM = 10            # 避开任务栏
MAX_SHOW = 4
GAP = 8
HOLD_FRAMES = 190          # ~3.1s @60fps
SLIDE_FRAMES = 20
FADE_FRAMES = 16
EASE_IN = 2.0

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
    "common":    (150, 150, 150),
    "uncommon":  (60, 140, 72),
    "rare":      (48, 100, 200),
    "epic":      (120, 68, 190),
    "legendary": (190, 145, 32),
    "mythic":    (200, 50, 44),
}

_ICON_PATH = None


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


def render_toast_bg(rarity: str = "common") -> Image.Image:
    """渲染卡片背景: 单一深色底 + 稀有度边框 + 圆角图标 (无文字)。

    文字由 tk.Label 叠加, Label 底色与卡片底色一致 → 无缝融合。
    """
    border_col = RARITY_BORDER_COLORS.get(rarity, RARITY_BORDER_COLORS["common"])
    bg_col = BG_MID  # 单一底色 (与 Label 文字区一致)

    im = Image.new("RGBA", (CARD_W, CARD_H), (0, 0, 0, 0))
    mask = Image.new("L", (CARD_W, CARD_H), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, CARD_W - 1, CARD_H - 1),
                                           radius=RADIUS, fill=255)

    # 纯色填充
    fill = Image.new("RGBA", (CARD_W, CARD_H), bg_col + (255,))
    im.paste(fill, (0, 0), mask)

    # 边框 (稀有度色)
    ImageDraw.Draw(im).rounded_rectangle(
        (1, 1, CARD_W - 2, CARD_H - 2), radius=RADIUS - 1,
        outline=border_col, width=1)

    # 图标 (圆角, 无边框)
    icon_path = _resolve_icon_path()
    if icon_path:
        icon = _rounded_icon(icon_path, size=70, radius=10)
        ic_x, ic_y = 12, (CARD_H - 70) // 2
        im.paste(icon, (ic_x, ic_y), icon)

    # key 色抠圆角外
    im = im.convert("RGB")
    key = tuple(int(COL_KEY[i:i + 2], 16) for i in (1, 3, 5))
    px = im.load()
    mask_px = mask.load()
    for y in range(CARD_H):
        for x in range(CARD_W):
            if mask_px[x, y] < 128:  # type: ignore
                px[x, y] = key  # type: ignore
    return im


def _hex(col) -> str:
    return "#%02x%02x%02x" % col


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

        bg = render_toast_bg(rarity)
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

        text_x = 84
        text_w = CARD_W - text_x - 14

        # tk.Label(self.win, text="解锁成就",
        #          font=(FONT_FAMILY, 8, "bold"),
        #          fg="#ffffff", bg=mid_col, bd=0, anchor="w").place(
        #     x=text_x, y=12, width=text_w, height=16)

        tk.Label(self.win, text=name,
                 font=(FONT_FAMILY, 15, "bold"),
                 fg=_hex(title_col), bg=mid_col, bd=0, anchor="w").place(
            x=text_x, y=18, width=text_w, height=24)

        if desc:
            if len(desc) > 24:
                desc = desc[:23] + "…"
            tk.Label(self.win, text=desc,
                     font=(FONT_FAMILY, 11, "normal"),
                     fg="#969ca6", bg=mid_col, bd=0, anchor="w").place(
                x=text_x, y=46, width=text_w, height=18)

        sw = self.win.winfo_screenwidth()
        sh = self.win.winfo_screenheight()
        self._screen_h = sh
        self._screen_w = sw
        self._target_x = sw - CARD_W - PAD_RIGHT
        self._target_y = sh - PAD_BOTTOM - CARD_H

        self.win.geometry(f"{CARD_W}x{CARD_H}+{sw}+{self._target_y}")
        try:
            self.win.attributes("-alpha", 0.0)
        except tk.TclError:
            pass
        self.win.deiconify()

        self._slide_from_x = sw
        self._frame = 0
        self._state = "in"
        self._y = self._target_y

    def set_slot(self, idx_from_bottom: int):
        ty = self._screen_h - PAD_BOTTOM - CARD_H - idx_from_bottom * (CARD_H + GAP)
        if ty < 40:
            ty = 40
        self._target_y = ty

    def tick(self) -> bool:
        try:
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

            self.win.geometry(f"{CARD_W}x{CARD_H}+{int(x)}+{int(self._y)}")
            try:
                self.win.attributes("-alpha", alpha)
            except tk.TclError:
                pass
            return True
        except Exception:
            self._destroy()
            return False

    def _destroy(self):
        if not self._alive:
            return
        self._alive = False
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
            while len(self._active) < MAX_SHOW:
                try:
                    name, desc, rarity = _toast_q.get_nowait()
                except queue.Empty:
                    break
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
    """演示: python toast.py 观看多稀有度弹窗效果。"""
    import time
    ctrl = ToastController()
    show_toast_async("初次战斗", "完成1场战斗", "common")
    show_toast_async("无伤通关", "完成至少1场战斗且没有角色死亡", "legendary")
    time.sleep(2)
    show_toast_async("天选之手", "累计点击 100000 次", "mythic")
    end = time.time() + 16
    while time.time() < end:
        ctrl.pump()
        time.sleep(0.016)
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
