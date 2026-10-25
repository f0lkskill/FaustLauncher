"""
FaustLauncher 主入口
程序将从此处进行初始化和运行。
"""


import os
import sys


def _project_root():
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


# 必须在任何 functions.* 导入之前切换工作目录。
# Steam 通过启动项拉起启动器时，工作目录是游戏安装目录（%command% 的所在目录），
# 启动器里大量相对路径（config/、resources/、lang/、assets/）会全部找错地方，
# 最先炸的是 config/settings.json 读不到 -> bg_gaussian_blur 为 None ->
# loading_info.py 在模块导入阶段就抛 TypeError。
try:
    os.chdir(_project_root())
except OSError as e:
    print(f"切换工作目录失败(继续使用当前目录): {e}")


from functions.base.app_initializer import launch_app

if __name__ == "__main__":
    launch_app()
