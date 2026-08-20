"""
Faust Launcher - 主入口

1. 模块化拆分：将页面加载逻辑分离到 PageLoader
2. 职责分离：UI结构和业务逻辑分离，分为 app_core.py 和 app_ui.py
3. 按需加载：支持延迟加载页面
4. 解耦合：降低模块间依赖
"""

import tkinter as tk
import os
import sys

def main():
    """优化后的主函数"""
    # 控制台切换为 UTF-8, 避免块状字符/emoji 在 GBK 控制台编码失败
    for stream in (sys.stdout, sys.stderr):
        try:
            if hasattr(stream, 'reconfigure'):
                stream.reconfigure(encoding='utf-8', errors='replace')  # type: ignore
        except Exception:
            pass

    # 今日指令独立窗口模式: 打包环境下由主 exe 以 --nyos-window 二次拉起自身,
    # 直接运行 pywebview 窗口, 不进入 tkinter 主界面 (也需跳过单实例检测)
    if "--nyos-window" in sys.argv:
        from functions.pages.tools.nyos_prescript import run_prescript_window
        run_prescript_window(debug="--debug" in sys.argv)
        return

    # 版本更新提示独立窗口模式: 与 --nyos-window 同一模式
    if "--update-window" in sys.argv:
        from functions.pages.notice.version_update_window import run_update_window
        payload_b64 = None
        if "--update-payload" in sys.argv:
            idx = sys.argv.index("--update-payload")
            if idx + 1 < len(sys.argv):
                payload_b64 = sys.argv[idx + 1]
        run_update_window(payload_b64, debug="--debug" in sys.argv)
        return

    # Mod管理器独立窗口模式: 与 --nyos-window 同一模式
    if "--mod-manager-window" in sys.argv:
        from functions.pages.tools.mod_manager_window import run_mod_manager_window
        run_mod_manager_window(debug="--debug" in sys.argv)
        return

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
        return
    
    # 扩展工具独立窗口模式: 与 --mod-manager-window 同一模式
    if "--extension-tools-window" in sys.argv:
        from functions.pages.tools.extension_tools_window import run_extension_tools_window
        run_extension_tools_window(debug="--debug" in sys.argv)
        return

    # 自定义汉化工具独立窗口模式: 与 --extension-tools-window 同一模式
    if "--custom-translation-window" in sys.argv:
        from functions.pages.tools.custom_translation_window import run_custom_translation_window
        run_custom_translation_window(debug="--debug" in sys.argv)
        return
    
    # Web 现代化 UI 模式: --web-ui 参数启动, 或在设置中选择"新版 Web 界面"后生效
    from functions.base.settings_manager import get_settings_manager
    if "--web-ui" in sys.argv or get_settings_manager().get_setting("ui_mode") == 1:
        from functions.pages.app.app_web import run_web_ui, check_single_instance
        if check_single_instance():
            os._exit(0)
        run_web_ui(debug="--debug" in sys.argv)
        return
    
    from functions.pages.app.app_core import FaustLauncherCore
    from functions.pages.app.app_ui import FaustLauncherUI, check_single_instance
    from functions.pages.notice.loading_info import create_simple_splash
    from functions.base.settings_manager import get_settings_manager
    from functions.base.sound_utils import play_sound
    
    # 检测是否已有实例在运行
    if check_single_instance():
        os._exit(0)
    
    # 初始化日志系统
    from functions.base.log_manager import init_logger
    init_logger()
    
    # 删除旧的更新脚本
    if os.path.exists("updater.vbs"):
        os.remove("updater.vbs")
    
    # 创建主窗口
    root = tk.Tk()
    root.withdraw()
    
    # 创建启动画面
    splash, splash_root = create_simple_splash(root)
    
    settings_manager = get_settings_manager()
    
    # 创建核心后端实例
    core = FaustLauncherCore()  # 传入调试参数
    
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


if __name__ == "__main__":
    main()
