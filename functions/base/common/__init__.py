
"""启动器公共基础能力。

这里集中导出跨页面复用的路径和 Markdown 渲染接口，避免业务模块重复
维护同一套环境判断与格式转换逻辑。
"""

from .markdown_render import md_to_html
from .path_utils import (
    get_launcher_data_dir,
    get_launcher_user_dir,
    get_roaming_appdata_dir,
)

__all__ = [
    "get_launcher_data_dir",
    "get_launcher_user_dir",
    "get_roaming_appdata_dir",
    "md_to_html",
]
