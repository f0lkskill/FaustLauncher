"""PE 文件小工具：节表解析、RVA ↔ 文件偏移、按 RVA 取字节。

用途：
- 生成 hook 目标的 ``prologue``（目标函数前 N 字节，DLL 侧用它做版本自检）
- 把 PE 节表换算成"进程内的模块内存范围"，让运行时扫描只扫 .data 之类
  真正会放指针的节（156 MB 的 GameAssembly.dll 全扫一遍没必要）

只依赖标准库。
"""

from __future__ import annotations

import os
import struct
from dataclasses import dataclass

# 节特性位
IMAGE_SCN_MEM_WRITE = 0x80000000
IMAGE_SCN_MEM_READ = 0x40000000
IMAGE_SCN_MEM_EXECUTE = 0x20000000
IMAGE_SCN_CNT_CODE = 0x00000020
IMAGE_SCN_CNT_INITIALIZED_DATA = 0x00000040
IMAGE_SCN_CNT_UNINITIALIZED_DATA = 0x00000080


@dataclass(frozen=True)
class PeSection:
    name: str
    virtual_address: int      # RVA
    virtual_size: int
    raw_offset: int           # 文件偏移
    raw_size: int
    characteristics: int

    @property
    def size_in_image(self) -> int:
        return max(self.virtual_size, self.raw_size)

    @property
    def writable(self) -> bool:
        return bool(self.characteristics & IMAGE_SCN_MEM_WRITE)

    @property
    def executable(self) -> bool:
        return bool(self.characteristics & (IMAGE_SCN_MEM_EXECUTE | IMAGE_SCN_CNT_CODE))


class PeFile:
    """惰性读取的 PE 文件（只解析头部与节表，不载入整个文件）。"""

    def __init__(self, path: str) -> None:
        self.path = path
        self.sections: list[PeSection] = []
        self.image_base = 0
        self.timestamp = 0
        self.machine = 0
        self._parse()

    def _parse(self) -> None:
        with open(self.path, "rb") as fh:
            head = fh.read(0x1000)
        if head[:2] != b"MZ":
            raise ValueError(f"不是 PE 文件（缺少 MZ 头）: {self.path}")
        pe_off = struct.unpack_from("<I", head, 0x3C)[0]
        if head[pe_off:pe_off + 4] != b"PE\x00\x00":
            raise ValueError(f"PE 签名错误: {self.path}")
        self.machine = struct.unpack_from("<H", head, pe_off + 4)[0]
        self.timestamp = struct.unpack_from("<I", head, pe_off + 8)[0]
        num_sections = struct.unpack_from("<H", head, pe_off + 6)[0]
        opt_size = struct.unpack_from("<H", head, pe_off + 20)[0]
        opt_off = pe_off + 24
        magic = struct.unpack_from("<H", head, opt_off)[0]
        if magic == 0x20B:                     # PE32+
            self.image_base = struct.unpack_from("<Q", head, opt_off + 24)[0]
        else:                                   # PE32
            self.image_base = struct.unpack_from("<I", head, opt_off + 28)[0]
        off = opt_off + opt_size
        for _ in range(num_sections):
            raw = head[off:off + 40]
            if len(raw) < 40:
                break
            name = raw[:8].rstrip(b"\x00").decode("latin1", "replace")
            vsize, va, rsize, roff = struct.unpack_from("<IIII", raw, 8)
            chars = struct.unpack_from("<I", raw, 36)[0]
            self.sections.append(PeSection(name, va, vsize, roff, rsize, chars))
            off += 40

    # ---------------------------------------------------------------- 换算
    def rva_to_offset(self, rva: int) -> int | None:
        for sec in self.sections:
            if sec.virtual_address <= rva < sec.virtual_address + sec.size_in_image:
                return sec.raw_offset + (rva - sec.virtual_address)
        return None

    def read_at_rva(self, rva: int, size: int) -> bytes:
        off = self.rva_to_offset(rva)
        if off is None:
            raise ValueError(f"RVA 0x{rva:X} 不在任何节内（{os.path.basename(self.path)}）")
        with open(self.path, "rb") as fh:
            fh.seek(off)
            data = fh.read(size)
        if len(data) < size:
            raise ValueError(f"RVA 0x{rva:X} 处读取不足 {size} 字节")
        return data

    def prologue(self, rva: int, size: int = 16) -> bytes:
        """目标函数前 ``size`` 字节（版本自检用；越界返回空）。"""
        try:
            return self.read_at_rva(rva, size)
        except (ValueError, OSError):
            return b""

    def data_ranges(self, writable_only: bool = True) -> list[tuple[int, int]]:
        """(RVA, 长度) 列表：可写数据节（默认）或全部非代码节。"""
        out = []
        for sec in self.sections:
            if writable_only and not sec.writable:
                continue
            if not writable_only and sec.executable:
                continue
            out.append((sec.virtual_address, sec.size_in_image))
        return out


def prologue_hex(data: bytes) -> str:
    """字节 → ``"48 89 5C 24 08"`` 形式（与 test/damage_log.py 的 payload 一致）。"""
    return " ".join(f"{b:02X}" for b in data)


def parse_prologue_hex(text: str) -> bytes:
    """``"48 89 5C"`` → bytes（解析失败返回空）。"""
    try:
        return bytes.fromhex("".join(str(text).split()))
    except ValueError:
        return b""
