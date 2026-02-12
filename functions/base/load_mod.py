import subprocess
import os
from functions.base.settings_manager import get_settings_manager

settings_manager = get_settings_manager()
extra_mod_loader_path:str = settings_manager.get_setting('extra_mod_loader') # type: ignore

def main(game_path: str):
    """使用当前系统的运行参数运行YiSangModLoader.exe来启动游戏。"""
    global settings_manager
    
    if not os.path.exists(extra_mod_loader_path):
        print(f"外部mod加载器不存在, 将使用默认的加载方式...")
    else:
        print(f'使用外部mod加载器启动游戏: {extra_mod_loader_path}')
        run = [extra_mod_loader_path, game_path + '/LimbusCompany.exe'] if settings_manager.get_setting("enable_mods") else ['start', 'steam://rungameid/1973530']
        flags = subprocess.CREATE_NO_WINDOW if settings_manager.get_setting("hide_mod_load") else 0
        # 使用CREATE_NO_WINDOW标志隐藏窗口
        subprocess.Popen(run, creationflags=flags)
    
    try:
        print("开始使用默认mod加载器启动游戏...")

        run = ["yisangModLoader.exe", game_path] if settings_manager.get_setting("enable_mods") else [game_path]
        flags = subprocess.CREATE_NO_WINDOW if settings_manager.get_setting("hide_mod_load") else 0
        # 使用CREATE_NO_WINDOW标志隐藏窗口
        subprocess.Popen(run, creationflags=flags)

        return True

        # TODO 找到兼容性使用的方法...?
        #! 使用这样的方式接入总是会导致游戏显示检测到缺失资源
        #! 并要求用户使用 steam 修复...?

        # from functions.modloader.main import main as load_mod
        # load_mod()

        # return True

    except Exception as e:
        print(f"启动失败: {e}")
        return False

if __name__ == "__main__":
    main("???")