import glob
import os
import shutil
import time
from threading import Thread
from functions.base.settings_manager import get_settings_manager

from functions.modloader.modfolder import get_mod_folder

game_path = get_settings_manager().get_setting('game_path')

def sound_folder(): # type: ignore
    # 改为正确的音效mod路径
    return f"{game_path}LimbusCompany_Data/StreamingAssets/Assets/Sound/FMODBuilds/Desktop"

def sound_data_paths(): # type: ignore
    return map(os.path.normpath, glob.glob(sound_folder() + "/*.bank"))

def smallest_sound_file(): # type: ignore
    return min(sound_data_paths(), key=os.path.getsize)

def wait_for_validation():
    smallest = smallest_sound_file()
    os.remove(smallest)
    while not os.path.exists(smallest):
        time.sleep(0.1)

def sound_replace_thread(mod_folder: str):
    wait_for_validation()

    print("验证完成, 开始替换音效...")
    target_folder = sound_folder()
    for sound_file in glob.glob(f"{mod_folder}/*.bank"):
        print("正在替换 %s", sound_file)
        target = os.path.join(target_folder, os.path.basename(sound_file))
        os.replace(target, target + ".bak")
        shutil.copyfile(sound_file, target)

def restore_sound():
    target_folder = sound_folder()
    for sound_file in glob.glob(f"{target_folder}/*.bank.bak"):
        target = sound_file.replace(".bak", "")
        os.replace(sound_file, target)

def replace_sound(mod_folder: str):
    mod_zips_root_path = get_mod_folder()
    if any(file_name.endswith(".bank") for file_name in os.listdir(mod_zips_root_path)):
        Thread(target=sound_replace_thread, args=(mod_folder,)).start()
    else:
        print("没有找到 .bank 文件, 跳过音效替换步骤...")