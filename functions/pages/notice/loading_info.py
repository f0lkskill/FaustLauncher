import tkinter as tk
import time
import threading
import sys
import os
from functions.base.window_utils import center_window
from functions.base.settings_manager import get_settings_manager

VERSION_INFO = get_settings_manager().get_setting("version_info")  # type: ignore
BG_COLOR: str = get_settings_manager().get_setting("bg_color")  # type: ignore
bg_gaussian_blur: int = get_settings_manager().get_setting("bg_gaussian_blur")  # type: ignore
bg_gaussian_blur += 5

def _parse_rgb(hex_color: str):
    h = hex_color.lstrip('#')
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))

TRANSPARENT = '#010203'
CARD_BG = BG_COLOR
ACCENT = '#4a9eff'
ACCENT_DIM = '#1a4a7a'
TEXT_PRIMARY = "#eaeaea"
TEXT_SECONDARY = "#ffffff"
TEXT_MUTED = "#c2dcff"

class ModernSplashScreen:
    def __init__(self, root):
        self.root = root
        self.splash = tk.Toplevel(root)
        self.splash.title("Faust Launcher")
        self.splash.geometry("520x380")
        self.splash.overrideredirect(True)
        self.splash.wm_attributes('-transparentcolor', TRANSPARENT)
        self.splash.attributes('-alpha', 0.0)
        self.splash.attributes('-topmost', True)
        self.splash.configure(bg=TRANSPARENT)

        self.canvas = tk.Canvas(self.splash,
                               bg=TRANSPARENT,
                               highlightthickness=0,
                               width=520,
                               height=380)
        self.canvas.pack(fill='both', expand=True)

        center_window(self.splash)
        
        self._bg_photo = None
        self._draw_background()
        self.create_ui_elements()

        self.animation_running = True
        self.fade_in_complete = False
        self._dots_frame = 0
        self._status_base_text = "正在启动"
        self._status_override = None
        self._glass_alpha = 1.0

    @staticmethod
    def _pil_rounded_rect_mask(size, radius):
        W, H = size
        from PIL import Image, ImageDraw
        mask = Image.new('L', (W, H), 0)
        draw = ImageDraw.Draw(mask)
        draw.rounded_rectangle((0, 0, W - 1, H - 1), radius=radius, fill=255)
        return mask

    def _draw_background(self):
        W, H = 520, 380
        R = 18

        bg_loaded = False
        try:
            from PIL import Image, ImageTk, ImageFilter, ImageEnhance
            import glob,random
            candidates = glob.glob('assets/images/background/*.jpg')
            base_dir = os.path.join(os.path.dirname(os.path.abspath(
                sys.argv[0])) if sys.argv else os.getcwd(), 'assets', 'images', 'background')
            if not os.path.isdir(base_dir):
                base_dir = os.path.join(os.getcwd(), 'assets', 'images', 'background')

            chosen = random.choice(candidates)
            if chosen is None:
                for fn in sorted(os.listdir(base_dir)):
                    if fn.lower().endswith(('.jpg', '.jpeg', '.png')):
                        chosen = os.path.join(base_dir, fn)
                        break

            if chosen:
                img = Image.open(chosen).convert('RGB')
                iw, ih = img.size
                scale = max(W / iw, H / ih)
                nw, nh = int(iw * scale), int(ih * scale)
                img = img.resize((nw, nh), Image.Resampling.LANCZOS)
                left = (nw - W) // 2
                top = (nh - H) // 2
                img = img.crop((left, top, left + W, top + H))
                img = img.filter(ImageFilter.GaussianBlur(radius=bg_gaussian_blur))
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
                self._rounded_rect(12, 12, 508, 368, r=R,
                                   fill=BG_COLOR, outline='')

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

    def center_window(self):
        self.splash.update_idletasks()
        screen_width = self.splash.winfo_screenwidth()
        screen_height = self.splash.winfo_screenheight()
        x = (screen_width - 500) // 2
        y = (screen_height - 350) // 2
        self.splash.geometry(f"+{x}+{y}")

    def _fade_in_item(self, item, item_type='text', target_fill=None, steps=12):
        if not self.animation_running:
            return
        self.canvas.itemconfig(item, state='normal')
        if steps <= 0:
            return
        stipple_levels = ['gray12', 'gray25', 'gray50', 'gray75']
        def step(i=0):
            if not self.animation_running:
                return
            if i < len(stipple_levels):
                try:
                    self.canvas.itemconfig(item, stipple=stipple_levels[i])
                except tk.TclError:
                    pass
                self.splash.after(25, lambda: step(i + 1))
            else:
                try:
                    self.canvas.itemconfig(item, stipple='')
                except tk.TclError:
                    pass
        step()

    def create_ui_elements(self):
        cx = 260

        try:
            import os
            icon_path = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])) if hasattr(sys, 'argv') and sys.argv else os.getcwd(),
                                      "assets/images/icon/icon.png")
            if not os.path.exists(icon_path):
                icon_path = os.path.join(os.getcwd(), "assets/images/icon/icon.png")
            from PIL import Image, ImageTk
            img = Image.open(icon_path)
            img = img.resize((100, 100), Image.Resampling.LANCZOS)
            self.icon_img = img
            self.icon_photo = ImageTk.PhotoImage(img)
            self.icon_item = self.canvas.create_image(cx, 80, image=self.icon_photo)
        except Exception:
            self.icon_item = self.canvas.create_text(cx, 90,
                                                     text="🎭",
                                                     font=('Microsoft YaHei UI', 40),
                                                     fill=ACCENT)

        self.title_item = self.canvas.create_text(cx, 155,
                                                  text="Faust Launcher",
                                                  font=('Microsoft YaHei UI', 22, 'bold'),
                                                  fill=TEXT_PRIMARY,
                                                  state='normal')

        self.subtitle_item = self.canvas.create_text(cx, 195,
                                                     text="正在启动...",
                                                     font=('Microsoft YaHei UI', 15),
                                                     fill=TEXT_SECONDARY,
                                                     state='normal')

        bar_x1, bar_x2 = 80, 440
        bar_y1, bar_y2 = 230, 240
        self._bar_x1, self._bar_x2 = bar_x1, bar_x2
        self._bar_y1, self._bar_y2 = bar_y1, bar_y2
        self._rounded_rect(bar_x1, bar_y1, bar_x2, bar_y2, r=5,
                           fill='#21262d', outline='')
        self.progress_fg = self.canvas.create_rectangle(
            bar_x1, bar_y1, bar_x1, bar_y2, fill=ACCENT, outline='')

        self.progress_text = self.canvas.create_text(cx, 258,
                                                     text="0%",
                                                     font=('Microsoft YaHei UI', 10, 'bold'),
                                                     fill=ACCENT,
                                                     state='normal')

        self.version_item = self.canvas.create_text(cx, 330,
                                                    text=f"{VERSION_INFO}",
                                                    font=('Microsoft YaHei UI', 14),
                                                    fill=TEXT_MUTED,
                                                    state='normal')

    def fade_in(self):
        def animate_fade_in(alpha=0.0):
            if alpha < 1.0 and self.animation_running:
                self.splash.attributes('-alpha', alpha)
                self.splash.after(25, lambda: animate_fade_in(alpha + 0.05))
            else:
                self.splash.attributes('-alpha', 1.0)
                self.fade_in_complete = True

        self.show_content_animation()
        animate_fade_in()
        
    def _show_item(self, item):
        self._fade_in_item(item)

    def show_content_animation(self):
        self.splash.after(700, self.start_progress_animation)

    def _animate_dots(self):
        if not self.animation_running:
            return
        self._dots_frame = (self._dots_frame + 1) % 4
        dots = '.' * self._dots_frame
        text = self._status_base_text + dots if dots else self._status_base_text
        if hasattr(self, '_status_override'):
            text = self._status_override
        self.canvas.itemconfig(self.subtitle_item, text=text)
        self.splash.after(400, self._animate_dots)

    def start_progress_animation(self):
        self._animate_dots()

        def animate_progress(progress=0):
            if progress <= 100 and self.animation_running:
                total_w = self._bar_x2 - self._bar_x1
                progress_w = self._bar_x1 + (progress / 100.0) * total_w
                self.canvas.coords(self.progress_fg,
                                   self._bar_x1, self._bar_y1,
                                   progress_w, self._bar_y2)
                self.canvas.itemconfig(self.progress_text, text=f"{progress}%")

                status_texts = [
                    "浮士德正在检查系统环境...",
                    "检测梅菲斯特剩余燃料...",
                    "初始化界面组件...",   
                    "正在准备但丁最喜欢的狂气...",
                    "初始化工具组...",
                    "云端数据同步...",
                    "即将完成..."
                ]
                idx = min(len(status_texts) - 1, progress // 25)
                self._status_base_text = status_texts[idx]
                self.canvas.itemconfig(self.subtitle_item, text=self._status_base_text,
                                       fill=ACCENT)
                delay = 12 if progress < 80 else 35
                self.splash.after(delay, lambda: animate_progress(progress + 1))
            elif progress > 100:
                self._status_override = "欢迎您，但丁。"
                self.canvas.itemconfig(self.subtitle_item, text=self._status_override,
                                       fill=ACCENT)
                self.splash.after(600, self.fade_out)

        animate_progress()

    def fade_out(self):
        def animate_fade_out(alpha=1.0):
            if alpha > 0.0 and self.animation_running:
                self.splash.attributes('-alpha', alpha)
                self.splash.after(20, lambda: animate_fade_out(alpha - 0.05))
            else:
                self.splash.attributes('-alpha', 0.0)
                self.close()
        animate_fade_out()

    def show(self):
        self.splash.update()
        self.splash.after(0, self.fade_in)
        return self.splash

    def close(self):
        self.animation_running = False
        self.splash.destroy()

    def update_status(self, text, progress=None):
        if hasattr(self, 'subtitle_item'):
            self.canvas.itemconfig(self.subtitle_item, text=text)
        
        if progress is not None and hasattr(self, 'progress_fg'):
            progress_width = 100 + (progress / 100) * 300
            self.canvas.coords(self.progress_fg, 100, 240, progress_width, 250)
            self.canvas.itemconfig(self.progress_text, text=f"{progress}%")
        
        self.splash.update()

def show_loading_page(root):
    splash = ModernSplashScreen(root)
    splash_root = splash.show()
    
    def init_app():
        stages = [
            ("浮士德正在检查系统环境...", 10),
            ("检测梅菲斯特剩余燃料...", 25),
            ("初始化界面组件...", 45),
            ("正在准备但丁最喜欢的狂气...", 65),
            ("正在给卡戎买糖果...", 85),
            ("即将完成...", 100)
        ]
        
        for text, progress in stages:
            time.sleep(0.8)
            splash_root.after(0, lambda t=text, p=progress: splash.update_status(t, p))
        
        time.sleep(0.5)
        splash_root.after(0, splash.fade_out)
    
    init_thread = threading.Thread(target=init_app)
    init_thread.daemon = True
    init_thread.start()
    
    splash_root.mainloop()

def create_simple_splash(root):
    splash = ModernSplashScreen(root)
    splash_root = splash.show()
    return splash, splash_root
