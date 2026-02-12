import json
import glob
from typing import Dict, Any
from functions.fancy.dialog_colorful import apply_color_gradient_custom
from functions.base.settings_manager import get_settings_manager

settings_manager = get_settings_manager()

def process_ego_json_files():
    """处理所有EGO技能JSON文件，对name和abName字段应用颜色渐变效果"""
    global settings_manager

    print("开始处理EGO技能JSON文件")
    
    # 定义JSON文件路径模式
    json_pattern = f"{settings_manager.get_setting('game_path')}/LimbusCompany_Data/Lang/LLC_zh-CN/Skills_Ego_Personality-*.json"
    
    # 获取所有匹配的JSON文件
    json_files = glob.glob(json_pattern)
    
    if not json_files:
        print("未找到匹配的JSON文件")
        return False
    
    print(f"找到 {len(json_files)} 个JSON文件")
    
    # 处理每个JSON文件
    for json_file in json_files:
        print(f"正在处理: {json_file}")
        success = process_single_json_file(json_file)
        if success:
            print(f"{json_file} 处理完成")
        else:
            print(f"{json_file} 处理失败")
    
    return True

def process_single_json_file(file_path: str) -> bool:
    """处理单个JSON文件"""
    try:
        # 读取JSON文件
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # 处理dataList中的每个字典
        if 'dataList' in data and isinstance(data['dataList'], list):
            for item in data['dataList']:
                process_ego_item(item)
            
            # 保存修改后的数据
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            return True
        else:
            print(f"文件 {file_path} 中没有找到dataList字段")
            return False
            
    except Exception as e:
        print(f"处理文件 {file_path} 时出错: {e}")
        return False

def process_ego_item(item: Dict[str, Any]):
    """处理单个EGO项目"""
    # 检查是否有levelList
    if 'levelList' not in item or not isinstance(item['levelList'], list):
        return
    
    # 处理每个level
    for level_data in item['levelList']:
        process_ego_level(level_data)

def process_ego_level(level_data: Dict[str, Any]):
    """处理单个技能等级数据"""
    # 检查desc字段是否包含"指定"
    desc_contains_specified = False
    if 'desc' in level_data and level_data['desc']:
        desc_contains_specified = '指定' in level_data['desc']
    
    # 处理name字段
    if 'name' in level_data and level_data['name']:
        level_data['name'] = process_text_field(
            level_data['name'], 
            desc_contains_specified
        )
    
    # 处理abName字段
    if 'abName' in level_data and level_data['abName']:
        level_data['abName'] = process_text_field(
            level_data['abName'], 
            desc_contains_specified
        )

def process_text_field(text: str, is_specified: bool) -> str:
    """处理文本字段，应用颜色渐变和格式化"""
    
    if is_specified:
        # 包含"指定"的情况：红色向白色渐变，添加粗体斜体和emoji
        # 应用颜色渐变：红色(#ff0000)向白色(#ffffff)渐变，渐变度0.5
        processed_text = apply_color_gradient_custom(f"⚠️{text}⚠️", "#ff0000", "#ffffff", 0.5)
        # 添加粗体和斜体标签
        processed_text = f"<b><i>{processed_text}</i></b>"
    else:
        # 不包含"指定"的情况：白色向亮灰色渐变
        # 亮灰色：#d3d3d3
        processed_text = text
        processed_text = f"<b><i>{processed_text}</i></b>"
    
    return processed_text

def main():
    """主函数"""
    print("=" * 50)
    print("EGO技能文本颜色渐变处理器")
    print("=" * 50)
    
    try:
        success = process_ego_json_files()
        if success:
            print("所有JSON文件处理完成")
        else:
            print("处理过程中出现错误")
        
        return success
        
    except Exception as e:
        print(f"处理失败: {e}")
        return False

if __name__ == "__main__":
    main()