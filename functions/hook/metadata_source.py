"""取得"标准明文 global-metadata.dat"的三条路（按可靠性排序）。

Limbus 的 ``global-metadata.dat`` 是**被保护过的**：文件头没有 IL2CPP 的
标准魔数 ``0xFAB11BAF``（实测前 17 MB 熵 ≈ 8.0，属于加密/置乱区），
所以 Il2CppDumper 直接读磁盘文件会报
``ERROR: Metadata file supplied is not valid metadata file``。

本模块负责把"能喂给 Il2CppDumper 的标准明文 metadata"弄到手：

1. ``disk``    磁盘文件本身就是标准明文（魔数正确）→ 直接用（游戏未加保护时）
2. ``static``  离线静态解密：``metadata_recovery`` 流水线
   （定位 GameAssembly.dll 里的解密入口 → 参数提取 → 结构验证 → 求解 →
   标准文件重建，约 40 秒，无需游戏运行）
3. ``memory``  运行时动态 dump：在游戏进程内存里按"标准魔数 + 磁盘明文尾部
   锚点"找到运行时解密后的 metadata 缓冲，整段读出来
   （纯 ctypes，不需要 Frida；需要游戏正在运行）

三条路都做同一套校验（魔数 / 版本 / 节范围 / string 节含 ``mscorlib``），
只有通过校验的产物才会被返回。
"""

from __future__ import annotations

import os
import struct
from dataclasses import dataclass, field

from . import paths as paths_mod
from .memory import ProcessMemoryReader

METADATA_MAGIC = 0xFAB11BAF
# 已知的 IL2CPP metadata 版本（39 = 本仓库验证过的当前版本；其它仅作为"看起来合法"的判据）
KNOWN_VERSIONS = (24, 27, 29, 31, 35, 37, 39, 40, 41, 42)
DEFAULT_VERSION = 39

# 运行时 dump 的扫描门槛：metadata 缓冲本身 ≥ 这个尺寸才会被优先扫描
_MIN_SCAN_SIZE = 32 << 20
_MAX_METADATA_SIZE = 256 << 20


# --------------------------------------------------------------------------- 头部校验


@dataclass
class MetadataHeader:
    version: int
    section_count: int
    max_end: int          # max(offset+size)：文件至少要有这么长
    sections: list[tuple[int, int]] = field(default_factory=list)
    layout: str = ""


def _section_count_from_first_offset(first_offset: int, stride: int) -> int | None:
    """用第一节的偏移反推头部里有多少节。

    标准 metadata 的第一节紧跟在头部后面，所以
    ``first_offset == 8 + 节数 * 每节字节数``（每个节在头部占 ``stride`` 个 u32）。
    这个自洽关系让“头部到底是 2 元组还是 3 元组”可以精确判定：
    算出来的节数不是整数的那套布局直接排除。
    """
    if first_offset < 8:
        return None
    unit = stride * 4
    if (first_offset - 8) % unit:
        return None
    count = (first_offset - 8) // unit
    return count if 1 <= count <= 64 else None


def _walk_sections(values: list[int], stride: int) -> list[tuple[int, int]] | None:
    """按给定步长读出节表（stride=2：(offset,size)；stride=3：(offset,size,count)）。

    节数由第一节的偏移反推（见 ``_section_count_from_first_offset``），
    所以不会把头部后面的节数据当成“更多节”。推不出来则返回 None。
    """
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
    """给一套（布局, 节表）打分，用于自动判别头部到底是 2 元组还是 3 元组。"""
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
    """校验标准 IL2CPP metadata 头，返回节表信息；不合法返回 None。

    头部布局随版本变化：

    - 经典（如 v24~v29）：``(offset, size)`` 对
    - 较新（本项目实测的 v39）：``(offset, size, count)`` 三元组

    两者用"节偏移是否严格递增/末节是否落在文件末尾"自动判别，不写死版本号。
    """
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
    """读文件头并校验（只读前 4KB，带上文件大小做交叉验证）。"""
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as fh:
            return parse_header(fh.read(4096), reference_size=size)
    except OSError:
        return None


def is_standard_metadata(path: str) -> bool:
    """磁盘文件是否为标准明文 metadata。"""
    return header_from_file(path) is not None


def _validate_file(path: str) -> tuple[bool, str]:
    """校验磁盘上的（解密后的）metadata 文件是否完整可用。"""
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
    """流式检查文件是否包含某段字节（避免整文件读进内存）。"""
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
    """校验内存 dump 出来的整段数据是否是完整可用的 metadata。"""
    header = parse_header(data)
    if header is None:
        return False, "魔数/头部非法"
    if header.max_end > len(data):
        return False, (f"节范围越界（需要 {header.max_end} 字节，实际 {len(data)}）")
    if b"mscorlib" not in data[-8 << 20:] and b"mscorlib" not in data[:_MIN_SCAN_SIZE]:
        return False, "未在 string 节附近找到 mscorlib（可能是加密残留）"
    return True, f"version={header.version} 节数≈{header.section_count} size={len(data)}"


# --------------------------------------------------------------------------- 结果对象


@dataclass
class MetadataResult:
    """可用的标准明文 metadata（或失败原因）。"""

    ok: bool
    source: str = ""            # disk / static / memory / ""
    path: str = ""
    version: int = 0
    encrypted: bool = False     # 磁盘上的原始文件是否被保护过
    sha1: str = ""
    size: int = 0
    detail: str = ""
    extras: dict = field(default_factory=dict)

    def describe(self) -> str:
        if not self.ok:
            return f"[metadata] 获取失败: {self.detail}"
        return (f"[metadata] 来源={self.source} version={self.version} "
                f"size={self.size} ({self.detail})")


# --------------------------------------------------------------------------- 1) 静态解密


def capstone_available() -> bool:
    try:
        from .metadata_recovery import capstone_available as _impl
        return bool(_impl())
    except Exception:
        return False


def install_capstone(on_log=None) -> dict:
    """用当前解释器 pip 安装 capstone（静态解密依赖它做反汇编）。"""
    try:
        from .metadata_recovery import install_capstone as _impl
        return _impl(on_log) # type: ignore
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "message": f"capstone 安装入口不可用: {exc}"}


def decrypt_static(metadata_path: str, dll_path: str, on_log=None,
                   out_dir: str = "", version: int = DEFAULT_VERSION,
                   expect_sha256: str = "") -> MetadataResult:
    """静态解密流水线（约 40 秒，不需要游戏运行）。"""
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
    """读文件头 + 尾部（少量取样用，完整校验请用 ``_validate_file``）。"""
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


# --------------------------------------------------------------------------- 2) 运行时 dump


def dump_from_memory(disk_metadata: str, process_name: str = "LimbusCompany.exe",
                     on_log=None, out_path: str = "",
                     reader: ProcessMemoryReader | None = None) -> MetadataResult:
    """在运行中的游戏进程里把解密后的 metadata 整段 dump 出来。

    算法（两条路，互相验证）：

    A. 直接找标准魔数 ``AF 1B B1 FA``：先扫"尺寸 ≥ 32 MB 的私有区域"
       （解密后的 metadata 缓冲就在这类区域里），找不到再全量扫。
    B. 用磁盘文件的**明文尾部**做锚点（加密只覆盖前半段，尾部是明文）：
       在内存里搜到这段字节后，按"锚点在文件里的偏移"反推头部地址，
       再核对那里的魔数。

    找到头部后，用头部里的节范围算出 metadata 长度，把那一段整块读出来。
    """
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

        # ---- A. 直接搜魔数
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

        # ---- B. 磁盘明文尾部锚点
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
    """分块读取大段内存（单块失败时降级为逐块 4KB，尽量拿到数据）。"""
    out = bytearray()
    offset = 0
    while offset < size:
        want = min(chunk, size - offset)
        data = reader.read(address + offset, want)
        if data is None:
            # 逐页重试，失败页留 0（metadata 里 0 填充区本来就多）
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
    """游戏在跑时，直接读内存里解密后的 metadata 版本号（静态解密版本表兜底用）。"""
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


# --------------------------------------------------------------------------- 统一入口


def obtain_metadata(metadata_path: str, gameassembly_path: str, on_log=None,
                    allow_static: bool = True, allow_memory: bool = True,
                    process_name: str = "LimbusCompany.exe",
                    dump_dir: str = "", version: int = DEFAULT_VERSION,
                    prefer_memory: bool | None = None) -> MetadataResult:
    """按 disk → (memory | static) → … 顺序拿到可用的标准 metadata。

    ``prefer_memory`` 为 None 时自动判断：游戏在跑就优先用内存 dump
    （只读几 MB，几秒就完事），没跑才走静态解密（约 40 秒、吃 capstone）。
    """
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
