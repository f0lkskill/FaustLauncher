"""YisangMirrorFlow 的核心逻辑（不依赖 pywebview）。

每个包就是 ``tools/workflow/mods/<包名>`` 下的一个文件夹：
  · 用户把 .zip / .bank / .carra2 / .rebank 放进该文件夹；
  · 解包时把 .zip 内第一个顶层目录的内容解压到包根目录；
  · 打包时把它作为 mod_loader 的 --work-dir；
  · .workflow_job.json 记录 worker 进程与结果，供总览页/子窗口轮询。
"""

from __future__ import annotations

import base64
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from datetime import datetime
from pathlib import Path

WORKFLOW_NAME = "YisangMirrorFlow"
VERSION = "0.0.23"

WORKFLOW_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = WORKFLOW_DIR.parent.parent
MODS_DIR = WORKFLOW_DIR / "mods"
SETTINGS_FILE = WORKFLOW_DIR / "settings.json"
WORKER_SCRIPT = WORKFLOW_DIR / "main.py"

JOB_NAME = ".workflow_job.json"
PROGRESS_NAME = "loader_progress.txt"
THREADS_NAME = "loader_threads.txt"
LOG_NAME = "log.txt"
WORKER_LOG_NAME = "workflow.log"
MANIFEST_NAME = "launcher_manifest.json"

# 包类型 / 发布信息的本地文件（均以 . 或固定名存放，不参与打包上传）
KIND_NAME = ".workflow_kind"           # {"kind": "mod"|"addon"}
PUBLISH_STATE_NAME = ".workflow_publish.json"  # {"last_version": "x"}
INFO_MOD_NAME = "mod_info.json"
INFO_ADDON_NAME = "addon_info.json"
ICON_NAME = "icon.png"
LOAD_EXTS = (".bank", ".carra2", ".rebank")

ADDON_SCR_TEMPLATE = (
    "# 插件代码入口: 在此编写插件的加载逻辑\n"
    "# 可用全局变量: ADDON_ARG (含 AddonManager / AddonName)\n"
    "# 完整示例请参考 addons/example/scr.py\n"
)

ALLOWED_EXTS = (".zip", ".7z", ".rar", ".bank", ".carra2", ".rebank")
IGNORED_NAMES = {
    JOB_NAME, PROGRESS_NAME, THREADS_NAME, LOG_NAME, WORKER_LOG_NAME,
    MANIFEST_NAME, KIND_NAME, PUBLISH_STATE_NAME,
}
STAGE_TOTAL = 4
STAGE_TITLES = {
    1: "准备打包",
    2: "压缩 lunartime → carra2",
    3: "bank → rebank",
    4: "打包完成",
}


def ensure_dirs() -> None:
    MODS_DIR.mkdir(parents=True, exist_ok=True)


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _read_json(path: Path) -> dict:
    try:
        with open(path, "r", encoding="utf-8-sig") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_json(path: Path, data: dict) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        return True
    except OSError:
        return False


def _read_text(path: Path, encoding: str = "utf-8") -> str:
    try:
        return path.read_text(encoding=encoding)
    except OSError:
        return ""


def pid_alive(pid: int) -> bool:
    if not pid:
        return False
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, int(pid))
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            if kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return code.value == 259  # STILL_ACTIVE
            return False
        finally:
            kernel32.CloseHandle(handle)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# 设置 / 游戏路径
# ---------------------------------------------------------------------------

def load_settings() -> dict:
    data = _read_json(SETTINGS_FILE)
    data.setdefault("game_path", "")
    data.setdefault("threads", 0)
    return data


def save_settings(settings: dict) -> None:
    _write_json(SETTINGS_FILE, settings)


def config_game_path() -> str:
    """读取启动器 config/settings.json 里的游戏路径。"""
    data = _read_json(PROJECT_ROOT / "config" / "settings.json")
    value = data.get("game_path")
    if isinstance(value, dict):
        value = value.get("value")
    return normalize_game_path(value)


# 游戏根目录之下的已知子目录链（大小写不敏感）。
# 用户经常把音效目录（原版 bank 所在处）整段填进“游戏路径”，
# 只要尾部能对上这条链的一段，就一路回退到游戏根目录。
_GAME_SUBPATH = ("LimbusCompany_Data", "StreamingAssets", "Assets",
                 "Sound", "FMODBuilds", "Desktop")


def _trim_game_subpath(text: str) -> str:
    parts = [p for p in text.split(os.sep) if p]
    if not parts:
        return text
    drop = 0
    for k in range(len(_GAME_SUBPATH), 1, -1):
        tail = [p.lower() for p in parts[-k:]]
        if len(tail) == k and tail == [c.lower() for c in _GAME_SUBPATH[-k:]]:
            drop = k
            break
    if drop == 0 and parts[-1].lower() == _GAME_SUBPATH[0].lower():
        drop = 1  # 只填到 LimbusCompany_Data 也回退一级
    trimmed = text
    for _ in range(drop):
        parent = os.path.dirname(trimmed)
        if not parent or parent == trimmed:
            break
        trimmed = parent
    return trimmed


def normalize_game_path(value) -> str:
    text = str(value or "").strip().strip('"').strip("'")
    if not text:
        return ""
    text = os.path.expandvars(os.path.expanduser(text))
    text = text.replace("/", os.sep)
    if not os.path.isabs(text):
        text = os.path.abspath(text)
    if os.path.isfile(text) or text.lower().endswith(".exe"):
        text = os.path.dirname(text)
    return _trim_game_subpath(os.path.normpath(text))


def resolve_game_path() -> str:
    settings = load_settings()
    path = normalize_game_path(settings.get("game_path"))
    if path:
        return path
    return config_game_path()


def sound_dir_for(game_path: str) -> str:
    if not game_path:
        return ""
    return os.path.join(
        game_path, "LimbusCompany_Data", "StreamingAssets", "Assets",
        "Sound", "FMODBuilds", "Desktop",
    )


def _has_original_banks(path: str) -> bool:
    """目录里确实有原版 FMOD bank 才算数（空的 Desktop 不算就绪）。"""
    if not path or not os.path.isdir(path):
        return False
    return bool(glob.glob(os.path.join(path, "*.bank")))


def find_sound_dir(game_path: str) -> str:
    """从游戏路径推导原版 bank 所在目录；找不到时返回空字符串。

    game_path 允许是游戏根目录，也可以是布局中间的任何一级
    （LimbusCompany_Data、…、Sound、FMODBuilds、Desktop 本身）。
    """
    if not game_path:
        return ""
    parts = [p for p in os.path.normpath(game_path).split(os.sep) if p]
    chain = _GAME_SUBPATH
    for m in range(min(len(chain), len(parts)), -1, -1):
        if m and [p.lower() for p in parts[-m:]] != [c.lower() for c in chain[:m]]:
            continue
        cand = game_path if m == len(chain) else os.path.join(game_path, *chain[m:])
        if _has_original_banks(cand):
            return cand
    # 常见变体：bank 直接放 FMODBuilds、或根目录多套了一层
    for pattern in (
        "LimbusCompany_Data/StreamingAssets/Assets/Sound/FMODBuilds",
        "*/Sound/FMODBuilds/Desktop",
        "*/StreamingAssets/Assets/Sound/FMODBuilds/Desktop",
    ):
        for cand in glob.glob(os.path.join(game_path, pattern)):
            cand = os.path.normpath(cand)
            if _has_original_banks(cand):
                return cand
    return ""


def resolve_sound_dir() -> str:
    return find_sound_dir(resolve_game_path())


def game_info() -> dict:
    path = resolve_game_path()
    sound = find_sound_dir(path)
    return {
        "path": path,
        "path_exists": bool(path and os.path.isdir(path)),
        "sound_dir": sound or sound_dir_for(path),
        "sound_exists": bool(sound),
        "source": "workflow" if load_settings().get("game_path") else "launcher",
    }


def set_game_path(value) -> dict:
    path = normalize_game_path(value)
    settings = load_settings()
    settings["game_path"] = path
    save_settings(settings)
    return game_info()


def resolve_threads() -> int:
    settings = load_settings()
    try:
        threads = int(settings.get("threads") or 0)
    except (TypeError, ValueError):
        threads = 0
    if threads <= 0:
        config = _read_json(PROJECT_ROOT / "config" / "settings.json")
        value = config.get("mod_loader_threads")
        if isinstance(value, dict):
            value = value.get("value")
        try:
            threads = int(value or 0)
        except (TypeError, ValueError):
            threads = 0
    if threads <= 0:
        threads = 5
    return max(1, min(10, threads))


def set_threads(value) -> dict:
    try:
        threads = int(value)
    except (TypeError, ValueError):
        threads = resolve_threads()
    settings = load_settings()
    settings["threads"] = max(1, min(10, threads))
    save_settings(settings)
    return {"threads": settings["threads"]}


# ---------------------------------------------------------------------------
# 包 / 文件
# ---------------------------------------------------------------------------

def safe_package_name(name) -> str:
    text = str(name or "").strip()
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", text)
    text = text.strip(" .")
    if not text:
        text = "新包"
    return text[:60]


def package_dir(name) -> Path:
    return MODS_DIR / safe_package_name(name)


def create_package(name, kind="mod") -> dict:
    """新建包。kind: "mod"（需打包）或 "addon"（插件包，自带 scr.py，免打包）。"""
    ensure_dirs()
    kind = "addon" if str(kind or "").lower() == "addon" else "mod"
    base = safe_package_name(name)
    candidate = base
    index = 2
    while (MODS_DIR / candidate).exists():
        candidate = "%s (%d)" % (base, index)
        index += 1
    path = MODS_DIR / candidate
    path.mkdir(parents=True, exist_ok=False)
    try:
        _write_json(path / KIND_NAME, {"kind": kind})
        if kind == "addon":
            # 插件包根目录自带 scr.py，开发者在此基础上写加载逻辑
            (path / "scr.py").write_text(ADDON_SCR_TEMPLATE, encoding="utf-8")
            _write_json(path / INFO_ADDON_NAME, {
                "name": candidate, "desc": "", "version": "0.0.1",
                "authors": {}, "settings": {"enable": False},
            })
        else:
            # 创建 Mod 包即写入初始 mod_info.json（后续“信息”里再补全）
            _write_json(path / INFO_MOD_NAME, {
                "name": candidate, "desc": "", "version": "0.0.1",
                "authors": {}, "settings": {"enable": True},
                "single_file": True, "file_names": [],
            })
    except OSError:
        pass
    return {"ok": True, "name": candidate, "kind": kind}


def _is_allowed_file(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in ALLOWED_EXTS


def package_files(name) -> list:
    path = package_dir(name)
    if not path.is_dir():
        return []
    files = []
    for item in path.iterdir():
        if item.name.startswith(".") or item.name in IGNORED_NAMES:
            continue
        if not _is_allowed_file(item):
            continue
        try:
            size = item.stat().st_size
        except OSError:
            size = 0
        files.append({
            "name": item.name,
            "ext": item.suffix.lower(),
            "size": size,
        })
    files.sort(key=lambda f: f["name"].lower())
    return files


def _file_counts(files: list) -> dict:
    counts = {".zip": 0, ".7z": 0, ".rar": 0, ".bank": 0, ".carra2": 0, ".rebank": 0}
    for item in files:
        ext = item.get("ext")
        if ext in counts:
            counts[ext] += 1
    counts["total"] = len(files)
    return counts


def add_files(name, source_paths) -> dict:
    """把文件复制进包；归档（zip/7z/rar）自动解包到包根并删除归档。"""
    pkg = package_dir(name)
    if not pkg.is_dir():
        return {"ok": False, "error": "包不存在", "added": 0, "skipped": [], "unpacked": [], "errors": []}
    job = read_job(name)
    if job["status"] == "running":
        return {"ok": False, "error": "正在打包，暂时不能添加文件", "added": 0,
                "skipped": [], "unpacked": [], "errors": []}

    added = 0
    skipped = []
    unpacked = []
    errors = []
    for src in source_paths or []:
        source = Path(str(src))
        if not _is_allowed_file(source):
            skipped.append(source.name or str(source))
            continue
        try:
            target = pkg / source.name
            if source.resolve() != target.resolve():
                shutil.copy2(source, target)
            added += 1
        except OSError as exc:
            skipped.append("%s (%s)" % (source.name, exc))
            continue
        # 归档自动解包，满足后续打包/识别；成功后移除归档，失败则保留
        if target.suffix.lower() in ARCHIVE_EXTS:
            try:
                detail = _unpack_one_archive(pkg, target)
                files = int(detail.get("files") or 0)
                if files > 0:
                    unpacked.append({"name": target.name, "dir": detail.get("dir"), "files": files})
                    try:
                        target.unlink()
                    except OSError:
                        pass
                else:
                    errors.append("%s (没有可解压的内容)" % target.name)
            except Exception as exc:
                errors.append("%s (%s)" % (target.name, exc))
    return {"ok": True, "added": added, "skipped": skipped,
            "unpacked": unpacked, "errors": errors, "error": ""}


def remove_file(name, filename) -> dict:
    pkg = package_dir(name)
    target = (pkg / os.path.basename(str(filename or ""))).resolve()
    try:
        if pkg.resolve() not in target.parents:
            return {"ok": False, "error": "非法路径"}
        if target.is_file():
            target.unlink()
        return {"ok": True}
    except OSError as exc:
        return {"ok": False, "error": str(exc)}


def delete_package(name) -> dict:
    pkg = package_dir(name)
    job = read_job(name)
    if job["status"] == "running":
        return {"ok": False, "error": "正在打包，不能删除"}
    try:
        if pkg.is_dir():
            shutil.rmtree(pkg)
        return {"ok": True}
    except OSError as exc:
        return {"ok": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# 解包（zip / 7z / rar）：自动识别并提取“合适的内容根”
#   · installer 类：归档里含 Installer.bat/Uninstaller.bat 的目录 → 提取该目录到包根
#   · bank 类：归档里的 .bank/.rebank/.carra2 等 → 提取到包根
# ---------------------------------------------------------------------------

ARCHIVE_EXTS = (".zip", ".7z", ".rar")
# 打包流真正需要的音效文件；其它（json/txt/图片等）一律不提取到包根
AUDIO_EXTS = (".bank", ".rebank", ".carra2")


def _find_7z() -> str:
    """定位 7-Zip 可执行文件（解 7z/rar 用）。"""
    candidates = [
        os.environ.get("SEVENZIP_PATH", ""),
        "7z",
        "7za",
        r"C:\Program Files\7-Zip\7z.exe",
        r"C:\Program Files (x86)\7-Zip\7z.exe",
    ]
    for cand in candidates:
        if not cand:
            continue
        if os.path.isabs(cand):
            if os.path.isfile(cand):
                return cand
        else:
            found = shutil.which(cand)
            if found:
                return found
    return ""


def _safe_extract_zip(zip_path: Path, out_dir: Path) -> None:
    """安全解压 zip 到 out_dir（跳过 .. 路径穿越）。"""
    with zipfile.ZipFile(zip_path, "r") as zf:
        for info in zf.infolist():
            name = str(info.filename or "").replace("\\", "/").lstrip("/")
            parts = [p for p in name.split("/") if p not in ("", ".")]
            if not parts or any(p == ".." for p in parts):
                continue
            target = out_dir.joinpath(*parts)
            try:
                if info.is_dir() or name.endswith("/"):
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info, "r") as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst, length=1024 * 1024)
            except (OSError, RuntimeError, NotImplementedError, KeyError, ValueError,
                    zipfile.BadZipFile):
                continue


def _extract_archive(archive: Path, out_dir: Path) -> None:
    """把归档解压到 out_dir（zip 用内置库；7z/rar 调 7-Zip）。"""
    if archive.suffix.lower() == ".zip":
        _safe_extract_zip(archive, out_dir)
        return
    seven = _find_7z()
    if not seven:
        raise RuntimeError("未找到 7-Zip，无法解压 %s（请安装 7-Zip 或设置 SEVENZIP_PATH）"
                           % archive.name)
    cmd = [seven, "x", "-y", "-scsUTF-8", "-o" + str(out_dir), str(archive)]
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    proc = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                          creationflags=flags, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        lines = [ln for ln in (proc.stderr or "").strip().splitlines() if ln.strip()]
        raise RuntimeError("7-Zip 解压失败(%d): %s"
                           % (proc.returncode, lines[-1] if lines else ""))


def _top_entries(base: Path) -> list:
    """顶层条目（跳过 __MACOSX / 隐藏）。"""
    try:
        items = sorted(os.listdir(base))
    except OSError:
        return []
    return [i for i in items if i != "__MACOSX" and not i.startswith(".")]


def _content_root(temp: Path) -> Path:
    """分级判断“内容根”：
    - 归档里只有一个顶层目录 → 去掉这层包裹，取该目录；
      （标准 bat 模组：Installer.bat 会随之落到包根；
       单目录音效包：里面的 bank/json 也会落到包根）
    - 其它情况（根直接文件 / 多混合）→ 取归档根，整体保留到包根。
    这样混合包（根有 bank/json + 子目录 installer）也能完整提取，不会丢内容。"""
    entries = _top_entries(temp)
    if len(entries) == 1 and (temp / entries[0]).is_dir():
        return temp / entries[0]
    return temp


def _copy_tree_into(src: Path, dst: Path) -> int:
    """把 src 内容覆盖复制到 dst（保留相对结构），返回文件数。"""
    count = 0
    for root, _dirs, files in os.walk(src):
        rel = os.path.relpath(root, src)
        target_root = dst if rel == "." else dst / rel
        try:
            target_root.mkdir(parents=True, exist_ok=True)
        except OSError:
            continue
        for f in files:
            try:
                shutil.copy2(os.path.join(root, f), os.path.join(target_root, f))
                count += 1
            except OSError:
                pass
    return count


def _installer_dirs(base: Path) -> list:
    """含 Installer.bat/Uninstaller.bat 的目录（取最外层，避免嵌套重复）。"""
    found = []
    for root, _dirs, files in os.walk(base):
        low = {f.lower() for f in files}
        if "installer.bat" in low or "uninstaller.bat" in low:
            found.append(Path(root))
    result = []
    for d in found:
        if not any(d != o and o in d.parents for o in found):
            result.append(d)
    return result


def _is_under(path: Path, dirs: list) -> bool:
    for d in dirs:
        try:
            path.relative_to(d)
            return True
        except ValueError:
            pass
    return False


def _zip_installer_dir(src_dir: Path, zip_path: Path, top_name: str) -> int:
    """把完整包目录压成 zip（保留顶层目录名，打包流只认 zip）。"""
    try:
        if zip_path.exists():
            zip_path.unlink()
    except OSError:
        pass
    count = 0
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _dirs, files in os.walk(src_dir):
            for f in files:
                full = Path(root) / f
                rel = os.path.relpath(full, src_dir).replace("\\", "/")
                arc = (top_name + "/" + rel) if top_name else rel
                try:
                    zf.write(full, arc)
                    count += 1
                except OSError:
                    pass
    return count


def _unpack_one_archive(pkg: Path, archive: Path) -> dict:
    """按“打包流需求”提取：
    - 含 Installer.bat 的完整包目录 → 单独压成 <目录名>.zip（保留顶层目录，打包流只认 zip）；
    - `.bank/.rebank/.carra2` 音效 → 复制到包根（完整包 zip 内的除外）；
    - json/txt 等其它无用文件一律忽略。"""
    temp = Path(tempfile.mkdtemp(prefix="wf_unpack_"))
    try:
        _extract_archive(archive, temp)
        base = _content_root(temp)
        at_temp = os.path.normcase(str(base)) == os.path.normcase(str(temp))
        installer_dirs = _installer_dirs(base)
        files = 0

        # 完整包 → 单独 zip
        used = set()
        for d in installer_dirs:
            if d == base:
                top = "mod" if at_temp else (base.name or "mod")
            else:
                top = d.name or "mod"
            fname = top + ".zip"
            if fname in used:
                fname = "%s_%d.zip" % (top, len(used) + 1)
            used.add(fname)
            files += _zip_installer_dir(d, pkg / fname, top)

        # 音效文件 → 包根（排除已进入完整包 zip 的）
        for root, _dirs, fs in os.walk(base):
            for f in fs:
                if os.path.splitext(f)[1].lower() not in AUDIO_EXTS:
                    continue
                full = Path(root) / f
                if _is_under(full, installer_dirs):
                    continue
                try:
                    pkg.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(full, pkg / f)
                    files += 1
                except OSError:
                    pass

        label = "(根目录)" if at_temp else base.name
        return {"archive": archive.name, "zip": archive.name,
                "dir": label, "files": files, "failed": 0}
    finally:
        shutil.rmtree(temp, ignore_errors=True)


def unpack_zips(name) -> dict:
    """解包包内全部 .zip/.7z/.rar：自动识别 installer 目录 / bank 类内容并提取到包根。

    函数名保留 unpack_zips（前端调用不变），但现在同时支持 7z / rar。
    """
    pkg = package_dir(name)
    if not pkg.is_dir():
        return {"ok": False, "error": "包不存在", "unpacked": 0, "errors": []}
    job = read_job(name)
    if job["status"] == "running":
        return {"ok": False, "error": "正在打包，暂时不能解包", "unpacked": 0, "errors": []}

    archives = sorted(
        [p for p in pkg.iterdir()
         if p.is_file() and not p.name.startswith(".") and p.suffix.lower() in ARCHIVE_EXTS],
        key=lambda p: p.name.lower(),
    )
    if not archives:
        return {"ok": False, "error": "包内没有可解包的归档 (.zip/.7z/.rar)",
                "unpacked": 0, "errors": []}

    unpacked = 0
    extracted_files = 0
    errors = []
    details = []
    for archive in archives:
        try:
            detail = _unpack_one_archive(pkg, archive)
        except Exception as exc:
            errors.append("%s (%s)" % (archive.name, exc))
            continue
        extracted_files += int(detail.get("files") or 0)
        if int(detail.get("files") or 0) > 0:
            unpacked += 1
            details.append(detail)
            # 解包成功即删除原归档
            try:
                archive.unlink()
            except OSError:
                pass
        else:
            errors.append("%s (没有可解压的内容)" % archive.name)

    return {
        "ok": True,
        "zip_count": len(archives),
        "archive_count": len(archives),
        "unpacked": unpacked,
        "extracted_files": extracted_files,
        "errors": errors,
        "details": details,
    }


# ---------------------------------------------------------------------------
# 任务状态
# ---------------------------------------------------------------------------

def _job_age_seconds(started_at: str, default: float = 999.0) -> float:
    try:
        started = datetime.fromisoformat(str(started_at))
        return max(0.0, (datetime.now() - started).total_seconds())
    except (TypeError, ValueError):
        return default


def read_job(name) -> dict:
    pkg = package_dir(name)
    data = _read_json(pkg / JOB_NAME)
    status = str(data.get("status") or "idle")
    try:
        pid = int(data.get("worker_pid") or 0)
    except (TypeError, ValueError):
        pid = 0
    if status == "running":
        if pid:
            if not pid_alive(pid):
                status = "interrupted"
        else:
            # start_package 只写 running/worker_pid=0，真实 pid 由 worker 自己写。
            # worker 启动失败或还没起来时，超时后允许重新开始。
            started_at = str(data.get("started_at") or "")
            if _job_age_seconds(started_at) > 30:
                status = "interrupted"
    return {
        "status": status,
        "worker_pid": pid,
        "started_at": str(data.get("started_at") or ""),
        "finished_at": str(data.get("finished_at") or ""),
        "message": str(data.get("message") or ""),
    }


def write_job(name, **fields) -> None:
    pkg = package_dir(name)
    data = _read_json(pkg / JOB_NAME)
    data.update(fields)
    data["updated_at"] = _now_iso()
    _write_json(pkg / JOB_NAME, data)


def package_kind(name) -> str:
    """读取包类型；没有记录时按是否已有 addon_info.json 推断。"""
    meta = _read_json(package_dir(name) / KIND_NAME)
    kind = str(meta.get("kind") or "").strip().lower()
    if kind in ("mod", "addon"):
        return kind
    return "addon" if (package_dir(name) / INFO_ADDON_NAME).is_file() else "mod"


def package_info(name) -> tuple:
    kind = package_kind(name)
    info_file = INFO_ADDON_NAME if kind == "addon" else INFO_MOD_NAME
    return kind, _read_json(package_dir(name) / info_file)


def package_icon_uri(name) -> str:
    try:
        path = package_dir(name) / ICON_NAME
        if path.is_file():
            return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode("ascii")
    except OSError:
        pass
    return ""


def scan_load_files(name) -> list:
    """包根目录下可载入游戏的文件（.bank/.carra2/.rebank）。"""
    result = []
    try:
        for item in package_dir(name).iterdir():
            if item.is_file() and not item.name.startswith(".") and item.suffix.lower() in LOAD_EXTS:
                result.append(item.name)
    except OSError:
        pass
    return sorted(result)


def _has_load_file_recursive(name) -> bool:
    for _root, _dirs, files in os.walk(package_dir(name)):
        for f in files:
            if not f.startswith(".") and os.path.splitext(f)[1].lower() in LOAD_EXTS:
                return True
    return False


def last_published_version(name) -> str:
    return str(_read_json(package_dir(name) / PUBLISH_STATE_NAME).get("last_version") or "")


def publish_missing(name) -> list:
    """发布前必填检查：名称/版本/描述/至少一作者/图标/（Mod 包）至少一个载入文件。"""
    kind, info = package_info(name)
    missing = []
    if not str(info.get("name") or "").strip():
        missing.append("名称")
    if not str(info.get("version") or "").strip():
        missing.append("版本号")
    if not str(info.get("desc") or "").strip():
        missing.append("描述")
    authors = info.get("authors") or {}
    if isinstance(authors, dict):
        has_author = any(str(k).strip() for k in authors)
    elif isinstance(authors, list):
        has_author = any(str(x).strip() for x in authors if isinstance(x, str))
    else:
        has_author = False
    if not has_author:
        missing.append("至少一位作者")
    if not (package_dir(name) / ICON_NAME).is_file():
        missing.append("图标")
    if kind == "mod" and not _has_load_file_recursive(name):
        missing.append("至少一个载入文件(.bank/.carra2/.rebank)")
    return missing


def package_summary(name) -> dict:
    files = package_files(name)
    counts = _file_counts(files)
    job = read_job(name)
    kind, info = package_info(name)
    missing = publish_missing(name)
    can_start = job["status"] != "running" and counts["total"] > 0
    # Mod 包需打包完成（无失败）才能发布；插件包免打包，随时可发布。
    publish_ready = job["status"] != "running" and (kind == "addon" or job["status"] == "done")
    return {
        "name": name,
        "path": str(package_dir(name)),
        "files": files,
        "counts": counts,
        "job": job,
        "can_start": can_start,
        "kind": kind,
        "info": {
            "name": str(info.get("name") or ""),
            "version": str(info.get("version") or ""),
            "desc": str(info.get("desc") or ""),
        },
        "icon": package_icon_uri(name),
        "load_files": scan_load_files(name),
        "last_version": last_published_version(name),
        "publish_missing": missing,
        "publish_ready": publish_ready,
    }


def list_packages() -> list:
    ensure_dirs()
    result = []
    for item in MODS_DIR.iterdir():
        if item.is_dir() and not item.name.startswith("."):
            result.append(package_summary(item.name))
    result.sort(key=lambda p: p["name"].lower())
    return result


def overview_state() -> dict:
    return {
        "ok": True,
        "name": WORKFLOW_NAME,
        "version": VERSION,
        "packages": list_packages(),
        "game": game_info(),
        "threads": resolve_threads(),
        "mods_dir": str(MODS_DIR),
    }


# ---------------------------------------------------------------------------
# 启动 / 打开
# ---------------------------------------------------------------------------

def start_package(name) -> dict:
    pkg = package_dir(name)
    if not pkg.is_dir():
        return {"ok": False, "error": "包不存在"}
    job = read_job(name)
    if job["status"] == "running":
        return {"ok": False, "error": "正在打包，请等待完成"}

    files = package_files(name)
    counts = _file_counts(files)
    if not counts["total"]:
        return {"ok": False, "error": "包内还没有文件"}

    if counts[".bank"]:
        sound_dir = resolve_sound_dir()
        if not sound_dir:
            current = resolve_game_path() or "未设置"
            return {"ok": False, "error": "包里有 .bank，但在 \"%s\" 下找不到原版 FMOD bank；"
                                          "请设置游戏根目录（也可直接填 …\\Sound\\FMODBuilds\\Desktop）"
                     % current}

    ensure_dirs()
    write_job(
        name,
        status="running",
        worker_pid=0,
        started_at=_now_iso(),
        finished_at="",
        message="",
    )

    cmd = [
        sys.executable,
        str(WORKER_SCRIPT),
        "--worker",
        "--package-dir",
        str(pkg),
    ]
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(PROJECT_ROOT),
            creationflags=creationflags,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError as exc:
        write_job(
            name,
            status="failed",
            finished_at=_now_iso(),
            message="无法启动打包进程: %s" % exc,
        )
        return {"ok": False, "error": "无法启动打包进程: %s" % exc}

    # 注意: 启动器 venv 的 python.exe 是转发器, Popen 的 pid 不等于 worker
    # 里 os.getpid() 到的真实 Python。这里不能把 proc.pid 写进 job, 否则
    # worker 会把自己当成"另一个正在运行的 worker"而退出。真实 pid 由
    # worker.run_worker 自己写入。
    return {"ok": True}


def open_path(path) -> dict:
    target = str(path or "")
    if not target or not os.path.exists(target):
        return {"ok": False, "error": "路径不存在"}
    try:
        os.startfile(target)
        return {"ok": True}
    except OSError as exc:
        return {"ok": False, "error": str(exc)}


def open_package(name) -> dict:
    return open_path(package_dir(name))


def open_mods_dir() -> dict:
    ensure_dirs()
    return open_path(MODS_DIR)


def append_worker_log(name, text: str) -> None:
    try:
        pkg = package_dir(name)
        pkg.mkdir(parents=True, exist_ok=True)
        with open(pkg / WORKER_LOG_NAME, "a", encoding="utf-8") as fh:
            fh.write("[%s] %s\n" % (_now_iso(), text))
    except OSError:
        pass
