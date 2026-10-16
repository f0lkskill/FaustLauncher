
from __future__ import annotations

import glob
import os

from functions.base import steam_locator as _sl

SECONDS_PER_MINUTE = 60

def localconfig_files() -> list[str]:
    out: list[str] = []
    for base in _sl._steam_install_paths():          # noqa: SLF001（同包内复用）
        pattern = os.path.join(str(base).replace("\\", "/"), "userdata", "*", "config",
                               "localconfig.vdf")
        out.extend(sorted(glob.glob(pattern)))
    return out

def _apps_table(path: str) -> dict:
    try:
        with open(path, encoding="utf-8", errors="ignore") as fh:
            data = _sl._parse_vdf(fh.read())         # noqa: SLF001
    except Exception:  # noqa: BLE001
        return {}
    store = data.get("UserLocalConfigStore") if isinstance(data, dict) else None
    software = (store or {}).get("Software") or {}
    steam = (software.get("Valve") or {}).get("Steam") or {}
    apps = steam.get("apps")
    return apps if isinstance(apps, dict) else {}

def _to_int(value) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return 0

def read_playtime(app_id: str = _sl.STEAM_APP_ID) -> dict:
    best: dict = {}
    files = localconfig_files()
    for path in files:
        apps = _apps_table(path)
        if not apps:
            continue
        entry = apps.get(str(app_id)) or apps.get(int(app_id)) \
            if str(app_id).isdigit() else apps.get(str(app_id))
        if not isinstance(entry, dict):
            continue
        minutes = _to_int(entry.get("Playtime"))
        if minutes <= 0:
            continue
        if minutes > _to_int(best.get("minutes")):
            best = {
                "minutes": minutes,
                "last_played": _to_int(entry.get("LastPlayed")),
                "source": path,
            }
    if not best:
        return {"ok": False, "accounts": len(files),
                "error": "Steam 本地缓存里没有这款游戏的时长记录" if files
                         else "没找到 Steam 的 localconfig.vdf（未安装/未登录 Steam？）"}
    seconds = int(best["minutes"]) * SECONDS_PER_MINUTE
    return {
        "ok": True,
        "seconds": seconds,
        "minutes": int(best["minutes"]),
        "hours": round(seconds / 3600.0, 1),
        "last_played": int(best.get("last_played") or 0),
        "accounts": len(files),
        "source": str(best.get("source") or ""),
    }

if __name__ == "__main__":
    import json
    info = read_playtime()
    if info.get("ok"):
        print(f"游玩时长: {info['hours']} 小时（{info['minutes']} 分钟 / {info['seconds']} 秒）")
        print(f"最后游玩: {info['last_played']}   账号数: {info['accounts']}")
        print(f"来源: {info['source']}")
    else:
        print(json.dumps(info, ensure_ascii=False, indent=2))
