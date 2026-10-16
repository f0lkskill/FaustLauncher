from __future__ import annotations

import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from functions.hook.memory import ProcessMemoryReader  # noqa: E402

CHUNK = 8 << 20
OVERLAP = 16

def find_value(reader: ProcessMemoryReader, target: int,
               ranges, limit: int = 24) -> list[int]:
    needle = struct.pack("<Q", target)
    hits: list[int] = []
    for r in ranges:
        pos = r.base
        while pos < r.end:
            size = min(CHUNK, r.end - pos)
            buf = reader.read(pos, size)
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
            pos += size if size <= OVERLAP else size - OVERLAP
    return hits

def try_string(reader: ProcessMemoryReader, v: int) -> str:
    if not v or v < 0x10000:
        return ""
    try:
        s = reader.read_cstring(v, 48)
    except Exception:
        return ""
    return s if s and s.isprintable() else ""

def main() -> int:
    rvas = [int(a, 16) for a in sys.argv[1:]]
    if not rvas:
        rvas = [0xBBCF60]

    reader = ProcessMemoryReader()
    if not reader.attach(timeout=3.0):
        print("附加失败（游戏没在跑？）")
        return 1

    base = reader.module_base("GameAssembly.dll") or 0
    mod = reader.module("GameAssembly.dll")
    print(f"GameAssembly.dll  base=0x{base:X}  size=0x{mod.size:X}")
    regions = reader.regions(readable_only=True)
    total = sum(r.size for r in regions)
    print(f"可读区域 {len(regions)} 段，共 {total / 1048576:.0f} MB")

    for rva in rvas:
        target = base + rva
        print(f"\n{'=' * 66}\nRVA 0x{rva:X}  ->  methodPointer 0x{target:X}\n{'=' * 66}")
        hits = find_value(reader, target, regions)
        print(f"命中 {len(hits)} 处")
        for h in hits[:8]:
            print(f"\n-- MethodInfo? @ 0x{h:X}")
            for i in range(14):
                v = reader.read_u64(h + i * 8)
                if v is None:
                    break
                s = try_string(reader, v)
                mark = "   <-- methodPointer" if i == 0 else ""
                line = f"   +0x{i * 8:02X} = 0x{v:016X}{mark}"
                print(line)
                if s:
                    print(f"              str: {s!r}")
    reader.detach()
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
