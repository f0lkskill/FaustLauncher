
from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes
import os
import threading
from dataclasses import dataclass

try:
    from functions.hook import index as _hook_index_mod
except Exception:
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

    module_name: str
    base_offset: int
    offsets: tuple[int, ...]
    value_type: str = "int32"

ENKEPHALIN_TARGET = MemoryTarget(
    module_name="GameAssembly.dll",
    base_offset=0x07BB4F90,
    offsets=(0xB8, 0x80, 0x18, 0x28),
)

_KNOWN_TARGETS = {"enkephalin": ENKEPHALIN_TARGET}
_CHAIN_LOCK = threading.Lock()
_RESOLVED: dict[str, MemoryTarget] = {}
_CHAIN_SOURCE: dict[str, str] = {}
_CLOUD_REFRESHED = False
_CLOUD_REFRESHING = False

def _local_gameassembly_size() -> int:
    try:
        from functions.hook.paths import game_paths
        paths = game_paths()
        if paths.gameassembly and os.path.isfile(paths.gameassembly):
            return os.path.getsize(paths.gameassembly)
    except Exception:
        pass
    return 0

def _target_from_dict(item: dict, default: MemoryTarget) -> MemoryTarget | None:
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
                print(f"[Achievement] 忽略链 {key}：索引对应 {note_size} 字节的 GameAssembly.dll，"
                      f"本地是 {local_size} 字节（版本不匹配）")
            else:
                candidate = _target_from_dict(item, default)
                if candidate is not None:
                    resolved, source = candidate, idx_source or "index"
    except Exception as exc:  # noqa: BLE001
        print(f"[Achievement] 读取 hook_index 失败，使用内置偏移: {type(exc).__name__}: {exc}")
    with _CHAIN_LOCK:
        _RESOLVED[key] = resolved
        _CHAIN_SOURCE[key] = source
    print(f"[Achievement] {key} 指针链来源: {source} → {resolved.module_name}+"
          f"0x{resolved.base_offset:X}+{[hex(x) for x in resolved.offsets]}")
    return resolved

def chain_source(key: str = "enkephalin") -> str:
    memory_target(key)
    with _CHAIN_LOCK:
        return _CHAIN_SOURCE.get(key, "unknown")

def _local_index_matches_game() -> bool:
    try:
        from functions.hook import index as index_mod
        from functions.hook import paths as paths_mod
        from functions.hook import preflight as preflight_mod
        ga = str(getattr(paths_mod.game_paths(), "gameassembly", "") or "")
        if not ga:
            return False
        index = index_mod.load_local()
        if index is None:
            return False
        return bool(preflight_mod.prologue_check(index, ga).get("ok"))
    except Exception:  # noqa: BLE001
        return False

def refresh_chain_from_cloud(background: bool = True, on_log=print) -> bool:
    global _CLOUD_REFRESHED, _CLOUD_REFRESHING
    hook_index = _hook_index_mod
    if hook_index is None:
        if on_log:
            on_log("[Achievement] hook 索引模块不可用，跳过云端刷新")
        return False
    with _CHAIN_LOCK:
        if _CLOUD_REFRESHED or _CLOUD_REFRESHING:
            return False
        _CLOUD_REFRESHING = True

    def worker() -> None:
        global _CLOUD_REFRESHED, _CLOUD_REFRESHING
        try:
            if _local_index_matches_game():
                with _CHAIN_LOCK:
                    _RESOLVED.clear()
                if on_log:
                    on_log("[Achievement] 本地偏移索引已对得上本机游戏 DLL → 跳过云端刷新")
                return
            got = hook_index.refresh_local_from_cloud(allow_refresh=True, on_log=on_log)
            with _CHAIN_LOCK:
                _RESOLVED.clear()
            if got is not None and on_log:
                on_log(f"[Achievement] 已从云端刷新偏移索引（游戏 sha256 "
                       f"{str(got.game.get('gameassembly_sha256') or '')[:12]}...）")
        except Exception as exc:  # noqa: BLE001
            if on_log:
                on_log(f"[Achievement] 云端刷新偏移索引失败（继续用本地/内置值）: "
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
    try:
        from functions.achievement.battle_watch import find_process_id
        return int(find_process_id(process_name) or 0)
    except Exception:
        return 0

class LimbusMemoryReader:

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
        address = self.read_pointer(target)
        raw = self._read_bytes(address, 4) if address else None
        return int.from_bytes(raw, "little", signed=True) if raw else None

    def read_enkephalin(self) -> int | None:
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
