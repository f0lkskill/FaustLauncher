"""从 Steam 本地缓存读游戏游玩时长（用于排行榜上报）。

数据来源：``<Steam>/userdata/<steam_id>/config/localconfig.vdf`` —— 一个 VDF 文本文件，
里面每个游戏一条：``Playtime`` = **累计分钟数**、``LastPlayed`` = 最后游玩时间戳（秒）。
文件结构：

    "UserLocalConfigStore"
    {
        "Software" { "Valve" { "Steam" { "apps" { "1973530" { "Playtime" "44884" } } } } }
    }

这个文件**只在已登录 Steam 客户端的本机存在**，远程拿不到 —— 所以只能在用户自己的
电脑上读。多账号（多个 userdata 目录）时取**时长最大的那条**（同一个游戏通常只在一个账号上玩）。

复用 ``steam_locator`` 里的 VDF 解析与 Steam 安装目录定位（同一个解析器解析
libraryfolders.vdf / appmanifest，实测能正确读出嵌套结构）。
"""

from __future__ import annotations

import glob
import os

from functions.base import steam_locator as _sl

#: 分钟 → 秒
SECONDS_PER_MINUTE = 60


def localconfig_files() -> list[str]:
    """列出本机所有 Steam 账号的 ``localconfig.vdf`` 路径。"""
    out: list[str] = []
    for base in _sl._steam_install_paths():          # noqa: SLF001（同包内复用）
        pattern = os.path.join(str(base).replace("\\", "/"), "userdata", "*", "config",
                               "localconfig.vdf")
        out.extend(sorted(glob.glob(pattern)))
    return out


def _apps_table(path: str) -> dict:
    """读一个 localconfig.vdf，返回 ``apps`` 那张表（读不到给空 dict）。"""
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
    """读该游戏的累计游玩时长。

    返回示例::

        {"ok": True, "seconds": 2693040, "minutes": 44884, "hours": 748.1,
         "last_played": 1791096623, "accounts": 2, "source": "<localconfig 路径>"}

    读不到（没装 Steam / 没登录过 / 该账号没这个游戏）返回 ``{"ok": False, "error": ...}``。
    """
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


if __name__ == "__main__":                            # 手动查看用
    import json
    info = read_playtime()
    if info.get("ok"):
        print(f"游玩时长: {info['hours']} 小时（{info['minutes']} 分钟 / {info['seconds']} 秒）")
        print(f"最后游玩: {info['last_played']}   账号数: {info['accounts']}")
        print(f"来源: {info['source']}")
    else:
        print(json.dumps(info, ensure_ascii=False, indent=2))
