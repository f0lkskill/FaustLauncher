import winsound
from threading import Thread

def play_sound(file_path):
    Thread(target=thread_play_sound, args=(file_path,), daemon=True).start()

def thread_play_sound(file_path):
    """使用 winsound 播放 WAV 文件（仅限 Windows）"""
    try:
        winsound.PlaySound(file_path, winsound.SND_FILENAME)
        return True
    except Exception as e:
        print(f"播放失败: {e}")
        return False