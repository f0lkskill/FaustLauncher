from functions.webFunc import Note
from functions.dowloads.zeroasso_dow import download_and_extract_gui, DownloadGUI
from json import loads,dumps
from threading import Thread

note = Note("FaustLauncher.res_info")
note.fetch_note_info()

note_content = note.note_content

data:dict = loads(loads(note_content)[0]['content'])
local_data:dict = loads(open("resources/resource_info.json",'r',encoding='utf-8').read())

def update_resource(main_root, download_files:list, res:str):
    import shutil
    try:shutil.rmtree(f"resources/{res}")
    except:pass
    dowload_gui = DownloadGUI(main_root, 'resources/', False)
    download_thread = Thread(target=download_and_extract_gui, args=(dowload_gui,'resources/', download_files))
    download_thread.start()
    while download_thread.is_alive():
        pass
    local_data[res]['version_info'] = data[res]['version_info']

def check_resource_update(main_root):
    for res in data:
        if data[res]['version_info'] != local_data[res]['version_info']:
            print(f"需要更新云端资源 {res}，url: {data[res]['url']}")
            download_files = [{
                "url": data[res]['url'],
                "name": f"更新资源：{res}",
                "temp_filename": f"{res}.zip"
            }]

            update_resource(main_root, download_files, res)

        else:
            print(f"资源 {res} 已为最新，无需更新。")
        
        # 保存更新后的本地资源信息
        with open("resources/resource_info.json",'w',encoding='utf-8') as f:
            f.write(dumps(local_data, ensure_ascii=False, indent=4))
        

if __name__ == "__main__":
    import tkinter
    root = tkinter.Tk()
    check_resource_update(root)
    root.mainloop()