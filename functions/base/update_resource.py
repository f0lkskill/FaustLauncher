from functions.webFunc import Note
from functions.dowloads.zeroasso_dow import download_and_extract_gui, DownloadGUI
from json import loads,dumps
from threading import Thread

note = Note("FaustLauncher.res_info")
note.fetch_note_info()

note_content = note.note_content

data:dict = loads(loads(note_content)[0]['content'])
local_data:dict = loads(open("resources/resource_info.json",'r',encoding='utf-8').read())

def update_resource(dow_root, download_files:list, res:str, auto_close:bool = True):
    import shutil
    from time import sleep
    try:shutil.rmtree(f"resources/{res}")
    except:pass
    dowload_gui = dow_root
    download_thread = Thread(target=download_and_extract_gui, args=(dowload_gui,'resources/', download_files, False))
    download_thread.start()
    while download_thread.is_alive():
        sleep(1)
        print(f"下载资源 {res} 正在进行中...")
    local_data[res]['version_info'] = data[res]['version_info']
    if auto_close:
        dowload_gui.is_downloading = False

def check_resource_update(dow_root):
    thread_count = 0
    download_files = []
    up_list = []

    for res in data:
        if data[res]['version_info'] != local_data[res]['version_info']:
            up_list.append(res)

    for res in data:

        if data[res]['version_info'] != local_data[res]['version_info']:
            print(f"需要更新云端资源 {res}，url: {data[res]['url']}")
            download_files = [{
                "url": data[res]['url'],
                "name": local_data[res]['name'],
                "temp_filename": f"{res}.zip"
            }]
            thread_count += 1
            auto_close = res == up_list[-1]
            print(f"是否自动关闭下载窗口: {auto_close}")
            update_resource(dow_root, download_files, res, auto_close)
        else:
            print(f"资源 {res} 已为最新，无需更新。")

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