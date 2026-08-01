from typing import Tuple


def hex_to_rgb(hex_color: str) -> Tuple[int, int, int]:
    """将十六进制颜色转换为RGB值"""
    hex_color = hex_color.lstrip('#')
    if len(hex_color) == 6:
        r = int(hex_color[0:2], 16)
        g = int(hex_color[2:4], 16)
        b = int(hex_color[4:6], 16)
    elif len(hex_color) == 3:
        r = int(hex_color[0]*2, 16)
        g = int(hex_color[1]*2, 16)
        b = int(hex_color[2]*2, 16)
    else:
        r, g, b = 255, 255, 255  # 默认白色
    return r, g, b


def rgb_to_hex(rgb: Tuple[int, int, int]) -> str:
    """将RGB值转换为十六进制颜色"""
    return f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"


def interpolate_color(start_rgb: Tuple[int, int, int], end_rgb: Tuple[int, int, int],
                     ratio: float) -> Tuple[int, int, int]:
    """在两个颜色之间插值"""
    r = int(start_rgb[0] + (end_rgb[0] - start_rgb[0]) * ratio)
    g = int(start_rgb[1] + (end_rgb[1] - start_rgb[1]) * ratio)
    b = int(start_rgb[2] + (end_rgb[2] - start_rgb[2]) * ratio)
    return r, g, b


def is_white_color(rgb: Tuple[int, int, int]) -> bool:
    """检查颜色是否为白色"""
    return rgb == (255, 255, 255)
