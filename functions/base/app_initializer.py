
import sys, os
import traceback
import tkinter as tk

from functions.achievement.hook import run_achievement_hook
from functions.pages.tools.nyos_prescript import run_prescript_window
from functions.pages.tools.mod_manager_window import run_mod_manager_window
from functions.pages.tools.extension_tools_window import run_extension_tools_window
from functions.pages.tools.custom_translation_window import run_custom_translation_window
from functions.pages.app.app_core import FaustLauncherCore
from functions.pages.app.app_ui import FaustLauncherUI, check_single_instance
from functions.pages.notice.loading_info import create_simple_splash
from functions.base.settings_manager import get_settings_manager
from functions.base.sound_utils import play_sound

WEB_UI_FLAG = 'WEB_UI'
TK_UI_FLAG = 'TK_UI'


def _game_path_from_argv():
    """从命令行里找游戏目录。

    Steam 启动项里的 `%command%` 会展开成游戏 exe 的完整路径，所以从 Steam 点
    启动时 argv 里天然带着它——比让用户事先配好路径可靠得多。
    """
    from functions.base.steam_locator import GAME_EXE, resolve_game_dir

    for arg in sys.argv[1:]:
        if not arg or arg.startswith("-"):
            continue
        candidate = arg.strip().strip('"')
        if os.path.basename(candidate).lower() != GAME_EXE.lower():
            continue
        found = resolve_game_dir(candidate)
        if found:
            return found
    return ""


def _ensure_game_path():
    """确保设置里的游戏路径可用，不可用时自动查找并写回配置。"""
    from functions.base.steam_locator import resolve_game_dir, find_steam_game_path

    manager = get_settings_manager()
    if resolve_game_dir(manager.get_setting("game_path") or ""):
        return True

    found = _game_path_from_argv()
    if found:
        print(f"[LauncherMode] 从启动参数定位到游戏路径: {found}")
    else:
        found = resolve_game_dir(find_steam_game_path() or "") or ""
        if found:
            print(f"[LauncherMode] 从 Steam 库定位到游戏路径: {found}")

    if not found:
        print("[LauncherMode] 未能自动定位游戏路径, 请先在启动器界面里设置")
        return False

    manager.set_setting("game_path", found)
    try:
        manager.save_settings()
    except Exception as exc:  # noqa: BLE001
        print(f"[LauncherMode] 保存游戏路径失败(继续): {exc}")
    return True


def run_launcher_mode(debug=False):
    """--launcher-mode：不进入 UI，直接跑完整后端启动流程。

    Steam 通过启动项把启动器拉起时走这里：检查/更新汉化 -> 应用到游戏目录 ->
    加载 mod -> 起游戏，最后照常弹出 mod 加载进度窗口。跑完即退出。

    这里第一步就把进程切成**完全静默模式**：本进程不创建任何窗口。后台进程没有
    Tk 主循环，任何 `tk.Tk()` / `Toplevel()` 都只会留下来一个永远无响应的空窗口，
    这正是「从 Steam 点启动后弹窗卡死」的原因。mod 加载进度窗口不受影响——它是
    另一个进程，自己跑自己的 mainloop。
    """
    from functions.base.headless_ui import install as _install_headless_ui
    _install_headless_ui()

    print("[LauncherMode] 以 Steam 启动器模式运行（不进入 UI）")
    try:
        from functions.base.log_manager import init_logger
        init_logger()
    except Exception as exc:  # noqa: BLE001
        print(f"[LauncherMode] 日志初始化失败(继续): {exc}")

    _ensure_game_path()

    try:
        from functions.pages.app.page_loader import download_and_launch
        download_and_launch(obj=None, need_run_game=True)
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        print(f"[LauncherMode] 启动流程失败: {exc}")


LAUNCH_MODE = {
    "--achievement-hook": run_achievement_hook,    
    "--nyos-window": run_prescript_window,
    "--mod-manager-window": run_mod_manager_window,
    "--extension-tools-window": run_extension_tools_window,
    "--custom-translation-window": run_custom_translation_window,
    "--launcher-mode": run_launcher_mode
}

DEBUG_MODE = '--debug' in sys.argv

def base_load():
        
    from functions.base.common.stdio import harden_stdio

    harden_stdio()

    try:
        from functions.base.console_log import install as _install_console_log
        _install_console_log()
    except Exception as _exc:  # noqa: BLE001
        print(f"控制台日志美化不可用(可忽略): {_exc}")

    try:
        if not os.path.isfile(os.path.join("assets", "images", "icon", "icon.png")):
            print(r"[Assets] 没找到 assets/images —— 素材不在仓库里，"
                  r"先拉资源包：tools\run\assets.bat fetch（或把资源包 zip 解压到项目根）")
    except Exception:  # noqa: BLE001
        pass

def detect_update_window() -> bool:
    if "--update-window" in sys.argv:
        from functions.pages.notice.version_update_window import run_update_window
        payload_b64 = None
        if "--update-payload" in sys.argv:
            idx = sys.argv.index("--update-payload")
            if idx + 1 < len(sys.argv):
                payload_b64 = sys.argv[idx + 1]
        run_update_window(payload_b64, debug=DEBUG_MODE)
        return True
    return False

def detect_mod_loader_window() -> bool:
    if "--mod-loader-progress" in sys.argv:
        from functions.pages.tools.mod_loader_progress import run_mod_loader_progress
        loader_pid = 0
        if "--pid" in sys.argv:
            idx = sys.argv.index("--pid")
            if idx + 1 < len(sys.argv):
                try:
                    loader_pid = int(sys.argv[idx + 1])
                except ValueError:
                    loader_pid = 0
        run_mod_loader_progress(loader_pid, debug="--debug" in sys.argv)
        return True
    return False

def _reconcile_steam_binding():
    """启动器初始化时核对 Steam 启动项，不符合当前设置就纠正。

    为什么放在这里而不是「启动游戏」流程里：一旦 Steam 的启动项指向一个已经被
    删掉的旧启动器，用户从 Steam 点游戏只会毫无反应，永远走不到启动游戏那段代码。
    只有「启动器自己被打开」这个时刻是必然发生的，所以检查点只能在这里。
    """
    from functions.base.launcher_mode import is_launcher_mode
    if is_launcher_mode():
        # launcher-mode 是 Steam 按启动项拉起来的：此刻启动项必然指向自己，
        # 再去关 Steam 会把正在拉起的这条链路自己掐断。
        return
    try:
        from functions.base import steam_binding
        result = steam_binding.reconcile()
        if result.get("changed"):
            print(f"[SteamBinding] {result.get('message', '')}")
            if result.get("ok") and result.get("value"):
                print(f"[SteamBinding] 已绑定: {result['value']}")
    except Exception as exc:
        print(f"[SteamBinding] 核对启动项失败(忽略): {exc}")


def _start_steam_binding_reconcile():
    """后台线程做核对：不一致时要先关 Steam 再写再起，不能卡住启动画面。"""
    import threading
    threading.Thread(target=_reconcile_steam_binding, daemon=True,
                     name="steam-binding-reconcile").start()


def detect_ui_mode() -> bool:
    from functions.base.settings_manager import get_settings_manager
    if "--tk-ui" in sys.argv:
        pass
    elif "--web-ui" in sys.argv or get_settings_manager().get_setting("ui_mode") != 0:
        from functions.pages.app.app_web import run_web_ui, check_single_instance
        if check_single_instance():
            os._exit(0)
        run_web_ui(debug="--debug" in sys.argv)
        return True
    return False

def launch_app():

    base_load()

    for arg in sys.argv:
        if LAUNCH_MODE.get(arg):
            LAUNCH_MODE.get(arg)(debug = DEBUG_MODE) # type: ignore
            return

    if detect_update_window():
        return

    if detect_mod_loader_window():
        return

    if "--extension-tools-window" in sys.argv:
        run_extension_tools_window(debug="--debug" in sys.argv)
        return

    if "--custom-translation-window" in sys.argv:
        run_custom_translation_window(debug="--debug" in sys.argv)
        return

    if getattr(sys, "frozen", False):
        _project_root = os.path.dirname(os.path.abspath(sys.executable))
    else:
        _project_root = os.path.abspath(
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
    _old_updater = os.path.join(_project_root, "updater.vbs")
    if os.path.exists(_old_updater):
        try:
            os.remove(_old_updater)
        except OSError:
            pass

    # Steam 启动项核对放在这里：update 窗口 / mod loader 进度窗口 / --launcher-mode
    # 都已经 return 了，剩下的是「用户真的打开了启动器」这条路径。
    _start_steam_binding_reconcile()

    if detect_ui_mode():
        return

    initialize_tk()

def initialize_tk():

    if check_single_instance():
        os._exit(0)

    from functions.base.log_manager import init_logger
    init_logger()

    root = tk.Tk()
    root.withdraw()

    splash, splash_root = create_simple_splash(root)

    settings_manager = get_settings_manager()

    core = FaustLauncherCore(DEBUG_MODE)

    def on_app_initialized():
        root.update_idletasks()
        root.update()
        root.after(4000, lambda: root.deiconify())

        ws_path = settings_manager.get_setting("welcome_sound")
        root.after(4000, lambda: play_sound(ws_path))

        core.terminal_redirector.enable_type = True  # type: ignore
        root.after(4500, core.check_settings)

    app = FaustLauncherUI(root, core, on_initialized=on_app_initialized)
    app.initialize_pages()

    root.mainloop()
