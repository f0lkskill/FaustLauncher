"""注入前的偏移量预检：**先和本机 DLL 对，对不上再动云端 / 重建**。

顺序（用户约定，2026-09-24；2026-10-09 重写为"云端优先 + 重建搬离启动窗口"）：

1. **先看手头能用的，都不联网**：本地完整版索引 + 本地缓存的云端索引，把每条钩子的
   ``prologue`` 逐字节与 ``GameAssembly.dll`` 的实际字节比对，并核对游戏指纹
   （size / PE 时间戳）。有**任何一份**能对上就直接用。
   两份都能对上时按 :func:`_candidate_score` 择优 —— **云端优先**（用户约定：云端那份
   对得上本机 DLL 就承认它是最新的，不再"只认本地对不对得上"）。
2. **都对不上才找云端**：强制联网拉一次云端索引；若云端这份能对上本机 DLL
   （说明"本地偏移量是旧版本，云端已经有新版"）→ 采用云端（写进云端缓存文件，
   **不覆盖**本地完整版索引），后续所有消费者都用它。
3. **都对不上**：本地重建（解密 → dump.cs → 解析 → 四重校验），写本地缓存，
   ``push=True`` 时把新偏移**上传云端**。

   ⚠ **游戏正在运行时绝不在这里重建**（``VERDICT_DEFERRED``）。解密约 50 秒满核 +
   Il2CppDumper 满核 1~2 分钟，跑在游戏启动/运行的同一时刻会把整台机器卡到鼠标拖影
   （实测 10-09：游戏 13:11:36 启动，解密 dump 13:12:51→13:15:11 全程并行）。
   改成排一个后台任务，等游戏退出后再以低优先级重建（见 ``updater.auto_update_async``
   的 ``wait_for_game_idle``）；启动器侧在游戏退出/启动器刚起来时也会主动触发一次。

第 3 步可以用设置项 ``auto_update_hook_index``（缺省 true）关掉；关掉时只做校验与
云端参考，不改本地、不上传。

判定"对得上"的为什么是 prologue 而不是指纹：真正决定能不能装钩的是
"索引里的 RVA 处、本机 DLL 的字节是不是我们记下的那几条指令"（DLL 装钩前也会再比一次）。
指纹（size / sha256 / PE 时间戳）只用来解释"为什么对不上"，两个信号都会记进日志。

另外多了一个**版本信号**（:func:`index_stale_for_game`）：索引里记着生成它的那份游戏的
Steam buildid / 更新时间，与当前 appmanifest 一比就知道这份索引是不是当前游戏版本生成的。
prologue 只覆盖代码钩子，结构体字段 / 数据链偏移过期它看不出来，版本信号补上这一块。
"""

from __future__ import annotations

import os

from . import index as index_mod
from . import paths as paths_mod

VERDICT_LOCAL_OK = "local-ok"            # 本地索引就能对上本机 DLL（未联网）
VERDICT_CLOUD_CACHED = "cloud-cached"    # 用本地缓存的云端索引（未联网）
VERDICT_CLOUD_UPDATED = "cloud-updated"  # 本地旧了，已采用云端索引
VERDICT_REBUILT = "rebuilt"              # 都对不上，已本地重建（并按需上传）
VERDICT_DEFERRED = "deferred"            # 需要重建，但游戏在跑 → 推迟到空闲时
VERDICT_STALE = "stale"                  # 对不上，但按要求不许重建/联网
VERDICT_NO_INDEX = "no-index"            # 本地/云端都没有索引
VERDICT_NO_GAME_DLL = "no-game-dll"      # 找不到 GameAssembly.dll
VERDICT_ERROR = "error"


def auto_rebuild_enabled() -> bool:
    """设置项 ``auto_update_hook_index``（缺省 true）：对不上时允不允许本地重建。"""
    try:
        from functions.base.settings_manager import get_settings_manager
        value = get_settings_manager().get_setting("auto_update_hook_index")
        return True if value is None else bool(value)
    except Exception:  # noqa: BLE001
        return True


def prologue_check(index, gameassembly: str, on_log=None) -> dict:
    """把索引里的每条钩子 prologue 与本机 DLL 字节比对。

    返回 ``{"ok", "checked", "matched", "mismatch", "skipped", "detail",
    "fingerprint_ok", "disk_size", "disk_timestamp", ...}``。
    """
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
        out["detail"] = (f"{out['matched']}/{out['checked']} 条一致"
                         + (f"；不一致: {'; '.join(out['mismatch'][:4])}" if out["mismatch"] else "")
                         + ("；索引里没有可校验的钩子" if not out["checked"] else ""))
    if out["mismatch"]:
        log(f"[偏移预检] 对不上的钩子: {'; '.join(out['mismatch'])}")
    return out


# --------------------------------------------------------------------------- 版本信号


def index_stale_for_game(index, paths) -> tuple[bool, str]:
    """这份索引是不是**当前这个游戏版本**生成的。

    prologue 只能证明"代码钩子那几条指令还在原处"；游戏更新常常只挪结构体字段、
    不动那几个函数 —— 那种情况下 prologue 全绿，但 ``fields`` / ``targets`` 里的偏移
    已经过期，继续用就会读出垃圾甚至崩游戏。这里用索引里记下的 Steam buildid /
    更新时间与本机 appmanifest 对比，把这种情况直接判成"过期"。

    只有索引**确实记了**版本才判断：老索引没有这些字段时返回 ``False`` + 说明，
    不拿它当否决理由（那时只能靠 prologue）。
    """
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
    """候选索引的择优键（越大越优先）。

    1) **版本对得上本机当前游戏** > 版本对不上（:func:`index_stale_for_game`）；
    2) **能证明自己是当前版本**（索引里记了 buildid / 更新时间且与本机一致）> 证明不了
       —— 老索引没有版本字段，prologue 全绿也可能带着过期的结构体字段 / 数据链偏移，
       这时候宁可先用那份能自证的（本地完整版通常是本机刚构建的）；
    3) 同档里 **云端优先** —— 用户约定：云端那份能证明自己是当前版本、又对得上本机 DLL，
       就承认它是最新的，不再像以前那样"只看本地 RVA 处的 16 字节对不对"；
    4) 再同档则 prologue 命中条数多的优先（信息更全）。
    """
    game = (entry.get("index").game or {}) if entry.get("index") is not None else {}
    has_version = bool(str(game.get("game_build_id") or "")
                       or str(game.get("game_updated_at") or ""))
    stale, _why = index_stale_for_game(entry.get("index"), paths)
    is_cloud = entry.get("source") != "local"
    return (0 if stale else 1,
            1 if (has_version and not stale) else 0,
            1 if is_cloud else 0,
            int(entry["check"].get("matched") or 0))


def ensure_offsets_ready(on_log=None, game_path: str = "", push: bool = True,
                         allow_cloud: bool = True, allow_rebuild: bool | None = None,
                         local_index=None, process_name: str = "LimbusCompany.exe") -> dict:
    """注入前的偏移量预检（同步；只有真的要重建时才会久，约 1~2 分钟）。

    返回 ``{"verdict", "source", "index", "check", "cloud_check", "detail", "pushed"}``；
    选定索引时会把进程内记忆一并固定（``index_mod.use_index``），保证后面钩子表 / 字段偏移 /
    数据链全用同一份。

    **本函数不会在游戏运行时做重建**：那种情况返回 ``VERDICT_DEFERRED`` 并排一个
    "等游戏退出再重建"的后台任务，调用方应当照常继续（用现有索引 / 内置回退偏移），
    只是本次观测可能不完整。
    """
    log = on_log or (lambda _m: None)
    if allow_rebuild is None:
        allow_rebuild = auto_rebuild_enabled()

    paths = paths_mod.game_paths(game_path)
    ga = getattr(paths, "gameassembly", "") or ""
    result = {"verdict": VERDICT_NO_INDEX, "source": "", "index": None, "check": {},
              "cloud_check": {}, "detail": "", "pushed": False}
    if not ga or not os.path.isfile(ga):
        result["verdict"] = VERDICT_NO_GAME_DLL
        result["detail"] = f"找不到 GameAssembly.dll（{ga or '路径未配置'}）"
        log(f"[偏移预检] {result['detail']}：跳过校验")
        return result

    # ---- 1) 手头能用的两份（本地完整版 + 本地缓存的云端索引）：都不联网
    entries: list[dict] = []
    local = local_index if local_index is not None else index_mod.get_index()[0]
    if local is not None:
        entries.append({"index": local, "source": "local",
                        "check": prologue_check(local, ga, on_log=log)})
    else:
        log("[偏移预检] 本地没有完整版索引")
    cloud_cache = index_mod.load_local(paths_mod.cloud_index_path())
    if cloud_cache is not None:
        entries.append({"index": cloud_cache, "source": "cloud-cache",
                        "check": prologue_check(cloud_cache, ga, on_log=log)})

    for entry in entries:
        stale, why = index_stale_for_game(entry["index"], paths)
        label = "本地" if entry["source"] == "local" else "云端缓存"
        log(f"[偏移预检] {label}偏移量 vs 本机 DLL: {entry['check']['detail']}"
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
        log("[偏移预检] 采用"
            + ("**云端**" if cloud_won else "本地")
            + f"偏移量（{chosen['check']['detail']}）"
            + ("；本机也有一份能对上的本地索引" if cloud_won and others else "")
            + " → 不联网、不重建")
        return result

    # ---- 2) 两份都对不上 → 和云端对照（这一步才联网）
    if not allow_cloud:
        result["verdict"] = VERDICT_STALE
        log("[偏移预检] 已按要求跳过云端对照")
        return result
    log("[偏移预检] 手头的索引都对不上本机 DLL → 开始与云端对照"
        f"（{index_mod.note_key()}）…")
    cloud = index_mod.refresh_local_from_cloud(allow_refresh=True, on_log=log)
    if cloud is not None:
        ccheck = prologue_check(cloud, ga, on_log=log)
        result["cloud_check"] = ccheck
        stale, why = index_stale_for_game(cloud, paths)
        log(f"[偏移预检] 云端偏移量 vs 本机 DLL: {ccheck['detail']}；版本: {why}")
        if ccheck["ok"]:
            index_mod.use_index(cloud, "cloud")
            result.update(verdict=VERDICT_CLOUD_UPDATED, index=cloud, source="cloud",
                          detail=ccheck["detail"])
            log("[偏移预检] 已采用云端索引（云端对得上本机 DLL）")
            return result
        log("[偏移预检] 云端偏移量也对不上本机 DLL")
    else:
        log("[偏移预检] 云端没有可用索引（首次使用/读取失败）")

    # ---- 3) 都对不上 → 需要重建
    if not allow_rebuild:
        result["verdict"] = VERDICT_STALE
        log("[偏移预检] 需要本地重建，但设置项「自动刷新游戏偏移索引」已关闭 / 本轮不允许"
            " → 跳过（本次钩子可能装不上，请在设置里打开或跑 "
            "python -m functions.hook.main update）")
        return result

    from .memory import is_process_running
    if is_process_running(process_name):
        # ⚠ 关键：绝不在游戏运行时重建。解密 + Il2CppDumper 是满核 1~2 分钟的重活，
        #    和游戏启动/运行重叠会把整台机器卡住（实测鼠标拖影）。
        result["verdict"] = VERDICT_DEFERRED
        result["detail"] = ("需要重建偏移索引，但游戏正在运行 → 本次不重建"
                           "（已排入后台，等游戏退出后以低优先级重建）")
        log(f"[偏移预检] {result['detail']}")
        if not _background_update_running(log):
            try:
                from . import updater as updater_mod
                updater_mod.auto_update_async(on_log=log, game_path=game_path, push=push,
                                              low_priority=True, wait_for_game_idle=True,
                                              process_name=process_name)
            except Exception as exc:  # noqa: BLE001
                log(f"[偏移预检] 排入后台重建失败: {type(exc).__name__}: {exc}")
        return result

    log("[偏移预检] 本地+云端都对不上本机 DLL，且游戏没在运行 → 本地重建偏移量"
        + ("并上传云端" if push else "（不上传）") + "…")
    try:
        from . import updater as updater_mod
        outcome = updater_mod.update_hook_index(game_path=game_path, force=True,
                                                push=push, on_log=log,
                                                low_priority=True,
                                                process_name=process_name)
    except Exception as exc:  # noqa: BLE001
        result["verdict"] = VERDICT_ERROR
        result["detail"] = f"本地重建失败: {type(exc).__name__}: {exc}"
        log(f"[偏移预检] {result['detail']}")
        return result
    index_mod.clear_memo()
    fresh, source = index_mod.get_index()
    check = prologue_check(fresh, ga, on_log=log) if fresh is not None else {}
    if fresh is not None:
        index_mod.use_index(fresh, "rebuilt")
    result.update(index=fresh, source="rebuilt", check=check, pushed=bool(outcome.pushed),
                  detail=(check.get("detail") or outcome.summary()))
    log(f"[偏移预检] 重建结果: {outcome.summary()}；校验: {check.get('detail', '无')}")
    result["verdict"] = (VERDICT_REBUILT if check.get("ok")
                         else f"{VERDICT_REBUILT}-unverified")
    return result


def _background_update_running(log) -> bool:
    """是否已经有一个后台重建任务在跑（避免重复排队）。"""
    try:
        from . import updater as updater_mod
        if updater_mod.is_auto_updating():
            log("[偏移预检] 已有后台重建任务在跑 → 不重复排队")
            return True
    except Exception:  # noqa: BLE001
        pass
    return False
