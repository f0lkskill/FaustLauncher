import os
import random
from functions.base.common.json_io import read_json, write_json

def simple_replace(battlehint_path:str):

    dir_path = os.path.dirname(battlehint_path)
    ui_file_path = os.path.join(dir_path, "LoginUIText.json")
    if os.path.isfile(ui_file_path):
        ui_data = read_json(ui_file_path)
        for k in (ui_data.get("dataList") or []):
            if k.get('id') == 'loginui_loading_battlehint':
                k['content'] = '你知道吗？'
        write_json(ui_file_path, ui_data, indent=4)

    loadingtext_path = r"config\loadingText.json"
    
    loading_data = read_json(loadingtext_path)
    
    loading_texts = loading_data.get("loadingTexts") or []
    
    battlehint_data = read_json(battlehint_path)
    
    data_list = battlehint_data.get("dataList") or []
    if not data_list or not loading_texts:
        print("  [Cosmetic] 跳过战斗提示替换: BattleHint/loadingText 为空或结构不符")
        return
    
    num_replacements = min(max(1, len(data_list)), len(loading_texts))
    indices_to_replace = random.sample(range(len(data_list)), num_replacements)
    
    replacement_texts = random.sample(loading_texts, num_replacements)
    
    for i, idx in enumerate(indices_to_replace):
        data_list[idx]["content"] = replacement_texts[i]
    
    write_json(battlehint_path, battlehint_data, indent=2)
    
    print(f"[Cosmetic] 成功替换了 {num_replacements} 个 Tip 的内容！")
