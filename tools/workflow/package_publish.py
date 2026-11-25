"""workflow 包的发布：就地保存信息 + 打包上传（先手动包装，再发布）。

包目录（tools/workflow/mods/<包名>）本身就是发布对象：
  · Mod 包：写 mod_info.json，file_names 自动取包根 .bank/.carra2/.rebank；
  · 插件包：写 addon_info.json（根目录已有 scr.py）；
  · 发布前按 core.publish_missing 检查必填项；
  · 每次发布保证版本号变化：与上次发布相同则自动 patch+1；
  · 上传时用临时干净目录，排除 .workflow_* / 日志 / 进度 / 源 .zip 等运行时文件。
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from datetime import datetime

import core
from functions.tools import post_extension_tools as pet


def _bump_patch(version: str) -> str:
    parts = str(version or "0.0.0").split(".")
    try:
        parts[-1] = str(int(parts[-1]) + 1)
    except (ValueError, IndexError):
        parts.append("1")
    return ".".join(parts)


def _next_version(current: str, last: str) -> str:
    current = str(current or "").strip() or "0.0.0"
    if str(last or "").strip() == current:
        return _bump_patch(current)
    return current


def _save_last_version(name: str, version: str) -> None:
    try:
        (core.package_dir(name) / core.PUBLISH_STATE_NAME).write_text(
            json.dumps({"last_version": version,
                        "at": datetime.now().isoformat(timespec="seconds")},
                       ensure_ascii=False),
            encoding="utf-8")
    except OSError:
        pass


def save_info(name, data) -> dict:
    """就地把填写的信息写进包目录（mod_info.json / addon_info.json + icon.png）。"""
    pkg = core.package_dir(name)
    if not pkg.is_dir():
        return {"ok": False, "error": "包不存在"}
    data = data or {}
    kind = core.package_kind(name)
    info = {
        "name": (str(data.get("name") or name)).strip() or name,
        "desc": str(data.get("desc") or "").strip(),
        "version": str(data.get("version") or "0.0.1").strip() or "0.0.1",
        "authors": data.get("authors") or {},
    }
    if kind == "addon":
        info["settings"] = {"enable": False}
        info_file = core.INFO_ADDON_NAME
    else:
        info["settings"] = {"enable": True}
        info["single_file"] = True
        info["file_names"] = core.scan_load_files(name)
        info_file = core.INFO_MOD_NAME

    try:
        icon_path = data.get("icon_path")
        if icon_path and os.path.isfile(icon_path):
            shutil.copy2(icon_path, pkg / core.ICON_NAME)
        elif not (pkg / core.ICON_NAME).is_file():
            pet.generate_icon(str(pkg / core.ICON_NAME), text=info["name"][:1])
    except Exception as e:
        return {"ok": False, "error": f"处理图标失败: {e}"}

    try:
        (pkg / info_file).write_text(
            json.dumps(info, ensure_ascii=False, indent=4), encoding="utf-8")
    except OSError as e:
        return {"ok": False, "error": f"写入信息失败: {e}"}
    return {"ok": True, "kind": kind, "info": info}


def _materialize(name: str, dst: str) -> None:
    """把包内可发布文件复制到干净目录，排除运行时文件与源 zip。"""
    pkg = core.package_dir(name)
    for root, _dirs, files in os.walk(pkg):
        for f in files:
            if f.startswith(".") or f in core.IGNORED_NAMES:
                continue
            if f.lower().endswith((".tmp", ".zip")):
                continue
            src = os.path.join(root, f)
            rel = os.path.relpath(src, pkg)
            out = os.path.join(dst, rel)
            os.makedirs(os.path.dirname(out), exist_ok=True)
            shutil.copy2(src, out)


def publish(name, log=None, progress=None) -> dict:
    """校验 → 版本自增 → 干净目录 → 上传蓝奏云并更新云端。"""
    if log is None:
        log = lambda *_a, **_k: None
    pkg = core.package_dir(name)
    if not pkg.is_dir():
        return {"ok": False, "msg": "包不存在"}

    missing = core.publish_missing(name)
    if missing:
        return {"ok": False, "msg": "请先补全：" + "、".join(missing), "missing": missing}

    kind, info = core.package_info(name)
    current = str(info.get("version") or "").strip() or "0.0.1"
    last = core.last_published_version(name)
    version = _next_version(current, last)
    if version != current:
        info = dict(info)
        info["version"] = version
        info_file = core.INFO_ADDON_NAME if kind == "addon" else core.INFO_MOD_NAME
        try:
            (pkg / info_file).write_text(
                json.dumps(info, ensure_ascii=False, indent=4), encoding="utf-8")
            log(f"版本号自动更新: {current} → {version}")
        except OSError as e:
            log(f"写入版本号失败: {e}")

    tmp = tempfile.mkdtemp(prefix="wf_publish_")
    try:
        _materialize(name, tmp)
        if progress:
            progress(0, "开始上传...")
        if kind == "addon":
            ok, msg = pet.publish_addon(tmp, log=log, progress=progress)
        else:
            ok, msg = pet.publish_mod(tmp, log=log, progress=progress)
        if ok:
            _save_last_version(name, version)
        return {"ok": bool(ok), "msg": msg, "version": version}
    except Exception as e:
        return {"ok": False, "msg": f"发布失败: {e}", "version": version}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
