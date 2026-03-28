from functions.fancy.dialog_colorful import process_dlg_text
from functions.base.settings_manager import get_settings_manager
from json import load,dump

settings_manager = get_settings_manager()
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

def skill_color_process(gameLang: str):
    import os
    package_files = get_personality_skill_files(gameLang, "LLC_zh-CN/Skills_")
    config_files = get_personality_skill_files("resources/siner_skill_info/")

    try:
        sin_color = load(open("resources/siner_skill_info/sin_color.json",'r',encoding='utf-8'))
    except Exception as e:
        print(f"加载 sin_color.json 失败: {e}")
        return

    for pf in package_files:
        # print(f"技能渐变色处理 {pf}")
        
        # 检查文件是否存在
        if not os.path.exists(pf):
            print(f"文件不存在: {pf}")
            continue
            
        # 检查配置文件是否存在
        cf_path = config_files[package_files.index(pf)]
        if not os.path.exists(cf_path):
            print(f"配置文件不存在: {cf_path}")
            continue

        try:
            with open(pf,'r',encoding='utf-8') as f:
                pf_c = load(f)

            with open(cf_path,'r',encoding='utf-8') as f:
                cf_c = load(f)

            for skill_content in pf_c["dataList"]:
                # print(f"处理技能 {skill_content['id']}")
                success = False

                for skill_info in cf_c:
                    if skill_info['id'] == skill_content['id']:
                        # id 符合，开始渐变化处理。
                        # print(f"技能 {skill_info['id']} 符合，正在开始处理...")
                        for signal_skill in skill_content['levelList']:
                            # print(f"{signal_skill['name']} 的罪孽类型为 {skill_info['type']}...")
                            process_str = f"<color={sin_color[skill_info['type']]}>{signal_skill['name']}</color>"
                            signal_skill['name'] = process_dlg_text(process_str, skill_text_gradient_rate)
                            success = True
                        break
                    
                # 缺少对应的 config 信息，请求用户输入并写入对应的文件
                # if not success:
                #     print(f"技能 {skill_content['levelList'][0]['name']} 缺少对应的 config 信息，请求用户输入...")
                #     skill_info = {
                #         "id": skill_content['id'],
                #         "type": input(f"请输入技能 {skill_content['id']} 的罪孽类型："),
                #         "desc": input(f"请输入技能 {skill_content['id']} 的描述：")
                #     }
                #     cf_c.append(skill_info)

                with open(pf, 'w', encoding='utf-8') as tar_file:
                    dump(pf_c, tar_file, indent=2, ensure_ascii=False)
                with open(cf_path, 'w', encoding='utf-8') as tar_file:
                    dump(cf_c, tar_file, indent=2, ensure_ascii=False)

        except Exception as e:
            print(f"处理文件 {pf} 时出错: {e}")