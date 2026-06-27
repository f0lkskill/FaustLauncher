import struct
import wave,time,os
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
_current_playing = None
_current_lock = threading.Lock()


# ========== ctypes 数据结构（解决自引用前向引用）==========
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
    """懒加载 winmm.dll（Windows 自带，无需额外安装）"""
    global _winmm
    if _winmm is None:
        try:
            _winmm = ctypes.windll.winmm
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


# ========== 播放线程（整块读取 + 整块 waveOutWrite：生命周期完全可控）==========
class _WavePlayThread(threading.Thread):
    """整块读取音频文件，一次性 waveOutWrite。
    关键安全措施：将 hWaveOut/buf/hdr 保存在线程实例上，直到播放完全结束，
    确保驱动消费期间 Python GC 不会回收它们。
    """

    MAX_AUDIO_BYTES = 8 * 1024 * 1024  # 上限 8MB，防止超长 WAV 占内存

    def __init__(self, file_path, volume):
        super().__init__(daemon=True)
        self.file_path = file_path
        self.volume = float(volume)
        self._stop_event = threading.Event()
        # 以下成员保存关键对象引用，避免被 GC 提前回收（导致驱动读到野指针→崩溃）
        self._hwout = ctypes.wintypes.HANDLE()
        self._buf = None    # ctypes 缓冲：驱动在播放期间会读取它，必须存活
        self._hdr = None    # WAVEHDR：驱动会读写 dwFlags 字段，必须存活
        self._winmm = None
        self._opened = False
        self._prepared = False

    def stop_playback(self):
        self._stop_event.set()
        # 立刻在调用者线程尝试复位驱动（让它释放缓冲）
        try:
            if self._opened and self._winmm is not None:
                self._winmm.waveOutReset(self._hwout)
        except Exception:
            pass

    def run(self):
        self._winmm = _get_winmm()
        if self._winmm is None:
            print("winmm.dll 不可用")
            return

        try:
            # 1) 读取整个 WAV 文件
            with wave.open(self.file_path, "rb") as wf:
                nchannels = wf.getnchannels()
                sampwidth = wf.getsampwidth()
                framerate = wf.getframerate()
                nframes = wf.getnframes()

                raw = wf.readframes(nframes)

            if not raw:
                return

            # 防超大文件（理论上 WAV 很少超过几 MB）
            if len(raw) > self.MAX_AUDIO_BYTES:
                raw = raw[:self.MAX_AUDIO_BYTES]

            # 2) 在样本层面应用音量（缩放后得到最终要播放的 bytes）
            final_bytes = _apply_volume_to_samples(raw, self.volume, sampwidth)

            # 3) 准备 WAVEFORMATEX
            wfx = WAVEFORMATEX()
            wfx.wFormatTag = WAVE_FORMAT_PCM
            wfx.nChannels = nchannels
            wfx.nSamplesPerSec = framerate
            wfx.wBitsPerSample = sampwidth * 8
            wfx.nBlockAlign = nchannels * sampwidth
            wfx.nAvgBytesPerSec = framerate * wfx.nBlockAlign
            wfx.cbSize = 0

            # 4) 打开 wave 输出设备
            ret = self._winmm.waveOutOpen(
                ctypes.byref(self._hwout),
                ctypes.c_uint(WAVE_MAPPER),
                ctypes.byref(wfx),
                ctypes.c_ulong(0),
                ctypes.c_ulong(0),
                ctypes.c_ulong(CALLBACK_NULL),
            )
            if ret != MMSYSERR_NOERROR:
                print(f"waveOutOpen 失败 (错误码={ret})")
                return
            self._opened = True

            # 5) 创建缓冲 + header —— 保存在 self 上直到全部完成
            #    这是根因修复：ctypes.create_string_buffer 返回的对象必须
            #    至少活到驱动完成 waveOutWrite，否则驱动会读释放后的内存 → 崩溃。
            self._buf = ctypes.create_string_buffer(final_bytes)
            self._hdr = WAVEHDR()
            self._hdr.lpData = ctypes.cast(self._buf, ctypes.wintypes.LPSTR)
            self._hdr.dwBufferLength = len(final_bytes)
            self._hdr.dwBytesRecorded = 0
            self._hdr.dwUser = 0
            self._hdr.dwFlags = 0
            self._hdr.dwLoops = 0

            # 6) PrepareHeader + Write
            ret = self._winmm.waveOutPrepareHeader(
                self._hwout, ctypes.byref(self._hdr), ctypes.sizeof(self._hdr)
            )
            if ret != MMSYSERR_NOERROR:
                print(f"waveOutPrepareHeader 失败 (错误码={ret})")
                return
            self._prepared = True

            ret = self._winmm.waveOutWrite(
                self._hwout, ctypes.byref(self._hdr), ctypes.sizeof(self._hdr)
            )
            if ret != MMSYSERR_NOERROR:
                print(f"waveOutWrite 失败 (错误码={ret})")
                return

            # 7) 轮询等待播放完成 / 收到停止信号
            #    预估总时长（秒）+ 2 秒缓冲，给驱动一点时间处理尾部
            total_sec = max(0.1, len(final_bytes) / max(1, wfx.nAvgBytesPerSec))
            deadline = time.time() + total_sec + 2.0

            while not self._stop_event.is_set() and time.time() < deadline:
                if self._hdr.dwFlags & WHDR_DONE:
                    break
                time.sleep(0.01)

        except Exception as e:
            print(f"播放异常: {e}")
        finally:
            # 8) 清理（无条件执行，保证驱动和内存都被正确释放）
            try:
                if self._opened and self._winmm is not None:
                    # Reset：让驱动立即放弃当前 waveOutWrite，这样 UnprepareHeader 才能成功
                    self._winmm.waveOutReset(self._hwout)
                    if self._prepared and self._hdr is not None:
                        self._winmm.waveOutUnprepareHeader(
                            self._hwout, ctypes.byref(self._hdr), ctypes.sizeof(self._hdr)
                        )
                    self._winmm.waveOutClose(self._hwout)
            except Exception:
                pass
            self._opened = False
            self._prepared = False
            # 清除对 buffer/header 的引用，让 GC 能回收它们（已安全：驱动已 Reset+Close）
            self._buf = None
            self._hdr = None
            # 从全局记录中清除自己
            with _current_lock:
                global _current_playing
                if _current_playing is self:
                    _current_playing = None


# ========== 对外 API ==========
def play_sound(file_path, sound_volume=None):
    """播放WAV音频文件（支持停止当前播放并播放新音频，支持音量控制 0.0 ~ 1.0）"""
    if sound_volume is None:
        sound_volume = settings_manager.get_setting('sound_volume') or 0.5

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
        stop_sound()  # 停掉旧的
        t = _WavePlayThread(file_path, sound_volume)
        with _current_lock:
            global _current_playing
            _current_playing = t
        t.start()
        return True
    except Exception as e:
        print(f"播放失败: {e}")
        return False


def stop_sound():
    """停止当前正在播放的音频"""
    t = None
    with _current_lock:
        global _current_playing
        t = _current_playing
        _current_playing = None
    if t is not None:
        try:
            t.stop_playback()
        except Exception:
            pass
    return True