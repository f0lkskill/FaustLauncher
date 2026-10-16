
from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes
import os
import struct
import time
from dataclasses import dataclass

PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010
TH32CS_SNAPPROCESS = 0x00000002
TH32CS_SNAPMODULE = 0x00000008
TH32CS_SNAPMODULE32 = 0x00000010

MEM_COMMIT = 0x1000
MEM_IMAGE = 0x1000000
MEM_MAPPED = 0x40000
MEM_PRIVATE = 0x20000

PAGE_READONLY = 0x02
PAGE_READWRITE = 0x04
PAGE_WRITECOPY = 0x08
PAGE_EXECUTE_READ = 0x20
PAGE_EXECUTE_READWRITE = 0x40
PAGE_EXECUTE_WRITECOPY = 0x80
PAGE_GUARD = 0x100
PAGE_NOACCESS = 0x01

_READABLE_PROTECTIONS = (
    PAGE_READONLY, PAGE_READWRITE, PAGE_WRITECOPY,
    PAGE_EXECUTE_READ, PAGE_EXECUTE_READWRITE, PAGE_EXECUTE_WRITECOPY,
)

MAX_USER_ADDRESS = 0x7FFFFFFF0000
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

class MEMORY_BASIC_INFORMATION64(ctypes.Structure):
    _fields_ = [
        ("BaseAddress", ctypes.c_ulonglong),
        ("AllocationBase", ctypes.c_ulonglong),
        ("AllocationProtect", wintypes.DWORD),
        ("__alignment1", wintypes.DWORD),
        ("RegionSize", ctypes.c_ulonglong),
        ("State", wintypes.DWORD),
        ("Protect", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("__alignment2", wintypes.DWORD),
    ]

class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", ctypes.c_wchar * 260),
    ]

class MODULEENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("th32ModuleID", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("GlblcntUsage", wintypes.DWORD),
        ("ProccntUsage", wintypes.DWORD),
        ("modBaseAddr", ctypes.c_void_p),
        ("modBaseSize", wintypes.DWORD),
        ("hModule", ctypes.c_void_p),
        ("szModule", ctypes.c_wchar * 256),
        ("szExePath", ctypes.c_wchar * 260),
    ]

@dataclass(frozen=True)
class RegionInfo:

    base: int
    size: int
    protect: int
    type: int

    @property
    def end(self) -> int:
        return self.base + self.size

    @property
    def is_image(self) -> bool:
        return self.type == MEM_IMAGE

    @property
    def is_private(self) -> bool:
        return self.type == MEM_PRIVATE

    def __contains__(self, addr: int) -> bool:
        return self.base <= addr < self.end

@dataclass(frozen=True)
class ModuleInfo:
    name: str
    base: int
    size: int

    @property
    def end(self) -> int:
        return self.base + self.size

    def __contains__(self, addr: int) -> bool:
        return self.base <= addr < self.end

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

def _configure_api() -> None:
    k = _kernel32
    k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k.OpenProcess.restype = wintypes.HANDLE
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    k.CloseHandle.restype = wintypes.BOOL
    k.ReadProcessMemory.argtypes = [
        wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
        ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
    k.ReadProcessMemory.restype = wintypes.BOOL
    k.VirtualQueryEx.argtypes = [
        wintypes.HANDLE, ctypes.c_void_p,
        ctypes.POINTER(MEMORY_BASIC_INFORMATION64), ctypes.c_size_t]
    k.VirtualQueryEx.restype = ctypes.c_size_t
    k.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    k.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    k.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    k.Process32FirstW.restype = wintypes.BOOL
    k.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    k.Process32NextW.restype = wintypes.BOOL
    k.Module32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MODULEENTRY32W)]
    k.Module32FirstW.restype = wintypes.BOOL
    k.Module32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MODULEENTRY32W)]
    k.Module32NextW.restype = wintypes.BOOL

_configure_api()

def find_process_id(process_name: str) -> int | None:
    wanted = process_name.lower()
    if not wanted.endswith(".exe"):
        wanted += ".exe"
    snapshot = _kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not snapshot or snapshot == INVALID_HANDLE_VALUE:
        return None
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        ok = _kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while ok:
            if str(entry.szExeFile).lower() == wanted:
                return int(entry.th32ProcessID)
            ok = _kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        _kernel32.CloseHandle(snapshot)
    return None

def is_process_running(process_name: str) -> bool:
    return find_process_id(process_name) is not None

class ProcessMemoryReader:

    def __init__(self, process_name: str = "LimbusCompany.exe",
                 pid: int | None = None) -> None:
        self.process_name = process_name
        self.pid_override = int(pid) if pid else None
        self.pid: int | None = None
        self.handle: int | None = None

    def attach(self, timeout: float = 0.0, poll: float = 0.5) -> bool:
        if self.attached:
            return True
        if self.pid_override:
            handle = _kernel32.OpenProcess(
                PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, False, self.pid_override)
            if handle:
                self.pid = self.pid_override
                self.handle = int(handle)
                return True
            return False
        deadline = time.time() + max(0.0, timeout)
        while True:
            pid = find_process_id(self.process_name)
            if pid:
                handle = _kernel32.OpenProcess(
                    PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, False, pid)
                if handle:
                    self.pid = pid
                    self.handle = int(handle)
                    return True
            if time.time() >= deadline:
                return False
            time.sleep(poll)

    def detach(self) -> None:
        if self.handle:
            _kernel32.CloseHandle(self.handle)
        self.handle = None
        self.pid = None

    @property
    def attached(self) -> bool:
        return bool(self.handle and self.pid)

    def __enter__(self) -> "ProcessMemoryReader":
        self.attach()
        return self

    def __exit__(self, *exc) -> None:
        self.detach()

    def __del__(self) -> None:
        try:
            self.detach()
        except Exception:
            pass

    def _module_snapshot(self, pid: int | None = None):
        pid = pid or self.pid
        flags = TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32
        snapshot = _kernel32.CreateToolhelp32Snapshot(flags, pid)
        if not snapshot or snapshot == INVALID_HANDLE_VALUE:
            return None
        return snapshot

    def modules(self) -> dict[str, ModuleInfo]:
        out: dict[str, ModuleInfo] = {}
        if not self.attached:
            return out
        snapshot = self._module_snapshot()
        if not snapshot:
            return out
        try:
            entry = MODULEENTRY32W()
            entry.dwSize = ctypes.sizeof(MODULEENTRY32W)
            ok = _kernel32.Module32FirstW(snapshot, ctypes.byref(entry))
            while ok:
                name = str(entry.szModule)
                out[name.lower()] = ModuleInfo(name, int(entry.modBaseAddr or 0),
                                               int(entry.modBaseSize or 0))
                ok = _kernel32.Module32NextW(snapshot, ctypes.byref(entry))
        finally:
            _kernel32.CloseHandle(snapshot)
        return out

    def module(self, name: str) -> ModuleInfo | None:
        mods = self.modules()
        info = mods.get(name.lower())
        if info:
            return info
        stem = name.lower()
        if not stem.endswith(".dll"):
            return mods.get(stem + ".dll")
        return None

    def module_base(self, name: str = "GameAssembly.dll") -> int | None:
        info = self.module(name)
        return info.base if info else None

    def regions(self, readable_only: bool = True,
                include_images: bool = True) -> list[RegionInfo]:
        out: list[RegionInfo] = []
        if not self.attached:
            return out
        mbi = MEMORY_BASIC_INFORMATION64()
        addr = 0
        while addr < MAX_USER_ADDRESS:
            got = _kernel32.VirtualQueryEx(
                self.handle, ctypes.c_void_p(addr), ctypes.byref(mbi),
                ctypes.sizeof(mbi))
            if not got:
                break
            base, size = int(mbi.BaseAddress), int(mbi.RegionSize)
            if size <= 0:
                break
            if (mbi.State == MEM_COMMIT
                    and (not readable_only or self._is_readable(mbi.Protect))
                    and (include_images or mbi.Type != MEM_IMAGE)):
                out.append(RegionInfo(base, size, int(mbi.Protect), int(mbi.Type)))
            addr = base + size
        return out

    @staticmethod
    def _is_readable(protect: int) -> bool:
        if protect & PAGE_GUARD or protect == PAGE_NOACCESS:
            return False
        return any(protect & p for p in _READABLE_PROTECTIONS)

    def read(self, address: int, size: int) -> bytes | None:
        if not self.attached or address <= 0 or size <= 0:
            return None
        buffer = ctypes.create_string_buffer(size)
        read = ctypes.c_size_t(0)
        ok = _kernel32.ReadProcessMemory(
            self.handle, ctypes.c_void_p(address), buffer, size, ctypes.byref(read))
        if not ok or read.value != size:
            return None
        return buffer.raw[:size]

    def read_into(self, address: int, buffer) -> bool:
        if not self.attached or address <= 0:
            return False
        size = ctypes.sizeof(buffer)
        read = ctypes.c_size_t(0)
        ok = _kernel32.ReadProcessMemory(
            self.handle, ctypes.c_void_p(address), buffer, size, ctypes.byref(read))
        return bool(ok) and read.value == size

    def read_u64(self, address: int) -> int | None:
        raw = self.read(address, 8)
        return int.from_bytes(raw, "little") if raw else None

    def read_u32(self, address: int) -> int | None:
        raw = self.read(address, 4)
        return int.from_bytes(raw, "little") if raw else None

    def read_i32(self, address: int) -> int | None:
        raw = self.read(address, 4)
        return int.from_bytes(raw, "little", signed=True) if raw else None

    def read_f32(self, address: int) -> float | None:
        raw = self.read(address, 4)
        return struct.unpack("<f", raw)[0] if raw else None

    def read_value(self, address: int, value_type: str = "int32"):
        vt = (value_type or "int32").lower()
        if vt in ("int32", "i32", "int"):
            return self.read_i32(address)
        if vt in ("uint32", "u32"):
            return self.read_u32(address)
        if vt in ("int64", "i64", "long"):
            raw = self.read(address, 8)
            return int.from_bytes(raw, "little", signed=True) if raw else None
        if vt in ("uint64", "u64", "pointer", "ptr"):
            return self.read_u64(address)
        if vt in ("float", "f32"):
            return self.read_f32(address)
        if vt in ("double", "f64"):
            raw = self.read(address, 8)
            return struct.unpack("<d", raw)[0] if raw else None
        return None

    def read_cstring(self, address: int, max_len: int = 128) -> str:
        raw = self.read(address, max_len)
        if not raw:
            return ""
        text = raw.split(b"\x00", 1)[0]
        if not text:
            return ""
        try:
            return text.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            return text.decode("latin1", errors="replace")

    def follow_chain(self, address: int, offsets, value_type: str = "pointer"):
        if not offsets:
            return self.read_value(address, value_type)
        current = self.read_u64(address) if value_type in ("pointer", "ptr", "uint64", "u64") \
            else self.read_value(address, value_type)
        for index, offset in enumerate(offsets):
            if not current:
                return None
            current = current + int(offset)
            if index == len(offsets) - 1:
                return self.read_value(current, value_type) # type: ignore
            raw = self.read_u64(current) # type: ignore
            if not raw:
                return None
            current = raw
        return None

    def resolve_chain_address(self, base_address: int, offsets) -> int | None:
        current = base_address
        for offset in offsets:
            raw = self.read_u64(current)
            if not raw:
                return None
            current = raw + int(offset)
        return current

    def scan_bytes(self, pattern: bytes, ranges=None, limit: int = 8,
                   chunk: int = 8 << 20, overlap: int = 32,
                   progress=None) -> list[int]:
        if not self.attached or not pattern:
            return []
        hits: list[int] = []
        ranges = list(ranges) if ranges is not None else [
            (r.base, r.size) for r in self.regions(include_images=False)]
        plen = len(pattern)
        buf = ctypes.create_string_buffer(chunk + overlap)
        for base, size in ranges:
            address = base
            end = base + size
            if progress:
                progress(base, size)
            while address < end:
                want = min(chunk, end - address)
                if want < plen:
                    break
                buffer = buf if want == chunk else ctypes.create_string_buffer(want)
                if not self.read_into(address, buffer):
                    address += 0x1000
                    data = b""
                else:
                    data = buffer.raw[:want]
                if data:
                    start = 0
                    while True:
                        found = data.find(pattern, start)
                        if found < 0:
                            break
                        hits.append(address + found)
                        if len(hits) >= limit:
                            return hits
                        start = found + 1
                address += want
        return hits

    def iter_pointers(self, ranges=None, chunk: int = 8 << 20,
                      pointer_filter=None, progress=None):
        if not self.attached:
            return
        ranges = list(ranges) if ranges is not None else [
            (r.base, r.size) for r in self.regions(include_images=False)]
        if pointer_filter is None:
            pointer_filter = lambda v: v > 0x10000 and (v & 7) == 0  # noqa: E731
        buf = ctypes.create_string_buffer(chunk)
        for base, size in ranges:
            if progress:
                progress(base, size)
            address = base
            end = base + size
            while address < end:
                want = min(chunk, end - address)
                buffer = buf if want == chunk else ctypes.create_string_buffer(want)
                if not self.read_into(address, buffer):
                    address += 0x1000
                    continue
                data = memoryview(buffer.raw)[:want]
                start = (-address) % 8
                for off in range(start, want - 7, 8):
                    value = int.from_bytes(data[off:off + 8], "little")
                    if pointer_filter(value):
                        yield address + off, value
                address += want

    def collect_pointers(self, ranges=None, chunk: int = 8 << 20,
                         pointer_filter=None, progress=None) -> list[tuple[int, int]]:
        return list(self.iter_pointers(ranges, chunk, pointer_filter, progress))

    def pointer_targets(self, ptr: int, offsets, depth: int = 32) -> list[int]:
        return [ptr + off for off in offsets]

def enumerate_pointer_value(reader: "ProcessMemoryReader", address: int) -> int | None:
    return reader.read_u64(address)

def describe_regions(regions, limit: int = 12) -> str:
    lines = []
    for region in list(regions)[:limit]:
        kind = "image" if region.is_image else ("heap" if region.is_private else "other")
        lines.append(f"  0x{region.base:012X} +0x{region.size:X} {kind}")
    if len(regions) > limit:
        lines.append(f"  ...（共 {len(regions)} 段）")
    return "\n".join(lines)

def main() -> int:
    import sys

    name = sys.argv[1] if len(sys.argv) > 1 else "LimbusCompany.exe"
    reader = ProcessMemoryReader(name)
    if not reader.attach():
        print(f"未找到进程: {name}")
        return 1
    modules = reader.modules()
    print(f"进程 {name} PID={reader.pid} 模块数={len(modules)}")
    for key in ("gameassembly.dll", "unityplayer.dll"):
        info = modules.get(key)
        if info:
            print(f"  {info.name}: base=0x{info.base:012X} size=0x{info.size:X}")
    regions = reader.regions()
    print(f"可读区域 {len(regions)} 段")
    print(describe_regions(regions))
    reader.detach()
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
