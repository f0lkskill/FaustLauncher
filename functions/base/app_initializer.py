
import sys, os
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

LAUNCH_MODE = {
    "--achievement-hook": run_achievement_hook,    
    "--nyos-window": run_prescript_window,
    "--mod-manager-window": run_mod_manager_window,
    "--extension-tools-window": run_extension_tools_window,
    "--custom-translation-window": run_custom_translation_window
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
