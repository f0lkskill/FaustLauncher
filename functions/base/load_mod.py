import subprocess
import os
from functions.base.settings_manager import get_settings_manager
from functions.extension.mod.mod_utils import ModManager

STEAM_APP_ID = "1973530"
GAME_EXE = "LimbusCompany.exe"

_settings = get_settings_manager()
# 注意: 不要把 game_path / extra_mod_loader 缓存在模块级变量里。
# 模块只在首次 import 时求值一次, 而用户随时可能在设置页改游戏路径 ——
# 缓存的旧路径会被原样交给 mod loader, 结果 mods 装到已废弃的目录 (或根本找不到
# 游戏 exe), 表现为"改了路径但 mod 还是不生效"。这两个值一律在用时实时读取。
# (_settings 是单例, get_setting 每次读的都是当前值, 可以放心持有。)

_MOD_FOLDER = os.path.join(os.getenv("APPDATA", ""), "LimbusCompanyMods")
_MOD_SUFFIXES = (".zip", ".carra", ".carra2", ".bank", ".rebank", ".bank.orig")


def _has_loader_mods():
    """是否存在需要 mod loader 处理的 mod:
    - mods/ 目录里已启用的 mod
    - %APPDATA%/LimbusCompanyMods 里的 zip/carra/bank 等资源
    """
    try:
        mgr = ModManager()
        for mod_path in mgr.get_mod_path():
            info = mgr.get_mod_info(os.path.basename(mod_path))
            if info.get("settings", {}).get("enable", False):
                return True
    except Exception:
        pass
    try:
        for name in os.listdir(_MOD_FOLDER):
            if name.lower().endswith(_MOD_SUFFIXES):
                return True
    except OSError:
        pass
    return False


def launch_game_process():
    """启动游戏进程：无 mod 时直接通过 Steam 启动，有 mod 时通过 mod loader 启动。"""
    if not _settings.get_setting("enable_mods"):
        print("启动器设置项禁用了 mod 加载功能, 直接启动游戏...\n (如有需要, 请在设置项启用 mod 加载功能)")
        subprocess.Popen(['start', f'steam://rungameid/{STEAM_APP_ID}'], shell=True)
        return True

    print("加载 mod 到游戏目录...")
    ModManager().load_all_mods()

    if not _has_loader_mods():
        print("没有检测到需要加载的 mod, 直接启动游戏...")
        subprocess.Popen(['start', f'steam://rungameid/{STEAM_APP_ID}'], shell=True)
        return True

    _start_with_mod_loader()

    return True


def _start_with_mod_loader():
    """选择合适的 mod loader 启动游戏（外部 loader 优先，否则用内置 yisangModLoader.exe）。

    yisangModLoader.exe 是独立子进程 (内部自带运行环境, 与启动器无关联):
    启动器只负责把它拉起来, 不做任何进程间耦合, 进度窗口仅通过文件轮询观察。
    hide_mod_load 设置只控制加载器自身的控制台窗口, 进度 GUI 窗口始终显示。
    """
    # 实时读取, 不能用模块级快照 (用户改过游戏路径后快照就是旧值)
    game_path = _settings.get_setting('game_path') or ''
    extra_mod_loader = _settings.get_setting('extra_mod_loader') or ''
    game_exe = os.path.join(game_path, GAME_EXE)

    # 读取线程数配置，默认 5
    thread_count = _settings.get_setting('mod_loader_threads') or 5

    if extra_mod_loader and os.path.exists(extra_mod_loader):
        print(f"使用外部 mod loader 启动: {extra_mod_loader}, 线程数: {thread_count}")
        flags = subprocess.CREATE_NO_WINDOW if _settings.get_setting("hide_mod_load") else 0
        subprocess.Popen([extra_mod_loader, game_exe, f"--threads={thread_count}"], creationflags=flags)
        return

    builtin_exe = os.path.join("resources", "mod_loader", "yisangModLoader.exe")
    if os.path.exists(builtin_exe):
        print(f"使用内置 mod loader 启动: {builtin_exe}")
        flags = subprocess.CREATE_NO_WINDOW if _settings.get_setting("hide_mod_load") else 0
        proc = subprocess.Popen([builtin_exe, game_exe, f"--threads={thread_count}"], creationflags=flags)
        from functions.pages.tools.mod_loader_progress import open_mod_loader_progress
        open_mod_loader_progress(proc.pid)
        return

    print("使用内置 mod loader (venv 直跑) 启动...")
    loader_py = "resources/mod_loader/_internal/venv/Bins/python.exe"
    loader_script = "resources/mod_loader/_internal/main.py"
    proc = subprocess.Popen([loader_py, loader_script, game_exe, f"--threads={thread_count}"],
                            creationflags=subprocess.CREATE_NO_WINDOW)
    from functions.pages.tools.mod_loader_progress import open_mod_loader_progress
    open_mod_loader_progress(proc.pid)