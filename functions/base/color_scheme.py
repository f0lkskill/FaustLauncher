"""
集中配色方案模块
所有 UI 颜色都从这里统一获取，不再在各文件中硬编码。
"""
import colorsys


# ========== 工厂函数 ==========

def lighten_color(color: str, percent: float) -> str:
    """颜色变亮 (HLS色彩空间，百分制)"""
    rgb = tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))
    h, l, s = colorsys.rgb_to_hls(rgb[0] / 255, rgb[1] / 255, rgb[2] / 255)
    l = min(1.0, l + percent / 100)
    r, g, b = colorsys.hls_to_rgb(h, l, s)
    return f"#{int(r * 255):02x}{int(g * 255):02x}{int(b * 255):02x}"


def darken_color(color: str, factor: float = 0.8) -> str:
    """加深颜色 (RGB线性缩放)"""
    if color.startswith('#'):
        r = int(color[1:3], 16)
        g = int(color[3:5], 16)
        b = int(color[5:7], 16)
        r = max(0, min(255, int(r * factor)))
        g = max(0, min(255, int(g * factor)))
        b = max(0, min(255, int(b * factor)))
        return f'#{r:02x}{g:02x}{b:02x}'
    return color


# ========== 语义化颜色常量 ==========

class SemanticColors:
    """语义化颜色常量 —— 所有 UI 都从这里引用"""
    
    # --- 强调色 ---
    ACCENT = '#6366f1'
    ACCENT_HOVER = '#4f46e5'
    ACCENT_LIGHT = '#818cf8'
    ACCENT_SECONDARY = '#3b82f6'
    ACCENT_SECONDARY_HOVER = '#2563eb'
    
    # --- 功能色 ---
    SUCCESS = '#10b981'
    SUCCESS_HOVER = '#059669'
    WARNING = '#f59e0b'
    WARNING_HOVER = '#d97706'
    DANGER = '#ef4444'
    DANGER_HOVER = '#dc2626'
    DANGER_DARK = '#b91c1c'
    INFO = '#3b82f6'
    INFO_HOVER = '#2563eb'
    
    # --- 辅助强调色 (工具卡片等) ---
    PURPLE = '#8b5cf6'
    PURPLE_HOVER = '#7c3aed'
    ORANGE = '#f59e0b'
    ORANGE_HOVER = '#d97706'
    CYAN = '#06b6d4'
    CYAN_HOVER = '#0891b2'
    PINK = '#ec4899'
    GRAY = '#6b7280'
    GRAY_DARK = '#475569'
    GRAY_DARKER = '#334155'
    
    # --- 文字色 ---
    TEXT_PRIMARY = '#f8fafc'
    TEXT_SECONDARY = '#cbd5e1'
    TEXT_MUTED = '#94a3b8'
    TEXT_WHITE = '#ffffff'
    
    # --- 终端专用 ---
    TERMINAL_BG = '#1e1e1e'
    TERMINAL_TEXT = '#ffffff'
    TERMINAL_INFO = '#ffffff'
    TERMINAL_ERROR = '#ff6b6b'
    TERMINAL_SUCCESS = '#4bff4e'
    TERMINAL_WARNING = '#f9ca24'
    TERMINAL_LINK = '#4ecbff'

    # --- 通用 ---
    TRANSPARENT = '#010203'
    
    # --- markdown 渲染 (version_info) ---
    MARKDOWN_NORMAL = '#D3D3D3'
    MARKDOWN_QUOTE_BG = '#334155'
    MARKDOWN_QUOTE_FG = '#94a3b8'
    MARKDOWN_CODE_BG = '#1e293b'
    MARKDOWN_CODE_FG = '#e2e8f0'
    MARKDOWN_H1 = '#f8fafc'
    MARKDOWN_H2 = '#e2e8f0'
    MARKDOWN_H3 = '#cbd5e1'
    MARKDOWN_H2_COLOR = '#fbbf24'
    MARKDOWN_CHECKED = '#22c55e'
    MARKDOWN_UNCHECKED = '#94a3b8'
    
    # --- 下载GUI ---
    DOWNLOAD_ACCENT = '#4a9eff'
    DOWNLOAD_BAR_BG = '#21262d'
    
    # --- 传统按钮色 (兼容旧版) ---
    LEGACY_BLUE = '#3498db'
    LEGACY_BLUE_HOVER = '#2980b9'
    LEGACY_GREEN = '#27ae60'
    LEGACY_GREEN_HOVER = '#10b981'
    LEGACY_PURPLE = '#8e44ad'
    LEGACY_RED = '#e74c3c'
    LEGACY_ORANGE = '#f39c12'
    LEGACY_DARK = '#2c3e50'
    
    # --- 链接色 ---
    LINK_COLORS = {
        "github": ("#24292e", "#1a1e22"),
        "blbl": ("#00a1d6", "#008cc7"),
        "website": ("#10b981", "#059669"),
        "twitter": ("#1da1f2", "#0d8ecf"),
        "email": ("#ea4335", "#d33b28"),
    }


class ThemeColors:
    """根据 bg_color 动态计算的派生颜色"""
    
    def __init__(self, bg_color: str):
        self.bg_color = bg_color
        self.surface = lighten_color(bg_color, 5)
        self.card_bg = bg_color
        self.card_border = lighten_color(bg_color, 18)
        self.entry_bg = darken_color(bg_color, 0.78)
        self.trough = darken_color(bg_color, 0.7)
        self.status_bg = darken_color(bg_color, 0.85)
    
    def lighten(self, color_or_percent, percent=None):
        """lighten(color, percent) 或 lighten(percent) 用 bg_color"""
        if percent is not None:
            return lighten_color(color_or_percent, percent)
        return lighten_color(self.bg_color, color_or_percent)
    
    def darken(self, color_or_factor, factor=None):
        """darken(color, factor) 或 darken(factor) 用 bg_color"""
        if factor is not None:
            return darken_color(color_or_factor, factor)
        return darken_color(self.bg_color, color_or_factor)
    
    def surface_lighten(self, percent: float) -> str:
        return lighten_color(self.surface, percent)
    
    def surface_darken(self, factor: float) -> str:
        return darken_color(self.surface, factor)

# 向后兼容别名
C = SemanticColors

def create_theme(bg_color: str) -> ThemeColors:
    return ThemeColors(bg_color)


def border_color(bg: str) -> str:
    """标准描边色：基于背景色提亮 22%，在所有深色主题下可见"""
    return lighten_color(bg, 22)


def make_card(parent, *, bg, border_color=None, border_width=1, **pack_kw):
    """创建带描边的现代化卡片容器"""
    import tkinter as tk
    border_color = border_color or lighten_color(bg, 22)
    card = tk.Frame(parent, bg=bg, relief='flat', borderwidth=0,
                    highlightthickness=border_width,
                    highlightbackground=border_color)
    if pack_kw:
        card.pack(**pack_kw)
    return card


def make_card(parent, *, bg, border_color=None, border_width=1, **pack_kw):
    """创建带描边的现代化卡片容器"""
    import tkinter as tk
    border_color = border_color or lighten_color(bg, 18)
    card = tk.Frame(parent, bg=bg, relief='flat', borderwidth=0,
                    highlightthickness=border_width,
                    highlightbackground=border_color)
    if pack_kw:
        card.pack(**pack_kw)
    return card
