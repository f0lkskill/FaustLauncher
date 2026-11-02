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
try:
    os.chdir(_project_root())
except OSError as e:
    print(f"切换工作目录失败(继续使用当前目录): {e}")


if __name__ == "__main__" and "--addon-host" in sys.argv:
    # 独立插件宿主走这里，不走 launch_app：宿主要抢在启动器那一大串 import
    # 之前拿到单实例锁，否则「启动器已退出、宿主还在导入模块」的那段空窗里，
    # 两边都会以为自己是唯一的钩子表写方。
    from functions.extension.addon.addon_host import run_host

    run_host()
    raise SystemExit(0)


from functions.base.app_initializer import launch_app

if __name__ == "__main__":
    launch_app()
