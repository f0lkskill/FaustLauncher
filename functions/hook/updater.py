"""编排：把"游戏文件 → 明文 metadata → dump.cs → 偏移索引 → 云端笔记"串起来。

一次完整更新做的事：

1. 读游戏路径 + 算 GameAssembly.dll 指纹（size + sha256）
2. 指纹没变且索引完整 → 直接说"已是最新"（不联网、不 dump）
3. 拿明文 metadata：磁盘明文 → 静态解密（约 40s）→ 运行时内存 dump（需游戏在跑）
4. 跑 Il2CppDumper（结果按指纹缓存在 ``cache/hook/dump/<指纹8位>/``，同版本复用）
5. 解析 dump.cs → 解析钩子 RVA + prologue / 数据链偏移（游戏在跑就实时重定位+校验）
6. 写本地缓存 ``cache/hook/hook_index.json``，再写云端笔记 ``FaustLauncher.hook_index``

第 5 步的数据链部分有两种情况：游戏在跑 → 真的去内存里校验/重定位（最可靠）；
游戏没跑 → 沿用上次偏移 + 按字段名从新 dump 刷新，并记 warning。
"""

from __future__ import annotations

import hashlib
import os
import re
import threading
import time
from dataclasses import dataclass, field
from copy import deepcopy

from . import dump_cs as dump_cs_mod
from . import dumper as dumper_mod
from . import index as index_mod
from . import locator
from . import metadata_source
from . import paths as paths_mod
from . import pe as pe_mod
from . import targets as targets_mod
from .memory import ProcessMemoryReader, is_process_running

PUBLISHED_LOCK = threading.Lock()
_auto_updating = False


@dataclass
class UpdateResult:
    status: str = "failed"           # updated / up-to-date / partial / failed / dry-run
    index: index_mod.HookIndex | None = None
    pushed: bool = False
    messages: list[str] = field(default_factory=list)
    elapsed: float = 0.0

    def summary(self) -> str:
        head = {
            "updated": "偏移索引已更新",
            "up-to-date": "偏移索引已是最新（无需更新）",
            "partial": "偏移索引部分更新（有警告）",
            "dry-run": "试运行完成（未上传）",
            "failed": "偏移索引更新失败",
        }.get(self.status, self.status)
        tail = ("；".join(self.messages[-3:])) if self.messages else ""
        return f"{head}，耗时 {self.elapsed:.1f}s" + (f"：{tail}" if tail else "")


# --------------------------------------------------------------------------- 发布标记


def _already_published(index: index_mod.HookIndex) -> bool:
    """本地这份索引是否已经与云端完全一致（避免每次启动重复上传）。"""
    return index_mod.already_published(index)


def _cloud_same_as(index: index_mod.HookIndex, log=None) -> tuple[bool, str]:
    """云端**现有**那份索引是否与本份等价（指纹一致 + 发布载荷哈希一致）。

    用来避免"没变化也上传"：真重建出来的索引若与云端完全一样，传上去没有任何信息增量，
    只白等一次 POST（实测 44,637 字节 / 1.38 秒）。读云端只是几十 KB 的 GET，比 POST 便宜。

    ⚠ 读不到（首次使用 / 网络失败）一律返回 False —— 该传还是要传，
    不能因为"比对不了"就把新索引憋在本地。
    """
    try:
        cloud = index_mod.pull_cloud(on_log=log)
        if cloud is None:
            return False, ""
        size, sha256 = index.fingerprint()
        csize, csha256 = cloud.fingerprint()
        if (int(csize), str(csha256).upper()) != (int(size), str(sha256).upper()):
            return False, ""
        if (index_mod.payload_hash(index.to_publish_json())
                != index_mod.payload_hash(cloud.to_publish_json())):
            return False, ""
        return True, "指纹与发布载荷哈希一致"
    except Exception as exc:  # noqa: BLE001
        if log:
            log(f"[hook_index] 云端等价性比对失败（按需上传处理）: {type(exc).__name__}: {exc}")
        return False, ""


# --------------------------------------------------------------------------- 状态


def status(game_path: str = "") -> dict:
    """看一眼当前索引与游戏文件的匹配情况（不联网、不 dump）。"""
    paths = paths_mod.game_paths(game_path)
    info = {
        "game_path": paths.root,
        "game_files_ok": paths.ok,
        "missing": paths.missing(),
        "note_key": index_mod.note_key(),
        "local_index": paths_mod.local_index_path(),
        "local_exists": os.path.isfile(paths_mod.local_index_path()),
        "fingerprint": None,
        "index_matches": False,
        "published": False,
        "game_running": is_process_running("LimbusCompany.exe"),
        "capstone": metadata_source.capstone_available(),
        "dumper": dumper_mod.find_dumper(),
    }
    local = index_mod.load_local()
    if local is not None:
        info["index"] = {
            "generated_at": local.generated_at,
            "game": local.game,
            "hooks": sorted(local.hooks.keys()),
            "targets": sorted(local.targets.keys()),
            "warnings": local.warnings,
        }
        info["published"] = index_mod.already_published(local)
        size, sha256 = local.fingerprint()
        info["fingerprint"] = {"size": size, "sha256": sha256}
    if paths.gameassembly and os.path.isfile(paths.gameassembly):
        size = os.path.getsize(paths.gameassembly)
        info["gameassembly_size"] = size
        if local is not None:
            info["index_matches"] = int(local.game.get("gameassembly_size") or 0) == size
    return info


# --------------------------------------------------------------------------- 主流程


def update_hook_index(game_path: str = "", force: bool = False, push: bool = True,
                      dry_run: bool = False, allow_download: bool = True,
                      allow_static_decrypt: bool = True, allow_memory_dump: bool = True,
                      on_log=None, process_name: str = "LimbusCompany.exe",
                      focus=(), reader: ProcessMemoryReader | None = None,
                      launcher_version: str = "") -> UpdateResult:
    """更新偏移索引（完整流程）。所有进度都走 ``on_log``。"""
    log = on_log or (lambda _m: None)
    started = time.time()
    messages: list[str] = []

    def note(msg: str) -> None:
        messages.append(msg)
        log(msg)

    paths = paths_mod.game_paths(game_path)
    if not paths.root:
        return UpdateResult("failed", messages=["没找到游戏目录：请在设置里配置游戏路径或确认 Steam 安装"],
                            elapsed=time.time() - started)
    missing = paths.missing()
    if missing:
        return UpdateResult("failed", messages=[f"游戏文件缺失: {'; '.join(missing)}"],
                            elapsed=time.time() - started)

    # ---- 指纹 + 缓存判断
    fingerprint = paths_mod.game_fingerprint(paths, on_log=log)
    previous = index_mod.load_local()
    if previous is not None and not force:
        if previous.matches(fingerprint.size, fingerprint.sha256):
            unresolved = [key for key, item in previous.targets.items()
                          if not item.get("base_offset") or not item.get("offsets")]
            if not unresolved:
                if push and not dry_run and not _already_published(previous):
                    result = index_mod.push_cloud(previous, on_log=log)
                    if result.get("ok"):
                        return UpdateResult("up-to-date", previous, True,
                                            ["已把本地索引补传到云端"],
                                            time.time() - started)
                note("GameAssembly.dll 指纹未变，索引已是最新")
                return UpdateResult("up-to-date", previous, False, messages,
                                    time.time() - started)
            note(f"指纹未变，但目标 {unresolved} 还没解析出来，继续完整更新")
        else:
            note("检测到游戏已更新（GameAssembly.dll 指纹变化），开始重建偏移索引")
    else:
        note("开始构建偏移索引")

    # ---- 明文 metadata
    dump_dir = paths_mod.cache_path("dump", fingerprint.short)
    meta = _reuse_decrypted(dump_dir, on_log=log)
    if meta is None:
        meta = metadata_source.obtain_metadata(
            paths.metadata, paths.gameassembly, on_log=log,
            allow_static=allow_static_decrypt, allow_memory=allow_memory_dump,
            process_name=process_name, dump_dir=dump_dir)
    log(meta.describe())
    if not meta.ok:
        note(f"拿不到明文 metadata: {meta.detail}")
        return UpdateResult("failed", previous, False, messages, time.time() - started)

    # ---- Il2CppDumper
    out_dir = os.path.join(dump_dir, "out")
    dump_cs_path = os.path.join(out_dir, "dump.cs")
    dumper_exe = ""
    if os.path.isfile(dump_cs_path) and not force:
        note(f"复用已存在的 dump.cs（{os.path.getsize(dump_cs_path) / 1048576:.1f} MB）")
    else:
        dumper_exe = dumper_mod.ensure_dumper(on_log=log, allow_download=allow_download)
        if not dumper_exe:
            note("没有可用的 Il2CppDumper（可手动下载后放到 cache/hook/tools/il2cppdumper/）")
            return UpdateResult("failed", previous, False, messages, time.time() - started)
        result = dumper_mod.run_dumper(dumper_exe, paths.gameassembly, meta.path,
                                       out_dir, on_log=log)
        if not result.ok:
            note(f"Il2CppDumper 失败: {result.detail}")
            log(result.stdout_tail)
            return UpdateResult("failed", previous, False, messages, time.time() - started)
        dump_cs_path = result.dump_cs
        note(f"dump.cs 已生成（{os.path.getsize(dump_cs_path) / 1048576:.1f} MB，"
             f"{result.elapsed:.1f}s）")

    # ---- 解析 dump.cs
    wanted = targets_mod.required_symbols()
    focus_patterns = tuple(focus) or targets_mod.FOCUS_PATTERNS
    symbols = dump_cs_mod.parse_dump_cs(dump_cs_path, focus=focus_patterns, wanted=wanted,
                                        on_log=log)
    pe = None
    try:
        pe = pe_mod.PeFile(paths.gameassembly)
    except Exception as exc:  # noqa: BLE001
        note(f"GameAssembly.dll 节表解析失败（prologue 会缺失）: {exc}")

    index = index_mod.HookIndex(
        generated_at=paths_mod.now_iso(),
        game={
            "path": paths.root,
            "gameassembly_size": fingerprint.size,
            "gameassembly_sha256": fingerprint.sha256,
            "pe_timestamp": getattr(pe, "timestamp", 0),
            "launcher_version": launcher_version,
        },
        metadata={
            "source": meta.source,
            "encrypted_on_disk": bool(meta.encrypted),
            "version": int(meta.version or 0),
            "size": int(meta.size or 0),
            "sha1": meta.sha1,
            "detail": meta.detail,
        },
        dumper={
            "tool": dumper_mod.DUMPER_EXE,
            "version": dumper_mod.dumper_version(dumper_exe) if dumper_exe else "",
            "config": dumper_mod.DUMPER_CONFIG,
            "dump_cs": dump_cs_path,
            "dump_cs_size": os.path.getsize(dump_cs_path) if os.path.isfile(dump_cs_path) else 0,
        },
    )

    warnings: list[str] = []

    # ---- 钩子（代码偏移）
    for key, symbol, description, compat_field in targets_mod.hook_symbol_entries():
        target = targets_mod.HookTarget(key=key, symbol=symbol, description=description,
                                        compat_field=compat_field)
        item = symbols.find_method(target.symbol)
        if not item:
            old = (previous.hooks.get(target.key) if previous else None) or {}
            if compat_field or old.get("rva"):
                warnings.append(f"符号 {target.symbol} 在 dump.cs 里没找到"
                                + ("（沿用旧值）" if old.get("rva") else ""))
            note(f"[hook] {target.key}: 未找到 {target.symbol}")
            if old.get("rva"):
                index.hooks[target.key] = old
            continue
        rva = int(item.get("rva") or 0)
        prologue = pe_mod.prologue_hex(pe.prologue(rva, 16)) if pe else ""
        index.hooks[target.key] = {
            "symbol": target.symbol.replace("$$", "::"),
            "alias": target.symbol.replace("::", "$$"),
            "description": target.description,
            "compat_field": target.compat_field,
            "rva": rva,
            "rva_hex": f"0x{rva:X}",
            "va": int(item.get("va") or 0),
            "file_offset": int(item.get("offset") or 0),
            "slot": item.get("slot"),
            "signature": item.get("sig", ""),
            "overloads": int(item.get("overloads") or 1),
            "prologue": prologue,
        }
        note(f"[hook] {target.key}: {target.symbol} → RVA 0x{rva:X} "
             f"(prologue {prologue[:23]}...)")

    # ---- 事件钩子要读的结构体字段（写进索引 fields 段；DLL 不写死偏移）
    for key, (cls, fld, fallback) in targets_mod.BATTLE_FIELDS.items():
        item = symbols.find_field(cls, fld)
        if item is None:
            warnings.append(f"字段 {cls}::{fld} 在 dump.cs 里没找到（使用回退偏移 0x{fallback:X}）")
            index.fields[key] = {"symbol": f"{cls}::{fld}", "offset": fallback,
                                 "source": "fallback"}
            continue
        offset = int(item.get("offset") or 0)
        index.fields[key] = {
            "symbol": f"{cls}::{fld}",
            "class": cls,
            "field": fld,
            "offset": offset,
            "offset_hex": f"0x{offset:X}",
            "static": bool(item.get("static")),
            "type": item.get("type", ""),
            "source": "dump.cs",
        }
    note("[fields] " + ", ".join(
        f"{k}=0x{int(v.get('offset') or 0):X}" for k, v in index.fields.items()))

    # ---- 游戏版本信号（Steam buildid / 更新时间；PE 编译时间只作旁证）
    version_info = _game_version_info(paths, pe, int(meta.version or 0))
    index.game.update(version_info)
    note("[version] 游戏版本 {v}（build {b}；更新于 {u}"
         "）".format(v=version_info["game_version"],
                     b=version_info["game_build_id"] or "未知",
                     u=version_info["game_updated_at"] or version_info["game_updated_source"] or "未知"))

    # ---- 兼容块（与 web.lcta.top/cheat_damage.json 同字段名）
    compat = {
        "game_version": version_info["game_version"],
        "gameassembly_sha256": fingerprint.sha256,
        "gameassembly_size": fingerprint.size,
    }
    for key, item in index.hooks.items():
        compat_field = item.get("compat_field")
        if compat_field:
            compat[compat_field] = int(item.get("rva") or 0)
    first_prologue = next((h.get("prologue") for h in index.hooks.values()
                           if h.get("compat_field") and h.get("prologue")), "")
    if first_prologue:
        compat["prologue"] = first_prologue
    # 版本旁证：外部脚本（test/damage_log.py 等）只看 game_version，多给的字段不破坏兼容
    compat["game_build_id"] = version_info["game_build_id"]
    compat["game_updated_at"] = version_info["game_updated_at"]
    compat["dll_build_time"] = version_info["dll_build_time"]
    compat["metadata_version"] = version_info["metadata_version"]
    index.cheat_damage = compat

    # ---- 数据链（运行时校验 / 重定位）
    running = is_process_running(process_name)
    if not running:
        note(f"游戏进程（{process_name}）没在运行：数据链只能沿用上次偏移 + 按名字刷新，"
             f"不做实时校验")

    for chain in targets_mod.CHAIN_TARGETS:
        effective = _merge_chain(chain, previous)
        # (1) 用 (类, 字段) 名字从新 dump 里刷新偏移
        resolved = locator.resolve_offsets_from_refs(symbols, effective, on_log=log)
        if resolved:
            effective = _replace_chain(effective, offsets=resolved)
        # (2) 运行时校验 / 重定位
        located: dict = {}
        if running:
            located = _locate_with_reader(effective, process_name, paths, reader, log)
            if located.get("ok"):
                effective = _replace_chain(
                    effective,
                    base_offset=int(located["base_offset"]),
                    root_class=str(located.get("root_class") or effective.root_class),
                    step_classes=tuple(located.get("step_classes") or ()),
                )
            else:
                warnings.append(f"{chain.key}: 运行时重定位失败（{located.get('reason')}）")
        else:
            warnings.append(f"{chain.key}: 游戏未运行，链未经实时校验"
                            + ("（首次还需一次运行时发现才能拿到类名）"
                               if not effective.root_class else ""))
        # (3) 名字回填
        if effective.root_class:
            attribution = locator.attribute_chain(symbols, effective, effective.root_class,
                                                  "class", on_log=log)
            if attribution["field_refs"]:
                effective = _replace_chain(effective, field_refs=tuple(attribution["field_refs"]),
                                           step_classes=tuple(attribution["step_classes"]))
            if not attribution["complete"]:
                note(f"[chain] {chain.key}: 名字回填不完整（{attribution['detail']}）")
        index.targets[chain.key] = effective.as_dict(
            source=located.get("source") or ("resolved" if running else "carried-over"),
            value=located.get("value"),
            verified=bool(located.get("ok")),
            updated_at=paths_mod.now_iso(),
        )
        note(f"[chain] {chain.key}: base=0x{int(effective.base_offset):X} "
             f"offsets={[hex(x) for x in effective.offsets]} "
             f"root_class={effective.root_class or '(未知)'} "
             f"value={located.get('value')}")

    # ---- 符号表（只保留裁剪后的方法/字段，供查表与名字回填）
    index.symbols = _build_symbols(symbols)
    index.warnings = warnings

    # ---- 落盘 / 发布
    local_path = index_mod.save_local(index)
    note(f"本地缓存已写入 {local_path}")

    pushed = False
    if dry_run:
        note("试运行模式：不上传云端")
        return UpdateResult("dry-run", index, False, messages, time.time() - started)
    if push:
        # 只上传**真正有变化**的索引。以前这里是无条件 push，实测出现过：
        # 本地重建出来的东西和云端那份完全等价（同指纹、同发布载荷），照样 POST 了
        # 44,637 字节回云端（1.38 秒纯浪费）。两次比对任一成立就跳过：
        #   · 云端现有那份与本份等价（指纹 + 发布载荷哈希都一致）→ 传上去没有任何信息增量；
        #   · 本机自己发布过同一份（本地发布标记命中）→ 更没必要再传。
        same_as_cloud, why = _cloud_same_as(index, log)
        if same_as_cloud:
            note(f"云端已有等价索引（{why}）→ 跳过上传")
        elif _already_published(index):
            note("本机已发布过同一份索引 → 跳过上传")
        else:
            result = index_mod.push_cloud(index, on_log=log)
            pushed = bool(result.get("ok"))
            if not pushed:
                warnings.append(f"云端写回失败: {result.get('error')}")
                index.warnings = warnings
                index_mod.save_local(index)
    status_ = "updated" if not warnings else "partial"
    return UpdateResult(status_, index, pushed, messages, time.time() - started)


STEAM_APP_ID = "1973530"          # Limbus Company


def _iso_local(timestamp: int) -> str:
    """Unix 时间戳 → 本地时间 ISO 串（失败返回空串）。

    ⚠ 必须用 ``localtime``：以前这里用 ``gmtime``，北京时间下午 4 点之后链接出来的
    DLL 会被算到**前一天**，日志里的版本日期看着永远比实际早一天。
    """
    if not timestamp:
        return ""
    try:
        return time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(int(timestamp)))
    except (ValueError, OSError, OverflowError):
        return ""


def _steam_app_state(game_root: str) -> dict:
    """读 Steam 的 ``appmanifest_<appid>.acf``（游戏在 ``<库>/steamapps/common/<installdir>``）。

    只有这里能给出**真正的游戏版本**：``buildid`` 是 Steam 构建号，``LastUpdated`` 是
    这次补丁落盘的时间。用正则直接抠两个字段，不依赖 VDF 解析器（结构变了也不会炸）。
    """
    root = str(game_root or "").rstrip("\\/")
    if not root:
        return {}
    steamapps = os.path.dirname(os.path.dirname(root))
    manifest = os.path.join(steamapps, f"appmanifest_{STEAM_APP_ID}.acf")
    try:
        with open(manifest, "r", encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError:
        return {}
    out = {}
    for key in ("buildid", "LastUpdated", "name", "StateFlags"):
        match = re.search(r'"%s"\s+"([^"]*)"' % re.escape(key), text)
        if match:
            out[key] = match.group(1)
    return out


def _game_version_info(paths, pe=None, metadata_version: int = 0) -> dict:
    """收集"这份索引对应哪个游戏版本"的可信信号。

    以前 ``game_version`` 直接拿 ``GameAssembly.dll`` 的 **PE 头编译时间**充数，结果
    游戏 10-09 更新、云端记录写 10-02 —— 那只是 IL2CPP 那批代码被链接器写进头里的
    时间，跟"游戏更新到哪一版"没有关系，玩家/服务端看一眼就会以为索引是旧的。

    现在按可信度取：

    1. ``appmanifest`` 的 ``LastUpdated``（Steam 打完补丁的时间）+ ``buildid``（构建号）；
    2. 拿不到 acf（非 Steam 安装）时退回游戏文件里最新的那个 mtime；
    3. PE 编译时间单独记成 ``dll_build_time``，只用来解释"为什么指纹变了"。

    另外把 ``metadata_version`` 一起记下：``global-metadata.dat`` 的版本号每次游戏更新都会涨，
    是判断"索引跟游戏对不对得上"的旁证。
    """
    app = _steam_app_state(getattr(paths, "root", "") or "")
    newest_name, newest_ts = "", 0.0
    for name, path in (("GameAssembly.dll", getattr(paths, "gameassembly", "")),
                       ("global-metadata.dat", getattr(paths, "metadata", "")),
                       ("LimbusCompany.exe", getattr(paths, "exe", ""))):
        try:
            stamp = os.path.getmtime(path)
        except OSError:
            continue
        if stamp > newest_ts:
            newest_name, newest_ts = name, stamp

    updated_ts = 0
    source = ""
    try:
        updated_ts = int(app.get("LastUpdated") or 0)
    except ValueError:
        updated_ts = 0
    if updated_ts:
        source = "steam-appmanifest"
    elif newest_ts:
        updated_ts = int(newest_ts)
        source = f"文件时间({newest_name})"

    updated_at = _iso_local(updated_ts)
    return {
        "game_version": updated_at[:10] if updated_at else "unknown",
        "game_build_id": str(app.get("buildid") or ""),
        "game_updated_at": updated_at,
        "game_updated_source": source,
        "dll_build_time": _iso_local(int(getattr(pe, "timestamp", 0) or 0)),
        "metadata_version": int(metadata_version or 0),
    }


def _reuse_decrypted(dump_dir: str, on_log=None) -> metadata_source.MetadataResult | None:
    """复用上一次已解密/已 dump 的明文 metadata（同一个游戏指纹下有效）。

    静态解密一次约 40 秒，同一指纹内没必要重复跑（``--force`` 想重建时跳过这步即可）。
    """
    log = on_log or (lambda _m: None)
    for name, source in (("standard-rebuilt.dat", "static"),
                         ("memory-global-metadata.dat", "memory")):
        path = os.path.join(dump_dir, name)
        if not os.path.isfile(path):
            continue
        ok, why = metadata_source._validate_file(path)
        if not ok:
            log(f"[metadata] 复用的 {name} 校验不通过（{why}），重新解密")
            continue
        log(f"[metadata] 复用已解密的 {name}（{os.path.getsize(path) / 1048576:.1f} MB）")
        header = metadata_source.header_from_file(path)
        return metadata_source.MetadataResult(
            ok=True, source=f"{source}-cached", path=path,
            version=header.version if header else 0, encrypted=True,
            sha1=paths_mod.file_sha1(path), size=os.path.getsize(path), detail=why)
    return None


def _locate_with_reader(effective: targets_mod.ChainTarget, process_name: str,
                        paths: paths_mod.GamePaths, reader: ProcessMemoryReader | None,
                        log) -> dict:
    """用（可复用的）进程读取器做一次运行时重定位。"""
    own = reader is None
    owner = reader or ProcessMemoryReader(process_name)
    try:
        if not owner.attached and not owner.attach():
            return {"ok": False, "reason": "附加游戏进程失败"}
        return locator.locate(owner, effective, on_log=log, local_path=paths.gameassembly)
    finally:
        if own:
            owner.detach()


def _merge_chain(chain: targets_mod.ChainTarget, previous: index_mod.HookIndex | None
                 ) -> targets_mod.ChainTarget:
    """把上次索引里的数字/类名合并进目标定义（索引比代码里的默认值更新）。"""
    merged = deepcopy(chain)
    if previous is None:
        return merged
    item = previous.target(chain.key)
    if not item:
        return merged
    if item.get("base_offset") is not None:
        merged.base_offset = int(item["base_offset"])
    if item.get("offsets"):
        merged.offsets = tuple(int(x) for x in item["offsets"])
    if item.get("root_class"):
        merged.root_class = str(item["root_class"])
    if item.get("field_refs"):
        merged.field_refs = tuple((str(a), str(b)) for a, b in item["field_refs"])
    if item.get("step_classes"):
        merged.step_classes = tuple(str(x) for x in item["step_classes"])
    if item.get("value_range"):
        merged.value_range = (item["value_range"][0], item["value_range"][1])
    return merged


def _replace_chain(chain: targets_mod.ChainTarget, **kwargs) -> targets_mod.ChainTarget:
    values = {
        "key": chain.key, "description": chain.description,
        "base_offset": chain.base_offset, "offsets": chain.offsets,
        "module": chain.module, "value_type": chain.value_type,
        "root_class": chain.root_class,
        "static_fields_offset": chain.static_fields_offset,
        "field_refs": chain.field_refs, "value_range": chain.value_range,
        "step_classes": chain.step_classes,
    }
    values.update(kwargs)
    return targets_mod.ChainTarget(**values)


def _build_symbols(symbols: dump_cs_mod.SymbolIndex) -> dict:
    """裁剪符号表（方法只留 rva，字段只留偏移），控制笔记体积。

    **钩子/观测符号优先入表**：它们必须永远在索引里，否则游戏更新后钩子拿不到新 RVA，
    只能靠代码里的回退值（而且回退值会过期）。以前是按 dump 顺序直接截断到上限，
    排在 dump 后面的类会被**静默丢掉** —— 实测：``RailwayDungeonHistoryDataByCollection``
    就这样被截掉（40000/60000 上限都一样，因为它排在 65 万行附近）。
    """
    def _slim(item: dict) -> dict:
        return {"rva": int(item.get("rva") or 0),
                "va": int(item.get("va") or 0),
                "slot": item.get("slot")}

    required = set(targets_mod.required_symbols())
    methods = {}
    for key, item in symbols.methods.items():          # 1) 钩子符号，不占上限
        if key in required:
            methods[key] = _slim(item)
    for key, item in symbols.methods.items():          # 2) 其余按 dump 顺序填到上限
        if key in methods:
            continue
        if len(methods) >= targets_mod.MAX_METHODS:
            break
        methods[key] = _slim(item)
    fields = {}
    for key, item in symbols.fields.items():
        fields[key] = int(item.get("offset") or 0)
        if len(fields) >= targets_mod.MAX_FIELDS:
            break
    return {"methods": methods, "fields": fields}


# --------------------------------------------------------------------------- 后台自动更新


def preload(on_log=None) -> None:
    """在**调用线程**（主线程）里把重量级依赖先导入好。

    Python 3.14 的 import 锁在“主线程正在导入某模块时，后台线程再去 import 同一模块”
    会直接抛 ``DeadlockError``（实测：成就监测进程里两个后台线程同时 import
    ``functions.hook.index``），所以后台更新前先把要用的模块导完。
    """
    log = on_log or (lambda _m: None)
    try:
        from . import metadata_source as _ms  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        log(f"[hook_index] 预加载 metadata_source 失败: {exc}")
    try:
        from .metadata_recovery import run_recovery  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        log(f"[hook_index] 预加载 metadata_recovery 失败（静态解密将不可用）: {exc}")


def auto_update_async(on_log=None, game_path: str = "", force: bool = False,
                      push: bool = True) -> bool:
    """在后台线程里跑一次更新（同时只允许一个）。

    典型用法：成就监测进程发现游戏刚起来 → 顺手刷新偏移索引。
    返回 False 表示已有任务在跑。
    """
    global _auto_updating
    preload(on_log=on_log)
    with PUBLISHED_LOCK:
        if _auto_updating:
            return False
        _auto_updating = True

    def worker() -> None:
        global _auto_updating
        try:
            # ⚡ 先做一次**便宜的预检**（本地索引 → 云端索引，都只是读文件 / 下几十 KB），
            #    只要其中一份对得上本机 DLL 就**不重建**。
            #
            # 为什么必须这样：``update_hook_index`` 在"本地没有索引"时会走 metadata
            # **静态解密（约 40 秒）**。游戏启动那一刻它和启动器/游戏抢 CPU 与磁盘，
            # 玩家感受到的就是"首次打开游戏卡好一阵子"——而这份索引往往**根本用不上**：
            # 预检随后从云端拿到一份对得上的索引就直接采用了（实测日志 18:45:36 开始重建，
            # 18:45:38 云端索引已 19/19 命中，重建纯属白烧）。
            # 这里传 allow_rebuild=False：预检只做判断，绝不在这里触发重建，
            # 免得两边同时解密。
            if not force:
                try:
                    from . import preflight as _preflight
                    verdict = _preflight.ensure_offsets_ready(
                        on_log=on_log, game_path=game_path, push=push,
                        allow_rebuild=False)
                    if verdict.get("source") in ("local", "cloud"):
                        if on_log:
                            on_log("[hook_index] 索引已可用"
                                   f"（{verdict.get('verdict', '')}，来源={verdict.get('source')}）"
                                   "→ 跳过本地重建（省掉约 40 秒静态解密）")
                        return
                except Exception as exc:  # noqa: BLE001
                    if on_log:
                        on_log(f"[hook_index] 预检失败（继续原流程）: {type(exc).__name__}: {exc}")
            result = update_hook_index(game_path=game_path, force=force, push=push,
                                       on_log=on_log)
            if on_log:
                on_log(f"[hook_index] 自动更新结束：{result.summary()}")
        except Exception as exc:  # noqa: BLE001
            if on_log:
                on_log(f"[hook_index] 自动更新异常: {type(exc).__name__}: {exc}")
        finally:
            with PUBLISHED_LOCK:
                _auto_updating = False

    threading.Thread(target=worker, name="hook-index-update", daemon=True).start()
    return True


def is_auto_updating() -> bool:
    return _auto_updating
