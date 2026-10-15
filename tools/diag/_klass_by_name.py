"""临时诊断：从类名字符串反向定位 Il2CppClass*，并尝试读出脑啡肽。

目标路径（来自 cache/hook/dump/DD6F2022/out/dump.cs）：

* ``UserDataManager`` (dump.cs:628260) 是 ``Singleton<UserDataManager>``
* ``Singleton<T>._instance`` (dump.cs:570387) 是静态字段，static_fields 内偏移 0x0
* ``UserDataManager._userInfo`` (dump.cs:628264) 实例偏移 **0x18**
* ``UserInfoData._stamina`` (dump.cs:629111) 实例偏移 **0x28**（int）

所以链是::

    klass = UserDataManager 的 Il2CppClass*
    sf    = *(klass + 0xB8)      # static_fields（索引里的 static_fields_offset=184）
    inst  = *(sf + 0x0)          # Singleton<UserDataManager>._instance
    ui    = *(inst + 0x18)       # _userInfo
    value = *(int32*)(ui + 0x28) # 脑啡肽

用法::

    python tools/diag/_klass_by_name.py UserDataManager
"""
from __future__ import annotations

import faulthandler
import os
import struct
import sys
import time

faulthandler.enable()
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from functions.hook.memory import ProcessMemoryReader  # noqa: E402

CHUNK = 8 << 20


def scan(reader: ProcessMemoryReader, needle: bytes, ranges, limit: int,
         tag: str = "") -> list[int]:
    """在 ranges 里找 needle 的所有出现，返回绝对地址。"""
    hits: list[int] = []
    step = max(1, len(needle))
    total = sum(r.size for r in ranges)
    done = 0
    t0 = time.time()
    for idx, r in enumerate(ranges):
        pos = r.base
        while pos < r.end:
            size = min(CHUNK, r.end - pos)
            if size <= 0:
                break
            buf = None
            try:
                buf = reader.read(pos, size)
            except Exception as exc:  # noqa: BLE001
                print(f"   [{tag}] read 0x{pos:X}+0x{size:X} 异常 {exc}", flush=True)
            if buf:
                start = 0
                while True:
                    i = buf.find(needle, start)
                    if i < 0:
                        break
                    hits.append(pos + i)
                    if len(hits) >= limit:
                        return hits
                    start = i + 1
            pos += max(1, size - step)
        done += r.size
        if idx % 300 == 0:
            print(f"   [{tag}] {idx + 1}/{len(ranges)} 段 "
                  f"{done / 1048576:.0f}/{total / 1048576:.0f} MB "
                  f"{time.time() - t0:.0f}s 命中 {len(hits)}", flush=True)
    return hits


def cstr(reader: ProcessMemoryReader, addr, n: int = 64) -> str:
    if not addr or addr < 0x10000 or addr > 0x7FFFFFFFFFFF:
        return ""
    try:
        return reader.read_cstring(addr, n) or ""
    except Exception:  # noqa: BLE001
        return ""


def read_i32(reader: ProcessMemoryReader, addr):
    try:
        b = reader.read(addr, 4)
    except Exception:  # noqa: BLE001
        return None
    return struct.unpack("<i", b)[0] if b and len(b) == 4 else None


def describe(reader: ProcessMemoryReader, klass: int, base: int, mod_end: int,
             want: str) -> list[str]:
    lines: list[str] = []
    try:
        image = reader.read_u64(klass)
        name = cstr(reader, reader.read_u64(klass + 0x10) or 0)
        ns = cstr(reader, reader.read_u64(klass + 0x18) or 0)
        raw = reader.read(klass, 0x20) or b""
        in_mod = bool(image and base <= image < mod_end)
        hit = bool(name == want and in_mod)
        lines.append(f"   klass=0x{klass:X} name={name!r} ns={ns!r} "
                     f"image=0x{image or 0:X} in_module={in_mod} "
                     f"-> {'*** HIT ***' if hit else '-'}")
        lines.append(f"      head {raw.hex(' ')}")
        if hit:
            sf = reader.read_u64(klass + 0xB8)
            lines.append(f"      +0xB8 static_fields = 0x{sf or 0:X}")
            if sf:
                for off in (0x0, 0x8, 0x10, 0x18):
                    v = reader.read_u64(sf + off)
                    lines.append(f"         sf+0x{off:X} = 0x{v or 0:X}")
                    if v and 0x10000 < v < 0x7FFFFFFFFFFF:
                        ui = reader.read_u64(v + 0x18)
                        lines.append(f"            [obj+0x18] _userInfo = 0x{ui or 0:X}")
                        if ui and 0x10000 < ui < 0x7FFFFFFFFFFF:
                            st = read_i32(reader, ui + 0x28)
                            lv = read_i32(reader, ui + 0x20)
                            lines.append(f"               +0x28 _stamina = {st}"
                                         f"   (+0x20 _level = {lv})")
    except Exception as exc:  # noqa: BLE001
        lines.append(f"   klass=0x{klass:X} 读取异常: {exc}")
    return lines


def main() -> int:
    names = [a for a in sys.argv[1:] if not a.startswith("--")] or ["UserDataManager"]

    reader = ProcessMemoryReader()
    if not reader.attach(timeout=3.0):
        print("附加失败（游戏没在跑？）")
        return 1

    base = reader.module_base("GameAssembly.dll") or 0
    mod = reader.module("GameAssembly.dll")
    mod_end = base + mod.size
    allr = reader.regions(readable_only=True)
    priv = [r for r in allr if r.is_private]
    print(f"模块 base=0x{base:X} size=0x{mod.size:X}", flush=True)
    print(f"私有可读 {len(priv)} 段 {sum(r.size for r in priv) / 1048576:.0f} MB "
          f"(全部可读 {len(allr)} 段)", flush=True)

    for nm in names:
        print("=" * 70, flush=True)
        print(f"类名 {nm!r}", flush=True)
        locs = scan(reader, nm.encode() + b"\0", priv, 8, "str")
        if not locs:
            print("  私有区域没有，回退全可读区域", flush=True)
            locs = scan(reader, nm.encode() + b"\0", allr, 8, "str*")
        print(f"  字符串 {len(locs)} 处: {[hex(x) for x in locs]}", flush=True)

        for s in locs[:3]:
            refs = scan(reader, struct.pack("<Q", s), allr, 12, "ref")
            print(f"  @0x{s:X} 引用槽 {len(refs)} 个: {[hex(x) for x in refs]}",
                  flush=True)
            for slot in refs[:8]:
                for line in describe(reader, slot - 0x10, base, mod_end, nm):
                    print(line, flush=True)
        print(flush=True)

    reader.detach()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
