"""成就解锁音效播放。

- 播放 assets/voices/achievement.wav (存在时)
- 线程安全, 异步 (SND_ASYNC)
- 防刷屏: 同一批连续解锁只播一次 (400ms 内去重)
"""

import os
import time
import threading

_WAV_PATH = None
_last_play: dict = {"t": 0.0}
_lock = threading.Lock()

_SND_ASYNC = 0x0001
_SND_FILENAME = 0x00020000
_SND_NODEFAULT = 0x0002


def _resolve_wav() -> str | None:
    """定位音效文件 assets/voices/achievement.wav。"""
    global _WAV_PATH
    if _WAV_PATH:
        return _WAV_PATH
    base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    cand = os.path.join(base, "assets", "voices", "achievement.wav")
    if os.path.exists(cand):
        _WAV_PATH = cand
        return cand
    return None


def play_achievement_sound() -> bool:
    """播放成就解锁音效 (异步, 400ms 去重)。

    返回:
        是否实际触发了播放
    """
    wav = _resolve_wav()
    if not wav:
        return False
    now = time.time()
    with _lock:
        if now - _last_play["t"] < 0.4:
            return False
        _last_play["t"] = now

    try:
        import ctypes
        # PlaySoundW(path, None, SND_FILENAME|SND_ASYNC|SND_NODEFAULT)
        ctypes.windll.winmm.PlaySoundW(wav, None, _SND_FILENAME | _SND_ASYNC | _SND_NODEFAULT)
        return True
    except Exception:
        return False
