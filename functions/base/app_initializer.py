"""
程序的基本初始化加载器。
用于进行程序加载所需进行的一般工作流程。
"""

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

    # 必须最早执行: 打包时 console=False 会让 sys.stdout/stderr 为 None, 而 rich 会退回它自己
    # 用系统首选编码(cp950/cp936/cp932)打开的 devnull —— 打印简体字/emoji 直接 UnicodeEncodeError,
    # 用户看到的就是 PyInstaller 弹出的 "Unhandled exception in script"。
    # (会把编码不变地改成 errors='replace'，放不下的字符退化成 '?' 而不报错)
    harden_stdio()

    # 控制台输出美化：给每行加 [时间] [区域] [级别] [文件:行] 前缀并着色。
    # 也要放在 UI 重定向器创建之前：两个重定向器都只把"转发到真实控制台"那一步交给
    # 构造时捕获的 sys.stdout，所以装在这里正好只影响 cmd，UI 终端与日志文件不受影响。
    try:
        from functions.base.console_log import install as _install_console_log
        _install_console_log()
    except Exception as _exc:  # noqa: BLE001
        print(f"控制台日志美化不可用(可忽略): {_exc}")


    # 素材检查：图标/音效/背景/皮肤图片已从仓库移出，改成独立的资源包分发
    try:
        if not os.path.isfile(os.path.join("assets", "images", "icon", "icon.png")):
            print(r"[Assets] 没找到 assets/images —— 素材不在仓库里，"
                  r"先拉资源包：tools\run\assets.bat fetch（或把资源包 zip 解压到项目根）")
    except Exception:  # noqa: BLE001
        pass

def detect_update_window() -> bool:
    # 版本更新提示独立窗口模式: 与 --nyos-window 同一模式
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
    # Mod加载器进度提示独立窗口模式: 与 --mod-manager-window 同一模式
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
    # Web 现代化 UI 模式: 默认启动方式 (新版 Web 界面)
    # 可用 --tk-ui 参数或设置"界面模式=旧版界面 (0)"回到经典 TK 界面
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

    # 一般性质工作流
    base_load()

    # 检查运行参数：
    for arg in sys.argv:
        if LAUNCH_MODE.get(arg):
            # 运行相关参数对应的模式
            LAUNCH_MODE.get(arg)(debug = DEBUG_MODE) # type: ignore
            return

    if detect_update_window():
        # 是进行更新
        return

    if detect_mod_loader_window():
        # 是进行mod加载器
        return

    # 扩展工具独立窗口模式: 与 --mod-manager-window 同一模式
    if "--extension-tools-window" in sys.argv:
        run_extension_tools_window(debug="--debug" in sys.argv)
        return

    # 自定义汉化工具独立窗口模式: 与 --extension-tools-window 同一模式
    if "--custom-translation-window" in sys.argv:
        run_custom_translation_window(debug="--debug" in sys.argv)
        return

    # 确认进入主流程
    # 删除旧的更新脚本
    # 必须按**安装根**定位, 不能用相对路径 "updater.vbs": 启动器的工作目录不一定是
    # 安装目录 (快捷方式/托盘/文件关联启动时 cwd 可能是 System32 之类), 用相对路径
    # 会删不到, 把 updater.vbs 一直留在 FaustLauncher.exe 旁边。
    # 那个脚本按"往上数三层"定位安装根, 直接在根目录里双击它会算到安装根的曾祖父目录,
    # 然后把它看到的每个文件"复制过去再删掉原件" —— exe 会当场从安装目录消失。
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
        # 是web UI，静默不处理
        return

    initialize_tk()

def initialize_tk():
    """TK UI 初始化"""

    # 检测是否已有实例在运行
    if check_single_instance():
        os._exit(0)

    # 初始化日志系统
    from functions.base.log_manager import init_logger
    init_logger()

    # 创建主窗口
    root = tk.Tk()
    root.withdraw()

    # 创建启动画面
    splash, splash_root = create_simple_splash(root)

    settings_manager = get_settings_manager()

    # 创建核心后端实例
    core = FaustLauncherCore(DEBUG_MODE)  # 传入调试参数

    def on_app_initialized():
        """应用程序初始化完成后的回调"""
        root.update_idletasks()
        root.update()
        root.after(4000, lambda: root.deiconify())

        ws_path = settings_manager.get_setting("welcome_sound")
        root.after(4000, lambda: play_sound(ws_path))

        core.terminal_redirector.enable_type = True  # type: ignore
        root.after(4500, core.check_settings)

    # 创建UI实例（传入核心后端）
    app = FaustLauncherUI(root, core, on_initialized=on_app_initialized)
    app.initialize_pages()

    # 启动主循环
    root.mainloop()