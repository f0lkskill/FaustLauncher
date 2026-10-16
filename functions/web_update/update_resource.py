from functions.webFunc import Note
from functions.base.web_config import get_webnote
from functions.web_update.zeroasso_download import download_and_extract_gui, DownloadGUI
from json import loads,dumps
from threading import Thread

note = Note("res_info", get_webnote('res_info')[0])
note.fetch_note_info()

note_content = note.note_content
data:dict = loads(note_content) if note_content.strip() else {}

download_gui:DownloadGUI = None # type: ignore

try:
    import os
    if not os.path.exists("resources/resource_info.json"):
        with open("resources/resource_info.json",'w',encoding='utf-8') as f:
            f.write(dumps({}, ensure_ascii=False, indent=4))
except:pass

local_data_str = open("resources/resource_info.json",'r',encoding='utf-8').read()
if local_data_str.strip() == "":
    local_data:dict = {}
else:
    local_data:dict = loads(local_data_str)

def _is_empty_dir(path):
    import os
    try:
        return os.path.isdir(path) and not any(os.scandir(path))
    except Exception:
        return False

def update_resource(dow_root:DownloadGUI, download_files:list, res:str, auto_close:bool = True):
    global download_gui
    
    import shutil,os
    from time import sleep
    os.makedirs(f"resources/{res}", exist_ok=True)
    success = False
    for attempt in range(1, 4):
        try:
            shutil.rmtree(f"resources/{res}")
        except:pass
        os.makedirs(f"resources/{res}", exist_ok=True)
        download_gui = dow_root
        download_thread = Thread(target=download_and_extract_gui, args=(download_gui,f"resources/{res}", download_files, False))
        download_thread.start()
        while download_thread.is_alive():
            sleep(1)
        if not _is_empty_dir(f"resources/{res}"):
            success = True
            break
        print(f"云端资源 {res} 下载后为空文件夹 (第 {attempt} 次), 重新尝试...")
    if success:
        local_data[res]['version_info'] = data[res]['version_info']
    else:
        print(f"⚠ 云端资源 {res} 多次下载后仍为空文件夹, 保持旧版本, 下次启动将再次检查")
    if auto_close:
        download_gui.is_downloading = False

def check_resource_update(dow_root):
    global download_gui
    
    thread_count = 0
    download_files = []
    up_list = []

    for res in data:
        if local_data.get(res) is None:
            local_data[res] = data[res].copy()
            local_data[res]['version_info'] = "None"
            del local_data[res]['url']

    for res in data:
        up_list.append(res)
        
    for res in up_list:
        if data[res]['version_info'] != local_data[res]['version_info']:
            print(f"需要更新云端资源 {res}，url: {data[res]['url']}")
            download_files = [{
                "url": data[res]['url'],
                "name": local_data[res]['name'],
                "temp_filename": f"{res}.zip"
            }]
            thread_count += 1
            auto_close = res == up_list[-1]
            update_resource(dow_root, download_files, res, auto_close)
        else:
            print(f"资源 {res} 已为最新，无需更新。")
    
    if download_gui is not None:
        download_gui.is_downloading = False

    with open("resources/resource_info.json",'w',encoding='utf-8') as f:
        f.write(dumps(local_data, ensure_ascii=False, indent=4))

    if thread_count == 0:
        print("所有资源均已最新。无需更新。")
        dow_root.is_downloading = False

if __name__ == "__main__":
    import tkinter
    root = tkinter.Tk()
    check_resource_update(root)
    root.mainloop()
