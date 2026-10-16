import glob
from typing import Dict, Any
from functions.fancy.dialog_colorful import apply_color_gradient_custom
from functions.base.settings_manager import get_settings_manager
from functions.base.common.json_io import read_json, write_json

settings_manager = get_settings_manager()

def process_ego_json_files():
    global settings_manager
    from functions.web_update.translation_source import get_translation_dir_name

    base_path = f"{settings_manager.get_setting('game_path')}/LimbusCompany_Data/Lang/{get_translation_dir_name()}/"
    
    json_pattern = f"{base_path}Skills_Ego_Personality-*.json"
    
    json_files = glob.glob(json_pattern)

    json_files.append(f"{base_path}Skills_Ego.json")
    
    if not json_files:
        print("未找到匹配的JSON文件")
        return False
    
    print(f"找到 {len(json_files)} 个JSON文件, 开始处理...")
    
    for json_file in json_files:
        success = process_single_json_file(json_file)
        if success:
            pass
        else:
            print(f"{json_file} 处理失败")
    
    return True

def process_single_json_file(file_path: str) -> bool:
    try:
        data = read_json(file_path)
        
        if 'dataList' in data and isinstance(data['dataList'], list):
            for item in data['dataList']:
                process_ego_item(item)
            
            write_json(file_path, data, indent=2)
            
            return True
        else:
            print(f"文件 {file_path} 中没有找到dataList字段")
            return False
            
    except Exception as e:
        print(f"处理文件 {file_path} 时出错: {e}")
        return False

def process_ego_item(item: Dict[str, Any]):
    if 'levelList' not in item or not isinstance(item['levelList'], list):
        return
    
    for level_data in item['levelList']:
        process_ego_level(level_data)

def process_ego_level(level_data: Dict[str, Any]):
    desc_contains_specified = False
    if 'desc' in level_data and level_data['desc']:
        desc_contains_specified = '指定' in level_data['desc']
    
    if 'name' in level_data and level_data['name']:
        level_data['name'] = process_text_field(
            level_data['name'], 
            desc_contains_specified
        )
    
    if 'abName' in level_data and level_data['abName']:
        level_data['abName'] = process_text_field(
            level_data['abName'], 
            desc_contains_specified
        )

def process_text_field(text: str, is_specified: bool) -> str:
    
    if is_specified:
        processed_text = apply_color_gradient_custom(f"! {text} !", "#ff0000", "#ffffff", 0.5)
        processed_text = f"<b><i>{processed_text}</i></b>"
    else:
        processed_text = text
        processed_text = f"<b><i>{processed_text}</i></b>"
    
    return processed_text

def main():
    
    try:
        success = process_ego_json_files()
        if success:
            print("[Cosmetic] 所有EGO技能JSON文件处理完成")
        else:
            print("[Cosmetic] EGO技能JSON文件处理失败，处理过程中出现错误")
        
        return success
        
    except Exception as e:
        print(f"[Cosmetic] 处理失败: {e}")
        return False

if __name__ == "__main__":
    main()
