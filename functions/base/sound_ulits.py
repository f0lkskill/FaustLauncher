import winsound
import os

# 全局变量，用于跟踪当前是否正在播放音频
_is_playing = False

def play_sound(file_path):
    """播放WAV音频文件（支持停止当前播放并播放新音频）"""
    global _is_playing
    
    # 如果文件不存在，直接返回
    if not os.path.exists(file_path):
        print(f"音频文件不存在: {file_path}")
        return False
    
    try:
        # 先停止当前正在播放的音频
        winsound.PlaySound(None, winsound.SND_FILENAME)
        
        # 使用异步模式播放新音频
        winsound.PlaySound(file_path, winsound.SND_FILENAME | winsound.SND_ASYNC)
        _is_playing = True
        return True
    except Exception as e:
        print(f"播放失败: {e}")
        _is_playing = False
        return False

def stop_sound():
    """停止当前正在播放的音频"""
    global _is_playing
    try:
        winsound.PlaySound(None, winsound.SND_FILENAME)
        _is_playing = False
        return True
    except Exception as e:
        print(f"停止播放失败: {e}")
        return False