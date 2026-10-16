import os
from functions.base.common.json_io import read_json, write_json

def handle_base_info(name:str) -> str:
    
    import re as _re
    placeholder_pattern = _re.compile(r'\{(\d+)(?::[^}]*)?\}')
    placeholders = []
    def _idx_to_chars(i: int) -> str:
        s = ""
        i += 1
        while i:
            i, r = divmod(i - 1, 26)
            s = chr(ord('a') + r) + s
        return s
    def _protect(m):
        placeholders.append(m.group(0))
        return f"\x00PLH_{_idx_to_chars(len(placeholders)-1)}_\x00"
    name = placeholder_pattern.sub(_protect, name)

    replace_dict = {
        "≥": ["不低于"],
        "≤": ["不高于"],
        ">": ["大于","高于"],
        "<": ["小于","低于"],
    }
    replace_pairs = sorted(((k, kw) for k, lst in replace_dict.items() for kw in lst),
                           key=lambda kv: len(kv[1]), reverse=True)
    for key, value in replace_pairs:
        name = name.replace(value, key)
    
    import re
    pattern = r'(-?\d+(?:\.\d+)?)'
    matches = list(re.finditer(pattern, name))
    
    for match in reversed(matches):
        number_str = match.group(1)
        
        max_color_value = 10
        end_pos = match.end()

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

        last_bracket = before.rfind('[')
        if last_bracket != -1 and before.find(']', last_bracket) == -1:
            continue

        if end_pos < len(name) and name[end_pos] == '%':
            max_color_value = 100

        try:
            number = float(number_str)
            
            if number < 0:
                color = "#FF0000"
            else:
                normalized_value = min(number / max_color_value, 1.0)
                
                blue_value = int(255 * (1 - normalized_value))
                color = f"#{255:02x}{255:02x}{blue_value:02x}"
            
            colored_number = f"<color={color}>{number_str}</color>"
            name = name[:match.start()] + colored_number + name[match.end():]
            
        except ValueError:
            continue

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
        f"<color={deep_brown}><u>$</u></color>": 
        ["自身","目标","行动槽","重复使用","基础威力","最终威力","拼点威力","混乱阈值","陷入混乱","混乱","回合结束","首个波次","首个回合","回合","波次","结束","首个","恐慌类型"],
        f"<color={backup_color}><u>$</u></color>":
        ["护盾","理智值"],
        f"<color={heal_color}><u>$</u></color>":
        ["体力"],
        f"<color={light_brown}><u>$</u></color>":
        ["敌方单位", "友方单位", "常驻效果", "不稳定E.G.O状态", "战斗开始", "攻击者"],
        f"<color={speed_color}><u>$</u></color>":
        ["速度值"],
        f"<color={cannot_color}><u>$</u></color>":
        ["无法使用", "无法解除", "无法进入", "无法生效", "无法", "解除"],
        f"<color={use_color}><u>$</u></color>":
        ["正面命中", "反面命中", "命中", "正面", "反面"],
        f"<color={coin_color}><u>$</u></color>":
        ["加算硬币","减算硬币","硬币威力","本硬币","硬币","减算","加算"],
    }

    for keyword, keywords in special_keywords.items():
        for k in keywords:
            name = name.replace(k, keyword.replace("$", k))
    
    for i, ph in enumerate(placeholders):
        name = name.replace(f"\x00PLH_{_idx_to_chars(i)}_\x00", ph)

    return name

def handle_skill_structure(skill_content:dict) -> dict: # type: ignore
    dataList = skill_content["dataList"]
    for skill in dataList:
        if not skill.get('levelList'):
            continue
        levelList = skill["levelList"]
        for level in levelList:
            level:dict
            if level.get('desc'):
                level['desc'] = handle_base_info(level['desc'])

            if not level.get('coinlist'):
                level['coinlist'] = [{"coindescs": [{"desc": "<i><color=#7C5738>无效果的硬币</color></i>"}]}]
                continue

            for coin in level['coinlist']:
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
            pass
    
    return passive_content

def _shape_problem(content):
    if not isinstance(content, dict):
        return "顶层不是对象(%s)" % type(content).__name__
    data_list = content.get("dataList")
    if data_list is None:
        keys = list(content)[:3]
        return "没有 dataList 键(%s)" % ("空对象 {}" if not keys else "keys=%s" % keys)
    if not isinstance(data_list, list):
        return "dataList 不是数组(%s)" % type(data_list).__name__
    return None

def get_skill_files(translate_pack_path) -> list:
    skill_info_list = []
    for root, dirs, files in os.walk(translate_pack_path):
        for file in files:
            file:str
            if file.endswith('.json'):
                if file[:5] == "Skill":
                    skill_info_list.append(os.path.join(root, file))

    return skill_info_list

def handle_base(translate_pack_path, func_file, func_structure, label="美化") -> None:
    file_list = func_file(translate_pack_path)
    done = skipped = failed = 0
    for file_path in file_list:
        name = os.path.basename(file_path)
        try:
            content = read_json(file_path)
            why = _shape_problem(content)
            if why:
                skipped += 1
                print(f"  [Cosmetic/{label}] 跳过 {name}: {why}")
                continue
            write_json(file_path, func_structure(content), indent=4)
            done += 1
        except Exception as e:
            failed += 1
            print(f"  [Cosmetic/{label}] {name} 处理失败: {type(e).__name__}: {e}")
    print(f"  [Cosmetic/{label}] 完成 {done} 个, 跳过 {skipped} 个(空文件/结构不符), 异常 {failed} 个")

def get_passive_files(translate_pack_path) -> list:
    passive_info_list = []
    for root, dirs, files in os.walk(translate_pack_path):
        for file in files:
            file:str
            if file.endswith('.json'):
                if file[:8] == "Passives":
                    passive_info_list.append(os.path.join(root, file))

    return passive_info_list

def get_EGOgift_files(translate_pack_path) -> list:
    EGOgift_info_list = []
    for root, dirs, files in os.walk(translate_pack_path):
        for file in files:
            file:str
            if file.endswith('.json'):
                if file[:7] == "EGOgift":
                    EGOgift_info_list.append(os.path.join(root, file))

    return EGOgift_info_list

def get_buff_files(translate_pack_path) -> list:
    buff_info_list = []
    for root, dirs, files in os.walk(translate_pack_path):
        for file in files:
            file:str
            if file.endswith('.json'):
                if file[:4] == "Bufs":
                    buff_info_list.append(os.path.join(root, file))

    return buff_info_list

def handle_skill(translate_pack_path) -> None:
    handle_base(translate_pack_path, get_skill_files, handle_skill_structure, "技能描述")

def handle_passive(translate_pack_path) -> None:
    handle_base(translate_pack_path, get_passive_files, handle_passive_structure, "被动描述")

def handle_EGOgift(translate_pack_path) -> None:
    handle_base(translate_pack_path, get_EGOgift_files, handle_passive_structure, "EGO饰品")

def handle_buff(translate_pack_path) -> None:
    handle_base(translate_pack_path, get_buff_files, handle_passive_structure, "Buff效果")

def total_handle(translate_pack_path) -> None:
    handle_skill(translate_pack_path)
    handle_passive(translate_pack_path)

if __name__ == '__main__':
    total_handle("../../lang")
