"""achievement 子模块：<sound>（具体职责见函数文档）。"""


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
    """内部解析wav。"""
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
    """play成就音效相关处理。"""
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
        ctypes.windll.winmm.PlaySoundW(wav, None, _SND_FILENAME | _SND_ASYNC | _SND_NODEFAULT)
        return True
    except Exception:
        return False
