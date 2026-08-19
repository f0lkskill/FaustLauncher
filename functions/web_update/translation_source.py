"""汉化包平台方统一入口

翻译目录名跟随所选平台动态变化, 启动器内所有硬编码的 LLC_zh-CN
路径都应改为通过本模块获取当前平台对应的目录名, 以保证汉化包
下载/同步/美化处理正常。

平台与目录名对应关系:
    0 零协会        -> LLC_zh-CN
    1 OurPlay 普通  -> OurPlayHanHua
    2 OurPlay 神人  -> OurPlayHanHua
"""
import os

from functions.base.settings_manager import get_settings_manager

# 平台枚举
SOURCE_ZERO = 0
SOURCE_OURPLAY = 1
SOURCE_OURPLAY_GOD = 2

# 各平台对应的翻译目录名 (lang/ 下)
DIR_NAME_BY_SOURCE = {
    SOURCE_ZERO: "LLC_zh-CN",
    SOURCE_OURPLAY: "OurPlayHanHua",
    SOURCE_OURPLAY_GOD: "OurPlayHanHua",
}


def get_translate_source() -> int:
    """当前汉化包平台方 (0 零协会 / 1 OurPlay 普通 / 2 OurPlay 神人)"""
    try:
        value = get_settings_manager().get_setting("translate_source")
        value = int(value)
        if value not in DIR_NAME_BY_SOURCE:
            return SOURCE_ZERO
        return value
    except Exception:
        return SOURCE_ZERO


def get_translation_dir_name() -> str:
    """当前汉化包平台对应的翻译目录名 (如 LLC_zh-CN / OurPlayHanHua)"""
    return DIR_NAME_BY_SOURCE[get_translate_source()]


def get_translation_dir() -> str:
    """启动器本地 lang/ 下的汉化目录 (如 lang/LLC_zh-CN)"""
    return os.path.join("lang", get_translation_dir_name())


def get_game_lang_dir(game_path: str) -> str:
    """游戏目录中的汉化目录 (LimbusCompany_Data/Lang/<目录名>)"""
    return os.path.join(game_path, "LimbusCompany_Data", "Lang", get_translation_dir_name())


def is_ourplay_source() -> bool:
    """当前平台是否为 OurPlay (普通/神人)"""
    return get_translate_source() in (SOURCE_OURPLAY, SOURCE_OURPLAY_GOD)


def is_god_source() -> bool:
    """当前平台是否为 OurPlay 神人版 (需要基板包转换)"""
    return get_translate_source() == SOURCE_OURPLAY_GOD


def get_local_version() -> str:
    """读取当前平台汉化包本地版本 (lang/<目录>/info/version.json), 无则返回空串"""
    version_path = os.path.join(get_translation_dir(), "info", "version.json")
    try:
        from json import load
        with open(version_path, "r", encoding="utf-8") as f:
            return str(load(f).get("version", ""))
    except Exception:
        return ""


def check_need_up_translate(version_info: str = "") -> bool:
    """当前平台的汉化包是否需要下载/更新

    本地目录不存在或版本信息缺失时返回 True (需要下载/安装);
    传入远端版本时与本地版本比较, 不一致返回 True。
    """
    if not os.path.isdir(get_translation_dir()):
        return True
    if not os.path.isfile(os.path.join(get_translation_dir(), "info", "version.json")):
        return True
    if version_info == "":
        return False
    try:
        return version_info.strip() != get_local_version().strip()
    except Exception:
        return True
