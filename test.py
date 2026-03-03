from functions.fancy.dialog_colorful import process_dlg_text
from functions.base.settings_manager import get_settings_manager
from json import load,dump

settings_manager = get_settings_manager()
game_path:str = settings_manager.get_setting("game_path") # type: ignore
skill_text_gradient_rate:float = settings_manager.get_setting("skill_text_gradient_rate") # type: ignore

def get_personality_skill_files(path = "",head_str = "") -> list:
    """
    get_personality_skill_files
    
    :return: 技能文件对象列表
    :rtype: list[Any]
    """
    files = []

    for id in range(1,13):
        str_id = ""
        if id < 10:
            str_id = "0"+str(id)
        else:str_id = str(id)

        files.append(f"{path}{head_str}personality-{str_id}.json")

    return files

def skill_color_process():
    package_files = get_personality_skill_files(game_path + 'LimbusCompany_Data/lang/', "LLC_zh-CN/Skills_")
    config_files = get_personality_skill_files("config/skills_info/")

    sin_color = load(open("config/sin_color.json",'r',encoding='utf-8'))

    for pf in package_files:
        print(f"处理 {pf}\n {config_files[package_files.index(pf)]}")

        pf_file = open(pf,'r+',encoding='utf-8')
        cf_file = open(config_files[package_files.index(pf)],'r',encoding='utf-8')

        pf_c = load(pf_file)
        cf_c = load(cf_file)
        for skill_content in pf_c["dataList"]:
            for skill_info in cf_c:
                if skill_info['id'] == skill_content['id']:
                    # id 符合，开始渐变化处理。
                    for signal_skill in skill_content['levelList']:
                        print(f"{signal_skill['name']} 的罪孽类型为 {skill_info['type']}...")
                        process_str = f"<color={sin_color[skill_info['type']]}>{signal_skill['name']}</color>"
                        signal_skill['name'] = process_dlg_text(process_str, skill_text_gradient_rate)
                    break
        
        with open(pf, 'w', encoding='utf-8') as tar_file:
            dump(pf_c, tar_file, indent=2)

        pf_file.close()
        cf_file.close()

skill_color_process()