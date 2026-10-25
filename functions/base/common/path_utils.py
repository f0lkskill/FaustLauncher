import os
import sys

MOD_ROOT_NAME = 'LimbusCompanyMods'

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
    roaming_path = os.getenv('APPDATA')
    mod_path = os.path.join(roaming_path, MOD_ROOT_NAME) # type: ignore

    if create and not os.path.exists(mod_path):
        os.makedirs(mod_path)
        print(f"创建Mod目录: {mod_path}")

    return mod_path
