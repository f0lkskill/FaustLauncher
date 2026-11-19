import os
import sys

MOD_ROOT_NAME = 'LimbusCompanyMods'
LAUNCHER_DIR_NAME = 'FaustLauncher'
LAUNCHER_USER_DIR_NAME = 'user'


def get_roaming_appdata_dir() -> str:
    """返回当前用户的 Windows Roaming APPDATA 目录。

    优先使用环境变量，便于测试和便携环境覆盖；环境变量缺失时回退到
    用户主目录下的标准 Windows 路径。

    Returns:
        str: Roaming APPDATA 的绝对路径。
    """
    roaming = os.getenv('APPDATA')
    if not roaming:
        roaming = os.path.join(
            os.path.expanduser('~'), 'AppData', 'Roaming')
    return os.path.abspath(os.path.expanduser(roaming))


def get_launcher_data_dir(*parts: str, create: bool = False) -> str:
    """返回启动器在 Roaming APPDATA 下的数据目录。

    Args:
        *parts: 数据目录下的可选子路径。
        create: 是否自动创建目标目录。

    Returns:
        str: 启动器数据目录的绝对路径。
    """
    path = os.path.join(
        get_roaming_appdata_dir(), LAUNCHER_DIR_NAME, *parts)
    if create:
        os.makedirs(path, exist_ok=True)
    return path


def get_launcher_user_dir(create: bool = False) -> str:
    """返回启动器保存用户设置、登录态和缓存数据的目录。"""
    return get_launcher_data_dir(LAUNCHER_USER_DIR_NAME, create=create)

def get_web_root(*parts) -> str:
    if getattr(sys, 'frozen', False):
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        candidates = []
        for dirname in ('web', 'html'):
            for base in ('_internal', ''):
                candidates.append(os.path.join(exe_dir, base, dirname, *parts))
    else:
        project_root = os.path.abspath(os.path.join(
            os.path.dirname(os.path.abspath(__file__)), '..', '..', '..'))
        candidates = [os.path.join(project_root, d, *parts) for d in ('web', 'html')]

    for cand in candidates:
        if os.path.exists(cand):
            return cand

    try:
        print("[web] 找不到前端资源 " + os.path.join('web', *parts)
              + ", 已尝试以下位置:\n  " + "\n  ".join(candidates), flush=True)
    except Exception:
        pass
    return candidates[0]

def get_app_root(create: bool = True) -> str:
    if getattr(sys, 'frozen', False):
        root = os.path.dirname(os.path.abspath(sys.executable))
    else:
        root = os.path.abspath(os.path.join(
            os.path.dirname(os.path.abspath(__file__)), '..', '..', '..'))
    if create:
        try:
            os.makedirs(root, exist_ok=True)
        except OSError:
            pass
    return root

def get_mod_root_dir(create: bool = True) -> str:
    """_返回 APPDATA 下面的单文件类型mod目录_

    Args:
        create (bool, optional): _是否自动创建目录_. Defaults to True.

    Returns:
        str: _Mod目录的路径_
    """
    mod_path = os.path.join(get_roaming_appdata_dir(), MOD_ROOT_NAME)

    if create and not os.path.exists(mod_path):
        os.makedirs(mod_path, exist_ok=True)
        print(f"创建Mod目录: {mod_path}")

    return mod_path
