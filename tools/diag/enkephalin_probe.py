"""脑啡肽（Enkephalin）内存读取独立自检脚本。

用途: 成就系统的脑啡肽读取失败时, 日志里**什么都看不到** —— ``read_enkephalin``
每条失败路径都只 ``return None``, ``MemoryAchievement.check`` 还把异常整个吞掉
（见 ``functions/achievement/base_achievement.py``）。本脚本把那条链拆开逐步打印,
一眼看出卡在哪一环, 且**不依赖启动器**: 游戏跑着就能单独跑它。

    python tools/diag/enkephalin_probe.py              # 读一次, 全程诊断
    python tools/diag/enkephalin_probe.py --watch      # 每 1s 读一次, Ctrl+C 停
    python tools/diag/enkephalin_probe.py --raw        # 只输出数字(适合塞进批处理)
    python tools/diag/enkephalin_probe.py --json       # 机器可读

它检查的环节（与生产代码**同一条路径**, 所以结论可直接采信）:
  1. 运行环境: 位数 / 是否管理员 —— 权限是 ``OpenProcess`` 最常见的失败原因
  2. 找进程: ``battle_watch.find_process_id`` → PID + 映像路径
  3. 开句柄: ``OpenProcess(PROCESS_VM_READ|PROCESS_QUERY_INFORMATION)`` + 错误码
  4. 定位模块: ``GameAssembly.dll`` 基址与大小（大小还能顺带看出索引版本是否匹配）
  5. 逐级指针: 每一跳的地址与读出的值, 断在哪一跳一目了然
  6. 最终值: int32, 并给出合理性判断与成就阈值提示

退出码: 0 成功 / 1 游戏没开 / 2 权限被拒 / 3 找不到模块 / 4 指针链断 / 5 其它
"""

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

# tools/diag/ -> 仓库根。必须把**仓库根**放进 sys.path 才能 import functions.*
# （与 tools/diag/webnote_diag.py 同一套处理）。
_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                     "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# 导入 functions.achievement.memory_reader 会连带执行 functions/achievement/__init__.py
# → achievements.py 的**模块级**注册, 那里有几句裸 print（"本地已完成 N 条"等）。
# --raw / --json 要求 stdout 干净, 所以在这些模式下把导入期的输出直接吞掉。
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

# 成就阈值: FullEnkephalinAchievement 要求 >= 100（data/ach_enkephalin_100.py）
ENKEPHALIN_ACH_THRESHOLD = 100
# 超过这个数基本可以断定读到的是错链/错版本, 而不是真的脑啡肽
ENKEPHALIN_SANE_MAX = 100000

EXIT_OK = 0
EXIT_NO_PROCESS = 1
EXIT_DENIED = 2
EXIT_NO_MODULE = 3
EXIT_CHAIN_BROKEN = 4
EXIT_OTHER = 5

# OpenProcess 常见错误码（只说人话）
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
    """当前进程是否已提权。拿不到 API 就返回 False（不当成致命错误）。"""
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:  # noqa: BLE001
        return False


def _image_path(kernel32, pid: int) -> str:
    """进程的映像全路径（拿不到返回空串）。"""
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
    """``(基址, 大小)``；找不到模块返回 None。

    与 ``LimbusMemoryReader._find_module`` 同一套快照枚举, 只是把 ``modBaseSize``
    也带出来 —— 这个大小可以直接和钩子索引里记的 ``gameassembly_size`` 对比,
    判断索引是不是对应另一个游戏版本。
    """
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
    """补上 memory_reader 没配的那几个 API 的签名。"""
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
    """放宽 stdout 的编码错误策略。

    输出被重定向到管道/文件时, Python 用系统 ANSI 编码(简体中文机器上是 GBK)写,
    而 "⚠ / ✅" 这类字符不在 GBK 里 —— 默认的 strict 策略会直接 UnicodeEncodeError
    崩掉整个脚本, 而不是少打一个符号。
    """
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:  # noqa: BLE001
        pass


# x64 Windows 用户态地址上限大致 0x7FFFFFFEFFFF，取上一档做粗判
_PTR_MAX = 0x0000800000000000


def _pointer_verdict(pointer: int) -> str:
    """给"解引用出来的指针"一个直白判断。

    **这是本次排障的关键**：如果某一跳读出来的值不是 8 字节对齐、或者超出用户态
    范围，那它压根不是指针 —— 说明链已经失效（游戏更新后静态槽位/结构偏移变了），
    而不是"游戏还没进主界面"。两种情况的处置完全不同。
    """
    if pointer == 0:
        return "NULL"
    if pointer % 8:
        return "UNALIGN"
    if pointer >= _PTR_MAX:
        return "OUTRANGE"
    return "OK"


def _index_target_meta(key: str) -> dict:
    """本地钩子索引里这条链的元信息（source / verified / value_range / 游戏 DLL 大小）。

    索引自己会记"这条链校验过没有"：``source="carried-over"`` + ``verified=False``
    意思就是**它只在生成索引时被照抄了一遍，从没在运行时验证过**。
    """
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
    """磁盘上 GameAssembly.dll 的字节数。

    索引里的 ``gameassembly_size`` 记的**就是这个量纲**（磁盘文件大小），
    而进程内的模块大小是内存映像大小（节对齐后更大）—— 两者不可直接比较。
    """
    try:
        from functions.hook import paths as paths_mod
        path = str(getattr(paths_mod.game_paths(), "gameassembly", "") or "")
        return os.path.getsize(path) if path and os.path.isfile(path) else 0
    except Exception:  # noqa: BLE001
        return 0


def _explain_break(bad_hops: list[int]) -> None:
    """链断掉之后，把"为什么断"和"下一步做什么"说清楚。"""
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
    """完整走一遍读取路径, 把每一步的结果都收集起来。

    返回 dict（键见下方 ``result`` 初始化）。**任何一步失败都只记录、不抛异常**,
    因为本脚本的全部价值就是把失败原因原样带出来。

    ``resolve=False`` 时不查钩子索引, 直接用传入的 ``target``（自检/调试用）。
    """
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

    # ---- 1. 运行环境 ---------------------------------------------------
    if verbose:
        line()
        print("1) 运行环境")
        info(f"Python {sys.version.split()[0]} "
             f"({ctypes.sizeof(ctypes.c_void_p) * 8} 位)")
        info(f"管理员权限: {'是' if _is_admin() else '否'}")
        if not _is_admin():
            info("提示: 游戏若以管理员身份运行, 非管理员的脚本 OpenProcess 会被拒。")

    # ---- 2. 找进程 -----------------------------------------------------
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

    # ---- 3. 目标链 -----------------------------------------------------
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

    # ---- 4. 开句柄（权限）---------------------------------------------
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
        # ---- 5. 定位模块 ----------------------------------------------
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

        # ---- 6. 逐级指针 ----------------------------------------------
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

        # ---- 7. 最终值 -------------------------------------------------
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
        # 这里必须把 reader 的状态复原: 上面的赋值是为了复用它的读函数,
        # 但句柄已经关掉了, 留着会让 reader 以为还 attach 着。
        reader.handle = None
        reader.pid = None
        reader.module_base = None


def _run_probe(reader: LimbusMemoryReader, key: str, *, verbose: bool,
               quiet: bool, process: str = TARGET_PROCESS) -> dict:
    """跑一次 ``probe``；``quiet=True`` 时把 ``memory_target`` 自己那句 print
    也一起吞掉 —— 否则它会污染 ``--raw`` 的数字和 ``--json`` 的 JSON。
    """
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
        # 静默模式: 连 memory_reader 里那些 print 一起压掉, 保证 stdout 只有一个数字
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

    # 单次运行: 用本次的退出码; watch 模式: 只要成功过一次就算成功
    if not args.watch:
        return int(codes[-1]) if codes else EXIT_OTHER
    return EXIT_OK if EXIT_OK in codes else (codes[-1] if codes else EXIT_OTHER)


if __name__ == "__main__":
    raise SystemExit(main())
