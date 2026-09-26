import os
import sys

MOD_ROOT_NAME = 'LimbusCompanyMods'


def get_web_root(*parts) -> str:
    """获取 web/ 前端目录下的路径 (所有 pywebview 页面都从这里取)

    打包布局 (onedir): web/ 被 PyInstaller 收进 _internal/, 与 exe 同级但不可见,
    因此按 _internal 优先、exe 目录兜底依次探测; 源码模式直接取项目根下的 web/。

    按候选顺序返回首个存在的路径; 均不存在时返回首选路径,
    交由调用方给出可读的报错 (而不是在这里静默返回空串)。

    Args:
        *parts: web/ 下的相对路径片段, 如 ('app', 'index.html')
    """
    rel = os.path.join('web', *parts) if parts else 'web'
    if getattr(sys, 'frozen', False):
        # 打包: 以 exe 所在目录为项目根, web/ 位于 _internal 内
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        candidates = (
            os.path.join(exe_dir, '_internal', rel),
            os.path.join(exe_dir, rel),
        )
    else:
        # 源码: functions/base/common/ -> 上溯三级到项目根
        project_root = os.path.abspath(os.path.join(
            os.path.dirname(os.path.abspath(__file__)), '..', '..', '..'))
        candidates = (os.path.join(project_root, rel),)

    for cand in candidates:
        if os.path.exists(cand):
            return cand
    # 都不存在时返回首选路径, 交由调用方给出可读的报错
    return candidates[0]


def get_mod_root_dir(create: bool = True) -> str:
    """获取Mod目录路径 (APPDATA/LimbusCompanyMods)

    Args:
        create: 目录不存在时是否创建
    """
    roaming_path = os.getenv('APPDATA')
    mod_path = os.path.join(roaming_path, MOD_ROOT_NAME) # type: ignore

    if create and not os.path.exists(mod_path):
        os.makedirs(mod_path)
        print(f"创建Mod目录: {mod_path}")

    return mod_path
