"""进程内存读写 / 扫描（纯 ctypes，无需 Frida、无需管理员即可读同用户进程）。

这个模块是整个 hook 子系统的"运行时眼睛"：元数据的动态 dump、指针链的
结构性重定位、目标值校验都靠它。设计上刻意与
``functions/achievement/memory_reader.py`` 保持一致的读取语义
（读失败返回 None 而不是抛异常、一律带边界校验），但补齐了区域枚举与
模式扫描能力。

约定：
- 所有读取失败（跨页/无权限/进程退出）都返回 ``None``，绝不抛异常；
- 地址都是进程内的绝对虚拟地址；
- ``scan_bytes`` 只在给出的范围内读，单块失败自动跳过。
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes
import os
import struct
import time
from dataclasses import dataclass

# ---- 访问权限 / 常量 ---------------------------------------------------------
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


# ---- 结构体 -----------------------------------------------------------------
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
    """一段已提交且可读的内存。"""

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
    """按进程名查 PID（不含 .exe 也可以）；找不到返回 None。"""
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
    """游戏进程内存读取器。

    用法::

        with ProcessMemoryReader() as reader:          # 默认 LimbusCompany.exe
            base = reader.module_base("GameAssembly.dll")
            value = reader.follow_chain(base + 0x7BB4F90, [0xB8, 0x80, 0x18], "int32")
    """

    def __init__(self, process_name: str = "LimbusCompany.exe",
                 pid: int | None = None) -> None:
        self.process_name = process_name
        self.pid_override = int(pid) if pid else None
        self.pid: int | None = None
        self.handle: int | None = None

    # ---------------------------------------------------------------- 生命周期
    def attach(self, timeout: float = 0.0, poll: float = 0.5) -> bool:
        """附加到目标进程；``timeout`` > 0 时轮询等待进程出现。

        构造时给了 ``pid`` 就直接用它（测试/指定进程场景）。
        """
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

    # ---------------------------------------------------------------- 模块 / 区域
    def _module_snapshot(self, pid: int | None = None):
        pid = pid or self.pid
        flags = TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32
        snapshot = _kernel32.CreateToolhelp32Snapshot(flags, pid)
        if not snapshot or snapshot == INVALID_HANDLE_VALUE:
            return None
        return snapshot

    def modules(self) -> dict[str, ModuleInfo]:
        """已加载模块表（键为小写模块名）。"""
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
        """枚举内存区域（默认只返回已提交且可读的）。"""
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

    # ---------------------------------------------------------------- 读取
    def read(self, address: int, size: int) -> bytes | None:
        """读 ``size`` 字节；失败返回 None。"""
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
        """读入调用方提供的 ctypes 缓冲区（大块读取更省内存）。"""
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
        """按类型读取（int32 / uint32 / int64 / uint64 / float / double / pointer）。"""
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
        """读 UTF-8/ASCII C 字符串（最多 ``max_len`` 字节，遇 0 截断）。"""
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
        """多级指针链：先按 ``value_type`` 读首地址，再逐级 +offset 解引用。

        与 ``functions/achievement/memory_reader.py`` 的语义一致：
        ``address`` 是首级数据的地址，offsets 的第一项作用于首级读取结果。
        """
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
        """多级指针链的最终地址（不解引用最后一级）。"""
        current = base_address
        for offset in offsets:
            raw = self.read_u64(current)
            if not raw:
                return None
            current = raw + int(offset)
        return current

    # ---------------------------------------------------------------- 扫描
    def scan_bytes(self, pattern: bytes, ranges=None, limit: int = 8,
                   chunk: int = 8 << 20, overlap: int = 32,
                   progress=None) -> list[int]:
        """在 ``ranges``（默认：可读的非映像区域）里搜索字节模式。

        返回匹配地址列表（最多 ``limit`` 个）。为了处理跨块匹配，每块之间保留
        ``overlap`` 字节重叠。
        """
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
                    # 单块读失败（很少见：区域内含保留页）→ 跳过 4KB 继续
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
        """流式产出范围内的"像指针的值" → ``(存放地址, 指针值)``。

        ``pointer_filter(value) -> bool`` 用于快速排除明显无效的指针（默认只
        要求 8 字节对齐且落在 0x10000 以上）。生成器形式可避免一次性塞满内存。
        """
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
                # 8 字节步进：只在 8 字节对齐的槽位上找指针
                start = (-address) % 8
                for off in range(start, want - 7, 8):
                    value = int.from_bytes(data[off:off + 8], "little")
                    if pointer_filter(value):
                        yield address + off, value
                address += want

    def collect_pointers(self, ranges=None, chunk: int = 8 << 20,
                         pointer_filter=None, progress=None) -> list[tuple[int, int]]:
        """``iter_pointers`` 的列表版本（小范围用；大范围请用生成器）。"""
        return list(self.iter_pointers(ranges, chunk, pointer_filter, progress))

    def pointer_targets(self, ptr: int, offsets, depth: int = 32) -> list[int]:
        """给定指针与其候选偏移，返回所有能读出可读地址的候选 ``ptr + off``。"""
        return [ptr + off for off in offsets]


def enumerate_pointer_value(reader: "ProcessMemoryReader", address: int) -> int | None:
    """便利函数：读一个 8 字节指针值（失败 None）。"""
    return reader.read_u64(address)


def describe_regions(regions, limit: int = 12) -> str:
    """区域列表 → 简短文本（日志用）。"""
    lines = []
    for region in list(regions)[:limit]:
        kind = "image" if region.is_image else ("heap" if region.is_private else "other")
        lines.append(f"  0x{region.base:012X} +0x{region.size:X} {kind}")
    if len(regions) > limit:
        lines.append(f"  ...（共 {len(regions)} 段）")
    return "\n".join(lines)


def main() -> int:  # 简易自检：python -m functions.hook.memory [进程名]
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
