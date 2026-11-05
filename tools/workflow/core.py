"""YisangMirrorFlow 的核心逻辑（不依赖 pywebview）。

每个包就是 ``tools/workflow/mods/<包名>`` 下的一个文件夹：
  · 用户把 .zip / .bank / .carra2 / .rebank 放进该文件夹；
  · 打包时把它作为 mod_loader 的 --work-dir；
  · .workflow_job.json 记录 worker 进程与结果，供总览页/子窗口轮询。
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

WORKFLOW_NAME = "YisangMirrorFlow"
VERSION = "0.0.1"

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

ALLOWED_EXTS = (".zip", ".bank", ".carra2", ".rebank")
IGNORED_NAMES = {
    JOB_NAME, PROGRESS_NAME, THREADS_NAME, LOG_NAME, WORKER_LOG_NAME,
    MANIFEST_NAME,
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


def normalize_game_path(value) -> str:
    text = str(value or "").strip().strip('"')
    if not text:
        return ""
    text = os.path.expandvars(os.path.expanduser(text))
    if not os.path.isabs(text):
        text = os.path.abspath(text)
    if os.path.isfile(text) or text.lower().endswith(".exe"):
        text = os.path.dirname(text)
    return os.path.normpath(text)


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


def resolve_sound_dir() -> str:
    game_path = resolve_game_path()
    sound_dir = sound_dir_for(game_path)
    return sound_dir if os.path.isdir(sound_dir) else ""


def game_info() -> dict:
    path = resolve_game_path()
    sound = sound_dir_for(path)
    return {
        "path": path,
        "path_exists": bool(path and os.path.isdir(path)),
        "sound_dir": sound,
        "sound_exists": bool(sound and os.path.isdir(sound)),
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


def create_package(name) -> dict:
    ensure_dirs()
    base = safe_package_name(name)
    candidate = base
    index = 2
    while (MODS_DIR / candidate).exists():
        candidate = "%s (%d)" % (base, index)
        index += 1
    path = MODS_DIR / candidate
    path.mkdir(parents=True, exist_ok=False)
    return {"ok": True, "name": candidate}


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
    counts = {".zip": 0, ".bank": 0, ".carra2": 0, ".rebank": 0}
    for item in files:
        ext = item.get("ext")
        if ext in counts:
            counts[ext] += 1
    counts["total"] = len(files)
    return counts


def add_files(name, source_paths) -> dict:
    pkg = package_dir(name)
    if not pkg.is_dir():
        return {"ok": False, "error": "包不存在", "added": 0, "skipped": []}
    job = read_job(name)
    if job["status"] == "running":
        return {"ok": False, "error": "正在打包，暂时不能添加文件", "added": 0, "skipped": []}

    added = 0
    skipped = []
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
    return {"ok": True, "added": added, "skipped": skipped, "error": ""}


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
# 任务状态
# ---------------------------------------------------------------------------

def read_job(name) -> dict:
    pkg = package_dir(name)
    data = _read_json(pkg / JOB_NAME)
    status = str(data.get("status") or "idle")
    try:
        pid = int(data.get("worker_pid") or 0)
    except (TypeError, ValueError):
        pid = 0
    if status == "running" and pid and not pid_alive(pid):
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


def package_summary(name) -> dict:
    files = package_files(name)
    counts = _file_counts(files)
    job = read_job(name)
    can_start = job["status"] != "running" and counts["total"] > 0
    return {
        "name": name,
        "path": str(package_dir(name)),
        "files": files,
        "counts": counts,
        "job": job,
        "can_start": can_start,
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
            return {"ok": False, "error": "包含 .bank，请先在总览页设置正确的游戏目录"}

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

    write_job(name, worker_pid=proc.pid)
    return {"ok": True, "pid": proc.pid}


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
