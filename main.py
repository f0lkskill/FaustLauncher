
from functions.base.app_initializer import launch_app
import sys, os

def _project_root():
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))

if __name__ == "__main__":

    try:
        os.chdir(_project_root())
    except OSError as e:
        print(f"切换工作目录失败(继续使用当前目录): {e}")

    launch_app()
