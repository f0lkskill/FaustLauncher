"""启动器运行时路径的统一解析。

区分三组路径：用户数据（``%APPDATA%/FaustLauncher/user``）、前端资源
（打包版在 exe 旁的 ``web``/``_internal/web``，开发版在仓库 ``web``）、
启动器根目录（配置/日志/插件/缓存所在）。打包后 ``__file__`` 位于
``_internal`` 里，不能拿来推算根目录，所以统一走 ``sys.executable``。
"""

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
    """返回启动器保存用户设置、登录态和缓存数据的目录。

    Args:
        create: 是否自动创建目录。

    Returns:
        str: ``%APPDATA%/FaustLauncher/user`` 的绝对路径。
    """
    return get_launcher_data_dir(LAUNCHER_USER_DIR_NAME, create=create)

def get_web_root(*parts) -> str:
    """找前端资源目录或文件；打包/开发、web/html 两种名字都兼容。

    Args:
        *parts: 资源目录下的相对路径片段。

    Returns:
        str: 第一个存在的候选路径；全都不存在时返回首个候选并打印诊断。
    """
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
    """返回启动器根目录：打包版是 exe 所在目录，开发版是仓库根。

    Args:
        create: 是否尝试创建目录（失败会被忽略）。
    """
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
