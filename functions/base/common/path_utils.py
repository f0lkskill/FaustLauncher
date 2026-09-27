import os
import sys

MOD_ROOT_NAME = 'LimbusCompanyMods'


def get_web_root(*parts) -> str:
    """获取 web/ 前端目录下的路径 (所有 pywebview 页面都从这里取)

    打包布局 (onedir): web/ 被 PyInstaller 收进 _internal/, 与 exe 同级但不可见,
    因此按 _internal 优先、exe 目录兜底依次探测; 源码模式直接取项目根下的 web/。

    另外一并兜住改名前的旧目录名 html/: 老用户升级不完整 (只换了 exe、_internal
    没跟上) 时, 安装目录里可能只留着旧结构, 能救一个是一个。

    按候选顺序返回首个存在的路径; 全都不存在时打印诊断信息 (这是"安装不完整"
    的典型症状) 并返回首选路径, 交由调用方给出可读的报错。

    Args:
        *parts: web/ 下的相对路径片段, 如 ('app', 'index.html')
    """
    if getattr(sys, 'frozen', False):
        # 打包: 以 exe 所在目录为项目根
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        candidates = []
        for dirname in ('web', 'html'):          # html = 改名前的旧目录名
            for base in ('_internal', ''):
                candidates.append(os.path.join(exe_dir, base, dirname, *parts))
    else:
        # 源码: functions/base/common/ -> 上溯三级到项目根
        project_root = os.path.abspath(os.path.join(
            os.path.dirname(os.path.abspath(__file__)), '..', '..', '..'))
        candidates = [os.path.join(project_root, d, *parts) for d in ('web', 'html')]

    for cand in candidates:
        if os.path.exists(cand):
            return cand

    # 全都不存在: 打印每个试过的位置, 便于直接看出是"安装缺文件"还是"路径不对"
    try:
        print("[web] 找不到前端资源 " + os.path.join('web', *parts)
              + ", 已尝试以下位置:\n  " + "\n  ".join(candidates), flush=True)
    except Exception:
        pass
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
