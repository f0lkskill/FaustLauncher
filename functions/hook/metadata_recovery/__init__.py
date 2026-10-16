# -*- coding: utf-8 -*-

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Callable

from .pipeline import (
    VERSION_DEFAULT,
    capstone_available,
    new_run_dir,
    output_dir,
    run_recovery,
)
from .universal.pipeline import run as run_universal

__all__ = [
    "run_recovery",
    "capstone_available",
    "install_capstone",
    "derive_game_files",
    "output_dir",
    "new_run_dir",
    "VERSION_DEFAULT",
    "run_universal",
]

def install_capstone(on_log: Callable = None) -> dict:
    if on_log is None:
        on_log = lambda msg: print(msg, flush=True)  # noqa: E731
    on_log("正在安装 capstone（pip install capstone）...")
    try:
        proc = subprocess.Popen(
            [sys.executable, "-m", "pip", "install", "capstone"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
        )
        tail: list[str] = []
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.rstrip()
            if line:
                on_log(line)
            tail.append(line)
            if len(tail) > 20:
                tail.pop(0)
        rc = proc.wait()
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "message": f"安装失败：{exc}"}
    if rc != 0:
        return {"success": False,
                "message": "pip 安装失败（返回码非 0）：\n" + "\n".join(tail)}
    if not capstone_available():
        return {"success": False, "message": "pip 已完成但 capstone 仍不可用，请重启应用"}
    on_log("capstone 安装完成")
    return {"success": True, "message": "capstone 安装完成"}

def derive_game_files(game_path: str = "") -> dict:
    if not game_path:
        return {"game_path": "", "derived": False,
                "metadata_path": "", "metadata_exists": False,
                "dll_path": "", "dll_exists": False}
    root = Path(game_path)
    metadata = root / "LimbusCompany_Data" / "il2cpp_data" / "Metadata" / "global-metadata.dat"
    dll = root / "GameAssembly.dll"
    return {
        "game_path": str(root),
        "derived": True,
        "metadata_path": str(metadata),
        "metadata_exists": metadata.is_file(),
        "dll_path": str(dll),
        "dll_exists": dll.is_file(),
    }
