"""启动器自身的启动模式判定。

被 Steam 通过启动选项拉起时，启动器会收到 `--launcher-mode`：此时不进入 UI，
直接跑完整后端流程（更新汉化 -> 应用到游戏目录 -> 加载 mod -> 起游戏）。

这里只放「怎么判断 / 怎么拼启动命令」这类最少依赖的东西，
真正去改 Steam 配置的逻辑在 functions/base/steam_binding.py。
"""

import os
import sys

__all__ = [
    "LAUNCHER_MODE_FLAG",
    "FILE_MODE_FLAG",
    "STEAM_BINDING_KEY",
    "is_launcher_mode",
    "is_file_mode",
    "project_root",
    "launcher_command",
]

LAUNCHER_MODE_FLAG = "--launcher-mode"
FILE_MODE_FLAG = "--file-mode"
STEAM_BINDING_KEY = "steam_launch_with_launcher"


def is_launcher_mode(argv: list[str] | None = None) -> bool:
    """当前进程是否被 Steam 以启动器模式拉起。"""
    return LAUNCHER_MODE_FLAG in (sys.argv if argv is None else argv)


def is_file_mode(argv: list[str] | None = None) -> bool:
    """当前进程是否要求「直接起游戏 exe」而不是再走一次 Steam。"""
    return FILE_MODE_FLAG in (sys.argv if argv is None else argv)


def project_root() -> str:
    """打包后是 exe 所在目录（config / logs / resources 都在那），开发时是仓库根。

    直接复用项目里的 `get_app_root()`，保证和 settings.json 等运行时文件同源：
    onedir 打包下 exe 在 `D:\\FaustLauncher\\FaustLauncher.exe`，配置在
    `D:\\FaustLauncher\\config\\`，不能用 `__file__` 推算（那会落到 _internal 里）。
    """
    from functions.base.common.path_utils import get_app_root
    return get_app_root(create=False)


def launcher_command() -> tuple[str, list[str]]:
    """返回 (可执行文件, 该 exe 需要的固定前置参数)。

    打包版：exe 自身（`D:\\FaustLauncher\\FaustLauncher.exe`），没有前置参数。
    开发版：`venv\\Scripts\\python.exe "D:\\...\\main.py"`。

    开发版刻意用 python.exe 而不是 pythonw.exe：pythonw 下 ``sys.stdout`` 是 None，
    启动器里大量 ``print`` 日志会直接抛异常，脚本等于跑不起来。代价是 Steam 拉起时
    会带一个控制台窗口，调试阶段正好能看见输出。
    """
    if getattr(sys, "frozen", False):
        return os.path.abspath(sys.executable), []

    main_py = os.path.join(project_root(), "main.py")
    exe = os.path.abspath(sys.executable)
    if os.path.basename(exe).lower() == "pythonw.exe":
        console_python = os.path.join(os.path.dirname(exe), "python.exe")
        if os.path.exists(console_python):
            exe = console_python
    return exe, [os.path.abspath(main_py)]
