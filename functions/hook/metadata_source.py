
from __future__ import annotations

import os
import struct
from dataclasses import dataclass, field

from . import paths as paths_mod
from .memory import ProcessMemoryReader

METADATA_MAGIC = 0xFAB11BAF
KNOWN_VERSIONS = (24, 27, 29, 31, 35, 37, 39, 40, 41, 42)
DEFAULT_VERSION = 39

_MIN_SCAN_SIZE = 32 << 20
_MAX_METADATA_SIZE = 256 << 20

@dataclass
class MetadataHeader:
    version: int
    section_count: int
    max_end: int
    sections: list[tuple[int, int]] = field(default_factory=list)
    layout: str = ""

def _section_count_from_first_offset(first_offset: int, stride: int) -> int | None:
    if first_offset < 8:
        return None
    unit = stride * 4
    if (first_offset - 8) % unit:
        return None
    count = (first_offset - 8) // unit
    return count if 1 <= count <= 64 else None

def _walk_sections(values: list[int], stride: int) -> list[tuple[int, int]] | None:
    if not values:
        return None
    count = _section_count_from_first_offset(int(values[0]), stride)
    if count is None or len(values) < count * stride:
        return None
    sections: list[tuple[int, int]] = []
    for index in range(count):
        offset = int(values[stride * index])
        size = int(values[stride * index + 1])
        if size < 0 or size > _MAX_METADATA_SIZE or offset > _MAX_METADATA_SIZE:
            return None
        sections.append((offset, size))
    return sections

def _score_layout(sections: list[tuple[int, int]], stride: int,
                  reference_size: int = 0) -> tuple:
    filled = [(offset, size) for offset, size in sections if size > 0]
    if not filled:
        return (-1,)
    offsets = [offset for offset, _size in filled]
    monotonic = 1 if all(a < b for a, b in zip(offsets, offsets[1:])) else 0
    max_end = max(offset + size for offset, size in filled)
    in_bounds = 1 if (not reference_size or max_end <= reference_size) else 0
    exact = 1 if (reference_size and max_end == reference_size) else 0
    header_len = 8 + len(sections) * stride * 4
    self_consistent = 1 if filled[0][0] == header_len else 0
    return (monotonic, in_bounds, exact, self_consistent, len(filled))

def parse_header(data: bytes, reference_size: int = 0) -> MetadataHeader | None:
    if len(data) < 16 or struct.unpack_from("<I", data, 0)[0] != METADATA_MAGIC:
        return None
    version = struct.unpack_from("<i", data, 4)[0]
    if version <= 0 or version > 100:
        return None
    count = min(len(data) // 4, 8 + 64 * 3)
    values = list(struct.unpack_from("<%dI" % count, data, 0))[2:]
    best: tuple | None = None
    best_stride = 0
    best_sections: list[tuple[int, int]] = []
    for stride in (3, 2):
        sections = _walk_sections(values, stride)
        if not sections:
            continue
        score = _score_layout(sections, stride, reference_size)
        if score[0] <= 0:
            continue
        if best is None or score > best:
            best, best_stride, best_sections = score, stride, sections
    if best is None:
        return None
    max_end = max(offset + size for offset, size in best_sections if size > 0)
    if max_end <= 0:
        return None
    return MetadataHeader(version=version, section_count=len(best_sections),
                          max_end=max_end, sections=best_sections,
                          layout=f"stride{best_stride}")

def header_from_file(path: str) -> MetadataHeader | None:
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as fh:
            return parse_header(fh.read(4096), reference_size=size)
    except OSError:
        return None

def is_standard_metadata(path: str) -> bool:
    return header_from_file(path) is not None

def _validate_file(path: str) -> tuple[bool, str]:
    size = os.path.getsize(path)
    header = header_from_file(path)
    if header is None:
        return False, "魔数/头部非法"
    if header.max_end > size:
        return False, f"节范围越界（需要 {header.max_end} 字节，文件只有 {size}）"
    if not _file_contains(path, b"mscorlib"):
        return False, "全文没有 mscorlib（string 节异常）"
    return True, (f"version={header.version} 节数={header.section_count}"
                  f"({header.layout}) size={size}")

def _file_contains(path: str, needle: bytes, chunk: int = 8 << 20) -> bool:
    overlap = len(needle) - 1
    tail = b""
    try:
        with open(path, "rb") as fh:
            while True:
                data = fh.read(chunk)
                if not data:
                    return False
                if needle in tail + data:
                    return True
                tail = data[-overlap:] if overlap else b""
    except OSError:
        return False

def _validate_payload(data: bytes) -> tuple[bool, str]:
    header = parse_header(data)
    if header is None:
        return False, "魔数/头部非法"
    if header.max_end > len(data):
        return False, (f"节范围越界（需要 {header.max_end} 字节，实际 {len(data)}）")
    if b"mscorlib" not in data[-8 << 20:] and b"mscorlib" not in data[:_MIN_SCAN_SIZE]:
        return False, "未在 string 节附近找到 mscorlib（可能是加密残留）"
    return True, f"version={header.version} 节数≈{header.section_count} size={len(data)}"

@dataclass
class MetadataResult:

    ok: bool
    source: str = ""
    path: str = ""
    version: int = 0
    encrypted: bool = False
    sha1: str = ""
    size: int = 0
    detail: str = ""
    extras: dict = field(default_factory=dict)

    def describe(self) -> str:
        if not self.ok:
            return f"[metadata] 获取失败: {self.detail}"
        return (f"[metadata] 来源={self.source} version={self.version} "
                f"size={self.size} ({self.detail})")

def capstone_available() -> bool:
    try:
        from .metadata_recovery import capstone_available as _impl
        return bool(_impl())
    except Exception:
        return False

def install_capstone(on_log=None) -> dict:
    try:
        from .metadata_recovery import install_capstone as _impl
        return _impl(on_log) # type: ignore
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "message": f"capstone 安装入口不可用: {exc}"}

def decrypt_static(metadata_path: str, dll_path: str, on_log=None,
                   out_dir: str = "", version: int = DEFAULT_VERSION,
                   expect_sha256: str = "") -> MetadataResult:
    log = on_log or (lambda _m: None)
    if not capstone_available():
        return MetadataResult(False, detail="缺少 capstone（pip install capstone 后重试）")
    if not out_dir:
        out_dir = paths_mod.cache_path("decrypt", "run_%s" % _stamp())
    try:
        from .metadata_recovery import run_recovery
    except Exception as exc:  # noqa: BLE001
        return MetadataResult(False, detail=f"解密流水线导入失败: {exc}")
    try:
        result = run_recovery(metadata_path, dll_path, expect_sha256=expect_sha256,
                              version=version, out_dir=out_dir, on_log=log)
    except Exception as exc:  # noqa: BLE001
        return MetadataResult(False, detail=f"解密异常: {exc}")
    std = (result.get("outputs") or {}).get("standard_rebuilt", "")
    if not result.get("success") or not os.path.isfile(std):
        return MetadataResult(
            False, detail=f"流水线未通过: verdicts={result.get('verdicts')} run_dir={result.get('run_dir')}",
            extras={"run_dir": result.get("run_dir"), "verdicts": result.get("verdicts")})
    ok, why = _validate_file(std)
    header = header_from_file(std) or MetadataHeader(version, 0, 0)
    if not ok:
        return MetadataResult(False, detail=f"重建文件校验失败: {why}",
                              extras={"run_dir": result.get("run_dir")})
    return MetadataResult(
        ok=True, source="static", path=std, version=header.version, encrypted=True,
        sha1=paths_mod.file_sha1(std), size=os.path.getsize(std),
        detail=f"{why}；流水线 {result.get('elapsed_sec')}s",
        extras={"run_dir": result.get("run_dir"), "verdicts": result.get("verdicts")})

def _read_head_tail(path: str, head: int = 1 << 20, tail: int = 8 << 20) -> bytes:
    with open(path, "rb") as fh:
        data = fh.read(head)
        try:
            fh.seek(-tail, os.SEEK_END)
            data += fh.read(tail)
        except OSError:
            pass
    return data

def _stamp() -> str:
    import time
    return time.strftime("%Y%m%d_%H%M%S")

def dump_from_memory(disk_metadata: str, process_name: str = "LimbusCompany.exe",
                     on_log=None, out_path: str = "",
                     reader: ProcessMemoryReader | None = None) -> MetadataResult:
    log = on_log or (lambda _m: None)
    owner = reader if reader is not None else ProcessMemoryReader(process_name)
    temp_attach = reader is None
    if not owner.attached and not owner.attach():
        return MetadataResult(False, encrypted=not is_standard_metadata(disk_metadata),
                              detail=f"未找到游戏进程 {process_name}（运行时 dump 需要游戏正在运行）")
    try:
        module = owner.module("GameAssembly.dll")
        log(f"[metadata] 已附加游戏进程 PID={owner.pid}"
            + (f"，GameAssembly.dll base=0x{module.base:012X}" if module else ""))

        magic = struct.pack("<I", METADATA_MAGIC)
        candidates: list[tuple[str, int]] = []
        big = [(r.base, r.size) for r in owner.regions(include_images=False)
               if r.size >= _MIN_SCAN_SIZE]
        for tag, ranges in (("大区域", big), ("全量", None)):
            if ranges is not None and not ranges:
                continue
            count = len(ranges) if ranges is not None else len(owner.regions(include_images=False))
            log(f"[metadata] 阶段 A/{tag}：搜索标准魔数（{count} 段）")
            hits = owner.scan_bytes(magic, ranges=ranges, limit=64)
            for addr in hits:
                head = owner.read(addr, 4096)
                if not head:
                    continue
                header = parse_header(head)
                if header and header.version in KNOWN_VERSIONS:
                    candidates.append((f"magic@{tag}", addr))
            if candidates:
                break

        if not candidates:
            try:
                size = os.path.getsize(disk_metadata)
                with open(disk_metadata, "rb") as fh:
                    fh.seek(max(0, size - (1 << 20)))
                    tail = fh.read()
                anchor = tail[len(tail) // 2: len(tail) // 2 + 64]
                if len(anchor) >= 32:
                    anchor_off = max(0, size - (1 << 20)) + len(tail) // 2
                    log(f"[metadata] 阶段 B：用磁盘明文尾部锚点定位（文件偏移 0x{anchor_off:X}）")
                    for addr in owner.scan_bytes(anchor, limit=16):
                        head_addr = addr - anchor_off
                        head = owner.read(head_addr, 4096) if head_addr > 0 else None
                        if head and parse_header(head):
                            candidates.append(("anchor@tail", head_addr))
                            break
            except OSError as exc:
                log(f"[metadata] 阶段 B 失败: {exc}")

        if not candidates:
            return MetadataResult(False, encrypted=True,
                                  detail="内存里没找到已解密的 metadata（游戏可能还没进入主界面）")

        source, head_addr = candidates[0]
        head = owner.read(head_addr, 4096)
        header = parse_header(head or b"")
        if header is None:
            return MetadataResult(False, detail="候选地址头部校验失败")
        length = header.max_end
        if length <= 0 or length > _MAX_METADATA_SIZE:
            return MetadataResult(False, detail=f"节范围异常: {length}")
        log(f"[metadata] 命中 {source} @0x{head_addr:012X}，"
            f"version={header.version} 长度={length} ({length / 1048576:.1f} MB)，开始整段读取...")
        data = _read_large(owner, head_addr, length)
        if not data:
            return MetadataResult(False, detail="读取 metadata 缓冲失败")
        ok, why = _validate_payload(data)
        if not ok:
            return MetadataResult(False, detail=f"dump 校验失败: {why}")
        if not out_path:
            out_path = paths_mod.cache_path("dump", "memory-global-metadata.dat")
        with open(out_path, "wb") as fh:
            fh.write(data)
        log(f"[metadata] 运行时 dump 完成: {out_path} ({len(data)} 字节, {why})")
        return MetadataResult(
            ok=True, source="memory", path=out_path, version=header.version,
            encrypted=True, sha1=paths_mod.file_sha1(out_path), size=len(data),
            detail=f"{why}；内存地址 0x{head_addr:012X}",
            extras={"address": head_addr, "module_base": module.base if module else 0})
    finally:
        if temp_attach:
            owner.detach()

def _read_large(reader: ProcessMemoryReader, address: int, size: int,
                chunk: int = 8 << 20) -> bytes:
    out = bytearray()
    offset = 0
    while offset < size:
        want = min(chunk, size - offset)
        data = reader.read(address + offset, want)
        if data is None:
            data = bytearray()
            page = 0x1000
            for page_off in range(0, want, page):
                piece = reader.read(address + offset + page_off, min(page, want - page_off))
                data += piece if piece else b"\x00" * min(page, want - page_off)
            data = bytes(data)
        out += data
        offset += want
    return bytes(out)

def detect_runtime_version(process_name: str = "LimbusCompany.exe") -> int | None:
    reader = ProcessMemoryReader(process_name)
    if not reader.attach():
        return None
    try:
        magic = struct.pack("<I", METADATA_MAGIC)
        for ranges in ([(r.base, r.size) for r in reader.regions(include_images=False)
                        if r.size >= _MIN_SCAN_SIZE], None):
            for addr in reader.scan_bytes(magic, ranges=ranges, limit=32):
                head = reader.read(addr, 8)
                if head:
                    header = parse_header(head + b"\x00" * 8)
                    if header:
                        return header.version
    finally:
        reader.detach()
    return None

def obtain_metadata(metadata_path: str, gameassembly_path: str, on_log=None,
                    allow_static: bool = True, allow_memory: bool = True,
                    process_name: str = "LimbusCompany.exe",
                    dump_dir: str = "", version: int = DEFAULT_VERSION,
                    prefer_memory: bool | None = None) -> MetadataResult:
    log = on_log or (lambda _m: None)
    if is_standard_metadata(metadata_path):
        header = header_from_file(metadata_path)
        log(f"[metadata] 磁盘文件已是标准明文 (version={header.version if header else '?'})")
        return MetadataResult(True, source="disk", path=metadata_path,
                              version=header.version if header else 0, encrypted=False,
                              sha1=paths_mod.file_sha1(metadata_path),
                              size=os.path.getsize(metadata_path), detail="磁盘明文")
    log("[metadata] 磁盘文件被保护（无标准魔数）→ 需要解密")

    if prefer_memory is None:
        from .memory import is_process_running
        prefer_memory = bool(allow_memory and is_process_running(process_name))
        if prefer_memory:
            log(f"[metadata] 检测到 {process_name} 正在运行 → 优先从进程内存 dump（更快）")

    def try_memory() -> MetadataResult:
        out_path = os.path.join(dump_dir, "memory-global-metadata.dat") if dump_dir else ""
        return dump_from_memory(metadata_path, process_name, on_log=log, out_path=out_path)

    def try_static() -> MetadataResult:
        return decrypt_static(metadata_path, gameassembly_path, on_log=log,
                              out_dir=dump_dir, version=version)

    order = [("memory", try_memory), ("static", try_static)]
    if not prefer_memory:
        order.reverse()
    last: MetadataResult | None = None
    for name, func in order:
        if name == "memory" and not allow_memory:
            continue
        if name == "static" and not allow_static:
            continue
        log(f"[metadata] 尝试{'运行时内存 dump' if name == 'memory' else '静态解密（约 40 秒）'}...")
        result = func()
        if result.ok:
            return result
        log(f"[metadata] {name} 不可用: {result.detail}")
        last = result
    if last is not None:
        return last
    return MetadataResult(False, encrypted=True,
                          detail="静态解密与运行时 dump 都不可用（检查 capstone / 游戏是否在运行）")
