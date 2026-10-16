
from __future__ import annotations

import contextlib
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
    status: str = "failed"
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

def _already_published(index: index_mod.HookIndex) -> bool:
    return index_mod.already_published(index)

@contextlib.contextmanager
def low_priority_process():
    kernel32 = None
    previous = 0
    try:
        import ctypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetPriorityClass.restype = ctypes.c_uint32
        kernel32.GetPriorityClass.argtypes = [ctypes.c_void_p]
        kernel32.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        handle = kernel32.GetCurrentProcess()
        previous = int(kernel32.GetPriorityClass(handle) or 0)
        BELOW_NORMAL = 0x00004000
        if previous and previous != BELOW_NORMAL:
            if not kernel32.SetPriorityClass(handle, BELOW_NORMAL):
                previous = 0
    except Exception:  # noqa: BLE001
        kernel32, previous = None, 0
    try:
        yield
    finally:
        if kernel32 is not None and previous:
            try:
                kernel32.SetPriorityClass(kernel32.GetCurrentProcess(), previous)
            except Exception:  # noqa: BLE001
                pass

def _cloud_same_as(index: index_mod.HookIndex, log=None) -> tuple[bool, str]:
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

def status(game_path: str = "") -> dict:
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

def update_hook_index(game_path: str = "", force: bool = False, push: bool = True,
                      dry_run: bool = False, allow_download: bool = True,
                      allow_static_decrypt: bool = True, allow_memory_dump: bool = True,
                      on_log=None, process_name: str = "LimbusCompany.exe",
                      focus=(), reader: ProcessMemoryReader | None = None,
                      launcher_version: str = "", low_priority: bool = False) -> UpdateResult:
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

    with (low_priority_process() if low_priority else contextlib.nullcontext()):
        if low_priority:
            note("以低优先级重建（避免和游戏抢 CPU/磁盘）")
        return _build_index(fingerprint, paths, previous, force=force, push=push,
                            dry_run=dry_run, allow_download=allow_download,
                            allow_static_decrypt=allow_static_decrypt,
                            allow_memory_dump=allow_memory_dump,
                            process_name=process_name, focus=focus, reader=reader,
                            launcher_version=launcher_version, low_priority=low_priority,
                            note=note, log=log, messages=messages, started=started)

def _build_index(fingerprint, paths, previous, *, force: bool, push: bool, dry_run: bool,
                 allow_download: bool, allow_static_decrypt: bool, allow_memory_dump: bool,
                 process_name: str, focus, reader, launcher_version: str,
                 low_priority: bool, note, log, messages: list[str],
                 started: float) -> UpdateResult:

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
                                       out_dir, on_log=log, low_priority=low_priority)
        if not result.ok:
            note(f"Il2CppDumper 失败: {result.detail}")
            log(result.stdout_tail)
            return UpdateResult("failed", previous, False, messages, time.time() - started)
        dump_cs_path = result.dump_cs
        note(f"dump.cs 已生成（{os.path.getsize(dump_cs_path) / 1048576:.1f} MB，"
             f"{result.elapsed:.1f}s）")

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

    version_info = _game_version_info(paths, pe, int(meta.version or 0))
    index.game.update(version_info)
    note("[version] 游戏版本 {v}（build {b}；更新于 {u}"
         "）".format(v=version_info["game_version"],
                     b=version_info["game_build_id"] or "未知",
                     u=version_info["game_updated_at"] or version_info["game_updated_source"] or "未知"))

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
    compat["game_build_id"] = version_info["game_build_id"]
    compat["game_updated_at"] = version_info["game_updated_at"]
    compat["dll_build_time"] = version_info["dll_build_time"]
    compat["metadata_version"] = version_info["metadata_version"]
    index.cheat_damage = compat

    running = is_process_running(process_name)
    if not running:
        note(f"游戏进程（{process_name}）没在运行：数据链只能沿用上次偏移 + 按名字刷新，"
             f"不做实时校验")

    for chain in targets_mod.CHAIN_TARGETS:
        effective = _merge_chain(chain, previous)
        resolved = locator.resolve_offsets_from_refs(symbols, effective, on_log=log)
        if resolved:
            effective = _replace_chain(effective, offsets=resolved)
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

    index.symbols = _build_symbols(symbols)
    index.warnings = warnings

    local_path = index_mod.save_local(index)
    note(f"本地缓存已写入 {local_path}")

    pushed = False
    if dry_run:
        note("试运行模式：不上传云端")
        return UpdateResult("dry-run", index, False, messages, time.time() - started)
    if push:
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

STEAM_APP_ID = "1973530"

def _iso_local(timestamp: int) -> str:
    if not timestamp:
        return ""
    try:
        return time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(int(timestamp)))
    except (ValueError, OSError, OverflowError):
        return ""

def _steam_app_state(game_root: str) -> dict:
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

def game_build_note(paths) -> dict:
    app = _steam_app_state(getattr(paths, "root", "") or "")
    updated_ts = 0
    try:
        updated_ts = int(app.get("LastUpdated") or 0)
    except ValueError:
        updated_ts = 0
    newest_name, newest_ts = "", 0.0
    for name, path in (("GameAssembly.dll", getattr(paths, "gameassembly", "")),
                       ("global-metadata.dat", getattr(paths, "metadata", ""))):
        try:
            stamp = os.path.getmtime(path)
        except OSError:
            continue
        if stamp > newest_ts:
            newest_name, newest_ts = name, stamp
    effective = updated_ts or int(newest_ts)
    return {
        "build_id": str(app.get("buildid") or ""),
        "updated_ts": effective,
        "updated_at": _iso_local(effective),
        "updated_source": ("steam-appmanifest" if updated_ts
                           else (f"文件时间({newest_name})" if newest_ts else "")),
    }

def _game_version_info(paths, pe=None, metadata_version: int = 0) -> dict:
    app = _steam_app_state(getattr(paths, "root", "") or "")
    build = game_build_note(paths)

    updated_at = build["updated_at"]
    return {
        "game_version": updated_at[:10] if updated_at else "unknown",
        "game_build_id": build["build_id"],
        "game_updated_at": updated_at,
        "game_updated_source": build["updated_source"],
        "dll_build_time": _iso_local(int(getattr(pe, "timestamp", 0) or 0)),
        "metadata_version": int(metadata_version or 0),
    }

def _reuse_decrypted(dump_dir: str, on_log=None) -> metadata_source.MetadataResult | None:
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
    def _slim(item: dict) -> dict:
        return {"rva": int(item.get("rva") or 0),
                "va": int(item.get("va") or 0),
                "slot": item.get("slot")}

    required = set(targets_mod.required_symbols())
    methods = {}
    for key, item in symbols.methods.items():
        if key in required:
            methods[key] = _slim(item)
    for key, item in symbols.methods.items():
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

def preload(on_log=None) -> None:
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
                      push: bool = True, low_priority: bool = True,
                      wait_for_game_idle: bool = True,
                      idle_wait_seconds: float = 900.0,
                      process_name: str = "LimbusCompany.exe") -> bool:
    global _auto_updating
    preload(on_log=on_log)
    with PUBLISHED_LOCK:
        if _auto_updating:
            return False
        _auto_updating = True

    def wait_until_game_idle() -> bool:
        try:
            from .memory import is_process_running
        except Exception:  # noqa: BLE001
            return True
        deadline = time.time() + max(0.0, float(idle_wait_seconds))
        announced = False
        while time.time() < deadline:
            if not is_process_running(process_name):
                if announced and on_log:
                    on_log("[hook_index] 游戏已退出 → 开始后台重建偏移索引（低优先级）")
                return True
            if not announced:
                announced = True
                if on_log:
                    on_log(f"[hook_index] 游戏正在运行 → 重建推迟到它退出之后"
                           f"（最多等 {idle_wait_seconds / 60:.0f} 分钟，避免和游戏抢 CPU/磁盘）")
            time.sleep(3.0)
        if on_log:
            on_log("[hook_index] 等待游戏退出超时 → 本轮不重建，下次空闲时再试")
        return False

    def worker() -> None:
        global _auto_updating
        try:
            if not force:
                try:
                    from . import preflight as _preflight
                    verdict = _preflight.ensure_offsets_ready(
                        on_log=on_log, game_path=game_path)
                    if verdict.get("source") in ("local", "cloud", "cloud-cache"):
                        if on_log:
                            on_log("[hook_index] 索引已可用"
                                   f"（{verdict.get('verdict', '')}，来源={verdict.get('source')}）"
                                   "→ 跳过本地重建（省掉约 40 秒静态解密）")
                        return
                except Exception as exc:  # noqa: BLE001
                    if on_log:
                        on_log(f"[hook_index] 预检失败（继续原流程）: {type(exc).__name__}: {exc}")
            if wait_for_game_idle and not wait_until_game_idle():
                return
            result = update_hook_index(game_path=game_path, force=force, push=push,
                                       on_log=on_log, low_priority=low_priority,
                                       process_name=process_name)
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
