import struct
import wave, time, os
import threading
import ctypes
import ctypes.wintypes

from functions.base.settings_manager import get_settings_manager
settings_manager = get_settings_manager()

# ========== winmm.dll 常量 ==========
WAVE_MAPPER = -1
CALLBACK_NULL = 0
MMSYSERR_NOERROR = 0
WAVE_FORMAT_PCM = 1
WHDR_DONE = 0x00000001

# ========== 全局状态 ==========
_winmm = None
_player = None
_player_lock = threading.Lock()


# ========== ctypes 数据结构 ==========
class WAVEFORMATEX(ctypes.Structure):
    _fields_ = [
        ('wFormatTag',      ctypes.wintypes.WORD),
        ('nChannels',       ctypes.wintypes.WORD),
        ('nSamplesPerSec',  ctypes.wintypes.DWORD),
        ('nAvgBytesPerSec', ctypes.wintypes.DWORD),
        ('nBlockAlign',     ctypes.wintypes.WORD),
        ('wBitsPerSample',  ctypes.wintypes.WORD),
        ('cbSize',          ctypes.wintypes.WORD),
    ]


class WAVEHDR(ctypes.Structure):
    pass
WAVEHDR._fields_ = [
    ('lpData',          ctypes.wintypes.LPSTR),
    ('dwBufferLength',  ctypes.wintypes.DWORD),
    ('dwBytesRecorded', ctypes.wintypes.DWORD),
    ('dwUser',          ctypes.wintypes.DWORD),
    ('dwFlags',         ctypes.wintypes.DWORD),
    ('dwLoops',         ctypes.wintypes.DWORD),
    ('lpNext',          ctypes.POINTER(WAVEHDR)),
    ('reserved',        ctypes.wintypes.DWORD),
]


def _get_winmm():
    """懒加载 winmm.dll 并声明参数类型（Windows 自带，无需额外安装）"""
    global _winmm
    if _winmm is None:
        try:
            w = ctypes.WinDLL('winmm')
            DWORD_PTR = ctypes.c_size_t
            w.waveOutOpen.argtypes = [
                ctypes.POINTER(ctypes.wintypes.HANDLE),  # LPHWAVEOUT
                ctypes.wintypes.UINT,                    # uDeviceID
                ctypes.POINTER(WAVEFORMATEX),            # LPWAVEFORMATEX
                DWORD_PTR,                               # dwCallback
                DWORD_PTR,                               # dwInstance
                DWORD_PTR,                               # fdwOpen
            ]
            w.waveOutOpen.restype = ctypes.wintypes.UINT
            for name in ('waveOutClose', 'waveOutReset',
                         'waveOutPrepareHeader', 'waveOutUnprepareHeader',
                         'waveOutWrite'):
                getattr(w, name).argtypes = [ctypes.wintypes.HANDLE,
                                             ctypes.POINTER(WAVEHDR),
                                             ctypes.wintypes.UINT]
                getattr(w, name).restype = ctypes.wintypes.UINT
            _winmm = w
        except Exception as e:
            print(f"加载 winmm.dll 失败: {e}")
    return _winmm


def _apply_volume_to_samples(raw_frames, volume, sampwidth):
    """PCM 样本层面按 volume 缩放 —— 不污染系统其他音频的音量。"""
    if volume >= 1.0 - 1e-6:
        return raw_frames
    if volume <= 0.0:
        return b"\x00" * len(raw_frames)

    if sampwidth == 2:
        # 16-bit 有符号短整型（little-endian）—— 最常见
        count = len(raw_frames) // 2
        samples = struct.unpack(f"<{count}h", raw_frames)
        scaled = [max(-32768, min(32767, int(s * volume))) for s in samples]
        return struct.pack(f"<{count}h", *scaled)
    if sampwidth == 1:
        # 8-bit 无符号（中心 128）
        samples = struct.unpack(f"<{len(raw_frames)}B", raw_frames)
        scaled = [max(0, min(255, int((s - 128) * volume) + 128)) for s in samples]
        return struct.pack(f"<{len(raw_frames)}B", *scaled)
    # 其他位宽（如 32-bit）：按字节缩放
    max_val = (1 << (sampwidth * 8 - 1)) - 1
    min_val = -max_val - 1
    result = bytearray(len(raw_frames))
    total = len(raw_frames) // sampwidth
    for i in range(total):
        off = i * sampwidth
        s = int.from_bytes(raw_frames[off:off + sampwidth], byteorder="little", signed=True)
        s = max(min_val, min(max_val, int(s * volume)))
        result[off:off + sampwidth] = s.to_bytes(sampwidth, byteorder="little", signed=True)
    return bytes(result)


# ========== 单例播放线程（设备复用，杜绝每点击一次开关设备的抖动/竞争）==========
class _SoundPlayer(threading.Thread):
    """串行播放器：
    - 只打开一次 waveOut 设备并复用，避免快速点击时设备忙/并发 Reset 造成
      无声、断断续续甚至崩溃；
    - 所有 winmm 调用都在本线程内完成，stop_sound 只发信号，不再跨线程碰设备；
    - 播放期间 hwout/buf/hdr 都挂在实例上，直到播完或被打断，防止 GC 提前回收。
    """

    MAX_AUDIO_BYTES = 8 * 1024 * 1024  # 上限 8MB，防止超长 WAV 占内存

    def __init__(self):
        super().__init__(daemon=True, name="sound-player")
        self._lock = threading.Lock()
        self._target = None              # (seq, file_path, volume) 最新播放任务
        self._wake = threading.Event()
        self._seq = 0
        self._is_playing = False
        # 以下 winmm 状态只在本线程内访问
        self._winmm = None
        self._hwout = ctypes.wintypes.HANDLE()
        self._opened = False
        self._wfx = None                 # 当前已打开的格式，用于对比
        self._buf = None
        self._hdr = None

    # ---------- 线程安全 API ----------
    def play(self, file_path, volume):
        with self._lock:
            self._seq += 1
            self._target = (self._seq, file_path, volume)
        self._wake.set()
        return True

    def stop(self):
        """请求停止当前播放（不跨线程碰设备，由播放线程自行处理）"""
        with self._lock:
            self._seq += 1
            self._target = None
        self._wake.set()

    def is_playing(self):
        return self._is_playing

    # ---------- 播放主循环 ----------
    def run(self):
        self._winmm = _get_winmm()
        if self._winmm is None:
            return
        while True:
            self._wake.wait()
            self._wake.clear()
            with self._lock:
                target = self._target
            if target is None:
                continue
            self._is_playing = True
            try:
                self._play_target(target)
            except Exception as e:
                print(f"播放异常: {e}")
            finally:
                self._is_playing = False

    def _play_target(self, target):
        seq, file_path, volume = target
        if not file_path or not os.path.exists(file_path):
            print(f"音频文件不存在: {file_path}")
            return

        try:
            with wave.open(file_path, "rb") as wf:
                nchannels = wf.getnchannels()
                sampwidth = wf.getsampwidth()
                framerate = wf.getframerate()
                nframes = wf.getnframes()
                raw = wf.readframes(nframes)
        except Exception as e:
            print(f"读取音频失败 {file_path}: {e}")
            return

        if not raw:
            return
        if len(raw) > self.MAX_AUDIO_BYTES:
            raw = raw[:self.MAX_AUDIO_BYTES]

        final_bytes = _apply_volume_to_samples(raw, volume, sampwidth)

        wfx = WAVEFORMATEX()
        wfx.wFormatTag = WAVE_FORMAT_PCM
        wfx.nChannels = nchannels
        wfx.nSamplesPerSec = framerate
        wfx.wBitsPerSample = sampwidth * 8
        wfx.nBlockAlign = nchannels * sampwidth
        wfx.nAvgBytesPerSec = framerate * wfx.nBlockAlign

        self._ensure_open(wfx)
        if not self._opened:
            return
        # 清掉上一段可能未播完的缓冲
        self._unprepare()

        self._buf = ctypes.create_string_buffer(final_bytes)
        self._hdr = WAVEHDR()
        self._hdr.lpData = ctypes.cast(self._buf, ctypes.wintypes.LPSTR)
        self._hdr.dwBufferLength = len(final_bytes)
        self._hdr.dwBytesRecorded = 0
        self._hdr.dwUser = 0
        self._hdr.dwFlags = 0
        self._hdr.dwLoops = 0

        ret = self._winmm.waveOutPrepareHeader(
            self._hwout, ctypes.byref(self._hdr), ctypes.sizeof(self._hdr))
        if ret != MMSYSERR_NOERROR:
            print(f"waveOutPrepareHeader 失败 (错误码={ret})")
            self._unprepare()
            return

        ret = self._winmm.waveOutWrite(
            self._hwout, ctypes.byref(self._hdr), ctypes.sizeof(self._hdr))
        if ret != MMSYSERR_NOERROR:
            print(f"waveOutWrite 失败 (错误码={ret})")
            self._unprepare()
            return

        # 轮询等待播放完成；若期间出现更新的任务/停止，则立即放弃当前缓冲
        total_sec = max(0.1, len(final_bytes) / max(1, wfx.nAvgBytesPerSec))
        deadline = time.time() + total_sec + 0.5
        while time.time() < deadline:
            with self._lock:
                current = self._target
            if current is None or current[0] != seq:
                break
            if self._hdr.dwFlags & WHDR_DONE:
                break
            time.sleep(0.005)
        self._unprepare()

    def _ensure_open(self, wfx):
        if self._opened and self._same_format(self._wfx, wfx):
            return
        self._close()
        ret = self._winmm.waveOutOpen(
            ctypes.byref(self._hwout),
            ctypes.wintypes.UINT(WAVE_MAPPER),
            ctypes.byref(wfx),
            ctypes.c_size_t(0),
            ctypes.c_size_t(0),
            ctypes.c_size_t(CALLBACK_NULL),
        )
        if ret != MMSYSERR_NOERROR:
            print(f"waveOutOpen 失败 (错误码={ret})")
            self._opened = False
            self._wfx = None
            return
        self._opened = True
        self._wfx = wfx

    def _same_format(self, a, b):
        if a is None or b is None:
            return False
        return (a.nChannels == b.nChannels
                and a.nSamplesPerSec == b.nSamplesPerSec
                and a.wBitsPerSample == b.wBitsPerSample)

    def _unprepare(self):
        """Reset + Unprepare + 释放缓冲引用（只在本线程调用）"""
        if not self._opened:
            return
        try:
            self._winmm.waveOutReset(self._hwout)
            if self._hdr is not None:
                self._winmm.waveOutUnprepareHeader(
                    self._hwout, ctypes.byref(self._hdr), ctypes.sizeof(self._hdr))
                self._hdr = None
            self._buf = None
        except Exception:
            pass

    def _close(self):
        if not self._opened:
            return
        try:
            self._winmm.waveOutReset(self._hwout)
            self._winmm.waveOutClose(self._hwout)
        except Exception:
            pass
        self._opened = False
        self._wfx = None
        self._hdr = None
        self._buf = None


def _get_player():
    global _player
    with _player_lock:
        if _player is None:
            p = _SoundPlayer()
            p.start()
            _player = p
    return _player


# ========== 对外 API ==========
def play_sound(file_path, sound_volume=None):
    """播放WAV音频文件（支持停止当前播放并播放新音频，支持音量控制 0.0 ~ 1.0）"""
    if sound_volume is None:
        # 注意：不能用 `or 0.5`，否则 0.0（静音）会被吞成 0.5
        sound_volume = settings_manager.get_setting('sound_volume')
    try:
        sound_volume = float(sound_volume)
    except (TypeError, ValueError):
        sound_volume = 0.5
    sound_volume = max(0.0, min(1.0, sound_volume))

    # 音量 0 时不用播放
    if sound_volume == 0.0:
        stop_sound()
        return True

    if not file_path or not os.path.exists(file_path):
        print(f"音频文件不存在: {file_path}")
        return False

    try:
        _get_player().play(file_path, sound_volume)
        return True
    except Exception as e:
        print(f"播放失败: {e}")
        return False


def stop_sound():
    """停止当前正在播放的音频"""
    try:
        player = _get_player()
        player.stop()
    except Exception:
        pass
    return True
