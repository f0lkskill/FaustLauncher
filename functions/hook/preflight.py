"""注入前的偏移量预检：**先和本机 DLL 对，对不上再动云端 / 重建**。

顺序（用户约定，2026-09-24）：

1. **本地优先、不联网**：拿手头能用的索引（本地完整版 → 云端缓存），把每条钩子的
   ``prologue`` 逐字节与 ``GameAssembly.dll`` 的实际字节比对，并核对游戏指纹
   （size / PE 时间戳）。能对上就直接用 —— 这条路径**一个网络请求都不发**。
2. **对不上才找云端**：强制联网拉一次云端索引；若云端这份能对上本机 DLL
   （说明"本地偏移量是旧版本，云端已经有新版"）→ 采用云端（写进云端缓存文件，
   **不覆盖**本地完整版索引），后续所有消费者都用它。
3. **都对不上**：本地重建（解密 → dump.cs → 解析 → 四重校验），写本地缓存，
   ``push=True`` 时把新偏移**上传云端**。

第 3 步可以用设置项 ``auto_update_hook_index``（缺省 true）关掉；关掉时只做校验与
云端参考，不改本地、不上传。

判定"对得上"的为什么是 prologue 而不是指纹：真正决定能不能装钩的是
"索引里的 RVA 处、本机 DLL 的字节是不是我们记下的那几条指令"（DLL 装钩前也会再比一次）。
指纹（size / sha256 / PE 时间戳）只用来解释"为什么对不上"，两个信号都会记进日志。
"""

from __future__ import annotations

import os

from . import index as index_mod
from . import paths as paths_mod

VERDICT_LOCAL_OK = "local-ok"            # 本地索引就能对上本机 DLL（未联网）
VERDICT_CLOUD_UPDATED = "cloud-updated"  # 本地旧了，已采用云端索引
VERDICT_REBUILT = "rebuilt"              # 都对不上，已本地重建（并按需上传）
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


def ensure_offsets_ready(on_log=None, game_path: str = "", push: bool = True,
                         allow_cloud: bool = True, allow_rebuild: bool | None = None,
                         local_index=None) -> dict:
    """注入前的偏移量预检（同步；只有真的要重建时才会久，约 1~2 分钟）。

    返回 ``{"verdict", "source", "index", "check", "cloud_check", "detail", "pushed"}``；
    选定索引时会把进程内记忆一并固定（``index.use_index``），保证后面钩子表 / 字段偏移 /
    数据链全用同一份。
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

    # ---- 1) 本地（含云端缓存）：不联网，先看能不能对上本机 DLL
    local = local_index if local_index is not None else index_mod.get_index()[0]
    if local is None:
        # 本地一个都没有：读一下云端缓存文件（也是本地磁盘，不联网）
        local = index_mod.load_local(paths_mod.cloud_index_path())
    if local is not None:
        check = prologue_check(local, ga, on_log=log)
        result.update(index=local, source="local", check=check, detail=check["detail"])
        log(f"[偏移预检] 本地偏移量 vs 本机 DLL: {check['detail']}")
        if check["ok"]:
            index_mod.use_index(local, "local")
            result["verdict"] = VERDICT_LOCAL_OK
            log("[偏移预检] 偏移量对得上本机 DLL → 直接使用（不联网、不重建）")
            return result
        log(f"[偏移预检] 本地偏移量对不上本机 DLL"
            f"（索引 size={int((local.game or {}).get('gameassembly_size') or 0)} "
            f"ts=0x{int((local.game or {}).get('pe_timestamp') or 0):X}；"
            f"磁盘 size={check['disk_size']} ts=0x{check['disk_timestamp']:X}）")
    else:
        result["detail"] = "本地没有任何索引"
        log("[偏移预检] 本地没有可用索引")

    # ---- 2) 本地对不上 → 和云端对照
    if not allow_cloud:
        result["verdict"] = VERDICT_STALE
        log("[偏移预检] 已按要求跳过云端对照")
        return result
    log("[偏移预检] 开始与云端对照（faustlauncher.hook_index）…")
    cloud = index_mod.refresh_local_from_cloud(allow_refresh=True, on_log=log)
    if cloud is not None:
        ccheck = prologue_check(cloud, ga, on_log=log)
        result["cloud_check"] = ccheck
        log(f"[偏移预检] 云端偏移量 vs 本机 DLL: {ccheck['detail']}")
        if ccheck["ok"]:
            index_mod.use_index(cloud, "cloud")
            result.update(verdict=VERDICT_CLOUD_UPDATED, index=cloud, source="cloud",
                          detail=ccheck["detail"])
            log("[偏移预检] 本地偏移量是旧版本 → 已采用云端索引（云端对得上本机 DLL）")
            return result
        log("[偏移预检] 云端偏移量也对不上本机 DLL")
    else:
        log("[偏移预检] 云端没有可用索引（首次使用/读取失败）")

    # ---- 3) 都对不上 → 本地重建（并按需上传）
    if not allow_rebuild:
        result["verdict"] = VERDICT_STALE
        log("[偏移预检] 需要本地重建，但设置项「自动刷新游戏偏移索引」已关闭 → 跳过"
            "（本次钩子可能装不上，请在设置里打开或跑 python -m functions.hook.main update）")
        return result
    log("[偏移预检] 本地+云端都对不上本机 DLL → 本地重建偏移量"
        + ("并上传云端" if push else "（不上传）") + "…")
    try:
        from . import updater as updater_mod
        # 启动时可能已经有一个后台重建在跑（hook._start_hook_index_refresh →
        # auto_update_async）：两边同时解密+dump 是白烧 CPU，等它结束再校验。
        if updater_mod.is_auto_updating():
            log("[偏移预检] 已有后台重建任务在跑 → 等它结束再校验（最多 5 分钟）")
            import time as _time
            deadline = _time.time() + 300
            while updater_mod.is_auto_updating() and _time.time() < deadline:
                _time.sleep(1.0)
            index_mod.clear_memo()
            fresh, source = index_mod.get_index()
            check = prologue_check(fresh, ga, on_log=log) if fresh is not None else {}
            if fresh is not None:
                index_mod.use_index(fresh, "background")
            result.update(index=fresh, source="background", check=check,
                          detail=(check.get("detail") or "后台重建结束"))
            result["verdict"] = (VERDICT_REBUILT if check.get("ok")
                                 else f"{VERDICT_REBUILT}-unverified")
            log(f"[偏移预检] 后台重建结束，校验: {check.get('detail', '无')}")
            return result
        outcome = updater_mod.update_hook_index(game_path=game_path, force=True,
                                               push=push, on_log=log)
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
