"""临时诊断：直接在内存里定位 UserInfoData 实例，从而读出脑啡肽。

依据 cache/hook/dump/DD6F2022/out/dump.cs：

* ``UserInfoData._uid``     @ +0x18 (dump.cs:629108, long)
* ``UserInfoData._level``   @ +0x20 (dump.cs:629109, int)
* ``UserInfoData._exp``     @ +0x24 (dump.cs:629110, int)
* ``UserInfoData._stamina`` @ +0x28 (dump.cs:629111, int)   <- 脑啡肽
* ``UserDataManager._userInfo`` @ +0x18 (dump.cs:628264) 持有它的引用

思路：不去找 Il2CppClass（那一路已证实走不通），而是用**字段布局本身**当指纹。
``_level``(1..80) + ``_exp`` + ``_stamina``(<1024) 这 12 字节的联合概率极低，
用正则可以直接把候选压到个位数。

用法::

    python tools/diag/_find_userinfo.py
"""
from __future__ import annotations

import os
import re
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from functions.hook.memory import ProcessMemoryReader  # noqa: E402

CHUNK = 8 << 20

# +0x20: level(1..80) | +0x24: exp(任意 int32) | +0x28: stamina(0..1023)
PAT = re.compile(rb"[\x01-\x50]\x00\x00\x00[\x00-\xff]{4}[\x00-\xff][\x00-\x03]\x00\x00")
TAIL = 64  # 块与块之间保留的重叠，避免跨块匹配丢失


def read_i32(reader: ProcessMemoryReader, addr):
    try:
        b = reader.read(addr, 4)
    except Exception:  # noqa: BLE001
        return None
    return struct.unpack("<i", b)[0] if b and len(b) == 4 else None


def read_u64(reader: ProcessMemoryReader, addr):
    try:
        return reader.read_u64(addr)
    except Exception:  # noqa: BLE001
        return None


def scan_pattern(reader: ProcessMemoryReader, ranges) -> list[int]:
    """返回所有候选结构基址（匹配位置 - 0x20）。"""
    bases: list[int] = []
    total = sum(r.size for r in ranges)
    done = 0
    t0 = time.time()
    for idx, r in enumerate(ranges):
        pos = r.base
        while pos < r.end:
            size = min(CHUNK, r.end - pos)
            if size <= 0:
                break
            try:
                buf = reader.read(pos, size)
            except Exception:  # noqa: BLE001
                buf = None
            if buf:
                for m in PAT.finditer(buf):
                    bases.append(pos + m.start() - 0x20)
            pos += max(1, size - TAIL)
        done += r.size
        if idx % 200 == 0:
            print(f"   [pat] {idx + 1}/{len(ranges)} 段 "
                  f"{done / 1048576:.0f}/{total / 1048576:.0f} MB "
                  f"{time.time() - t0:.0f}s 候选 {len(bases)}", flush=True)
    return bases


def find_refs(reader: ProcessMemoryReader, value: int, ranges, limit: int = 24) -> list[int]:
    """找值恰好等于 value 的 8 字节槽。"""
    needle = struct.pack("<Q", value)
    hits: list[int] = []
    for r in ranges:
        pos = r.base
        while pos < r.end:
            size = min(CHUNK, r.end - pos)
            if size <= 0:
                break
            try:
                buf = reader.read(pos, size)
            except Exception:  # noqa: BLE001
                buf = None
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
            pos += max(1, size - 8)
    return hits


def main() -> int:
    reader = ProcessMemoryReader()
    if not reader.attach(timeout=3.0):
        print("附加失败（游戏没在跑？）")
        return 1

    base = reader.module_base("GameAssembly.dll") or 0
    mod = reader.module("GameAssembly.dll")
    print(f"模块 base=0x{base:X} size=0x{mod.size:X}", flush=True)

    allr = reader.regions(readable_only=True)
    priv = [r for r in allr if r.is_private and r.size >= 0x1000]
    print(f"私有可读(>=4K) {len(priv)} 段 {sum(r.size for r in priv) / 1048576:.0f} MB",
          flush=True)

    bases = scan_pattern(reader, priv)
    print(f"\n布局指纹候选 {len(bases)} 个", flush=True)

    for cand in bases[:24]:
        if cand % 8:
            continue
        klass = read_u64(reader, cand)
        sf = read_u64(reader, cand + 8)
        uid = read_u64(reader, cand + 0x18)
        lvl = read_i32(reader, cand + 0x20)
        exp = read_i32(reader, cand + 0x24)
        st = read_i32(reader, cand + 0x28)
        print(f"\n候选 0x{cand:X}", flush=True)
        print(f"   +0x00 klass?=0x{klass or 0:X}   +0x08=0x{sf or 0:X}", flush=True)
        print(f"   +0x18 _uid={uid}  +0x20 _level={lvl}  "
              f"+0x24 _exp={exp}  +0x28 _stamina={st}", flush=True)

        refs = find_refs(reader, cand, allr, 8)
        print(f"   引用槽 {len(refs)} 个: {[hex(x) for x in refs]}", flush=True)
        for slot in refs[:6]:
            um = slot - 0x18  # UserDataManager._userInfo 在 +0x18
            umk = read_u64(reader, um)
            print(f"      slot=0x{slot:X} -> 若为 _userInfo，则 UserDataManager=0x{um:X} "
                  f"klass?=0x{umk or 0:X}", flush=True)

    reader.detach()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
