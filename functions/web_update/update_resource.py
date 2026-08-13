from functions.webFunc import Note
from functions.base.web_config import get_webnote
from functions.web_update.zeroasso_download import download_and_extract_gui, DownloadGUI
from json import loads,dumps
from threading import Thread

note = Note(get_webnote('res_info')[0])
note.fetch_note_info()

note_content = note.note_content
data:dict = loads(note_content) if note_content.strip() else {}

download_gui:DownloadGUI = None # type: ignore

# 不存在文件时，创建空字典
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

def update_resource(dow_root:DownloadGUI, download_files:list, res:str, auto_close:bool = True):
    global download_gui
    
    import shutil,os
    from time import sleep
    try:
        shutil.rmtree(f"resources/{res}")
    except:pass
    os.makedirs(f"resources/{res}", exist_ok=True)
    download_gui = dow_root
    download_thread = Thread(target=download_and_extract_gui, args=(download_gui,f"resources/{res}", download_files, False))
    download_thread.start()
    while download_thread.is_alive():
        sleep(1)
        # print(f"下载资源 {res} 正在进行中...")
    local_data[res]['version_info'] = data[res]['version_info']
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
        # print(f"检查资源 {res}，云端版本: {data[res]['version_info']}，本地版本: {local_data[res]['version_info']}")
        up_list.append(res)
        
    # print(up_list)

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
        # 关闭下载窗口
        download_gui.is_downloading = False

    # 保存更新后的本地资源信息
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