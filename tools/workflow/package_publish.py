"""workflow 包的发布：提取信息 → 生成临时目录 → 生成临时 zip → 上传。

包目录（tools/workflow/mods/<包名>）本身是发布对象：
  · 发布前从 mod_info.json / addon_info.json 提取信息并按必填项校验；
  · 只排除启动器/工作流的运行时标记文件（见 _keep），其余内容统一带上；
  · 再把临时目录压缩成临时 zip，用该 zip 上传蓝奏云，最后更新云端信息；
  · 每次发布保证版本号变化：与上次发布相同则自动 patch+1。
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import zipfile
from datetime import datetime

import core
from functions.tools import post_extension_tools as pet

# 发布时排除的启动器/工作流运行时标记（只排这些，其余内容统一发布）：
#   · core.IGNORED_NAMES 里的 job / 进度 / 日志 / manifest 等固定文件名
#   · 任意 *.log（打包日志）
#   · 音效备份与版本标记：<bank>.bank.orig、<stem>.rebank.src
#   · 临时文件 *.tmp
# 注意：mod_info.json / addon_info.json / changes.json / 任意 .json 都是内容，不排除。
_PUBLISH_SKIP_SUFFIXES = (".log", ".bank.orig", ".rebank.src", ".tmp")
_PUBLISH_SKIP_NAMES = {name.lower() for name in core.IGNORED_NAMES}


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
    # 作者：没填时默认把自己（启动器记录的用户名 + 主页 URL）作为第一位作者
    authors = data.get("authors") or {}
    if not authors:
        try:
            from functions.base import user_system
            from functions.base.settings_manager import get_settings_manager
            ui = user_system.get_user_info(get_settings_manager())
            uname = str(ui.get("user_name") or "").strip()
            if uname:
                authors = {uname: str(ui.get("profile_url") or "").strip()}
        except Exception:
            authors = {}
    info = {
        "name": (str(data.get("name") or name)).strip() or name,
        "desc": str(data.get("desc") or "").strip(),
        "version": str(data.get("version") or "0.0.1").strip() or "0.0.1",
        "authors": authors,
    }
    if kind == "addon":
        info["settings"] = {"enable": True}
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


def _keep(rel: str, fname: str) -> bool:
    """判断包内某文件是否进入发布内容。

    只排除启动器/工作流的运行时标记文件，其余内容一律发布：
    不再按 carra2 / rebank / json 白名单挑选，避免“无法打成 carra2”的
    mod（Installer 完整包、混合资源等）在发布时被误删内容。
    """
    rel_parts = rel.replace("\\", "/").split("/")
    # 隐藏文件/目录（.workflow_* 等标记）与 Python 缓存一律不带
    if any(p.startswith(".") for p in rel_parts) or "__pycache__" in rel_parts:
        return False
    lower = fname.lower()
    if lower in _PUBLISH_SKIP_NAMES:
        return False
    return not lower.endswith(_PUBLISH_SKIP_SUFFIXES)


def _materialize(name: str, dst: str) -> None:
    """把需要发布的文件复制到临时发布目录（只跳过运行时标记）。"""
    pkg = core.package_dir(name)
    for root, _dirs, files in os.walk(pkg):
        for f in files:
            if f.startswith(".") or f in core.IGNORED_NAMES:
                continue
            src = os.path.join(root, f)
            rel = os.path.relpath(src, pkg)
            if not _keep(rel, f):
                continue
            out = os.path.join(dst, rel)
            os.makedirs(os.path.dirname(out), exist_ok=True)
            shutil.copy2(src, out)


def _expand_installer_archives(root: str, log) -> None:
    """上传前把含 installer.bat 的归档展开到发布根目录。

    · 含安装脚本的 .zip / .zip.back：去掉外层目录展开到根目录后删除归档，
      发布内容根目录即 installer.bat / uninstaller.bat / Assets；
    · 其它 .zip.back：仅恢复为 .zip（标记只是阻止打包流识别）。
    """
    try:
        entries = sorted(os.listdir(root))
    except OSError:
        return
    for entry in entries:
        path = os.path.join(root, entry)
        if not os.path.isfile(path):
            continue
        lower = entry.lower()
        if not (lower.endswith(".zip") or lower.endswith(".zip.back")):
            continue
        detail = core.expand_installer_archive(path, root)
        if not detail.get("ok"):
            log(f"展开 {entry} 失败: {detail.get('error')}")
            continue
        if detail.get("expanded"):
            try:
                os.remove(path)
            except OSError:
                pass
            log(f"已展开安装包 {entry} → 根目录（installer.bat / Assets）")
        elif lower.endswith(".zip.back"):
            target = os.path.join(root, entry[:-5])
            if not os.path.exists(target):
                try:
                    os.rename(path, target)
                    log(f"已恢复归档名: {entry} → {entry[:-5]}")
                except OSError as exc:
                    log(f"恢复 {entry} 失败: {exc}")


def _zip_dir(src_dir: str, zip_path: str, arc_name: str) -> int:
    """把临时目录压成临时 zip，返回文件数。"""
    if os.path.exists(zip_path):
        try:
            os.remove(zip_path)
        except OSError:
            pass
    files = []
    for root, _dirs, fs in os.walk(src_dir):
        for f in fs:
            files.append(os.path.join(root, f))
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for full in files:
            rel = os.path.relpath(full, src_dir).replace("\\", "/")
            zf.write(full, (arc_name + "/" + rel) if arc_name else rel)
    return len(files)


def _upload_zip(kind: str, info_dir: str, zip_path: str, log, progress) -> dict:
    """用已生成的临时 zip 上传蓝奏云（跳过重复压缩），返回直链。"""
    meta = pet.INFO_KINDS.get(kind)
    if not meta:
        raise RuntimeError(f"未知的扩展类型: {kind}")
    info, err = pet.load_extension_info(kind, info_dir)
    if err:
        raise RuntimeError(err)
    icon_path = os.path.join(info_dir, "icon.png")
    if not os.path.isfile(icon_path):
        raise RuntimeError(f"缺少图标文件: {icon_path}")

    cfg = pet.get_lanzou_config()
    icons_folder = (cfg.get("icons_folder") or "FaustLauncher.icons").strip()
    target_folder = (cfg.get(meta["folder_key"]) or meta["folder_default"]).strip()
    max_size_mb = int(cfg.get("max_size_mb") or 66)

    from functions.web_update.lanzou_utils import GetOrCreateFolder, UploadFile

    session = pet._lanzou_session(log)
    partial = {}

    def _fail(msg):
        e = RuntimeError(msg)
        e.partial_urls = dict(partial)
        raise e

    zip_size_mb = os.path.getsize(zip_path) / 1024.0 / 1024.0
    log(f"临时 zip 大小: {zip_size_mb:.1f} MB")
    if zip_size_mb > max_size_mb:
        raise RuntimeError(
            f"{meta['label']}包 {zip_size_mb:.1f} MB 超过蓝奏云单文件上限 {max_size_mb} MB")

    log(f"定位蓝奏云文件夹: {icons_folder}")
    icon_fid = GetOrCreateFolder(session, icons_folder)
    if not icon_fid:
        _fail(f"无法创建/定位蓝奏云文件夹: {icons_folder}")
    log("上传图标...")
    ret_icon = UploadFile(
        session, icon_path, folder_id=icon_fid,
        progress_callback=lambda p: progress and progress(p * 100, f"上传图标 {p * 100:.0f}%"))
    if ret_icon.get("status") != 1:
        _fail(f"图标上传失败: {ret_icon.get('msg')}")
    icon_share = ret_icon.get("share_url") or ""
    if not icon_share:
        _fail("图标上传缺少 share_url")
    partial = {"icon_url": pet.PARSER_BASE + icon_share, "icon_share_url": icon_share}

    log(f"定位蓝奏云文件夹: {target_folder}")
    pack_fid = GetOrCreateFolder(session, target_folder)
    if not pack_fid:
        _fail(f"无法创建/定位蓝奏云文件夹: {target_folder}")
    log("上传压缩包...")
    ret_pack = UploadFile(
        session, zip_path, folder_id=pack_fid, max_size_mb=max_size_mb,
        progress_callback=lambda p: progress and progress(p * 100, f"上传压缩包 {p * 100:.0f}%"))
    if ret_pack.get("status") != 1:
        _fail(f"压缩包上传失败: {ret_pack.get('msg')}")
    pack_share = ret_pack.get("share_url") or ""
    if not pack_share:
        _fail("压缩包上传缺少 share_url")

    return {
        "icon_url": pet.PARSER_BASE + icon_share,
        "dowload_url": pet.PARSER_BASE + pack_share,
        "icon_share_url": icon_share,
        "mod_share_url": pack_share,
    }


def publish(name, log=None, progress=None) -> dict:
    """校验 → 版本自增 → 提取内容到临时目录 → 临时 zip → 上传 → 更新云端。"""
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

    arc_name = str(info.get("name") or name).strip() or name
    tmp = tempfile.mkdtemp(prefix="wf_publish_")
    zip_path = tmp + ".zip"
    try:
        _materialize(name, tmp)
        log("已提取发布内容到临时目录")
        _expand_installer_archives(tmp, log)
        # 走统一的“测验 → 上传 → 提交审核”流程（publish_mod/addon 内部处理）
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
        try:
            if os.path.isfile(zip_path):
                os.remove(zip_path)
        except OSError:
            pass
