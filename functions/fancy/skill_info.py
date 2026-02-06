import json
import os


def handle_skill_info(skill_name:str) -> str:
    # 为原始的技能信息添加更好的样式
    
    # 逻辑性文本替换, 比如大于, 不少于等等.
    replace_dict = {
        ">": ["大于"],
        "<": ["小于"],
        "≥": ["不低于"],
        "≤": ["不高于"],
    }
    for key, value in replace_dict.items():
        for v in value:
            skill_name = skill_name.replace(v, key)

    # 数字颜色处理 - 根据数字大小进行渐变：数字越大越黄，越小越白
    import re
    # 匹配所有数字（包括整数、小数、负数）
    pattern = r'(-?\d+(?:\.\d+)?)'
    matches = list(re.finditer(pattern, skill_name))
    
    # 处理每个匹配的数字
    for match in reversed(matches):  # 反向处理避免位置偏移
        number_str = match.group(1)
        
        # 检查是否有百分号在后面
        # 获取 match 的结束位置
        Mcolor_value = 10
        end_pos = match.end()
        is_color = False

        # 检测数字是不是十六进制的颜色值, 检测其是否在 <> 中
        for i in range(end_pos, len(skill_name)):
            if skill_name[i] == '<':
                is_color = True
        
        if is_color:
            continue

        # 检查是否有百分号在后面
        if end_pos < len(skill_name) and skill_name[end_pos] == '%':
            # 如果有百分号，将其添加到数字后面
            Mcolor_value = 100

        try:
            number = float(number_str)
            
            # 根据数字大小计算颜色渐变
            # 数字越大越黄，越小越白
            # 假设数字范围在0-100之间，可以根据实际情况调整
            if number < 0:
                # 负数：使用红色
                color = "#FF0000"
            else:
                # 正数：根据大小渐变，从白色到黄色
                # 将数字映射到0-1的范围，假设最大值为100
                normalized_value = min(number / Mcolor_value, 1.0)
                
                # 计算RGB值：白色(255,255,255)到黄色(255,255,0)的渐变
                # 保持红色和绿色为255，蓝色从255渐变到0
                blue_value = int(255 * (1 - normalized_value))
                color = f"#{255:02x}{255:02x}{blue_value:02x}"
            
            # 为数字添加颜色标签
            colored_number = f"<color={color}>{number_str}</color>"
            skill_name = skill_name[:match.start()] + colored_number + skill_name[match.end():]
            
        except ValueError:
            # 如果无法转换为数字，跳过
            continue

    # 特殊关键词处理 - 下划线, 浅棕色 #7C5738
    light_brown = "#7C5738"
    keyword_color = "#FFFFFF"
    backup_color = "#81BBE8"
    heal_color = "#61DA61"
    special_keywords = {
        f"<u><color={light_brown}>$</color></u>": 
        ["自身","目标","行动槽","重复使用","基础威力","最终威力","硬币威力","拼点威力"],
        # f"<color={keyword_color}>$</color>":
        # ["层数","强度","层","级"],
        f"<u><color={backup_color}>$</color></u>":
        ["护盾","理智值"],
        f"<u><color={heal_color}>$</color></u>":
        ["体力"],
    }

    for keyword, keywords in special_keywords.items():
        for k in keywords:
            skill_name = skill_name.replace(k, keyword.replace("$", k))
    
    return skill_name

def handle_skill_strcture(skill_content:dict) -> dict: # type: ignore
    # 处理技能信息, 提取需要的信息, 并返回一个字典
    dataList = skill_content["dataList"]
    for skill in dataList:
        if not skill.get('levelList'):
            continue
        levelList = skill["levelList"]
        for level in levelList:
            level:dict
            # 技能的描述
            if level.get('desc'):
                level['desc'] = handle_skill_info(level['desc'])

            if not level.get('coinlist'):
                level['coinlist'] = [{"coindescs": [{"desc": "<i><color=#7C5738>无效果的硬币</color></i>"}]}]
                continue

            for coin in level['coinlist']:
                # 硬币的描述
                coin:dict
                if coin == {}:
                    coin = {"coindescs":[{"desc": "<i><color=#7C5738>无效果的硬币</color></i>"}]}
                else:
                    for coindesc in coin['coindescs']:
                        coindesc:dict
                        if coindesc.get('desc'):
                            coindesc['desc'] = handle_skill_info(coindesc['desc'])

    return skill_content
        
def get_skill_files(translate_pack_path) -> list:
    # 遍历json文件, 并选择名字为Skill***.json的文件, 获取其文件名字为列表
    import os
    skill_info_list = []
    for root, dirs, files in os.walk(translate_pack_path):
        for file in files:
            file:str
            if file.endswith('.json'):
                if file[:5] == "Skill":
                    skill_info_list.append(file)

    return skill_info_list

def handle_skill(translate_pack_path) -> None:
    file_list = get_skill_files(translate_pack_path)
    for file in file_list:
        file_path = os.path.join(translate_pack_path, file)
        with open(file_path, 'r', encoding='utf-8') as f:
            skill_content = json.load(f)

        print(f"正在处理技能描述: {file}")
        skill_content = handle_skill_strcture(skill_content)
        
        # 保存处理后的文件
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(skill_content, f, ensure_ascii=False, indent=4)

if __name__ == '__main__':
    handle_skill("workshop")