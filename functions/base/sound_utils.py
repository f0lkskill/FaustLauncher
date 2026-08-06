import io
import os
import struct
import tempfile
import threading
import time
import wave
import winsound


# ========== PCM 缓存 ==========
_pcm_cache = {}  # path -> (rate, nch, sampwidth, samples:list[int])


def _load_pcm(file_path):
    """读取 WAV 为内存样本（16-bit 小端交错），结果缓存"""
    item = _pcm_cache.get(file_path)
    if item is None:
        with wave.open(file_path, "rb") as wf:
            rate = wf.getframerate()
            nch = wf.getnchannels()
            sw = wf.getsampwidth()
            raw = wf.readframes(wf.getnframes())
        if len(raw) > 8 * 1024 * 1024:
            raw = raw[:8 * 1024 * 1024]
        samples = list(struct.unpack(f"<{len(raw) // 2}h", raw)) if sw == 2 else None
        item = (rate, nch, sw, samples)
        _pcm_cache[file_path] = item
    return item


# ========== 混音播放线程 ==========
class _MixerPlayer(threading.Thread):
    """软件混音 + 异步播放线程。

    同一时刻只能有一个 winsound 播放实例，且后发请求会排队等待，
    因此"同时播放两个音效"必须在本线程内做样本级混音：
    - 每段声音都以 PCM 样本常驻内存，按已播放帧数推进游标；
    - 新声音到达时，把当前未播完的各层 + 新声音混成一段新 WAV，
      在播放线程内 purge 旧实例并重新异步播放；
    - 界面线程只发信号，从不触碰播放器内部状态。
    """

    MAX_LAYERS = 6

    def __init__(self):
        super().__init__(daemon=True, name="sound-player")
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._pending = []     # 待提交路径
        self._stop_flag = False
        self._layers = []      # [(samples, consumed_frames)]
        self._fmt = None       # (rate, nch, sw)
        self._mix_start = 0.0
        self._expected_end = 0.0
        self._tmp_files = []   # 已交给 PlaySound 的临时混音文件

    # ---------- 界面线程 API ----------
    def submit(self, file_path):
        with self._lock:
            self._pending.append(file_path)
        self._wake.set()

    def request_stop(self):
        with self._lock:
            self._stop_flag = True
            self._pending.clear()
        self._wake.set()

    def is_playing(self):
        return time.monotonic() < self._expected_end

    # ---------- 播放线程 ----------
    def run(self):
        while True:
            try:
                self._process()
            except Exception as e:
                print(f"播放线程异常: {e}")
            self._wake.wait()
            self._wake.clear()

    def _process(self):
        with self._lock:
            pending = list(self._pending)
            self._pending.clear()
            stop_requested = self._stop_flag
            self._stop_flag = False
            layers = list(self._layers)
            fmt = self._fmt
            mix_start = self._mix_start

        # 1) 推进各层已播放帧数
        if layers and fmt is not None and mix_start:
            elapsed = time.monotonic() - mix_start
            advance = int(elapsed * fmt[0])
            layers = [(s, c + advance) for s, c in layers]

        # 2) 处理停止请求
        if stop_requested:
            layers = []
            fmt = None
            pending = []

        # 3) 挂载新声音
        for path in pending:
            try:
                rate, nch, sw, samples = _load_pcm(path)
            except Exception as e:
                print(f"读取音频失败 {path}: {e}")
                continue
            if samples is None:
                print(f"不支持的音频格式（仅支持16bit WAV）: {path}")
                continue
            if fmt is None:
                fmt = (rate, nch, sw)
            if (rate, nch, sw) != fmt:
                # 格式不同无法混音：只保留新声音
                layers = [(samples, 0)]
                fmt = (rate, nch, sw)
            else:
                layers.append((samples, 0))
            if len(layers) > self.MAX_LAYERS:
                layers = layers[-self.MAX_LAYERS:]

        # 4) 丢弃已播完的层
        if fmt is not None:
            nch = fmt[1]
            layers = [(s, c) for s, c in layers if c * nch < len(s)]

        # 5) 混音并播放
        self._purge()
        if layers and fmt is not None:
            wav_bytes = self._mix_to_wav(layers, fmt)
            self._play_async(wav_bytes)
            with self._lock:
                self._layers = layers
                self._fmt = fmt
                self._mix_start = time.monotonic()
                remaining = max((len(s) - c * fmt[1]) / (fmt[0] * fmt[1])
                                for s, c in layers)
                self._expected_end = self._mix_start + remaining
        else:
            with self._lock:
                self._layers = []
                self._fmt = None
                self._mix_start = 0.0
                self._expected_end = 0.0

    def _mix_to_wav(self, layers, fmt):
        """把各层从当前游标起混合成一段 WAV 字节"""
        rate, nch, sw = fmt
        total_frames = 0
        for samples, consumed in layers:
            total_frames = max(total_frames, (len(samples) // nch) - consumed)
        total_frames = min(total_frames, 10 * 60 * rate)  # 上限 10 分钟
        mixed = [0] * (total_frames * nch)
        for samples, consumed in layers:
            off = consumed * nch
            seg = samples[off:off + total_frames * nch]
            for i, v in enumerate(seg):
                mixed[i] += v
        for i in range(len(mixed)):
            v = mixed[i]
            if v > 32767:
                mixed[i] = 32767
            elif v < -32768:
                mixed[i] = -32768
        pcm = struct.pack(f"<{len(mixed)}h", *mixed)
        bio = io.BytesIO()
        with wave.open(bio, "wb") as wf:
            wf.setnchannels(nch)
            wf.setsampwidth(sw)
            wf.setframerate(rate)
            wf.writeframes(pcm)
        return bio.getvalue()

    def _purge(self):
        """停止当前异步播放，并清理旧临时文件（数据已载入内存，可安全删除）"""
        try:
            winsound.PlaySound(None, winsound.SND_PURGE)
        except Exception:
            pass
        for p in self._tmp_files:
            try:
                os.remove(p)
            except OSError:
                pass
        self._tmp_files = []

    def _play_async(self, wav_bytes):
        """混音结果写临时 WAV 文件，异步播放（SND_MEMORY 不允许 SND_ASYNC）"""
        fd, path = tempfile.mkstemp(prefix="faust_snd_", suffix=".wav")
        with os.fdopen(fd, "wb") as f:
            f.write(wav_bytes)
        winsound.PlaySound(
            path,
            winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT,
        )
        self._tmp_files.append(path)


_player = None
_player_lock = threading.Lock()


def _get_player():
    global _player
    with _player_lock:
        if _player is None:
            p = _MixerPlayer()
            p.start()
            _player = p
    return _player


# ========== 对外 API ==========
def play_sound(file_path):
    """异步播放WAV音频文件，可与正在播放的音效混音同时出声"""
    if not file_path or not os.path.exists(file_path):
        print(f"音频文件不存在: {file_path}")
        return False
    try:
        _get_player().submit(file_path)
        return True
    except Exception as e:
        print(f"播放失败: {e}")
        return False


def stop_sound():
    """停止全部音效（含待播）"""
    try:
        _get_player().request_stop()
    except Exception:
        pass
    return True
