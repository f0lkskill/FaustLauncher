#! 扩展工具入口 — 集成全部功能 (HTML webview 窗口)
#? 所有后端操作位于 functions/tools/post_extension_tools.py,
#? 窗口实现位于 functions/pages/tools/extension_tools_window.py (pywebview + html/extension_tools/index.html)
#? 功能:
#?   - 包装 Mod (选择原始文件夹, 填写 mod_info.json, 复制到 mods/)
#?   - 生成插件模板 (addons/ 下生成 scr.py + icon.png + addon_info.json)
#?   - 发布 Mod 信息到云端 (web_config.json 中 mod_info 地址, dowload_url/icon_url 留空)
#?
#? 用法:
#?   - 独立运行: python extension_tools.py  (打开 HTML 工具窗口)
#?   - 应用内: 工具页 -> 扩展工具 (同一 HTML 窗口, 子进程方式拉起)
#?   - 代码调用: from extension_tools import spawn_extension, wrap_mod, upload_mod_info

import sys

from functions.pages.tools.extension_tools_window import (
    run_extension_tools_window,
    open_extension_tools_window,
)
from functions.tools.post_extension_tools import (
    MODS_DIR,
    ADDONS_DIR,
    spawn_extension,
    wrap_mod,
    load_mod_info,
    upload_mod_info,
    generate_icon,
)

__all__ = [
    'MODS_DIR',
    'ADDONS_DIR',
    'spawn_extension',
    'wrap_mod',
    'load_mod_info',
    'upload_mod_info',
    'generate_icon',
    'run_extension_tools_window',
    'open_extension_tools_window',
]


def extension_tools_gui(root=None):
    """非阻塞拉起扩展工具 HTML 窗口"""
    return open_extension_tools_window(root)


if __name__ == '__main__':
    # 独立运行: 直接在当前进程启动 pywebview 窗口
    run_extension_tools_window(debug='--debug' in sys.argv)
