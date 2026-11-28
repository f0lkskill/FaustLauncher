"""web_update 子模块：<download_utils>（具体职责见函数文档）。"""

from functions.web_update.translation_source import (
    check_need_up_translate,
    get_local_version,
    get_translation_dir,
    get_translation_dir_name,
)

__all__ = [
    "check_need_up_translate",
    "get_local_version",
    "get_translation_dir",
    "get_translation_dir_name",
]
