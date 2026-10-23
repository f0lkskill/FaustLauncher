import subprocess
import os
from functions.base.settings_manager import get_settings_manager
from functions.base.launcher_mode import is_launcher_mode, STEAM_BINDING_KEY
from functions.extension.mod.mod_utils import ModManager

STEAM_APP_ID = "1973530"
GAME_EXE = "LimbusCompany.exe"

FILE_MODE_FLAG = "--file-mode"

_settings = get_settings_manager()

_MOD_FOLDER = os.path.join(os.getenv("APPDATA", ""), "LimbusCompanyMods")
_MOD_SUFFIXES = (".zip", ".carra", ".carra2", ".bank", ".rebank", ".bank.orig")

def _has_loader_mods():
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


def _game_exe_path() -> str:
    game_path = _settings.get_setting('game_path') or ''
    return os.path.join(game_path, GAME_EXE)


def _run_game_exe():
    """绕过 Steam 直接拉起游戏 exe（异步，不等它退出）。"""
    game_path = _settings.get_setting('game_path') or ''
    exe = os.path.join(game_path, GAME_EXE)
    if not os.path.isfile(exe):
        print(f"找不到游戏 exe: {exe}")
        return False
    print(f"直接启动游戏进程: {exe}")
    subprocess.Popen([exe], cwd=game_path or None)
    return True


def _launch_via_steam():
    subprocess.Popen(['start', f'steam://rungameid/{STEAM_APP_ID}'], shell=True)
    return True


def _steam_launch_bound() -> bool:
    """Steam 的启动项是否已经指向本启动器。

    指向了的话，再调 `steam://rungameid` 会让 Steam 按启动项把启动器再拉起一次，
    结果就是两个启动器实例同时改游戏目录，所以这种情况必须自己起 exe。
    """
    try:
        if not _settings.get_setting(STEAM_BINDING_KEY):
            return False
        from functions.base import steam_binding
        return steam_binding.is_bound()
    except Exception:
        return False


def _sync_steam_binding():
    """启动前对齐 Steam 启动项：设置项关掉了就把残留的绑定删掉。

    只在「确实是我们写进去的绑定」或者「存在绑定备份」时才动手，否则会把
    用户自己设的 -dx11 之类参数一起删掉。任何异常都不许拖累启动流程。
    """
    try:
        if _settings.get_setting(STEAM_BINDING_KEY):
            return
        from functions.base import steam_binding
        if not steam_binding.is_bound() and not os.path.exists(steam_binding._BACKUP_FILE):
            return
        print("设置项已关闭, 清理 Steam 启动项绑定...")
        result = steam_binding.apply(False)
        if result.get("ok"):
            print(f"已删除 Steam 启动项: {result.get('message', '')}")
        else:
            print(f"删除 Steam 启动项失败(继续启动): {result.get('error', '')}")
    except Exception as exc:
        print(f"清理 Steam 启动项异常(继续启动): {exc}")


def _start_game(launcher_mode: bool) -> bool:
    if launcher_mode:
        return _run_game_exe()
    if _steam_launch_bound():
        print("Steam 启动项已绑定本启动器, 为免重复拉起启动器, 这里直接启动游戏 exe")
        return _run_game_exe()
    return _launch_via_steam()


def launch_game_process():
    launcher_mode = is_launcher_mode()

    # 启动之前先对齐 Steam 启动项：设置项关了就把绑定删掉
    _sync_steam_binding()

    if not _settings.get_setting("enable_mods"):
        print("启动器设置项禁用了 mod 加载功能, 直接启动游戏...\n (如有需要, 请在设置项启用 mod 加载功能)")
        return _start_game(launcher_mode)

    print("加载 mod 到游戏目录...")
    ModManager().load_all_mods()

    if not _has_loader_mods():
        print("没有检测到需要加载的 mod, 直接启动游戏...")
        return _start_game(launcher_mode)

    _start_with_mod_loader(launcher_mode)

    return True

def _start_with_mod_loader(launcher_mode: bool = False):
    game_path = _settings.get_setting('game_path') or ''
    extra_mod_loader = _settings.get_setting('extra_mod_loader') or ''
    game_exe = os.path.join(game_path, GAME_EXE)

    thread_count = _settings.get_setting('mod_loader_threads') or 5

    # --launcher-mode 下 Steam 已经被启动项接管，mod loader 不能再让 Steam 启动游戏，
    # 必须自己起 exe，所以加 --file-mode。
    mode_args = [FILE_MODE_FLAG] if launcher_mode else []

    if extra_mod_loader and os.path.exists(extra_mod_loader):
        print(f"使用外部 mod loader 启动: {extra_mod_loader}, 线程数: {thread_count}")
        flags = subprocess.CREATE_NO_WINDOW if _settings.get_setting("hide_mod_load") else 0
        subprocess.Popen([extra_mod_loader, game_exe, f"--threads={thread_count}", *mode_args],
                         creationflags=flags)
        return

    builtin_exe = os.path.join("resources", "mod_loader", "yisangModLoader.exe")
    if os.path.exists(builtin_exe):
        print(f"使用内置 mod loader 启动: {builtin_exe}")
        flags = subprocess.CREATE_NO_WINDOW if _settings.get_setting("hide_mod_load") else 0
        proc = subprocess.Popen([builtin_exe, game_exe, f"--threads={thread_count}", *mode_args],
                                creationflags=flags)
        from functions.pages.tools.mod_loader_progress import open_mod_loader_progress
        open_mod_loader_progress(proc.pid)
        return

    print("使用内置 mod loader (venv 直跑) 启动...")
    loader_py = "resources/mod_loader/_internal/venv/Bins/python.exe"
    loader_script = "resources/mod_loader/_internal/main.py"
    proc = subprocess.Popen([loader_py, loader_script, game_exe, f"--threads={thread_count}", *mode_args],
                            creationflags=subprocess.CREATE_NO_WINDOW)
    from functions.pages.tools.mod_loader_progress import open_mod_loader_progress
    open_mod_loader_progress(proc.pid)
