#! 版本更新提示统一出口

import json
import os
import re
import sys
import time
from threading import Lock, Thread

if getattr(sys, "frozen", False):
    _PROJECT_ROOT = os.path.dirname(os.path.abspath(sys.executable))
else:
    _PROJECT_ROOT = os.path.abspath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))

_WEB_PUSHER = None

_LAST_SHOWN = {"t": 0.0, "forced": False}
_DEDUPE_SECONDS = 8.0

_DOWNLOAD_LOCK = Lock()
_DOWNLOAD_STATE = {"running": False}

_MEM = {"info": None, "payload": None, "t": 0.0}

def remember_version_info(info):
    if not isinstance(info, dict):
        return
    _MEM["info"] = dict(info)
    _MEM["t"] = time.time()

def remember_version_payload(payload):
    if not isinstance(payload, dict):
        return
    _MEM["payload"] = dict(payload)
    _MEM["t"] = time.time()

def cached_version_info():
    info = _MEM.get("info")
    return dict(info) if isinstance(info, dict) else None

def cached_version_payload():
    payload = _MEM.get("payload")
    return dict(payload) if isinstance(payload, dict) else None

def register_web_pusher(pusher):
    global _WEB_PUSHER
    _WEB_PUSHER = pusher

def unregister_web_pusher():
    global _WEB_PUSHER
    _WEB_PUSHER = None

def get_web_pusher():
    return _WEB_PUSHER

def _render_markdown_html(description):
    text = description or ""
    if not text.strip():
        return ""
    try:
        from functions.pages.notice.version_update_window import md_to_html
        return md_to_html(text)
    except Exception as e:
        print(f"[Update] Markdown 渲染失败: {e}")
        import html as _html
        return "<p>" + _html.escape(text) + "</p>"

def collect_version_info(allow_refresh=False):
    from functions.base.settings_manager import get_settings_manager
    current = str(get_settings_manager().get_setting("version_info") or "")
    result = {"current": current, "latest": "", "has_update": False, "entry": {}, "error": None}
    try:
        from functions.base.web_config import get_webnote
        from functions.webFunc.Webnote import Note
        from json import loads

        note = Note("version_info", get_webnote("version_info")[0])
        note.fetch_note_info(allow_refresh=bool(allow_refresh))
        if not note.note_content.strip():
            result["error"] = "未配置版本信息 (云端不可用)"
            return result
        info = loads(note.note_content)
        latest = str(info.get("latest_release_version") or "").strip()
        entry = info.get("versions", {}).get(latest, {}) if latest else {}
        result["latest"] = latest
        result["entry"] = entry if isinstance(entry, dict) else {}
        from functions.base.version_compare import is_newer_version
        result["has_update"] = bool(latest and is_newer_version(latest, current))
        remember_version_info(result)
    except Exception as e:
        result["error"] = str(e)
    return result

def _fmt_date(value):
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    text = str(value or "").strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}-\d{2}:\d{2}", text):
        text = text[:10] + " " + text[11:]
    return text

def build_payload(current_version, latest_info, info="发现新版本",
                  has_new_version=False, forced=False):
    latest_info = latest_info or {}
    description = latest_info.get("description") or latest_info.get("version_description") or ""
    url = latest_info.get("bilibili_url") or latest_info.get("url") or ""
    date = latest_info.get("date") or latest_info.get("data") or latest_info.get("created_at")

    can_update = bool(url)
    has_update = bool(has_new_version and can_update)
    if has_update:
        title = "发现新版本"
        forced = bool(forced)
    else:
        title = info or "已是最新版本"
        forced = False

    return {
        "title": title,
        "current": str(current_version or ""),
        "latest": str(latest_info.get("version_name") or ""),
        "date": _fmt_date(date),
        "url": str(url or ""),
        "html": _render_markdown_html(description),
        "has_update": has_update,
        "forced": bool(forced and has_update),
        "can_update": can_update,
        "auto_start": bool(forced and has_update),
    }

def notify_version(current_version, latest_info, info="发现新版本", root=None,
                   has_new_version=False, forced=False):
    pusher = _WEB_PUSHER
    if pusher is None:
        return False

    payload = build_payload(current_version, latest_info, info,
                            has_new_version=has_new_version, forced=forced)
    now = time.time()
    if now - _LAST_SHOWN["t"] < _DEDUPE_SECONDS:
        if (not payload["forced"]) or _LAST_SHOWN["forced"]:
            return True

    remember_version_payload(payload)
    try:
        ok = bool(pusher(payload))
    except Exception as e:
        print(f"[Update] 推送应用内模态窗口失败: {e}")
        return False
    if ok:
        _LAST_SHOWN["t"] = now
        _LAST_SHOWN["forced"] = payload["forced"]
    return ok

class _TextVar:

    def __init__(self, on_set, initial=""):
        self._value = initial
        self._on_set = on_set

    def set(self, value):
        self._value = str(value)
        try:
            self._on_set(self._value)
        except Exception:
            pass

    def get(self):
        return self._value

class _ProgressGui:

    def __init__(self, push, task="版本更新"):
        self.push = push
        self.task = task
        self.is_downloading = True
        self.current_file_var = _TextVar(lambda t: push({"stage": "status", "text": t}))

    def update_progress(self, percent, downloaded, total, speed):
        try:
            percent = round(float(percent), 1)
        except Exception:
            percent = 0
        self.push({
            "stage": "progress",
            "percent": percent,
            "downloaded": downloaded,
            "total": total,
            "speed": speed,
        })

def is_downloading():
    with _DOWNLOAD_LOCK:
        return bool(_DOWNLOAD_STATE["running"])

def start_version_download(version_name, url, push):
    with _DOWNLOAD_LOCK:
        if _DOWNLOAD_STATE["running"]:
            push({"stage": "error", "text": "更新包正在下载中, 请稍候"})
            return False
        _DOWNLOAD_STATE["running"] = True

    def _run():
        try:
            _download_and_install(version_name, url, push)
        except Exception as e:
            import traceback
            print(f"[Update] 下载安装失败: {e}")
            print(traceback.format_exc())
            push({"stage": "error", "text": f"更新失败: {e}"})
        finally:
            with _DOWNLOAD_LOCK:
                _DOWNLOAD_STATE["running"] = False

    Thread(target=_run, daemon=True).start()
    return True

def _download_and_install(version_name, url, push):
    import shutil
    import subprocess

    from functions.web_update.zeroasso_download import (
        download_file_with_gui, extract_7z_file, verify_download,
    )

    version_name = str(version_name or "").strip() or "latest"
    target_root = os.path.join(_PROJECT_ROOT, "cache", "new_version")
    temp_dir = os.path.join(_PROJECT_ROOT, "cache", "new_version_pkg")
    os.makedirs(temp_dir, exist_ok=True)
    temp_file = os.path.join(temp_dir, "FaustLauncher_%s.zip" % version_name.replace(".", "_"))

    print(f"[Update] 开始下载新版本 {version_name}: {url}", flush=True)
    push({"stage": "status", "text": f"正在下载 {version_name} 安装包…"})

    gui = _ProgressGui(push)
    ok = download_file_with_gui(url, temp_file, gui, "正在下载更新包…")
    if ok is False or not os.path.exists(temp_file):
        push({"stage": "error", "text": "更新包下载失败, 请检查网络后重试"})
        return
    if not verify_download(temp_file):
        push({"stage": "error", "text": "更新包不完整 (文件校验失败), 请重试"})
        return

    push({"stage": "status", "text": "下载完成, 正在解压安装包…"})
    shutil.rmtree(target_root, ignore_errors=True)
    os.makedirs(target_root, exist_ok=True)
    if not extract_7z_file(temp_file, target_root):
        push({"stage": "error", "text": "更新包解压失败, 请重试"})
        return
    try:
        os.remove(temp_file)
    except Exception:
        pass

    new_dir = os.path.join(target_root, "FaustLauncher")
    if not os.path.isdir(new_dir):
        sub = [d for d in os.listdir(target_root) if os.path.isdir(os.path.join(target_root, d))]
        if len(sub) == 1 and os.path.exists(os.path.join(target_root, sub[0], "FaustLauncher.exe")):
            new_dir = os.path.join(target_root, sub[0])
        else:
            push({"stage": "error", "text": "更新包结构异常 (未找到 FaustLauncher 目录)"})
            return

    exe_path = os.path.join(new_dir, "FaustLauncher.exe")
    if not os.path.exists(exe_path):
        push({"stage": "error", "text": "更新包中未找到 FaustLauncher.exe"})
        return

    push({"stage": "status", "text": "正在同步设置并准备安装…"})
    try:
        from functions.update.sync_setting import sync_settings
        sync_settings()
    except Exception as e:
        print(f"[Update] 设置同步失败 (继续安装): {e}")

    updater = os.path.join(new_dir, "updater.vbs")
    if not os.path.exists(updater):
        push({"stage": "error", "text": "更新包中未找到更新器 updater.vbs, 请手动解压覆盖"})
        return

    push({"stage": "ready", "percent": 100, "text": "更新准备完成, 即将重启并安装新版本…"})
    print("[Update] 新版本准备完成, 启动更新器并退出启动器", flush=True)
    time.sleep(1.2)
    subprocess.Popen(["wscript.exe", updater], cwd=new_dir, close_fds=True)
    os._exit(0)

def manual_payload():
    payload = cached_version_payload()
    if payload:
        payload["forced"] = False
        return payload
    info = cached_version_info()
    if not info:
        print("[Update] 内存里还没有版本信息 (启动检查未完成), 用本地缓存兜底")
        info = collect_version_info(allow_refresh=False)
    entry = dict(info.get("entry") or {})
    entry["version_name"] = info.get("latest") or ""
    title = "发现新版本" if info.get("has_update") else "已是最新版本"
    return build_payload(info.get("current"), entry, title,
                         has_new_version=info.get("has_update"), forced=False)
