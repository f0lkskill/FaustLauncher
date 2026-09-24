"""Limbus Company 进程内存读取器。

当前支持读取脑啡肽容量。指针链有两个来源：

1. **云端笔记** ``FaustLauncher.hook_index``（由 functions.hook 自动生成，
   ``targets.enkephalin`` 字段；本地 ``cache/hook/hook_index.json`` 缓存优先，
   不阻塞读取）—— 游戏更新后偏移会自动跟着变，不需要改代码；
2. 代码里的内置默认值（下面的 ``ENKEPHALIN_TARGET``，来自桌面 ok.py 的 CE 结果），
   作为拿不到索引时的兜底。

索引里的链只在 ``gameassembly_size`` 与本地 GameAssembly.dll 一致时才会被采用
（大小不一致 = 索引对应的是另一个游戏版本，用了只会读出垃圾）。

读不到索引时会在后台线程拉一次云端笔记（一次启动只拉一次），不影响读取。
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes
import os
import threading
from dataclasses import dataclass

# 注意：``functions.hook`` 在**模块级**导入（不在读取路径里惰性 import）。
# 成就监测是“监控线程 + 主线程”并发结构，而 Python 3.14 的 import 锁在“一个线程正在
# 导入某模块时另一个线程也去 import 同一模块”会抛 DeadlockError —— 实测就是这么踩到的。
# 这里在主线程 import 期间就把依赖解析完，读取路径上只剩纯计算。
try:
    from functions.hook import index as _hook_index_mod
except Exception:            # 打包环境缺模块时仍要能用内置偏移
    _hook_index_mod = None  # type: ignore[assignment]


PROCESS_VM_READ = 0x0010
PROCESS_QUERY_INFORMATION = 0x0400
TH32CS_SNAPMODULE = 0x00000008
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


class MODULEENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("th32ModuleID", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("GlblcntUsage", wintypes.DWORD),
        ("ProccntUsage", wintypes.DWORD),
        ("modBaseAddr", ctypes.c_void_p),
        ("modBaseSize", wintypes.DWORD),
        ("hModule", ctypes.c_void_p),
        ("szModule", ctypes.c_char * 256),
        ("szExePath", ctypes.c_char * 260),
    ]


@dataclass(frozen=True)
class MemoryTarget:
    """一个内存目标的指针链配置。"""

    module_name: str
    base_offset: int
    offsets: tuple[int, ...]
    value_type: str = "int32"


ENKEPHALIN_TARGET = MemoryTarget(
    module_name="GameAssembly.dll",
    base_offset=0x07BB4F90,
    offsets=(0xB8, 0x80, 0x18, 0x28),
)

# 笔记里允许拿到的目标名（键名 → 默认链）
_KNOWN_TARGETS = {"enkephalin": ENKEPHALIN_TARGET}
_CHAIN_LOCK = threading.Lock()
_RESOLVED: dict[str, MemoryTarget] = {}
_CHAIN_SOURCE: dict[str, str] = {}
_CLOUD_REFRESHED = False
_CLOUD_REFRESHING = False


def _local_gameassembly_size() -> int:
    """本地 GameAssembly.dll 大小（拿不到返回 0；只用来校验索引是否配套）。"""
    try:
        from functions.hook.paths import game_paths
        paths = game_paths()
        if paths.gameassembly and os.path.isfile(paths.gameassembly):
            return os.path.getsize(paths.gameassembly)
    except Exception:
        pass
    return 0


def _target_from_dict(item: dict, default: MemoryTarget) -> MemoryTarget | None:
    """把索引里的 target 字典转成 MemoryTarget（校验不通过返回 None）。"""
    try:
        base_offset = int(item.get("base_offset")) # type: ignore
        offsets = tuple(int(x) for x in item.get("offsets") or [])
    except (TypeError, ValueError):
        return None
    if base_offset <= 0 or not offsets:
        return None
    return MemoryTarget(
        module_name=str(item.get("module") or default.module_name),
        base_offset=base_offset,
        offsets=offsets,
        value_type=str(item.get("value_type") or default.value_type),
    )


def memory_target(key: str = "enkephalin") -> MemoryTarget:
    """取某条链的当前可用参数（索引优先，回退内置默认值）。"""
    default = _KNOWN_TARGETS.get(key, ENKEPHALIN_TARGET)
    with _CHAIN_LOCK:
        cached = _RESOLVED.get(key)
        if cached is not None:
            return cached
    resolved, source = default, "builtin"
    try:
        get_index = getattr(_hook_index_mod, "get_index", None)
        if get_index is None:
            raise RuntimeError("functions.hook.index 不可用")
        index, idx_source = get_index()
        if index is not None:
            item = index.target(key)
            local_size = _local_gameassembly_size()
            note_size = int(index.game.get("gameassembly_size") or 0)
            if note_size and local_size and note_size != local_size:
                print(f"[成就] 忽略链 {key}：索引对应 {note_size} 字节的 GameAssembly.dll，"
                      f"本地是 {local_size} 字节（版本不匹配）")
            else:
                candidate = _target_from_dict(item, default)
                if candidate is not None:
                    resolved, source = candidate, idx_source or "index"
    except Exception as exc:  # noqa: BLE001
        print(f"[成就] 读取 hook_index 失败，使用内置偏移: {type(exc).__name__}: {exc}")
    with _CHAIN_LOCK:
        _RESOLVED[key] = resolved
        _CHAIN_SOURCE[key] = source
    print(f"[成就] {key} 指针链来源: {source} → {resolved.module_name}+"
          f"0x{resolved.base_offset:X}+{[hex(x) for x in resolved.offsets]}")
    return resolved


def chain_source(key: str = "enkephalin") -> str:
    """当前链的来源描述（诊断用）。"""
    memory_target(key)
    with _CHAIN_LOCK:
        return _CHAIN_SOURCE.get(key, "unknown")


def refresh_chain_from_cloud(background: bool = True, on_log=print) -> bool:
    """从云端笔记拉一次 hook_index 并刷新本地缓存（一次启动只自动拉一次）。

    成就监测进程启动时调一次即可：拿到新偏移后，下一次 ``memory_target()``
    就会用新的链（读取过程中不会因此阻塞）。

    注意：依赖模块在**调用线程**（主线程）里先导入好。Python 3.14 的 import 锁
    在“主线程正在导入某模块时、后台线程再去 import 同一模块”会直接抛
    ``_DeadlockError``（实测过），所以不能让工作线程承担首次导入。
    """
    global _CLOUD_REFRESHED, _CLOUD_REFRESHING
    hook_index = _hook_index_mod
    if hook_index is None:
        if on_log:
            on_log("[成就] hook 索引模块不可用，跳过云端刷新")
        return False
    with _CHAIN_LOCK:
        if _CLOUD_REFRESHED or _CLOUD_REFRESHING:
            return False
        _CLOUD_REFRESHING = True

    def worker() -> None:
        global _CLOUD_REFRESHED, _CLOUD_REFRESHING
        try:
            got = hook_index.refresh_local_from_cloud(allow_refresh=True, on_log=on_log)
            with _CHAIN_LOCK:
                _RESOLVED.clear()          # 让下次读取重新解析
            if got is not None and on_log:
                on_log(f"[成就] 已从云端刷新偏移索引（游戏 sha256 "
                       f"{str(got.game.get('gameassembly_sha256') or '')[:12]}...）")
        except Exception as exc:  # noqa: BLE001
            if on_log:
                on_log(f"[成就] 云端刷新偏移索引失败（继续用本地/内置值）: "
                       f"{type(exc).__name__}: {exc}")
        finally:
            with _CHAIN_LOCK:
                _CLOUD_REFRESHED = True
                _CLOUD_REFRESHING = False

    if not background:
        worker()
        return True
    threading.Thread(target=worker, name="ach-hook-index-refresh", daemon=True).start()
    return True


def _fast_find_process(process_name: str = "LimbusCompany.exe") -> int:
    """用 ctypes 枚举进程（~7ms），拿不到返回 0。

    内部复用 ``battle_watch.find_process_id``（同一套 CreateToolhelp32Snapshot 枚举），
    避免每个模块各自实现一份；导入失败时返回 0，调用处会回退 tasklist。
    """
    try:
        from functions.achievement.battle_watch import find_process_id
        return int(find_process_id(process_name) or 0)
    except Exception:
        return 0


class LimbusMemoryReader:
    """读取游戏进程内存的轻量封装。"""

    def __init__(self, process_name: str = "LimbusCompany.exe") -> None:
        self.process_name = process_name.lower()
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.handle: int | None = None
        self.pid: int | None = None
        self.module_base: int | None = None
        self.module_name: str | None = None

        self._configure_api()

    def _configure_api(self) -> None:
        k = self.kernel32
        k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k.OpenProcess.restype = wintypes.HANDLE
        k.CloseHandle.argtypes = [wintypes.HANDLE]
        k.CloseHandle.restype = wintypes.BOOL
        k.ReadProcessMemory.argtypes = [
            wintypes.HANDLE,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_size_t,
            ctypes.POINTER(ctypes.c_size_t),
        ]
        k.ReadProcessMemory.restype = wintypes.BOOL
        k.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        k.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        k.Module32First.argtypes = [wintypes.HANDLE, ctypes.POINTER(MODULEENTRY32)]
        k.Module32First.restype = wintypes.BOOL
        k.Module32Next.argtypes = [wintypes.HANDLE, ctypes.POINTER(MODULEENTRY32)]
        k.Module32Next.restype = wintypes.BOOL

    def _find_process(self) -> tuple[int, int] | None:
        """查找游戏进程（ctypes 枚举，~7ms）。

        以前每次都 ``subprocess.run(["tasklist", ...])`` → 单次 ~400ms，而这个读取会被
        成就轮询频繁问到（以前它还跑在弹窗动画的线程上，所以弹窗末尾卡顿/看着像卡死）。
        现在只走 ctypes；游戏没开就是 ~7ms 返回 ``None``（不再回退去 spawn tasklist——
        那才是那 400ms 的元凶）。
        """
        pid = _fast_find_process(self.process_name)
        return (pid, 0) if pid else None

    def _find_module(self, pid: int, module_name: str) -> int | None:
        snapshot = self.kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPMODULE, pid)
        if snapshot in (None, INVALID_HANDLE_VALUE):
            return None
        try:
            entry = MODULEENTRY32()
            entry.dwSize = ctypes.sizeof(MODULEENTRY32)
            if not self.kernel32.Module32First(snapshot, ctypes.byref(entry)):
                return None
            while True:
                name = bytes(entry.szModule).split(b"\0", 1)[0].decode(
                    "mbcs", errors="ignore"
                )
                if name.lower() == module_name.lower():
                    return int(entry.modBaseAddr or 0)
                if not self.kernel32.Module32Next(snapshot, ctypes.byref(entry)):
                    break
        finally:
            self.kernel32.CloseHandle(snapshot)
        return None

    def attach(self, target: MemoryTarget = ENKEPHALIN_TARGET) -> bool:
        """附加游戏并定位目标模块。"""
        if self.is_attached:
            return True
        found = self._find_process()
        if found is None:
            return False
        pid, _ = found
        handle = self.kernel32.OpenProcess(
            PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, False, pid
        )
        if not handle:
            return False
        base = self._find_module(pid, target.module_name)
        if base is None:
            self.kernel32.CloseHandle(handle)
            return False
        self.pid = pid
        self.handle = int(handle)
        self.module_base = base
        self.module_name = target.module_name
        return True

    @property
    def is_attached(self) -> bool:
        return bool(self.handle and self.pid and self.module_base)

    def _read_bytes(self, address: int, size: int) -> bytes | None:
        if not self.handle or address <= 0:
            return None
        buffer = ctypes.create_string_buffer(size)
        read = ctypes.c_size_t(0)
        ok = self.kernel32.ReadProcessMemory(
            self.handle,
            ctypes.c_void_p(address),
            buffer,
            size,
            ctypes.byref(read),
        )
        if not ok or read.value != size:
            return None
        return buffer.raw[:size]

    def read_pointer(self, target: MemoryTarget) -> int | None:
        """沿用 ok.py 的多级指针语义读取最终地址。"""
        if not self.is_attached or self.module_base is None:
            return None
        address = self.module_base + target.base_offset
        for offset in target.offsets:
            raw = self._read_bytes(address, ctypes.sizeof(ctypes.c_void_p))
            if raw is None:
                return None
            address = int.from_bytes(raw, "little")
            if not address:
                return None
            address += offset
        return address

    def read_int32(self, target: MemoryTarget = ENKEPHALIN_TARGET) -> int | None:
        """读取目标的 32 位整数值。"""
        address = self.read_pointer(target)
        raw = self._read_bytes(address, 4) if address else None
        return int.from_bytes(raw, "little", signed=True) if raw else None

    def read_enkephalin(self) -> int | None:
        """读取脑啡肽容量，不是狂气。"""
        target = memory_target("enkephalin")
        if not self.is_attached and not self.attach(target):
            return None
        value = self.read_int32(target)
        if value is None:
            self.detach()
        return value

    def detach(self) -> None:
        if self.handle:
            self.kernel32.CloseHandle(self.handle)
        self.handle = None
        self.pid = None
        self.module_base = None
        self.module_name = None

    def __del__(self) -> None:
        self.detach()
