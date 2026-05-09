from functions.webFunc import Note
from functions.dowloads.zeroasso_dow import download_and_extract_gui
from json import loads,dumps
from threading import Thread

note = Note("FaustLauncher.res_info")
note.fetch_note_info()

note_content = note.note_content
data:dict = loads(loads(note_content)[0]['content'])

# 不存在文件时，创建空字典
try:
    with open("resources/resource_info.json",'w',encoding='utf-8') as f:
        f.write(dumps({}, ensure_ascii=False, indent=4))
except:pass

local_data_str = open("resources/resource_info.json",'r',encoding='utf-8').read()
if local_data_str.strip() == "":
    local_data:dict = {}
else:
    local_data:dict = loads(local_data_str)

def update_resource(dow_root, dowload_files:list, res:str, auto_close:bool = True):
    import shutil,os
    from time import sleep
    try:
        shutil.rmtree(f"resources/{res}")
    except:pass
    os.makedirs(f"resources/{res}", exist_ok=True)
    dowload_gui = dow_root
    download_thread = Thread(target=download_and_extract_gui, args=(dowload_gui,f"resources/{res}", dowload_files, False))
    download_thread.start()
    while download_thread.is_alive():
        sleep(1)
        # print(f"下载资源 {res} 正在进行中...")
    local_data[res]['version_info'] = data[res]['version_info']
    if auto_close:
        dowload_gui.is_dowloading = False

def check_resource_update(dow_root):

    thread_count = 0
    dowload_files = []
    up_list = []

    for res in data:
        if local_data.get(res) is None:
            local_data[res] = data[res].copy()
            local_data[res]['version_info'] = "None"
            del local_data[res]['url']

    for res in data:
        # print(f"检查资源 {res}，云端版本: {data[res]['version_info']}，本地版本: {local_data[res]['version_info']}")
        if data[res]['version_info'] != local_data[res]['version_info']:
            up_list.append(res)

    for res in up_list:
        if data[res]['version_info'] != local_data[res]['version_info']:
            print(f"需要更新云端资源 {res}，url: {data[res]['url']}")
            dowload_files = [{
                "url": data[res]['url'],
                "name": local_data[res]['name'],
                "temp_filename": f"{res}.zip"
            }]
            thread_count += 1
            auto_close = res == up_list[-1]
            update_resource(dow_root, dowload_files, res, auto_close)
        else:
            print(f"资源 {res} 已为最新，无需更新。")

    # 保存更新后的本地资源信息
    with open("resources/resource_info.json",'w',encoding='utf-8') as f:
        f.write(dumps(local_data, ensure_ascii=False, indent=4))

    if thread_count == 0:
        print("所有资源均已最新。无需更新。")
        dow_root.is_dowloading = False

if __name__ == "__main__":
    import tkinter
    root = tkinter.Tk()
    check_resource_update(root)
    root.mainloop()