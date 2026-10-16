from __future__ import annotations

import json
import os
import struct
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_DLL = r"D:\steam\steamapps\common\Limbus Company\GameAssembly.dll"

def dll_from_index() -> str:
    p = os.path.join(REPO, "cache", "hook", "hook_index.json")
    try:
        with open(p, "r", encoding="utf-8") as fh:
            game = json.load(fh).get("game") or {}
        return game.get("path") or ""
    except Exception:
        return ""

def parse_exports(path: str) -> list[str]:
    with open(path, "rb") as fh:
        data = fh.read()

    e_lfanew = struct.unpack_from("<I", data, 0x3C)[0]
    if data[e_lfanew:e_lfanew + 4] != b"PE\0\0":
        raise ValueError("不是有效 PE 文件")
    coff = e_lfanew + 4
    n_sec = struct.unpack_from("<H", data, coff + 2)[0]
    opt_size = struct.unpack_from("<H", data, coff + 16)[0]
    opt = coff + 20
    magic = struct.unpack_from("<H", data, opt)[0]
    pe32plus = magic == 0x20B

    dd = opt + (112 if pe32plus else 96)
    exp_rva = struct.unpack_from("<I", data, dd)[0]

    secs = []
    so = opt + opt_size
    for i in range(n_sec):
        b = so + i * 40
        name = data[b:b + 8].rstrip(b"\0").decode("latin1")
        vsize, vaddr, rsize, raddr = struct.unpack_from("<IIII", data, b + 8)
        secs.append((name, vaddr, vsize, raddr, rsize))

    def rva2off(rva: int) -> int | None:
        for _n, vaddr, vsize, raddr, rsize in secs:
            if vaddr <= rva < vaddr + max(vsize, rsize):
                return raddr + (rva - vaddr)
        return None

    eo = rva2off(exp_rva)
    if eo is None:
        raise ValueError("没有导出目录")
    n_names = struct.unpack_from("<I", data, eo + 24)[0]
    names_rva = struct.unpack_from("<I", data, eo + 32)[0]
    no = rva2off(names_rva)
    if no is None:
        return []

    out = []
    for i in range(n_names):
        (nrva,) = struct.unpack_from("<I", data, no + i * 4)
        o = rva2off(nrva)
        if o is None:
            continue
        end = data.find(b"\0", o)
        out.append(data[o:end].decode("latin1"))
    return out

def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else (dll_from_index() or DEFAULT_DLL)
    if path and os.path.isdir(path):
        path = os.path.join(path, "GameAssembly.dll")
    if not os.path.isfile(path):
        print(f"找不到 DLL: {path}")
        return 1
    size = os.path.getsize(path)
    print(f"DLL      : {path}")
    print(f"大小     : {size:,} 字节 ({size / 1048576:.1f} MB)")
    names = parse_exports(path)
    print(f"导出总数 : {len(names)}")

    il2 = sorted(n for n in names if n.startswith("il2cpp_"))
    print(f"il2cpp_* : {len(il2)}")
    for n in il2:
        print(f"   {n}")

    if not il2:
        print("   (无 —— 引擎 API 未导出，只能走内存扫描)")

    want = [
        "il2cpp_domain_get", "il2cpp_domain_get_assemblies",
        "il2cpp_class_from_name", "il2cpp_class_get_static_field_data",
        "il2cpp_field_get_offset", "il2cpp_class_get_field_from_name",
        "il2cpp_assembly_get_image", "il2cpp_thread_attach",
        "il2cpp_free", "il2cpp_alloc",
    ]
    have = set(names)
    print("\n关键 API:")
    for w in want:
        print(f"   {'OK ' if w in have else '-- '} {w}")

    other = sorted(n for n in names if not n.startswith("il2cpp_"))
    print(f"\n其它导出（前 40，共 {len(other)}）:")
    for n in other[:40]:
        print(f"   {n}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
