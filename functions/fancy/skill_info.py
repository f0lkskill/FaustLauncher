import os
from functions.base.common.json_io import read_json, write_json


def handle_base_info(name:str) -> str:
    # 为原始的技能信息添加更好的样式
    
    # 逻辑性文本替换, 比如大于, 不少于等等.
    replace_dict = {
        "≥": ["不低于"],
        "≤": ["不高于"],
        ">": ["大于","高于"],
        "<": ["小于","低于"],
    }
    # 按关键词长度降序替换, 避免 "不低于" 先被 "低于" 替换成 "不<"
    replace_pairs = sorted(((k, kw) for k, lst in replace_dict.items() for kw in lst),
                           key=lambda kv: len(kv[1]), reverse=True)
    for key, value in replace_pairs:
        name = name.replace(value, key)
    
    # 数字颜色处理 - 根据数字大小进行渐变：数字越大越黄，越小越白
    import re
    # 匹配所有数字（包括整数、小数、负数）
    pattern = r'(-?\d+(?:\.\d+)?)'
    matches = list(re.finditer(pattern, name))
    
    # 处理每个匹配的数字
    for match in reversed(matches):  # 反向处理避免位置偏移
        number_str = match.group(1)
        
        # 检查是否有百分号在后面
        # 获取 match 的结束位置
        max_color_value = 10
        end_pos = match.end()

        # 检测数字是否位于 <...> 标签内部 (如 <color=#a16a3b> 的颜色值、<sprite=3> 参数等),
        # 标签属性内的数字不处理。
        # 注意两点:
        # 1) 不能用"数字后面存在 <"判断: 描述后续的 <i>/<color> 标签会让数字全部漏色;
        # 2) 逻辑替换产生的裸 < (如 "低于"→"<") 不是标签, 不能参与配对判断
        before = name[:match.start()]
        inside_tag = False
        scan = before
        while scan:
            lt = scan.rfind('<')
            if lt == -1:
                break
            nxt = lt + 1
            is_tag = False
            if nxt < len(before):
                ch = before[nxt]
                if ch == '/':
                    is_tag = nxt + 1 < len(before) and before[nxt + 1].isascii() and before[nxt + 1].isalpha()
                else:
                    is_tag = ch.isascii() and ch.isalpha()
            if is_tag:
                if before.find('>', lt) == -1:
                    inside_tag = True
                break
            scan = scan[:lt]
        if inside_tag:
            continue

        # 检查是否有百分号在后面
        if end_pos < len(name) and name[end_pos] == '%':
            # 如果有百分号，将其添加到数字后面
            max_color_value = 100

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
                normalized_value = min(number / max_color_value, 1.0)
                
                # 计算RGB值：白色(255,255,255)到黄色(255,255,0)的渐变
                # 保持红色和绿色为255，蓝色从255渐变到0
                blue_value = int(255 * (1 - normalized_value))
                color = f"#{255:02x}{255:02x}{blue_value:02x}"
            
            # 为数字添加颜色标签
            colored_number = f"<color={color}>{number_str}</color>"
            name = name[:match.start()] + colored_number + name[match.end():]
            
        except ValueError:
            # 如果无法转换为数字，跳过
            continue

    # 特殊关键词处理 - 下划线, 浅棕色 #7C5738
    deep_brown = "#7C5738"
    light_brown = "#936E46"
    keyword_color = "#FFFFFF"
    backup_color = "#81BBE8"
    heal_color = "#61DA61"
    speed_color = "#FFA500"
    cannot_color = "#FF2828"
    use_color = "#CAFE98"
    damage_color = "#FF5C5C"
    coin_color = "#d1a261"

    special_keywords = {
        f"<u><color={deep_brown}>$</color></u>": 
        ["自身","目标","行动槽","重复使用","基础威力","最终威力","硬币威力","拼点威力","混乱阈值","陷入混乱","混乱","回合结束","首个波次","首个回合","回合","波次","结束","首个","恐慌类型"],
        # f"<u>$</u>":
        # ["层数","强度","层","级"],
        f"<u><color={backup_color}>$</color></u>":
        ["护盾","理智值"],
        f"<u><color={heal_color}>$</color></u>":
        ["体力"],
        f"<u><color={light_brown}>$</color></u>":
        ["敌方单位", "友方单位", "常驻效果", "不稳定E.G.O状态", "战斗开始", "攻击者"],
        f"<u><color={speed_color}>$</color></u>":
        ["速度值"],
        f"<u><color={cannot_color}>$</color></u>":
        ["无法使用", "无法解除", "无法进入", "无法生效", "无法", "解除"],
        f"<u><color={use_color}>$</color></u>":
        ["正面命中", "反面命中", "命中", "正面", "反面"],
        f"<u><color={damage_color}>$</color></u>":
        ["伤害"],
        f"<u><color={coin_color}>$</color></u>":
        ["加算硬币","减算硬币","本硬币","硬币", "减算","加算"],
    }

    for keyword, keywords in special_keywords.items():
        for k in keywords:
            name = name.replace(k, keyword.replace("$", k))
    
    return name

def handle_skill_structure(skill_content:dict) -> dict: # type: ignore
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
                level['desc'] = handle_base_info(level['desc'])

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
                            coindesc['desc'] = handle_base_info(coindesc['desc'])

    return skill_content

def handle_passive_structure(passive_content:dict) -> dict:
    dataList = passive_content["dataList"]
    for data in dataList:
        try:
            data['desc'] = handle_base_info(data['desc'])
        except:
            # print(f"处理data美化时出错: {data}")
            pass
    
    return passive_content

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

def handle_base(translate_pack_path, func_file, func_structure) -> None:
    file_list = func_file(translate_pack_path)
    for file in file_list:
        file_path = os.path.join(translate_pack_path, file)
        skill_content = read_json(file_path)

        # print(f"正在处理被动描述: {file}")
        skill_content = func_structure(skill_content)
        
        # 保存处理后的文件
        write_json(file_path, skill_content, indent=4)

def get_passive_files(translate_pack_path) -> list:
    # 遍历json文件, 并选择名字为Passive***.json的文件, 获取其文件名字为列表
    import os
    passive_info_list = []
    for root, dirs, files in os.walk(translate_pack_path):
        for file in files:
            file:str
            if file.endswith('.json'):
                if file[:8] == "Passives":
                    passive_info_list.append(file)

    return passive_info_list

def get_EGOgift_files(translate_pack_path) -> list:
    # 遍历json文件, 并选择名字为EGOgift***.json的文件, 获取其文件名字为列表
    import os
    EGOgift_info_list = []
    for root, dirs, files in os.walk(translate_pack_path):
        for file in files:
            file:str
            if file.endswith('.json'):
                if file[:7] == "EGOgift":
                    EGOgift_info_list.append(file)

    return EGOgift_info_list

def get_buff_files(translate_pack_path) -> list:
    # 遍历json文件, 并选择名字为Bufs***.json的文件, 获取其文件名字为列表
    import os
    buff_info_list = []
    for root, dirs, files in os.walk(translate_pack_path):
        for file in files:
            file:str
            if file.endswith('.json'):
                if file[:4] == "Bufs":
                    buff_info_list.append(file)

    return buff_info_list

def handle_skill(translate_pack_path) -> None:
    handle_base(translate_pack_path, get_skill_files, handle_skill_structure)

def handle_passive(translate_pack_path) -> None:
    handle_base(translate_pack_path, get_passive_files, handle_passive_structure)

def handle_EGOgift(translate_pack_path) -> None:
    handle_base(translate_pack_path, get_EGOgift_files, handle_passive_structure)

def handle_buff(translate_pack_path) -> None:
    handle_base(translate_pack_path, get_buff_files, handle_passive_structure)

def total_handle(translate_pack_path) -> None:
    handle_skill(translate_pack_path)
    handle_passive(translate_pack_path)

if __name__ == '__main__':
    total_handle("../../lang")