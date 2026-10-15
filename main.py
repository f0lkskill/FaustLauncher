"""
Faust Launcher - 主入口

1. 模块化拆分：将页面加载逻辑分离到 PageLoader
2. 职责分离：UI结构和业务逻辑分离，分为 app_core.py 和 app_ui.py
3. 按需加载：支持延迟加载页面
4. 解耦：降低模块间依赖
"""

from functions.base.app_initializer import launch_app
import sys, os

def _project_root():
    """项目根目录: 打包后是 exe 所在目录, 源码下是 main.py 所在目录。

    代码里大量使用相对路径 ('mods'、'addons'、'assets'、'lang'、'resources'、
    'config'...), 它们都相对项目根。而进程的工作目录取决于用户怎么启动:
    从命令行在别的目录执行、快捷方式起始位置为空、被别的程序拉起 ——
    这些情况下相对路径全部指错, 表现为"找不到 mods 目录 / 资源缺失"。
    build.py 早就显式 chdir 到脚本目录, 这里保持一致。
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))

if __name__ == "__main__":

    # 把工作目录固定到项目根, 相对路径才稳定 (见 _project_root 的说明)。
    # 必须放在所有"独立窗口模式"分支之前: 那些子进程同样依赖相对路径。
    try:
        os.chdir(_project_root())
    except OSError as e:
        print(f"切换工作目录失败(继续使用当前目录): {e}")

    # 启动 APP
    launch_app()