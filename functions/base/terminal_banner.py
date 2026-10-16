import pyfiglet, colorama

FONT_ANSI_REGULAR = 'ansi_regular'
FONT_ANSI_SHADOW = 'ansi_shadow'
FONT_SLANT = 'slant'
FONT_SMALL_SLANT = 'small_slant'
FONT_SMALL = 'small'
FONT_STANDARD = 'standard'
FONT_BANNER3 = 'banner3'
FONT_BANNER3D = 'banner3-D'
FONT_BIG = 'big'
FONT_BLOCK = 'block'
FONT_SHADOW = 'shadow'
FONT_ROUNDED = 'rounded'
FONT_STARWARS = 'starwars'
FONT_THIN = 'thin'
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
    colors = [WHITE, RED, GREEM, BLUE, YELLOW, MAGENTA, CYAN]
    import random
    return random.choice(colors)

def get_random_font() -> str:
    fonts = [
        FONT_ANSI_REGULAR, FONT_ANSI_SHADOW, FONT_SLANT, FONT_SMALL_SLANT,
        FONT_SMALL, FONT_STANDARD, FONT_BANNER3, FONT_BANNER3D, FONT_BIG,
        FONT_BLOCK, FONT_SHADOW, FONT_ROUNDED,
        FONT_STARWARS, FONT_THIN
    ]
    import random
    return random.choice(fonts)

def get_banner(text='FaustLauncher', font=DEFAULT_FONT, colors=WHITE) -> str:
    try:
        if colors != '':
            return colors + pyfiglet.figlet_format(text, font=font) + RESET
        else:
            return pyfiglet.figlet_format(text, font=font)
    except Exception:
        return text

def get_banner_with_random_style(text='FaustLauncher') -> str:
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
    
