def download_bubble_files(config_path: str = "") -> bool:
    """从数据库下载JSON文件到游戏目录"""
    # 加载游戏路径配置
    game_path = config_path
    
    if not game_path:
        print("未配置游戏路径，请在config/settings.json中设置game_path")
        return False
    
    import shutil, glob
    bubble_mod_files = glob.glob(f"resources/bubble_speech/*.json")
    try:
        for f in bubble_mod_files:
            print(f"处理气泡mod文件: {f}")
            shutil.copy(f, game_path + '/LLC_zh-CN/')
    except:pass
    return True

def main(config_path: str = ""):
    """命令行入口点"""
    print("=" * 50)
    print("Bubble 气泡文本效用")
    print("=" * 50)
    
    success = download_bubble_files(config_path=config_path)
    
    if success:
        print("操作完成!")
    else:
        print("操作失败!")
        
if __name__ == "__main__":
    main()