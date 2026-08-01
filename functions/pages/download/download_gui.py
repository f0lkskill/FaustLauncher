import tkinter as tk
import threading
import time
from functions.base.window_utils import center_window
from functions.base.settings_manager import get_settings_manager
from functions.base.color_scheme import C, ThemeColors

BG_COLOR: str = get_settings_manager().get_setting("bg_color") # type: ignore
_bg_blur_raw: int = get_settings_manager().get_setting("bg_gaussian_blur") # type: ignore
BG_GAUSSIAN_BLUR: int = _bg_blur_raw + 5


def _parse_rgb(hex_color: str):
    h = hex_color.lstrip('#')
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


TRANSPARENT = C.TRANSPARENT
ACCENT = C.DOWNLOAD_ACCENT
TEXT_PRIMARY = C.TEXT_PRIMARY
TEXT_SECONDARY = C.TEXT_WHITE
TEXT_MUTED = "#c2dcff"
BAR_BG = C.DOWNLOAD_BAR_BG


class DownloadGUI:
    def __init__(self, parent, config_path: str = "", auto_start: bool = True,
                 download_func=None):
        self.root = tk.Toplevel(parent)
        self.root.attributes('-alpha', 0.0)
        self.root.withdraw()
        
        self.root.title("下载中...")

        W, H = 500, 280
        self.root.geometry(f"{W}x{H}")
        self.root.overrideredirect(True)
        self.root.wm_attributes('-transparentcolor', TRANSPARENT)
        # self.root.attributes('-topmost', True)
        self.root.configure(bg=TRANSPARENT)

        center_window(self.root)
        
        self.canvas = tk.Canvas(self.root, bg=TRANSPARENT,
                                highlightthickness=0, width=W, height=H)
        self.canvas.pack(fill='both', expand=True)

        self.canvas.bind('<Button-1>', self._start_drag)
        self.canvas.bind('<B1-Motion>', self._do_drag)


        self.config_path = config_path
        self.is_downloading = True
        self._bg_photo = None

        self.current_file_var = tk.StringVar(value="初始化下载组件...")
        self.progress_var = tk.DoubleVar()
        self.progress_text_var = tk.StringVar(value="0%")
        self.speed_var = tk.StringVar(value="0 KB/s")
        self.status_var = tk.StringVar(value="准备开始下载...")

        self.current_file_var.trace('w', self._on_file_var_changed)

        self._draw_background()
        self.create_widgets()

        self.fade_in()

        if auto_start:
            self.start_download(download_func)

    @staticmethod
    def _pil_rounded_rect_mask(size, radius):
        from PIL import Image, ImageDraw
        W, H = size
        mask = Image.new('L', (W, H), 0)
        draw = ImageDraw.Draw(mask)
        draw.rounded_rectangle((0, 0, W - 1, H - 1), radius=radius, fill=255)
        return mask

    def _draw_background(self):
        W, H = 500, 280
        R = 18

        bg_loaded = False
        try:
            from PIL import Image, ImageTk, ImageFilter, ImageEnhance
            import glob as _glob
            import random as _random
            candidates = _glob.glob('assets/images/background/*.jpg')

            if candidates:
                chosen = _random.choice(candidates)
                img = Image.open(chosen).convert('RGB')
                iw, ih = img.size
                scale = max(W / iw, H / ih)
                nw, nh = int(iw * scale), int(ih * scale)
                img = img.resize((nw, nh), Image.Resampling.LANCZOS)
                left = (nw - W) // 2
                top = (nh - H) // 2
                img = img.crop((left, top, left + W, top + H))
                img = img.filter(ImageFilter.GaussianBlur(radius=BG_GAUSSIAN_BLUR))
                img = ImageEnhance.Brightness(img).enhance(0.65)
                final = Image.new('RGB', (W, H), _parse_rgb(TRANSPARENT))
                mask = self._pil_rounded_rect_mask((W, H), R)
                final.paste(img, (0, 0), mask)
                self._bg_photo = ImageTk.PhotoImage(final)
                self.canvas.create_image(W // 2, H // 2, image=self._bg_photo)
                bg_loaded = True
        except Exception:
            pass

        if not bg_loaded:
            try:
                from PIL import Image, ImageTk
                final = Image.new('RGB', (W, H), _parse_rgb(TRANSPARENT))
                panel = Image.new('RGB', (W - 24, H - 24), _parse_rgb(BG_COLOR))
                mask = self._pil_rounded_rect_mask((W - 24, H - 24), R)
                final.paste(panel, (12, 12), mask)
                self._bg_photo = ImageTk.PhotoImage(final)
                self.canvas.create_image(W // 2, H // 2, image=self._bg_photo)
            except Exception:
                pass

    def _rounded_rect(self, x1, y1, x2, y2, r=12, **kwargs):
        d = r * 2
        self.canvas.create_arc(x1, y1, x1 + d, y1 + d,
                               start=90, extent=90, style='pieslice', **kwargs)
        self.canvas.create_arc(x2 - d, y1, x2, y1 + d,
                               start=0, extent=90, style='pieslice', **kwargs)
        self.canvas.create_arc(x1, y2 - d, x1 + d, y2,
                               start=180, extent=90, style='pieslice', **kwargs)
        self.canvas.create_arc(x2 - d, y2 - d, x2, y2,
                               start=270, extent=90, style='pieslice', **kwargs)
        self.canvas.create_rectangle(x1 + r, y1, x2 - r, y2, **kwargs)
        self.canvas.create_rectangle(x1, y1 + r, x2, y2 - r, **kwargs)

    def fade_in(self):
        def animate(alpha=0.0):
            if alpha < 1.0 and self.is_downloading:
                self.root.attributes('-alpha', alpha)
                self.root.after(25, lambda: animate(alpha + 0.05))
            else:
                self.root.attributes('-alpha', 1.0)
        animate()

    def create_widgets(self):
        cx = 250

        self.title_item = self.canvas.create_text(
            cx, 85, text="正在下载",
            font=('Microsoft YaHei UI', 20, 'bold'), fill=TEXT_PRIMARY)

        self.file_item = self.canvas.create_text(
            cx, 115, text="初始化下载组件...",
            font=('Microsoft YaHei UI', 12), fill=TEXT_MUTED)

        bar_x1, bar_x2 = 60, 440
        bar_y1, bar_y2 = 148, 158
        self._bar_x1, self._bar_x2 = bar_x1, bar_x2
        self._bar_y1, self._bar_y2 = bar_y1, bar_y2
        self._rounded_rect(bar_x1, bar_y1, bar_x2, bar_y2, r=5,
                           fill=BAR_BG, outline='')
        self.progress_fg = self.canvas.create_rectangle(
            bar_x1, bar_y1, bar_x1, bar_y2, fill=ACCENT, outline='')

        self.percent_item = self.canvas.create_text(
            65, 180, text="0%",
            font=('Microsoft YaHei UI', 13, 'bold'),
            fill=ACCENT, anchor='w')

        self.size_item = self.canvas.create_text(
            245, 180, text="-- / --",
            font=('Microsoft YaHei UI', 11),
            fill=TEXT_MUTED, anchor='center')

        self.speed_item = self.canvas.create_text(
            435, 180, text="速度: 0 KB/s",
            font=('Microsoft YaHei UI', 11),
            fill=TEXT_MUTED, anchor='e')

        self.status_item = self.canvas.create_text(
            cx, 215, text="准备开始下载...",
            font=('Microsoft YaHei UI', 12), fill=ACCENT)

    # ── 拖拽支持 ──
    def _start_drag(self, event):
        self._drag_x = event.x
        self._drag_y = event.y

    def _do_drag(self, event):
        dx = event.x - self._drag_x
        dy = event.y - self._drag_y
        x = self.root.winfo_x() + dx
        y = self.root.winfo_y() + dy
        self.root.geometry(f'+{x}+{y}')

    # ── 淡出动画 ──
    def fade_out(self):
        def animate(alpha=1.0):
            if alpha > 0.0:
                self.root.attributes('-alpha', alpha)
                self.root.after(20, lambda: animate(alpha - 0.05))
            else:
                self.root.attributes('-alpha', 0.0)
                self.is_downloading = False
                self.root.destroy()
        animate()

    def _on_file_var_changed(self, *args):
        try:
            if hasattr(self, 'file_item'):
                self.canvas.itemconfig(self.file_item, text=self.current_file_var.get())
        except Exception:
            pass

    def update_progress(self, percent, downloaded, total, speed):
        if hasattr(self, 'progress_fg'):
            total_w = self._bar_x2 - self._bar_x1
            if total_w > 0:
                progress_w = self._bar_x1 + (percent / 100.0) * total_w
                self.canvas.coords(self.progress_fg,
                                   self._bar_x1, self._bar_y1,
                                   progress_w, self._bar_y2)

        if percent < 10:
            status = "初始化下载..."
        elif percent < 50:
            status = "下载中..."
        elif percent < 90:
            status = "马上就好..."
        elif percent < 100:
            status = "即将完成..."
        else:
            status = "下载完成!"
        if hasattr(self, 'status_item'):
            self.canvas.itemconfig(self.status_item, text=status)

        if total >= 1024 * 1024 * 1024:
            d_str = f"{downloaded / 1024 / 1024 / 1024:.1f}GB"
            t_str = f"{total / 1024 / 1024 / 1024:.1f}GB"
        elif total >= 1024 * 1024:
            d_str = f"{downloaded / 1024 / 1024:.1f}MB"
            t_str = f"{total / 1024 / 1024:.1f}MB"
        elif total >= 1024:
            d_str = f"{downloaded / 1024:.1f}KB"
            t_str = f"{total / 1024:.1f}KB"
        else:
            d_str = f"{downloaded}B"
            t_str = f"{total}B"

        if hasattr(self, 'percent_item'):
            self.canvas.itemconfig(self.percent_item, text=f"{percent:.1f}%")
        if hasattr(self, 'size_item'):
            self.canvas.itemconfig(self.size_item, text=f"{d_str} / {t_str}")

        if speed >= 1024:
            speed_s = f"{speed / 1024:.1f} MB/s"
        else:
            speed_s = f"{speed:.1f} KB/s"
        if hasattr(self, 'speed_item'):
            self.canvas.itemconfig(self.speed_item, text=f"速度: {speed_s}")

        self.progress_var.set(percent)
        self.speed_var.set(f"速度: {speed_s}")
        self.status_var.set(status)

        self.root.update_idletasks()

    def start_download(self, download_func=None):
        self.is_downloading = True
        thread = threading.Thread(target=self.run_download, args=(download_func,))
        thread.daemon = True
        thread.start()

    def run_download(self, download_func=None):
        try:
            success = download_func(self, self.config_path) # type: ignore
            if success:
                self.root.after(1000, self.root.destroy)
            else:
                self.current_file_var.set("下载失败，请检查错误信息")
                time.sleep(3)
                self.root.after(1000, self.root.destroy)
        except Exception as e:
            self.current_file_var.set(f"下载过程中出现错误: {e}")
        finally:
            self.is_downloading = False
            self.root.after(1000, self.root.destroy)