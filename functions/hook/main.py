"""hook 子系统的命令行入口。

用法（在项目根目录）::

    python -m functions.hook.main status                 # 看当前索引/游戏文件是否匹配
    python -m functions.hook.main update                 # 完整更新（解密 → dump → 索引 → 上传）
    python -m functions.hook.main update --force         # 忽略缓存强制重建
    python -m functions.hook.main update --dry-run       # 只生成不上传
    python -m functions.hook.main decrypt                # 只解出明文 metadata（不跑 dumper）
    python -m functions.hook.main dump                   # 只跑 Il2CppDumper（复用已解密 metadata）
    python -m functions.hook.main show                   # 打印本地缓存里的索引 JSON
    python -m functions.hook.main gen-header --out hook_index.h
    python -m functions.hook.main pull / push            # 云端笔记 ↔ 本地缓存
    python -m functions.hook.main locate --key enkephalin
    python -m functions.hook.main locate --class BattleUnitModel   # 按类名找模块槽位

``status``/``update`` 都会把每一步打到 stdout；在启动器里调用时把 ``on_log``
换成界面终端/日志文件的写函数即可。
"""

from __future__ import annotations

import argparse
import json
import os

from . import dump_cs as dump_cs_mod
from . import dumper as dumper_mod
from . import index as index_mod
from . import locator
from . import metadata_source
from . import paths as paths_mod
from . import targets as targets_mod
from . import updater
from .memory import ProcessMemoryReader


def _print(message: str) -> None:
    print(message, flush=True)


# --------------------------------------------------------------------------- 子命令


def cmd_status(args) -> int:
    info = updater.status(args.game)
    _print(json.dumps(info, ensure_ascii=False, indent=1))
    if info.get("local_exists"):
        local = index_mod.load_local()
        if local:
            _print("")
            _print(local.describe())
    if not info.get("game_files_ok"):
        _print(f"\n游戏文件不完整: {info.get('missing')}")
    return 0


def cmd_update(args) -> int:
    result = updater.update_hook_index(
        game_path=args.game, force=args.force, push=not args.no_push,
        dry_run=args.dry_run, allow_download=not args.no_download,
        allow_static_decrypt=not args.memory_only,
        allow_memory_dump=not args.static_only,
        focus=tuple(args.focus or ()), on_log=_print)
    if result.index is not None:
        _print("")
        _print(result.index.describe())
    _print("")
    _print(result.summary())
    return 0 if result.status in ("updated", "up-to-date", "partial", "dry-run") else 1


def cmd_pull(args) -> int:
    index = index_mod.refresh_local_from_cloud(allow_refresh=True, on_log=_print)
    if index is None:
        _print("云端没有可用索引")
        return 1
    _print(index.describe())
    return 0


def cmd_push(args) -> int:
    index = index_mod.load_local()
    if index is None:
        _print("本地没有缓存索引，先跑 update")
        return 1
    result = index_mod.push_cloud(index, on_log=_print)
    return 0 if result.get("ok") else 1


def cmd_show(args) -> int:
    index = index_mod.load_local()
    if index is None:
        _print("本地没有缓存索引")
        return 1
    _print(index.to_json(compact=not args.full))
    return 0


def cmd_gen_header(args) -> int:
    index = index_mod.load_local()
    if index is None:
        _print("本地没有缓存索引，先跑 update")
        return 1
    text = index_mod.render_c_header(index, prefix=args.prefix)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text)
        _print(f"已写入 {args.out}（{len(text)} 字节）")
    else:
        _print(text)
    return 0


def cmd_decrypt(args) -> int:
    paths = paths_mod.game_paths(args.game)
    if not paths.ok:
        _print(f"游戏文件缺失: {paths.missing()}")
        return 1
    if args.install_capstone:
        result = metadata_source.install_capstone(on_log=_print)
        _print(json.dumps(result, ensure_ascii=False))
    dump_dir = paths_mod.cache_path("decrypt", "run_cli")
    if not args.memory:
        result = metadata_source.decrypt_static(paths.metadata, paths.gameassembly,
                                                on_log=_print, out_dir=dump_dir)
        if result.ok:
            _print(result.describe())
            return 0
        _print(f"静态解密失败: {result.detail}")
    result = metadata_source.dump_from_memory(paths.metadata, on_log=_print)
    _print(result.describe())
    return 0 if result.ok else 1


def cmd_dump(args) -> int:
    paths = paths_mod.game_paths(args.game)
    if not paths.ok:
        _print(f"游戏文件缺失: {paths.missing()}")
        return 1
    metadata = args.metadata
    if not metadata:
        _print("未指定 --metadata，先尝试获取明文 metadata（解密/内存 dump）...")
        dump_dir = paths_mod.cache_path("dump", "cli")
        result = metadata_source.obtain_metadata(
            paths.metadata, paths.gameassembly, on_log=_print,
            allow_static=True, allow_memory=True, dump_dir=dump_dir)
        _print(result.describe())
        if not result.ok:
            return 1
        metadata = result.path
    exe = dumper_mod.ensure_dumper(on_log=_print, allow_download=not args.no_download)
    if not exe:
        _print("没有可用的 Il2CppDumper")
        return 1
    out_dir = args.out or paths_mod.cache_path("dump", "cli", "out")
    result = dumper_mod.run_dumper(exe, paths.gameassembly, metadata, out_dir, on_log=_print)
    _print(result.detail)
    return 0 if result.ok else 1


def cmd_locate(args) -> int:
    paths = paths_mod.game_paths(args.game)
    reader = ProcessMemoryReader(args.process)
    if not reader.attach():
        _print(f"未找到游戏进程 {args.process}（运行时重定位需要游戏在运行）")
        return 1
    try:
        module = reader.module("GameAssembly.dll")
        if module is None:
            _print("游戏进程里没有 GameAssembly.dll")
            return 1
        _print(f"已附加 PID={reader.pid}，模块基址 0x{module.base:012X}")
        if args.class_name:
            chain = targets_mod.ENKEPHALIN_CHAIN
            candidates = locator.find_class_slot(
                reader, args.class_name, chain.module, paths.gameassembly,
                chain.offsets, chain.value_type, chain.value_range, on_log=_print) # type: ignore
            for candidate in candidates:
                _print(json.dumps(candidate.as_dict(), ensure_ascii=False))
            if not candidates:
                _print("没有命中（类名可能写错，或该类没有静态槽位）")
            return 0 if candidates else 1
        target = next((c for c in targets_mod.CHAIN_TARGETS if c.key == args.key), None)
        if target is None:
            _print(f"未知的链: {args.key}（可用: {[c.key for c in targets_mod.CHAIN_TARGETS]}）")
            return 1
        check = locator.validate_chain(reader, target.base_offset, target)
        _print("旧偏移校验: " + json.dumps(check, ensure_ascii=False))
        result = locator.locate(reader, target, on_log=_print, local_path=paths.gameassembly)
        _print(json.dumps(result, ensure_ascii=False, indent=1))
        return 0 if result.get("ok") else 1
    finally:
        reader.detach()


def cmd_symbols(args) -> int:
    """按名字查 dump.cs 里的 RVA / 字段偏移（临时用，不依赖索引）。"""
    paths = paths_mod.game_paths(args.game)
    dump_cs_path = args.dump_cs
    if not dump_cs_path:
        candidates = [os.path.join(paths_mod.cache_path("dump"), d, "out", "dump.cs")
                      for d in os.listdir(paths_mod.cache_path("dump"))
                      if os.path.isdir(os.path.join(paths_mod.cache_path("dump"), d))]
        candidates = [c for c in candidates if os.path.isfile(c)]
        if not candidates:
            _print("没找到 dump.cs，先跑 update 或 dump")
            return 1
        dump_cs_path = max(candidates, key=os.path.getmtime)
    _print(f"解析 {dump_cs_path}")
    symbols = dump_cs_mod.parse_dump_cs(dump_cs_path, focus=tuple(args.focus or ()),
                                        wanted=tuple(args.name or ()), on_log=_print)
    for name in args.name or ():
        _print(f"{name} → 方法 {symbols.find_method(name)} / 字段 {symbols.find_field('', name)}")
    return 0


# --------------------------------------------------------------------------- 解析


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m functions.hook.main",
        description="边狱巴士偏移索引（hook_index）：解密 → dump → 云端笔记")
    parser.add_argument("--game", default="", help="游戏目录（默认取设置/Steam 自动定位）")
    parser.add_argument("--process", default="LimbusCompany.exe", help="游戏进程名")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="查看索引与游戏文件的匹配情况").set_defaults(func=cmd_status)

    update = sub.add_parser("update", help="完整更新（解密 → dump → 索引 → 上传）")
    update.add_argument("--force", action="store_true", help="忽略缓存强制重建")
    update.add_argument("--no-push", action="store_true", help="不上传云端（只写本地缓存）")
    update.add_argument("--dry-run", action="store_true", help="只生成不上传")
    update.add_argument("--no-download", action="store_true", help="不允许自动下载 Il2CppDumper")
    update.add_argument("--static-only", action="store_true", help="只用静态解密（不读游戏内存）")
    update.add_argument("--memory-only", action="store_true", help="只从游戏内存 dump")
    update.add_argument("--focus", action="append", help="额外保留的类名（可多次）")
    update.set_defaults(func=cmd_update)

    sub.add_parser("pull", help="云端笔记 → 本地缓存").set_defaults(func=cmd_pull)
    sub.add_parser("push", help="本地缓存 → 云端笔记").set_defaults(func=cmd_push)

    show = sub.add_parser("show", help="打印本地缓存索引")
    show.add_argument("--full", action="store_true", help="打印完整版（含 sig 等）")
    show.set_defaults(func=cmd_show)

    header = sub.add_parser("gen-header", help="生成 C 头文件（给注入 DLL 用）")
    header.add_argument("--out", default="", help="输出路径（默认打印到 stdout）")
    header.add_argument("--prefix", default="LIMBUS_", help="宏前缀")
    header.set_defaults(func=cmd_gen_header)

    decrypt = sub.add_parser("decrypt", help="只解出明文 metadata")
    decrypt.add_argument("--memory", action="store_true", help="改为从运行中的游戏内存 dump")
    decrypt.add_argument("--install-capstone", action="store_true", help="先 pip 安装 capstone")
    decrypt.set_defaults(func=cmd_decrypt)

    dump = sub.add_parser("dump", help="只跑 Il2CppDumper")
    dump.add_argument("--metadata", default="", help="明文 metadata 路径（默认自动获取）")
    dump.add_argument("--out", default="", help="输出目录")
    dump.add_argument("--no-download", action="store_true", help="不允许自动下载 Il2CppDumper")
    dump.set_defaults(func=cmd_dump)

    locate = sub.add_parser("locate", help="运行时校验/重定位数据链")
    locate.add_argument("--key", default="enkephalin", help="链名（默认 enkephalin）")
    locate.add_argument("--class", dest="class_name", default="", help="按类名找模块槽位")
    locate.set_defaults(func=cmd_locate)

    symbols = sub.add_parser("symbols", help="临时按名字查 dump.cs 的 RVA/字段偏移")
    symbols.add_argument("--dump-cs", default="", help="dump.cs 路径")
    symbols.add_argument("--name", action="append", help="要查的符号（类::方法 / 类::字段）")
    symbols.add_argument("--focus", action="append", help="额外保留的类名")
    symbols.set_defaults(func=cmd_symbols)
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
