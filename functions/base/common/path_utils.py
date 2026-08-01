import os

MOD_ROOT_NAME = 'LimbusCompanyMods'


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
