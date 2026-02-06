import json
import random

def simple_replace(battlehint_path:str):
    """简单版本，直接替换BattleHint.json中的内容"""
    
    # 文件路径
    loadingtext_path = r"config\loadingText.json"
    
    # 读取loadingText.json
    with open(loadingtext_path, 'r', encoding='utf-8') as f:
        loading_data = json.load(f)
    
    loading_texts = loading_data["loadingTexts"]
    
    # 读取BattleHint.json
    with open(battlehint_path, 'r', encoding='utf-8') as f:
        battlehint_data = json.load(f)
    
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
    with open(battlehint_path, 'w', encoding='utf-8') as f:
        json.dump(battlehint_data, f, ensure_ascii=False, indent=2)
    
    print(f"成功替换了 {num_replacements} 个 Tip 的内容！")