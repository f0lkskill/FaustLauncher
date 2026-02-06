from functions.dowloads.sql_manager import *

def download_bubble_files(config_path: str = "") -> bool:
    """从数据库下载JSON文件到游戏目录"""
    # 加载游戏路径配置
    game_path = config_path
    
    if not game_path:
        print("未配置游戏路径，请在config/settings.json中设置game_path")
        return False
    
    # 使用sql_manager中的下载功能
    return download_bubble_files_to_game(**db_config, game_path=game_path)

def upload_bubble_files():
    """上传temp目录中的JSON文件到数据库"""
    # 使用sql_manager中的上传功能
    return upload_bubble_files_from_temp(**db_config)

def main(config_path: str = ""):
    """命令行入口点"""
    print("=" * 50)
    print("Bubble 气泡文本下载")
    print("=" * 50)
    
    success = download_bubble_files(config_path=config_path)
    
    if success:
        print("操作完成!")
    else:
        print("操作失败!")
        
if __name__ == "__main__":
    main()