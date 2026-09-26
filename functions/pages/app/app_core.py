import os
import sys
from subprocess import Popen
from threading import Thread
from functions.base.settings_manager import get_settings_manager
from functions.web_update.translation_source import get_translation_dir
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
        if not self.settings_manager.get_setting("click_sound"):
            return
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
        """打开自定义汉化工具 (HTML webview 窗口, 独立子进程)"""
        try:
            from functions.pages.tools.custom_translation_window import open_custom_translation_window
            open_custom_translation_window(self)
            print("🔧 自定义汉化工具已打开")
        except Exception as e:
            print(f"打开自定义汉化工具失败: {e}")
            from tkinter import messagebox
            messagebox.showerror("错误", f"打开自定义汉化工具失败: {str(e)}")

    def open_post_extension_tools(self):
        """打开扩展工具 HTML 窗口 (插件模板 / 包装 Mod / 发布 Mod), 需密钥验证"""
        try:
            from tkinter import simpledialog, messagebox
            from functions.base.web_config import get_web_config
            secret = get_web_config().get('extension_tool_key')
            if not secret:
                messagebox.showerror("访问被拒绝", "未配置开发者工具密钥 (extension_tool_key), 无法访问")
                return
            answer = simpledialog.askstring("密钥验证", "请输入开发者工具密钥:", show='*', parent=self.root)
            if answer is None:
                return
            if answer.strip() != str(secret):
                messagebox.showerror("访问被拒绝", "密钥错误, 无法访问开发者工具")
                return
            from functions.pages.tools.extension_tools_window import open_extension_tools_window
            open_extension_tools_window(self)
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
        import webbrowser
        webbrowser.open("https://www.showdoc.com.cn/faustlauncher/11559060627455094")
        # Popen(["notepad", "README.md"], shell=True)
        
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
        elif feature['name'] == "📦 GitHub":
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
            
    def _ask_web_game_path(self, found: str, force=False) -> None:
        """Web 模式: 把 Steam 自动检测到的路径推给前端, 由模态窗口问用户

        只记录待确认路径 (self.pending_steam_path), 不写设置 —— 用户在前端点
        "是" 才写 (AppApi.confirm_steam_game_path), 点 "不是" 则由前端强制选目录
        (AppApi.apply_game_path)。

        路径里必须有 LimbusCompany.exe: 检测到的路径没有这个文件时 path_ok=False
        (pending_steam_path 仍保留原值, 只用于界面提示"Steam 里读到的是这个, 但无效"),
        前端会跳过确认、直接要求用户自己选目录。found 为空串表示没检测到。

        force=True 用于"路径后来失效了"的重复弹出 (前端平时只问一次)。
        """
        from functions.base.steam_locator import resolve_game_dir, GAME_EXE
        found = str(found or "").strip()
        resolved = resolve_game_dir(found) if found else ""
        prev = getattr(self, "pending_steam_path", None)
        same = (prev is not None and str(prev) == found
                and bool(getattr(self, "_steam_path_ok", False)) == bool(resolved))
        self.pending_steam_path = found          # 展示用原始路径 (可能是无效路径)
        self._steam_path_ok = bool(resolved)     # 与 pending 配套, 用于"同结果不重复弹窗"
        self._steam_path_checked = True          # 供前端兜底查询: 检测已做完
        if same and not force:
            # 同一次启动里两次检测得到同一结果 (ensure_game_path 与 check_settings 都会走到):
            # 不要再弹一次 —— 否则用户会看到"两个询问"
            print("[设置] 游戏路径检测结果与上次相同, 不重复弹窗")
            return
        try:
            from functions.web_update import zeroasso_download as _zd
            push = getattr(_zd, "_web_progress", None)
            if not push:
                print("[设置] 前端推送不可用, 无法弹出游戏路径确认窗口 (请在设置页手动选择)")
                return
            push("path_confirm", {
                "path": found,
                "path_ok": bool(resolved),
                "from_steam": bool(resolved),
                "game_exe": GAME_EXE,
                "force": bool(force),
            })
            if resolved:
                print(f"[设置] 已从 Steam VDF 获取到游戏路径, 等待用户确认: {resolved}")
            elif found:
                print(f"[设置] Steam 检测到的路径下没有 {GAME_EXE}, 视为无效路径: {found}")
            else:
                print("[设置] 未从 Steam VDF 获取到游戏路径, 等待用户手动选择")
        except Exception as e:
            print(f"[设置] 推送游戏路径确认窗口失败: {e}")

    def ensure_game_path(self, interactive=True):
        """确定游戏路径: 没有就定位 Steam, 再让用户确认 / 自己选。

        Web 模式 (interactive=False): 只记录待确认路径并推给前端模态窗口; 检测过一次就
        不再重复推送 (self._steam_path_checked) —— 前端据此"检测中 -> 出结果"只走一遍。
        桌面模式 (interactive=True): 纯系统询问窗口, 没选 / 选到没 exe 的目录都直接退出。
        """
        if self.settings_manager.get_setting("game_path"):
            return
        if not interactive and getattr(self, "_steam_path_checked", False):
            return
        print("错误: 未配置游戏路径")
        # 尝试通过 Steam VDF 自动定位边狱巴士, 找到后询问用户确认
        # resolve_game_dir: 目录里必须有 LimbusCompany.exe 才算有效路径
        from functions.base.steam_locator import (
            find_steam_game_path, resolve_game_dir, GAME_EXE,
        )
        raw_found = find_steam_game_path() or ""
        found = resolve_game_dir(raw_found) or None
        if not interactive:
            # Web 模式: 不静默写入, 交给前端模态窗口问用户。
            # 没检测到 / 检测到的路径里没有 LimbusCompany.exe, 都算"没检测到",
            # 前端会跳过确认、直接要求用户自己选目录 (路径里有 exe 是硬要求)。
            self._ask_web_game_path(raw_found)
            return
        # 桌面版: 纯系统询问窗口; 没选 / 选到没有 exe 的目录都直接退出启动器
        from tkinter import messagebox
        from tkinter.filedialog import askopenfilename
        if found and messagebox.askyesno(
                "检测到边狱巴士",
                f"启动器已自动从 Steam VDF 获取到边狱巴士安装路径:\n{found}\n\n这是你的游戏路径吗？",
                parent=self.root):
            print(f"用户确认了自动检测到的路径: {found}")
        else:
            if raw_found and not found:
                print(f"错误: Steam 检测到的路径下没有 {GAME_EXE}, 视为无效: {raw_found}")
            elif found:
                print("用户未确认自动检测的路径, 回退到手动选择")
            found = None
        while found is None:
            file_path = askopenfilename(
                title=f"请选择边狱巴士主程序 ({GAME_EXE})",
                filetypes=[("边狱巴士主程序", GAME_EXE), ("可执行文件", "*.exe"),
                           ("所有文件", "*.*")])
            if not file_path:
                print("错误: 未选择游戏主程序, 退出启动器")
                os._exit(-1)
            found = resolve_game_dir(file_path) or None
            if found is None:
                print(f"错误: 选择的路径下没有 {GAME_EXE}: {file_path}")
                messagebox.showerror(
                    "路径无效",
                    f"选择的目录下没有 {GAME_EXE}:\n{file_path}\n\n"
                    f"请重新选择游戏主程序, 或点取消退出启动器。",
                    parent=self.root)
        if found:
            self.settings_manager.set_setting("game_path", found)
            self.settings_manager.save_settings()
            settings_page = self.page_loader.get_page('settings')  # type: ignore
            if settings_page:
                settings_page.refresh_all_displays()
            print(f"游戏路径已保存: {found}")

    def check_settings(self, skip_auto_download=False, interactive=True):
        """检查设置"""
        # 游戏路径 (没有就定位 Steam / 让用户选; Web 模式只推给前端, 不静默写入)
        self.ensure_game_path(interactive=interactive)

        mems: dict = self.settings_manager.get_setting('mems')  # type: ignore
        has_notify = mems.get('version_notify_flag')
        from functions.update.version_utils import check_version_update
        from functions.web_update.sql_manager import notify_new_version
        
        has_update, latest_info, name, current_version = check_version_update(self.root)
        if has_update:
            print(f"启动器的新版本已经发布: {name}")
        latest_info['version_name'] = name

        # 首次启动: 弹出一次版本信息窗口 (右上角带关闭按钮)
        # 有更新时 check_version_update 会弹出强制更新窗口 (每次启动都弹, 见 version_utils)
        if not has_notify:
            if current_version == "V0.8.4-LimbusCompany_Release":
                from tkinter.messagebox import showinfo
                from functions.base.sound_utils import play_sound
                play_sound("assets/voices/welcome_1.wav")
                showinfo("你知道吗？", "当前版本 V0.8.4 是一个特殊版本！\n前面忘了，后面忘了，总之\n0!!! 8!!! 4!!! 康破尼！！！")
            else:
                # print(f"当前版本 {latest_info['version_name']} 不是特殊版本")
                pass

            print('发现新版本，创建版本详细介绍窗口。')
            # print(f'参数: {name}, {has_update}, {latest_info}')
            notify_new_version(name, root=self.root, has_new_version=has_update, 
                            latest_info=latest_info, info='发现新版本' if has_update else '已是最新版本', must_show=True)
            mems['version_notify_flag'] = True
            self.settings_manager.set_setting('mems', mems)
        
        if not skip_auto_download and (len(sys.argv) > 1 or not os.path.exists(get_translation_dir())):
            from functions.pages.app.page_loader import download_and_launch
            Thread(target=download_and_launch).start()
        
        if not os.path.exists("assets/Font/Context/ChineseFont.ttf"):
            print("未找到字体文件 Font/Context/ChineseFont.ttf\n请尝试手动添加或者使用汉化更新修复")

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
