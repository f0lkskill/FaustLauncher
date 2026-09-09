"""Limbus Company 进程内存读取器。

当前支持读取脑啡肽容量。指针链来自桌面 ok.py:
GameAssembly.dll + 0x07BB4F90 -> 0xB8 -> 0x80 -> 0x18 -> 0x28
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes
import os
from dataclasses import dataclass


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
        """查找游戏进程，避免依赖 psutil。"""
        try:
            import subprocess

            result = subprocess.run(
                ["tasklist", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                encoding="mbcs",
                errors="replace",
                check=False,
            )
            for line in result.stdout.splitlines():
                fields = [field.strip('"') for field in line.split('","')]
                if len(fields) >= 2 and fields[0].lower() == self.process_name:
                    return int(fields[1]), 0
        except (OSError, ValueError):
            pass
        return None

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
        if not self.is_attached and not self.attach(ENKEPHALIN_TARGET):
            return None
        value = self.read_int32(ENKEPHALIN_TARGET)
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
