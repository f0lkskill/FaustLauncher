# 新版本采用蓝奏云云端更新，而不是数据库，所以本集成库现在为纯粹的文件操作。
# bubble_dow.py 更名为 bubble_transfer.py

def transfer_bubble_files(config_path: str = "") -> bool:
    """转移效用，覆盖气泡文件"""
    # 加载游戏路径配置
    game_path = config_path
    
    if not game_path:
        print("[美化] 未配置游戏路径，请在 config/settings.json 中设置 game_path")
        return False
    
    import shutil, glob, os
    bubble_mod_files = glob.glob(f"resources/bubble_speech/*.json")
    try:
        print(f"[美化] 目标汉化包路径: {game_path}")
        for f in bubble_mod_files:
            print(f"[美化] 转移气泡文本文件: {f}")
            shutil.copy(f, game_path)
    except Exception as e:
        print(f"[美化] 转移气泡文本文件时出错: {e}")
        return False
    return True

def main(config_path: str = ""):
    """命令行入口点"""
    
    success = transfer_bubble_files(config_path=config_path)
    
    if success:
        print("[美化] 气泡文件转移完成!")
    else:
        print("[美化] 气泡文件转移失败!")
        
if __name__ == "__main__":
    main()