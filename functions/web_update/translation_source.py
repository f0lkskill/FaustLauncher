"""汉化来源与本地汉化包路径的集中解析。

内置来源有三种（零协会 / OurPlay 普通 / OurPlay 神人），插件还能通过
``set_extend_translate_source`` 注册额外来源；所有“用哪个目录、要不要更新”
的判断都走这里，避免下载链路和游戏启动链路各自猜路径。
"""

import os

from functions.base.settings_manager import get_settings_manager

SOURCE_ZERO = 0
SOURCE_OURPLAY = 1
SOURCE_OURPLAY_GOD = 2

DIR_NAME_BY_SOURCE = {
    SOURCE_ZERO: "LLC_zh-CN",
    SOURCE_OURPLAY: "OurPlayHanHua",
    SOURCE_OURPLAY_GOD: "OurPlayHanHua",
}

SOURCE_NAMES = {
    SOURCE_ZERO: "零协会",
    SOURCE_OURPLAY: "OurPlay 普通版",
    SOURCE_OURPLAY_GOD: "OurPlay 神人版",
}

PLATFORM_TAG_BY_SOURCE = {
    SOURCE_ZERO: "zeroasso",
    SOURCE_OURPLAY: "ourplay_normal",
    SOURCE_OURPLAY_GOD: "ourplay_god",
}

extend_translate_source:list[CustomTranslateSource] = []

class CustomTranslateSource:
    """插件注册的自定义汉化源：来源路径 + 显示名。"""
    def __init__(self, source: str, name: str):
        """保存来源地址与显示名。"""
        self.source = source
        self.name = name

    def __str__(self):
        """自定义源的文本表示。"""
        return self.name, self.source

def get_translate_source() -> int:
    """从设置读取汉化来源编号，非法值回退到零协会。"""
    try:
        value = get_settings_manager().get_setting("translate_source")
        value = int(value) # type: ignore
        if value not in DIR_NAME_BY_SOURCE:
            return SOURCE_ZERO
        return value
    except Exception:
        return SOURCE_ZERO

def set_extend_translate_source(sources=None) -> list:
    """原地更新插件注册的额外汉化源列表，返回该列表。"""
    try:
        extend_translate_source[:] = list(sources or [])
    except Exception:
        pass
    return extend_translate_source

def get_translate_source_name() -> str:
    """优先用插件自定义源的名字，否则用内置来源名。"""
    for source in extend_translate_source:
        name = str(getattr(source, "name", "") or "").strip()
        if name:
            return name
    return SOURCE_NAMES.get(get_translate_source(), "未知")

def get_translation_dir_name() -> str:
    """当前汉化包目录名：自定义源取路径末段，否则用内置约定。"""
    if len(extend_translate_source) == 0:
        return DIR_NAME_BY_SOURCE[get_translate_source()]
    else:
        return extend_translate_source[-1].source.split("/")[-1]

def get_translation_dir() -> str:
    """当前汉化包所在的本地目录。"""
    if len(extend_translate_source) == 0:
        dir_source = os.path.join("lang", get_translation_dir_name())
    else:
        dir_source = extend_translate_source[-1].source
    return dir_source

def get_builtin_dir_name() -> str:
    """内置来源对应的目录名（忽略插件自定义源）。"""
    return DIR_NAME_BY_SOURCE[get_translate_source()]

def get_builtin_translation_dir() -> str:
    """内置来源对应的本地目录。"""
    return os.path.join("lang", get_builtin_dir_name())

def get_game_lang_dir(game_path: str) -> str:
    """游戏目录下汉化资源应投放的 Lang 子目录。"""
    if len(extend_translate_source) == 0:
        return os.path.join(game_path, "LimbusCompany_Data", "Lang", get_translation_dir_name())
    else:
        return os.path.join(game_path, "LimbusCompany_Data", "Lang", extend_translate_source[-1].source.split("/")[-1])

def is_ourplay_source() -> bool:
    """当前是否为 OurPlay 来源（普通版或神人版）。"""
    return get_translate_source() in (SOURCE_OURPLAY, SOURCE_OURPLAY_GOD)

def is_god_source() -> bool:
    """当前是否为 OurPlay 神人版。"""
    return get_translate_source() == SOURCE_OURPLAY_GOD

def get_local_version() -> str:
    """读内置汉化包 info/version.json 的 version，失败返回空串。"""
    version_path = os.path.join(get_builtin_translation_dir(), "info", "version.json")
    try:
        from json import load
        with open(version_path, "r", encoding="utf-8") as f:
            return str(load(f).get("version", ""))
    except Exception:
        return ""

def get_local_platform() -> str:
    """读内置汉化包 info/version.json 的 platform，失败返回空串。"""
    version_path = os.path.join(get_builtin_translation_dir(), "info", "version.json")
    try:
        from json import load
        with open(version_path, "r", encoding="utf-8") as f:
            return str(load(f).get("platform", ""))
    except Exception:
        return ""

def check_need_up_translate(version_info: str = "") -> bool:
    """比对本地版本/平台标记与云端版本，判断是否需要更新汉化包。"""
    local_dir = get_builtin_translation_dir()
    if not os.path.isdir(local_dir):
        print(f"[Locale] 本地没有内置汉化包目录 {local_dir}, 需要下载")
        return True
    if not os.path.isfile(os.path.join(local_dir, "info", "version.json")):
        print(f"[Locale] 本地 {local_dir} 缺少 info/version.json, 需要下载")
        return True
    if version_info == "":
        return False
    try:
        local_platform = get_local_platform()
        if local_platform and local_platform != PLATFORM_TAG_BY_SOURCE[get_translate_source()]:
            print(f"[Locale] 平台标记不一致 (本地 {local_platform}), 需要重新下载")
            return True
        if not local_platform and is_ourplay_source():
            print("[Locale] OurPlay 旧版安装缺 platform 标记, 强制更新一次补全")
            return True
        same = str(version_info).strip() == get_local_version().strip()
        print(f"[Locale] 本地 {get_local_version()} / 云端 {version_info} -> "
              f"{'一致, 无需更新' if same else '需要更新'}")
        return not same
    except Exception as e:
        print(f"[Locale] 比对失败 ({e}), 按需要更新处理")
        return True
