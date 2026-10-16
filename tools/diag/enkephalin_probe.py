
from __future__ import annotations

import argparse
import contextlib
import ctypes
import ctypes.wintypes as wintypes
import io
import json
import os
import sys
import time

_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                     "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

_SILENT = ("--raw" in sys.argv or "--json" in sys.argv)
with (contextlib.redirect_stdout(io.StringIO()) if _SILENT
      else contextlib.nullcontext()):
    from functions.achievement.memory_reader import (  # noqa: E402
        ENKEPHALIN_TARGET,
        INVALID_HANDLE_VALUE,
        MODULEENTRY32,
        PROCESS_QUERY_INFORMATION,
        PROCESS_VM_READ,
        TH32CS_SNAPMODULE,
        LimbusMemoryReader,
        chain_source,
        memory_target,
    )

TARGET_PROCESS = "LimbusCompany.exe"
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

ENKEPHALIN_ACH_THRESHOLD = 100
ENKEPHALIN_SANE_MAX = 100000

EXIT_OK = 0
EXIT_NO_PROCESS = 1
EXIT_DENIED = 2
EXIT_NO_MODULE = 3
EXIT_CHAIN_BROKEN = 4
EXIT_OTHER = 5

_WINERR_HINT = {
    5: "拒绝访问 —— 游戏以管理员身份运行而本进程不是（或被安全软件拦了）。"
       "请用管理员权限重跑本脚本，或让启动器也以管理员身份运行。",
    87: "参数错误 —— PID 已经失效（游戏刚退出）。",
    6: "句柄无效 —— PID 已经失效。",
}

WIDTH = 74

def line(ch: str = "─") -> None:
    print(ch * WIDTH)

def head(title: str) -> None:
    line()
    print(title)
    line()

def ok(msg: str) -> None:
    print(f"  [ OK ] {msg}")

def bad(msg: str) -> None:
    print(f"  [FAIL] {msg}")

def info(msg: str) -> None:
    print(f"         {msg}")

def _is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:  # noqa: BLE001
        return False

def _image_path(kernel32, pid: int) -> str:
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(1024)
        buf = ctypes.create_unicode_buffer(size.value)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buf,
                                               ctypes.byref(size)):
            return buf.value
    except Exception:  # noqa: BLE001
        return ""
    finally:
        kernel32.CloseHandle(handle)
    return ""

def _module_info(kernel32, pid: int, module_name: str) -> tuple[int, int] | None:
    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPMODULE, pid)
    if snapshot in (None, INVALID_HANDLE_VALUE):
        return None
    try:
        entry = MODULEENTRY32()
        entry.dwSize = ctypes.sizeof(MODULEENTRY32)
        if not kernel32.Module32First(snapshot, ctypes.byref(entry)):
            return None
        while True:
            name = bytes(entry.szModule).split(b"\0", 1)[0].decode(
                "mbcs", errors="ignore")
            if name.lower() == module_name.lower():
                return int(entry.modBaseAddr or 0), int(entry.modBaseSize or 0)
            if not kernel32.Module32Next(snapshot, ctypes.byref(entry)):
                break
    finally:
        kernel32.CloseHandle(snapshot)
    return None

def _configure_extra_api(kernel32) -> None:
    try:
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL,
                                         wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        kernel32.QueryFullProcessImageNameW.argtypes = [
            wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD)]
        kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    except Exception:  # noqa: BLE001
        pass

def _harden_stdout() -> None:
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:  # noqa: BLE001
        pass

_PTR_MAX = 0x0000800000000000

def _pointer_verdict(pointer: int) -> str:
    if pointer == 0:
        return "NULL"
    if pointer % 8:
        return "UNALIGN"
    if pointer >= _PTR_MAX:
        return "OUTRANGE"
    return "OK"

def _index_target_meta(key: str) -> dict:
    try:
        from functions.hook import paths as paths_mod
        path = str(paths_mod.local_index_path())
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        meta = dict((data.get("targets") or {}).get(key) or {})
        meta["_gameassembly_size"] = int(
            (data.get("game") or {}).get("gameassembly_size") or 0)
        return meta
    except Exception:  # noqa: BLE001
        return {}

def _disk_module_size() -> int:
    try:
        from functions.hook import paths as paths_mod
        path = str(getattr(paths_mod.game_paths(), "gameassembly", "") or "")
        return os.path.getsize(path) if path and os.path.isfile(path) else 0
    except Exception:  # noqa: BLE001
        return 0

def _explain_break(bad_hops: list[int]) -> None:
    if bad_hops:
        where = "、".join(str(i + 1) for i in bad_hops)
        info(f"⚠ 第 {where} 跳读出的值不是合法指针（未 8 字节对齐 / 超出用户态范围）")
        info("   → 那个偏移处根本不是指针：**链已经失效**。游戏更新后模块里的")
        info("     静态槽位和结构偏移都会变，这条链需要重新定位。")
        info("   → 这不是权限问题，也不是“游戏没进主界面”能解释的。")
        info("   下一步: python -m functions.hook.main locate --key enkephalin")
    else:
        info("指针为 NULL = 那一级结构还没建立（在标题界面 / 没进镜像迷宫）。")
        info("请进到能看到脑啡肽的界面再跑一次；若任何界面都读不到，见上一条。")

def probe(reader: LimbusMemoryReader, target, *, key: str = "enkephalin",
          process: str = TARGET_PROCESS, verbose: bool = True,
          resolve: bool = True) -> dict:
    k = reader.kernel32
    result: dict = {
        "process": process, "pid": 0, "image": "",
        "open_handle": False, "win_error": 0, "error": "",
        "module": target.module_name, "module_base": 0, "module_size": 0,
        "chain_source": "", "base_offset": target.base_offset,
        "offsets": list(target.offsets), "hops": [], "final_addr": 0,
        "value": None, "exit_code": EXIT_OTHER,
        "index_meta": {}, "disk_module_size": 0, "index_gameassembly_size": 0,
        "bad_hops": [],
    }

    if verbose:
        head(f"脑啡肽内存读取自检  ({time.strftime('%Y-%m-%d %H:%M:%S')})")

    if verbose:
        line()
        print("1) 运行环境")
        info(f"Python {sys.version.split()[0]} "
             f"({ctypes.sizeof(ctypes.c_void_p) * 8} 位)")
        info(f"管理员权限: {'是' if _is_admin() else '否'}")
        if not _is_admin():
            info("提示: 游戏若以管理员身份运行, 非管理员的脚本 OpenProcess 会被拒。")

    from functions.achievement.memory_reader import _fast_find_process
    pid = int(_fast_find_process(process) or 0)
    if verbose:
        line()
        print("2) 查找游戏进程")
    if not pid:
        result["error"] = f"没有找到 {process}"
        result["exit_code"] = EXIT_NO_PROCESS
        if verbose:
            bad(result["error"])
            info("请先启动 Limbus Company（游戏在装载 GameAssembly.dll 之后才有可读的链）。")
        return result
    result["pid"] = pid
    image = _image_path(k, pid) if verbose else ""
    result["image"] = image
    if verbose:
        ok(f"PID = {pid}")
        info(f"映像: {image or '（取不到，可能需要更高权限）'}")

    if verbose:
        line()
        print("3) 解析指针链配置")
    resolved, src = target, "(direct)"
    if resolve:
        try:
            resolved = memory_target(key)
            src = chain_source(key)
        except Exception as exc:  # noqa: BLE001
            resolved, src = ENKEPHALIN_TARGET, "builtin"
            if verbose:
                bad(f"memory_target 异常, 回退内置链: {type(exc).__name__}: {exc}")
    result["chain_source"] = src
    result["base_offset"] = resolved.base_offset
    result["offsets"] = list(resolved.offsets)
    result["module"] = resolved.module_name
    if verbose:
        ok(f"来源 = {src}")
        info(f"{resolved.module_name}+0x{resolved.base_offset:X}"
             f"+{[hex(x) for x in resolved.offsets]}")
        if resolved.value_type != "int32":
            info(f"注意: 目标声明 value_type={resolved.value_type}, "
                 f"本脚本固定按 int32 读。")
        meta = _index_target_meta(key)
        if meta:
            result["index_meta"] = {k2: v for k2, v in meta.items()
                                    if not k2.startswith("_")}
            origin = meta.get("source") or "?"
            verified = meta.get("verified")
            info(f"索引元信息: source={origin}  verified={verified}  "
                 f"value_range={meta.get('value_range')}")
            if verified is False:
                info("⚠ 索引里这条链标记 verified=false —— 它从未在运行时校验过,")
                info("  只在生成索引时被原样抄录。这类链极可能已经失效。")

    if verbose:
        line()
        print("4) 打开进程句柄 (PROCESS_VM_READ | PROCESS_QUERY_INFORMATION)")
    ctypes.set_last_error(0)
    handle = k.OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION,
                           False, pid)
    err = ctypes.get_last_error()
    result["win_error"] = err
    if not handle:
        result["error"] = (f"OpenProcess 失败, GetLastError={err}"
                           f"（{_WINERR_HINT.get(err, '未知错误码')}）")
        result["exit_code"] = EXIT_DENIED if err == 5 else EXIT_OTHER
        if verbose:
            bad(result["error"])
        return result
    result["open_handle"] = True
    if verbose:
        ok(f"句柄 = {int(handle)}")

    try:
        if verbose:
            line()
            print("5) 定位模块")
        mod = _module_info(k, pid, resolved.module_name)
        if mod is None or mod[0] == 0:
            result["error"] = f"在本进程里找不到模块 {resolved.module_name}"
            result["exit_code"] = EXIT_NO_MODULE
            if verbose:
                bad(result["error"])
                info("游戏还在加载 / 读的是另一个进程 / 模块已被卸载。")
            return result
        base, size = mod
        result["module_base"], result["module_size"] = base, size
        disk = _disk_module_size()
        index_size = int(_index_target_meta(key).get("_gameassembly_size") or 0)
        result["disk_module_size"] = disk
        result["index_gameassembly_size"] = index_size
        if verbose:
            ok(f"{resolved.module_name} 基址 = 0x{base:X}")
            info(f"内存映像大小 = {size} 字节（{size / 1024 / 1024:.1f} MB）"
                 "  ← 这个值**不是**磁盘文件大小")
            if disk:
                info(f"磁盘文件大小 = {disk} 字节（{disk / 1024 / 1024:.1f} MB）")
            if index_size:
                if not disk:
                    verdict = "（没找到磁盘文件, 无法比对）"
                elif index_size == disk:
                    verdict = "一致 → 索引对应本机这一版游戏"
                else:
                    verdict = "不一致 → 索引是另一个版本, 读出的值必然是垃圾"
                info(f"索引 gameassembly_size = {index_size} → {verdict}")

        if verbose:
            line()
            print("6) 逐级解引用（Cheat Engine 语义: 读 → 加偏移, 最后再读值）")
        reader.handle = int(handle)
        reader.pid = pid
        reader.module_base = base
        reader.module_name = resolved.module_name

        address = base + resolved.base_offset
        if verbose:
            info(f"起点 = 0x{base:X} + 0x{resolved.base_offset:X} = 0x{address:X}")
        broken_at = -1
        fail_kind = ""
        fail_addr = 0
        bad_hops: list[int] = []
        for idx, offset in enumerate(resolved.offsets):
            raw = reader._read_bytes(address,
                                     ctypes.sizeof(ctypes.c_void_p))
            if raw is None:
                broken_at, fail_kind, fail_addr = idx, "read", address
                break
            pointer = int.from_bytes(raw, "little")
            nxt = pointer + offset
            verdict = _pointer_verdict(pointer)
            result["hops"].append({"index": idx, "offset": offset,
                                   "addr": address, "pointer": pointer,
                                   "next": nxt, "verdict": verdict})
            if verbose:
                info(f"[{verdict:<8}] 读 0x{address:X} → 0x{pointer:X}"
                     f"  (+{hex(offset)}) → 0x{nxt:X}")
            if verdict == "NULL":
                broken_at, fail_kind, fail_addr = idx, "null", address
                break
            if verdict != "OK":
                bad_hops.append(idx)
            address = nxt

        result["bad_hops"] = bad_hops

        if broken_at >= 0:
            hop_no = len(result["hops"]) + 1
            if fail_kind == "read":
                result["error"] = (f"指针链在第 {hop_no} 跳断裂："
                                   f"读 0x{fail_addr:X} 失败（该地址不可读）")
            else:
                result["error"] = (f"指针链在第 {hop_no} 跳断裂："
                                   f"指针为 NULL（读 0x{fail_addr:X} 得到 0）")
            result["exit_code"] = EXIT_CHAIN_BROKEN
            if verbose:
                bad(result["error"] + f"（共 {len(resolved.offsets)} 跳）")
                _explain_break(bad_hops)
            return result

        result["final_addr"] = address

        if verbose:
            line()
            print("7) 读取最终值")
        raw = reader._read_bytes(address, 4)
        if raw is None:
            result["error"] = f"读取最终地址 0x{address:X} 失败"
            result["exit_code"] = EXIT_CHAIN_BROKEN
            if verbose:
                bad(result["error"])
            return result
        value = int.from_bytes(raw, "little", signed=True)
        result["value"] = value
        result["exit_code"] = EXIT_OK
        if verbose:
            ok(f"最终地址 = 0x{address:X}")
            print()
            line("═")
            print(f"  脑啡肽 = {value}")
            line("═")
            if value > ENKEPHALIN_SANE_MAX or value < 0:
                info(f"⚠ 这个值不合常理（合法区间大致 0~{ENKEPHALIN_ACH_THRESHOLD}+）。")
                info("  多半是索引版本不匹配 / 读到别的东西 —— 别信这个数。")
            elif bad_hops:
                where = "、".join(str(i + 1) for i in bad_hops)
                info(f"⚠ 链路第 {where} 跳的值不是合法指针, 却一路读到了 {value}。")
                info("  这是巧合落在可读内存上的垃圾, **不可信**。")
            else:
                info(f"成就阈值 {ENKEPHALIN_ACH_THRESHOLD}: "
                     + ("已满足 ✅" if value >= ENKEPHALIN_ACH_THRESHOLD
                        else f"还差 {ENKEPHALIN_ACH_THRESHOLD - value}"))
        return result
    finally:
        k.CloseHandle(handle)
        reader.handle = None
        reader.pid = None
        reader.module_base = None

def _run_probe(reader: LimbusMemoryReader, key: str, *, verbose: bool,
               quiet: bool, process: str = TARGET_PROCESS) -> dict:
    if not quiet:
        return probe(reader, memory_target(key), key=key, process=process,
                     verbose=verbose)
    with contextlib.redirect_stdout(io.StringIO()):
        return probe(reader, memory_target(key), key=key, process=process,
                     verbose=False)

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="独立读取 Limbus Company 的脑啡肽数量（不依赖启动器）")
    parser.add_argument("--watch", action="store_true",
                        help="持续读取，直到 Ctrl+C")
    parser.add_argument("--interval", type=float, default=1.0,
                        help="--watch 的间隔秒数（默认 1.0）")
    parser.add_argument("--raw", action="store_true",
                        help="只输出数字（失败输出 -1），不做任何诊断打印")
    parser.add_argument("--json", action="store_true",
                        help="输出 JSON（机器可读）")
    parser.add_argument("--key", default="enkephalin",
                        help="内存目标名（默认 enkephalin）")
    parser.add_argument("--process", default=TARGET_PROCESS,
                        help=f"目标进程名（默认 {TARGET_PROCESS}）")
    args = parser.parse_args(argv)

    _harden_stdout()
    reader = LimbusMemoryReader()
    _configure_extra_api(reader.kernel32)

    if args.raw:
        res = _run_probe(reader, args.key, verbose=False, quiet=True,
                         process=args.process)
        val = res.get("value")
        print(-1 if val is None else val)
        return int(res.get("exit_code", EXIT_OTHER))

    codes = []
    try:
        while True:
            res = _run_probe(reader, args.key,
                             verbose=not (args.json or args.watch),
                             quiet=args.json or args.watch,
                             process=args.process)
            codes.append(res.get("exit_code", EXIT_OTHER))
            if args.json:
                print(json.dumps(res, ensure_ascii=False))
            elif args.watch:
                val = res.get("value")
                stamp = time.strftime("%H:%M:%S")
                if val is None:
                    print(f"[{stamp}] 读取失败: {res.get('error')}")
                else:
                    print(f"[{stamp}] 脑啡肽 = {val}")
            if not args.watch:
                break
            time.sleep(max(0.05, args.interval))
    except KeyboardInterrupt:
        print("\n已停止。")

    if not args.watch:
        return int(codes[-1]) if codes else EXIT_OTHER
    return EXIT_OK if EXIT_OK in codes else (codes[-1] if codes else EXIT_OTHER)

if __name__ == "__main__":
    raise SystemExit(main())
