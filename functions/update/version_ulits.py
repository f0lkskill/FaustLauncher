from functions.webFunc import *
from json import loads
from functions.base.settings_manager import get_settings_manager
from threading import Thread
from tkinter import messagebox
from functions.web_update.zeroasso_dow import download_and_extract_gui

settings_manager = get_settings_manager()

def download_new_version(dow_root, download_files:list):
    import os,subprocess
    from time import sleep
    print("正在更新启动器版本...")
    os.makedirs(f"cache/new_version", exist_ok=True)
    download_gui = dow_root
    download_thread = Thread(target=download_and_extract_gui, args=(download_gui,f"cache/new_version", download_files, False))
    download_thread.start()
    while download_thread.is_alive():
        sleep(1)


    print("新版本下载完成，正在准备安装...")
    
    # 同步两个版本的设置
    from functions.update.sync_setting import sync_settings
    sync_settings()
    print("设置项同步完成...")
    
    updater_exe_path = "updater.vbs"
    
    # 运行vbs更新器
    if os.path.exists(updater_exe_path):
        subprocess.Popen(['start', updater_exe_path], shell=True, cwd='cache/new_version/FaustLauncher')
    else:
        print("未找到更新器，无法继续安装新版本。")
    
    os._exit(0)

def check_version_update(root):

    current_version: str = settings_manager.get_setting("version_info") # type: ignore

    need_update = False
    version_note = Note('FaustLauncher.version_info')
    version_note.fetch_note_info()
    version_info = version_note.note_content

    version_info = loads(loads(version_info)[0]['content'])

    if version_info['latest_release_version'] != current_version:
        print(f"检测到启动器新版本: {version_info['latest_release_version']}，当前版本: {current_version}")
        if 'release' not in current_version:
            if not messagebox.askyesno("版本更新", f"检测到启动器新版本: {version_info['latest_release_version']}\n当前版本: {current_version}\n是否更新？"):
                return need_update, version_info['versions'][version_info['latest_release_version']], version_info['latest_release_version']
            
        from functions.web_update.zeroasso_dow import DownloadGUI
        gui_dow = DownloadGUI(root, 'cache/', False, download_func=download_and_extract_gui)

        download_files = [{
            "url": version_info['versions'][version_info['latest_release_version']]['url'],
            "name": f"FaustLauncher_{version_info['latest_release_version']} 安装包",
            "temp_filename": f"FaustLauncher_{version_info['latest_release_version'].replace('.','_')}.zip"
        }]
        Thread(target=download_new_version, args=(gui_dow, download_files)).start()
        need_update = True
    else:
        print(f"当前启动器版本 {current_version} 已是最新版本，无需更新。")
    
    return need_update, version_info['versions'][version_info['latest_release_version']], version_info['latest_release_version']