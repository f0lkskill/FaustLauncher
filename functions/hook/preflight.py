
from __future__ import annotations

import os

from . import index as index_mod
from . import paths as paths_mod

VERDICT_LOCAL_OK = "local-ok"
VERDICT_CLOUD_CACHED = "cloud-cached"
VERDICT_CLOUD_UPDATED = "cloud-updated"
VERDICT_REBUILT = "rebuilt"
VERDICT_STALE = "stale"
VERDICT_NO_INDEX = "no-index"
VERDICT_NO_GAME_DLL = "no-game-dll"
VERDICT_ERROR = "error"

def prologue_check(index, gameassembly: str, on_log=None) -> dict:
    log = on_log or (lambda _m: None)
    out = {"ok": False, "checked": 0, "matched": 0, "mismatch": [], "skipped": [],
           "detail": "", "fingerprint_ok": False, "disk_size": 0, "disk_timestamp": 0}
    if index is None:
        out["detail"] = "没有索引"
        return out
    if not gameassembly or not os.path.isfile(gameassembly):
        out["detail"] = "找不到 GameAssembly.dll"
        return out
    try:
        from .pe import PeFile
        pe = PeFile(gameassembly)
    except Exception as exc:  # noqa: BLE001
        out["detail"] = f"解析 GameAssembly.dll 失败: {exc}"
        return out

    out["disk_size"] = os.path.getsize(gameassembly)
    out["disk_timestamp"] = int(getattr(pe, "timestamp", 0) or 0)
    rec_size = int((index.game or {}).get("gameassembly_size") or 0)
    rec_ts = int((index.game or {}).get("pe_timestamp") or 0)
    out["fingerprint_ok"] = bool((not rec_size or rec_size == out["disk_size"])
                                 and (not rec_ts or rec_ts == out["disk_timestamp"]))

    for key, item in (index.hooks or {}).items():
        if not isinstance(item, dict):
            continue
        rva = int(item.get("rva") or 0)
        text = str(item.get("prologue") or "").replace(" ", "")
        if not rva or not text:
            out["skipped"].append(key)
            continue
        try:
            want = bytes.fromhex(text)
        except ValueError:
            out["skipped"].append(key)
            continue
        got = pe.read_at_rva(rva, len(want)) or b""
        out["checked"] += 1
        if got[:len(want)] == want:
            out["matched"] += 1
        else:
            out["mismatch"].append(f"{key}@0x{rva:X}(本机 {got[:len(want)].hex(' ') or '读不到'})")

    out["ok"] = bool(out["checked"] and not out["mismatch"])
    if out["ok"]:
        out["detail"] = (f"{out['matched']}/{out['checked']} 条 prologue 与本机 DLL 一致"
                         + ("（指纹也一致）" if out["fingerprint_ok"] else "（⚠ 指纹不一致）")
                         + (f"；{len(out['skipped'])} 条无 prologue 跳过" if out["skipped"] else ""))
    else:
        brief = "; ".join(out["mismatch"][:3])
        more = f" …等共 {len(out['mismatch'])} 条" if len(out["mismatch"]) > 3 else ""
        out["detail"] = (f"{out['matched']}/{out['checked']} 条一致"
                         + (f"；不一致: {brief}{more}" if out["mismatch"] else "")
                         + ("；索引里没有可校验的钩子" if not out["checked"] else ""))
    if out["mismatch"]:
        log(f"[OffsetProbe] 对不上的钩子 {len(out['mismatch'])}/{out['checked']} 条:")
        for item in out["mismatch"]:
            log(f"[OffsetProbe]   不一致: {item}")
    return out

def index_stale_for_game(index, paths) -> tuple[bool, str]:
    game = (index.game or {}) if index is not None else {}
    recorded_id = str(game.get("game_build_id") or "")
    recorded_at = str(game.get("game_updated_at") or "")
    if not recorded_id and not recorded_at:
        return False, "索引没有版本记录（只能按 prologue 判定）"
    try:
        from . import updater as updater_mod
        current = updater_mod.game_build_note(paths)
    except Exception as exc:  # noqa: BLE001
        return False, f"读不到本机游戏构建信息: {type(exc).__name__}: {exc}"
    if recorded_id and current["build_id"] and recorded_id != current["build_id"]:
        return True, (f"索引是 build {recorded_id} 生成的，本机现在是 "
                      f"build {current['build_id']}")
    if recorded_at and current["updated_at"] and recorded_at != current["updated_at"]:
        return True, (f"索引记的更新时间 {recorded_at} 与本机 {current['updated_at']} 不一致")
    return False, "索引版本与本机一致"

def _candidate_score(entry: dict, paths) -> tuple:
    game = (entry.get("index").game or {}) if entry.get("index") is not None else {}
    has_version = bool(str(game.get("game_build_id") or "")
                       or str(game.get("game_updated_at") or ""))
    stale, _why = index_stale_for_game(entry.get("index"), paths)
    is_cloud = entry.get("source") != "local"
    return (0 if stale else 1,
            1 if (has_version and not stale) else 0,
            1 if is_cloud else 0,
            int(entry["check"].get("matched") or 0))

def ensure_offsets_ready(on_log=None, game_path: str = "",
                         allow_cloud: bool = True, local_index=None) -> dict:
    log = on_log or (lambda _m: None)

    paths = paths_mod.game_paths(game_path)
    ga = getattr(paths, "gameassembly", "") or ""
    result = {"verdict": VERDICT_NO_INDEX, "source": "", "index": None, "check": {},
              "cloud_check": {}, "detail": ""}
    if not ga or not os.path.isfile(ga):
        result["verdict"] = VERDICT_NO_GAME_DLL
        result["detail"] = f"找不到 GameAssembly.dll（{ga or '路径未配置'}）"
        log(f"[OffsetProbe] {result['detail']}：跳过校验")
        return result

    entries: list[dict] = []
    local = local_index if local_index is not None else index_mod.get_index()[0]
    if local is not None:
        entries.append({"index": local, "source": "local",
                        "check": prologue_check(local, ga, on_log=log)})
    else:
        log("[OffsetProbe] 本地没有完整版索引")
    cloud_cache = index_mod.load_local(paths_mod.cloud_index_path())
    if cloud_cache is not None:
        entries.append({"index": cloud_cache, "source": "cloud-cache",
                        "check": prologue_check(cloud_cache, ga, on_log=log)})

    for entry in entries:
        stale, why = index_stale_for_game(entry["index"], paths)
        label = "本地" if entry["source"] == "local" else "云端缓存"
        log(f"[OffsetProbe] {label}偏移量 vs 本机 DLL: {entry['check']['detail']}"
            f"；版本: {why}")
        result["check"] = entry["check"]

    valid = [entry for entry in entries if entry["check"]["ok"]]
    if valid:
        chosen = max(valid, key=lambda entry: _candidate_score(entry, paths))
        index_mod.use_index(chosen["index"], chosen["source"])
        cloud_won = chosen["source"] != "local"
        others = [e for e in valid if e is not chosen]
        result.update(index=chosen["index"], source=chosen["source"],
                      check=chosen["check"], detail=chosen["check"]["detail"],
                      verdict=VERDICT_CLOUD_CACHED if cloud_won else VERDICT_LOCAL_OK)
        log("[OffsetProbe] 采用"
            + ("**云端**" if cloud_won else "本地")
            + f"偏移量（{chosen['check']['detail']}）"
            + ("；本机也有一份能对上的本地索引" if cloud_won and others else "")
            + " → 不联网、不重建")
        return result

    if not allow_cloud:
        result["verdict"] = VERDICT_STALE
        log("[OffsetProbe] 已按要求跳过云端对照")
        return result
    log("[OffsetProbe] 手头的索引都对不上本机 DLL → 开始与云端对照"
        f"（{index_mod.note_key()}）…")
    cloud = index_mod.refresh_local_from_cloud(allow_refresh=True, on_log=log)
    if cloud is not None:
        ccheck = prologue_check(cloud, ga, on_log=log)
        result["cloud_check"] = ccheck
        stale, why = index_stale_for_game(cloud, paths)
        log(f"[OffsetProbe] 云端偏移量 vs 本机 DLL: {ccheck['detail']}；版本: {why}")
        if ccheck["ok"]:
            index_mod.use_index(cloud, "cloud")
            result.update(verdict=VERDICT_CLOUD_UPDATED, index=cloud, source="cloud",
                          detail=ccheck["detail"])
            log("[OffsetProbe] 已采用云端索引（云端对得上本机 DLL）")
            return result
        log("[OffsetProbe] 云端偏移量也对不上本机 DLL")
    else:
        log("[OffsetProbe] 云端没有可用索引（首次使用/读取失败）")

    result["verdict"] = VERDICT_STALE
    result["detail"] = "偏移量与本机 GameAssembly.dll 对不上，且客户端已取消本地重建"
    log("[OffsetProbe] 本地与云端都对不上本机 DLL → 不再本地重建（客户端已取消该行为）。"
        "本次钩子可能装不上；需要新偏移请等云端更新，"
        "或手动跑 python -m functions.hook.main update")
    return result
