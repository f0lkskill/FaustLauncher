"""终端 3D 艺术字体 - 基于第三方库 pyfiglet

使用 pyfiglet 的 banner3-D 字体生成 3D 立体效果艺术字。
"""
import pyfiglet

_FONT = 'slant'


def get_banner(text='FaustLauncher'):
    """生成 3D 艺术字多行字符串"""
    try:
        return pyfiglet.figlet_format(text, font=_FONT)
    except Exception:
        return text

if __name__ == "__main__":
    print(get_banner("\nFaustLauncher"))