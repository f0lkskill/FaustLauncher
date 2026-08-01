"""
Faust Launcher - 主入口

优化内容：
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
    
    from functions.pages.app.app_core import FaustLauncherCore
    from functions.pages.app.app_ui import FaustLauncherUI, check_single_instance
    from functions.pages.notice.loading_info import create_simple_splash
    from functions.base.settings_manager import get_settings_manager
    from functions.base.sound_ulits import play_sound
    
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
