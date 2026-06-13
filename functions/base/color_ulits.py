# 颜色工具函数
# color 参数是str

def lighten_color(color, percent):
    """颜色变亮"""
    import colorsys
    # 将十六进制颜色转换为RGB
    rgb = tuple(int(color[i:i+2], 16) for i in (1, 3, 5))
    # 转换为HSL
    h, l, s = colorsys.rgb_to_hls(rgb[0]/255, rgb[1]/255, rgb[2]/255)
    # 增加亮度
    l = min(1.0, l + percent/100)
    # 转换回RGB
    r, g, b = colorsys.hls_to_rgb(h, l, s)
    # 返回十六进制
    return f"#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}"

def darken_color(color, factor=0.8):
    """加深颜色"""
    if color.startswith('#'):
        r = int(color[1:3], 16)
        g = int(color[3:5], 16)
        b = int(color[5:7], 16)
        r = max(0, min(255, int(r * factor)))
        g = max(0, min(255, int(g * factor)))
        b = max(0, min(255, int(b * factor)))
        return f'#{r:02x}{g:02x}{b:02x}'
    return color