"""终端 3D 艺术字体 - 基于第三方库 pyfiglet

使用 pyfiglet 生成艺术字，预设字体通过常量标识符调用。
"""
import pyfiglet, colorama

# ---------- 字体预设常量标识符 ----------
FONT_ANSI_REGULAR = 'ansi_regular'      # ANSI 转义码彩色字体（终端显示彩色）
FONT_ANSI_SHADOW = 'ansi_shadow'        # ANSI 转义码阴影字体
FONT_SLANT = 'slant'                    # 斜体
FONT_SMALL_SLANT = 'small_slant'        # 小型斜体
FONT_SMALL = 'small'                    # 小型
FONT_STANDARD = 'standard'              # 标准（pyfiglet 默认）
FONT_BANNER3 = 'banner3'                # 横幅3
FONT_BANNER3D = 'banner3-D'             # 3D 立体效果
FONT_BIG = 'big'                        # 大号
FONT_BLOCK = 'block'                    # 块状
FONT_SHADOW = 'shadow'                  # 阴影
FONT_ROUNDED = 'rounded'                # 圆角
FONT_STARWARS = 'starwars'              # 星球大战
FONT_THIN = 'thin'                      # 细体
DEFAULT_FONT = FONT_SLANT

WHITE = colorama.Fore.WHITE
RED = colorama.Fore.RED
GREEM = colorama.Fore.GREEN
BLUE = colorama.Fore.BLUE
YELLOW = colorama.Fore.YELLOW
MAGENTA = colorama.Fore.MAGENTA
CYAN = colorama.Fore.CYAN
RESET = colorama.Fore.RESET

def get_random_color() -> str:
    """随机获取一个颜色预设常量标识符"""
    colors = [WHITE, RED, GREEM, BLUE, YELLOW, MAGENTA, CYAN]
    import random
    return random.choice(colors)

def get_random_font() -> str:
    """随机获取一个字体预设常量标识符"""
    fonts = [
        FONT_ANSI_REGULAR, FONT_ANSI_SHADOW, FONT_SLANT, FONT_SMALL_SLANT,
        FONT_SMALL, FONT_STANDARD, FONT_BANNER3, FONT_BANNER3D, FONT_BIG,
        FONT_BLOCK, FONT_SHADOW, FONT_ROUNDED,
        FONT_STARWARS, FONT_THIN
    ]
    import random
    return random.choice(fonts)

def get_banner(text='FaustLauncher', font=DEFAULT_FONT, colors=WHITE) -> str:
    """生成艺术字多行字符串

    Args:
        text: 要渲染的文本
        font: 字体预设常量，如 FONT_ANSI_REGULAR
        color: 颜色，如 WHITE, RED
    """
    try:
        if colors != '':
            return colors + pyfiglet.figlet_format(text, font=font) + RESET
        else:
            return pyfiglet.figlet_format(text, font=font)
    except Exception:
        return text

def get_banner_with_random_style(text='FaustLauncher') -> str:
    """随机生成艺术字多行字符串"""
    return get_banner(text, font=get_random_font(), colors=get_random_color())

if __name__ == "__main__":
    print(get_banner("FaustLauncher", font=FONT_SMALL))
    print(get_banner("FaustLauncher", font=FONT_STANDARD))
    print(get_banner("FaustLauncher", font=FONT_SHADOW))
    print(get_banner("FaustLauncher", font=FONT_ROUNDED))
    print(get_banner("FaustLauncher", font=FONT_STARWARS))
    print(get_banner("FaustLauncher", font=FONT_THIN))
    print(get_banner("FaustLauncher", font=FONT_BANNER3D))
    print(get_banner("FaustLauncher", font=FONT_BIG))
    print(get_banner("FaustLauncher", font=FONT_BLOCK))
    print(get_banner("FaustLauncher", font=FONT_SHADOW))
    print(get_banner("FaustLauncher", font=FONT_SLANT))
    print(get_banner("FaustLauncher", font=FONT_SMALL_SLANT))
    print(get_banner("FaustLauncher", font=FONT_BANNER3))
    print(get_banner("FaustLauncher", font=FONT_ANSI_REGULAR))
    print(get_banner("FaustLauncher", font=FONT_ANSI_SHADOW))
    print(get_banner("FaustLauncher", font=DEFAULT_FONT, colors=RED))
    
    
    