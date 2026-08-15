from functions.webFunc import *
from json import loads
from functions.base.settings_manager import get_settings_manager
from functions.base.web_config import get_webnote
from threading import Thread
from tkinter import messagebox
from functions.web_update.zeroasso_download import download_and_extract_gui

settings_manager = get_settings_manager()

def download_new_version(dow_root, download_files:list):
    import os,subprocess
    from time import sleep
    print("正在更新启动器版本...")
    os.makedirs(f"cache/new_version", exist_ok=True)
    
    download_gui = dow_root
    download_gui.root.deiconify()
    
    download_thread = Thread(target=download_and_extract_gui, args=(download_gui,f"cache/new_version", download_files, False))
    download_thread.start()
    
    while download_thread.is_alive():
        sleep(1)
    
    target_exe = os.path.abspath("cache/new_version/FaustLauncher/FaustLauncher.exe")
    if not os.path.exists(target_exe):
        print(f"更新下载失败，未找到新版本可执行文件: {target_exe}")
        download_gui.current_file_var.set("更新失败，请稍后重试")
        download_gui.root.after(3000, download_gui.root.destroy)
        return
    
    print("新版本下载完成，正在准备安装...")
    
    from functions.update.sync_setting import sync_settings
    sync_settings()
    print("设置项同步完成...")
    
    new_version_dir = os.path.abspath("cache/new_version/FaustLauncher")
    updater_vbs_path = os.path.join(new_version_dir, "updater.vbs")
    
    # 运行vbs更新器
    if os.path.exists(updater_vbs_path):
        print(f"正在启动更新器: {updater_vbs_path}")
        # 使用 wscript.exe 运行 vbs，避免依赖文件关联；close_fds=True 确保子进程独立于父进程
        subprocess.Popen(
            ['wscript.exe', updater_vbs_path],
            cwd=new_version_dir,
            close_fds=True
        )
    else:
        print(f"未找到更新器: {updater_vbs_path}，无法继续安装新版本。")
    
    os._exit(0)

def _start_update_download(root, latest_entry, version_name):
    """创建下载窗口并后台开始下载新版本 (须在 tkinter 主线程调用)"""
    from functions.web_update.zeroasso_download import DownloadGUI
    gui_dow = DownloadGUI(root, 'cache/', False, download_func=download_and_extract_gui)

    download_files = [{
        "url": latest_entry['url'],
        "name": f"FaustLauncher_{version_name} 安装包",
        "temp_filename": f"FaustLauncher_{version_name.replace('.','_')}.zip"
    }]

    Thread(target=download_new_version, args=(gui_dow, download_files)).start()


def _on_update_choice(root, latest_entry, version_name, action):
    """更新询问窗口关闭后的回调 (后台线程); 选择更新时回到主线程开始下载"""
    if action != 'update':
        print(f"[版本更新] 用户选择: {action or '未选择(窗口直接关闭或超时)'}")
        return
    if root is not None:
        try:
            root.after(0, _start_update_download, root, latest_entry, version_name)
            return
        except Exception:
            pass
    Thread(target=_start_update_download, args=(root, latest_entry, version_name)).start()


def check_version_update(root):

    current_version: str = settings_manager.get_setting("version_info") # type: ignore

    need_update = False
    version_note = Note(get_webnote('version_info')[0])
    version_note.fetch_note_info()
    version_info = version_note.note_content
    if not version_info.strip():
        print("获取版本信息失败 (webnote 不可用或未配置)")
        return need_update, {}, current_version
    version_info = loads(version_info) # type: ignore

    latest_release = (version_info.get('latest_release_version') or '').strip()
    if not latest_release:
        # 服务器侧尚未填写最新版本标记, 视为暂无更新
        print("云端版本信息未填写最新版本 (latest_release_version 为空), 跳过更新检查")
        return need_update, {}, current_version

    if latest_release != current_version:
        print(f"检测到启动器新版本: {latest_release}，当前版本: {current_version}")
        latest_entry = version_info['versions'][latest_release]
        # 正式版/测试版统一询问用户, 不再自动更新
        from functions.pages.notice.version_update_window import open_version_update_window
        ok = open_version_update_window(
            current_version,
            {'version_name': latest_release,
             'description': latest_entry.get('description', ''),
             'date': latest_entry.get('data') or latest_entry.get('date'),
             'bilibili_url': latest_entry.get('url', '')},
            info='版本更新', ask_update=True,
            on_result=lambda action: _on_update_choice(
                root, latest_entry, latest_release, action))
        if ok is None:
            # 窗口无法启动: 回退到普通询问框
            choice = messagebox.askyesno(
                "版本更新", f"检测到启动器新版本: {latest_release}\n当前版本: {current_version}\n是否更新？")
            if choice:
                _start_update_download(root, latest_entry, latest_release)
                need_update = True
    else:
        print(f"当前启动器版本 {current_version} 已是最新版本，无需更新。")
    
    return need_update, version_info['versions'][latest_release], latest_release