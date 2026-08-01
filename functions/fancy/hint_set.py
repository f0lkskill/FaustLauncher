import os
import random
from functions.base.common.json_io import read_json, write_json

def simple_replace(battlehint_path:str):
    """简单版本，直接替换BattleHint.json中的内容"""

    dir_path = os.path.dirname(battlehint_path)
    ui_file_path = os.path.join(dir_path, "LoginUIText.json")
    ui_data = read_json(ui_file_path)
    for k in ui_data["dataList"]:
        if k['id'] == 'loginui_loading_battlehint':
            k['content'] = '你知道吗？'
    write_json(ui_file_path, ui_data, indent=4)

    # 文件路径
    loadingtext_path = r"config\loadingText.json"
    
    # 读取loadingText.json
    loading_data = read_json(loadingtext_path)
    
    loading_texts = loading_data["loadingTexts"]
    
    # 读取BattleHint.json
    battlehint_data = read_json(battlehint_path)
    
    data_list = battlehint_data["dataList"]
    
    # 随机选择要替换的条目（替换1/3的条目）
    num_replacements = max(1, len(data_list))
    indices_to_replace = random.sample(range(len(data_list)), num_replacements)
    
    # 随机选择替换文本
    replacement_texts = random.sample(loading_texts, num_replacements)
    
    # 替换内容
    for i, idx in enumerate(indices_to_replace):
        data_list[idx]["content"] = replacement_texts[i]
    
    # 保存修改后的文件
    write_json(battlehint_path, battlehint_data, indent=2)
    
    print(f"成功替换了 {num_replacements} 个 Tip 的内容！")