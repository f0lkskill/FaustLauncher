import subprocess
import os
from functions.settings_manager import get_settings_manager

settings_manager = get_settings_manager()

def main(game_path: str):
    """使用当前系统的运行参数运行YiSangModLoader.exe来启动游戏。"""
    global settings_manager

    exe_path = "YiSangModLoader.exe"
    
    if not os.path.exists(exe_path):
        print(f"错误: 找不到 {exe_path}")
        return False
    
    try:
        print("启动游戏...")
        run = [exe_path, game_path] if settings_manager.get_setting("enable_mods") else [game_path]
        flags = subprocess.CREATE_NO_WINDOW if settings_manager.get_setting("hide_mod_load") else 0

        # 使用CREATE_NO_WINDOW标志隐藏窗口
        subprocess.Popen(run, creationflags=flags)
        return True
    except Exception as e:
        print(f"启动失败: {e}")
        return False

if __name__ == "__main__":
    main("???")