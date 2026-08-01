import subprocess
import os
from functions.base.settings_manager import get_settings_manager
from functions.extension.mod.mod_utils import ModManager

STEAM_APP_ID = "1973530"
GAME_EXE = "LimbusCompany.exe"

_settings = get_settings_manager()
_extra_mod_loader: str = _settings.get_setting('extra_mod_loader')  # type: ignore
_game_path: str = _settings.get_setting('game_path')  # type: ignore


def launch_game_process():
    """启动游戏进程：无 mod 时直接通过 Steam 启动，有 mod 时通过 mod loader 启动。"""
    if not _settings.get_setting("enable_mods"):
        print("启动器设置项禁用了 mod 加载功能, 直接启动游戏...\n (如有需要, 请在设置项启用 mod 加载功能)")
        subprocess.Popen(['start', f'steam://rungameid/{STEAM_APP_ID}'], shell=True)
        return True

    print("加载 mod 到游戏目录...")
    ModManager().load_all_mods()

    _start_with_mod_loader()

    return True


def _start_with_mod_loader():
    """选择合适的 mod loader 启动游戏（外部 loader 优先，否则用内置 loader）。"""
    game_exe = os.path.join(_game_path, GAME_EXE)

    if os.path.exists(_extra_mod_loader):
        print(f"使用外部 mod loader 启动: {_extra_mod_loader}")
        flags = subprocess.CREATE_NO_WINDOW if _settings.get_setting("hide_mod_load") else 0
        subprocess.Popen([_extra_mod_loader, game_exe], creationflags=flags)
        return

    print("使用内置 mod loader 启动...")
    loader = "resources/mod_loader/yisangModLoader.exe"
    flags = subprocess.CREATE_NO_WINDOW if _settings.get_setting("hide_mod_load") else 0
    subprocess.Popen([loader, game_exe], creationflags=flags)
