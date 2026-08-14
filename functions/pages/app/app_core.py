import os
import sys
from subprocess import Popen
from threading import Thread
from functions.base.settings_manager import get_settings_manager
from functions.base.sound_utils import play_sound
from functions.base.color_scheme import lighten_color as _lighten_color, darken_color as _darken_color
from rich import print
import tkinter as tk
from functions.extension.addon.addon_utils import AddonManager
from functions.extension.mod.mod_utils import ModManager
from functions.pages.terminal.terminal_redirect import TerminalRedirector
from functions.pages.app.page_loader import PageLoader


class FaustLauncherCore:
    """应用程序核心后端类"""
    
    def __init__(self, debug=False):
        self.settings_manager = get_settings_manager()
        self.bg_color: str = self.settings_manager.get_setting("bg_color")  # type: ignore
        self.version_info = self.settings_manager.get_setting("version_info")
        
        self.debug = debug
        self._last_sound_ms = 0
        self.addon_manager: AddonManager = None  # type: ignore
        self.mod_manager: ModManager = None  # type: ignore
        self.page_loader:PageLoader = None  # type: ignore
        self.terminal_redirector:TerminalRedirector = None  # type: ignore
        self.terminal_text:tk.Text = None  # type: ignore
        
        self.background_images = []
        self.current_bg_index = 0
        self.current_bg_image = None
        self.current_blurred_bg = None
        self.current_content_bg = None
        
        self.lighten_bg_color = self.lighten_color(self.bg_color, 5)
        
        self.load_background_images()
        
        self.root: tk.Tk = None  # type: ignore
        
    def refresh_all_tabs(self):
        """刷新所有标签页"""
        self.page_loader.pages['mod_addon'].refresh_all_tabs()

    def load_background_images(self):
        """加载背景图片"""
        background_dir = "assets/images/background"
        if os.path.exists(background_dir):
            for file in os.listdir(background_dir):
                if file.lower().endswith(('.png', '.jpg', '.jpeg')):
                    file_path = os.path.join(background_dir, file)
                    self.background_images.append(file_path)
        
        if not self.background_images:
            print("未找到背景图片，将使用默认背景")
        else:
            print(f"找到 {len(self.background_images)} 张背景图片")

    def _on_global_click(self, event):
        """全局点击事件处理：播放音效"""
        import time
        now_ms = int(time.time() * 1000)
        if now_ms - self._last_sound_ms < 30:
            return
        self._last_sound_ms = now_ms
        
        widget_name = getattr(event.widget, 'winfo_class', lambda: '')()
        if getattr(event.widget, '_is_button', False):
            play_sound("assets/voices/click.wav")
            return
        container_classes = {'Frame', 'TFrame', 'Canvas', 'Toplevel',
                            'Labelframe', 'TLabelframe', 'Panedwindow',
                            'TPanedwindow'}
        if widget_name not in container_classes:
            play_sound("assets/voices/click.wav")

    def _on_reload_addons(self):
        """重载插件"""
        try:
            self.addon_manager.reload_all_addons()
            if hasattr(self, 'tray') and self.tray is not None: # type: ignore
                try:
                    self.tray.update_menu() # type: ignore
                except Exception:
                    pass
        except Exception as e:
            print(f"重载插件时发生错误: {e}")

    def setup_terminal_redirect(self):
        """设置终端重定向"""
        if self.terminal_text:
            import tkinter as tk
            self.terminal_text.config(state=tk.NORMAL)
            self.terminal_redirector = TerminalRedirector(self.terminal_text)
            self.terminal_redirector.start_redirect(self.debug)
            self.terminal_text.config(state=tk.DISABLED)
            print("终端重定向已启用")
            
    def add_terminal_message(self, message: str):
        """添加消息到终端"""
        if self.terminal_text:
            import tkinter as tk
            self.terminal_text.config(state=tk.NORMAL)
            self.terminal_text.insert(tk.END, message + "\n")
            self.terminal_text.see(tk.END)
            self.terminal_text.config(state=tk.DISABLED)
            self.terminal_text.update_idletasks()
            
    def clear_terminal(self):
        """清空终端内容"""
        if self.terminal_text:
            import tkinter as tk
            self.terminal_text.config(state=tk.NORMAL)
            self.terminal_text.delete(1.0, tk.END)
            self.terminal_text.config(state=tk.DISABLED)
            print("🗑️ 终端内容已清空")
            
    def copy_terminal_content(self):
        """复制终端内容到剪贴板"""
        try:
            if self.terminal_text:
                content = self.terminal_text.get(1.0, tk.END)
                self.root.clipboard_clear()
                self.root.clipboard_append(content)
                print("📋 终端内容已复制到剪贴板")
        except Exception as e:
            print(f"复制失败: {e}")
            
    def open_custom_translation_tool(self):
        """打开自定义汉化工具"""
        try:
            sys.path.append('functions')
            from functions.pages.tools.custom_translation import open_custom_translation_tool
            open_custom_translation_tool(self)
            print("🔧 自定义汉化工具已打开")
        except Exception as e:
            print(f"打开自定义汉化工具失败: {e}")
            from tkinter import messagebox
            messagebox.showerror("错误", f"打开自定义汉化工具失败: {str(e)}")

    def open_post_extension_tools(self):
        """打开扩展工具 (插件模板 / 包装 Mod)"""
        try:
            from functions.tools.post_extension_tools import post_extension_tools_gui
            post_extension_tools_gui(self)
            print("🧩 扩展工具已打开")
        except Exception as e:
            print(f"打开扩展工具失败: {e}")
            from tkinter import messagebox
            messagebox.showerror("错误", f"打开扩展工具失败: {str(e)}")

    def update_translation(self):
        """更新汉化"""
        from functions.pages.app.page_loader import download_and_launch
        Thread(target=download_and_launch).start()
        
    def show_help(self):
        """显示帮助信息"""
        Popen(["notepad", "README.md"], shell=True)
        
    def open_feature(self, feature):
        """打开指定功能"""
        import webbrowser
        
        if feature['name'] == "📁 游戏目录":
            path = self.settings_manager.get_setting("game_path")
            if path and os.path.exists(path):
                os.startfile(path)
        elif feature['name'] == "🔄 零协会":
            webbrowser.open("https://zeroasso.top")
        elif feature['name'] == "📒 气泡文本":
            webbrowser.open("https://wwyi.lanzoub.com/b014wpn02j")
        elif feature['name'] == "📝 维基":
            webbrowser.open("https://limbuscompany.huijiwiki.com/wiki/%E9%A6%96%E9%A1%B5")
        elif feature['name'] == "📖 N网":
            webbrowser.open("https://www.nexusmods.com/limbuscompany/mods")
        elif feature['name'] == "📦 Github":
            webbrowser.open("https://github.com/f0lkskill/FaustLauncher")
            
    def open_website(self):
        """打开作者网站"""
        import webbrowser
        webbrowser.open("https://space.bilibili.com/599331034")
        
    def send_feedback(self):
        """发送反馈"""
        import webbrowser
        webbrowser.open("https://space.bilibili.com/599331034")
        
    def open_mod_manager(self):
        """打开mod管理器 (工具页卡片入口)"""
        try:
            from functions.pages.tools.mod_manager_window import open_mod_manager_window
            open_mod_manager_window(self)
        except Exception as e:
            print(f"打开mod管理器失败: {e}")
            from tkinter import messagebox
            messagebox.showerror("错误", f"打开mod管理器失败: {str(e)}")
            
    def check_settings(self):
        """检查设置"""
        if not self.settings_manager.get_setting("game_path"):
            print("错误: 未配置游戏路径")
            from tkinter.filedialog import askopenfilename
            file_path = askopenfilename(title="选择边狱巴士主程序", filetypes=[("边狱巴士主程序", "LimbusCompany.exe")])
            if file_path:
                self.settings_manager.set_setting("game_path", file_path.replace('LimbusCompany.exe', ''))
                self.settings_manager.save_settings()
                settings_page = self.page_loader.get_page('settings')  # type: ignore
                if settings_page:
                    settings_page.refresh_all_displays()
            else:
                print("错误: 未选择游戏文件")
                os._exit(-1)
                
        mems: dict = self.settings_manager.get_setting('mems')  # type: ignore
        has_notify = mems.get('version_notify_flag')
        from functions.update.version_utils import check_version_update
        from functions.web_update.sql_manager import notify_new_version
        
        has_update, latest_info, name = check_version_update(self.root)
        if has_update:
            print(f"启动器的新版本已经发布: {name}")
        latest_info['version_name'] = name
        if not has_notify:
            print('发现新版本，创建版本详细介绍窗口。')
            # print(f'参数: {name}, {has_update}, {latest_info}')
            notify_new_version(name, root=self.root, has_new_version=has_update, 
                            latest_info=latest_info, info='发现新版本' if has_update else '已是最新版本', must_show=True)
            mems['version_notify_flag'] = True
            self.settings_manager.set_setting('mems', mems)
        
        if len(sys.argv) > 1 or not os.path.exists("lang/LLC_zh-CN"):
            from functions.pages.app.page_loader import download_and_launch
            Thread(target=download_and_launch).start()
        
        if not os.path.exists("assets/Font/Context/ChineseFont.ttf"):
            print("错误: 未找到字体文件 Font/Context/ChineseFont.ttf\n请尝试手动添加或者使用汉化更新修复")

    def folder_link(self):
        """创建文件夹超链接"""
        import tkinter.messagebox as messagebox
        from tkinter.filedialog import askdirectory
        
        try:
            messagebox.showinfo("选择源文件夹", "请选择要创建链接的源文件夹")
            source_path = askdirectory(title="选择源文件夹")
            if not source_path:
                messagebox.showwarning("取消", "操作已取消")
                return
            
            messagebox.showinfo("选择目标位置", "请选择链接要放置的目标文件夹")
            target_path = askdirectory(title="选择目标文件夹")
            if not target_path:
                messagebox.showwarning("取消", "操作已取消")
                return
            
            source_name = os.path.basename(source_path)
            link_path = os.path.join(target_path, source_name)
            
            if os.path.exists(link_path):
                response = messagebox.askyesno("确认覆盖", 
                    f"目标位置已存在同名文件夹 '{source_name}'，是否覆盖？")
                if not response:
                    messagebox.showinfo("取消", "操作已取消")
                    return
            
            mklink_command = f'mklink /J "{link_path}" "{source_path}"'
            
            batch_content = f'''@echo off
echo 正在创建文件夹链接...
{mklink_command}
if %errorlevel% equ 0 (
    echo 文件夹链接创建成功！
    echo 源文件夹: {source_path}
    echo 链接位置: {link_path}
    pause
) else (
    echo 创建文件夹链接失败，请检查权限或路径是否正确
)
'''
            
            batch_file = "create_link.bat"
            with open(batch_file, 'w', encoding='gbk') as f:
                f.write(batch_content)
            
            Popen(f'powershell Start-Process "{batch_file}" -Verb runAs', shell=True)
            
        except Exception as e:
            messagebox.showerror("错误", f"创建文件夹链接时出错: {str(e)}")
            
    def lighten_color(self, color, percent):
        return _lighten_color(color, percent)
        
    def darken_color(self, color, factor=0.8):
        return _darken_color(color, factor)