from __future__ import annotations

import json
import os
import re
import threading

SKIN_SETTING_KEY = "skin"
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")

THEME_STYLE_ID = "fl-theme"

def skins_root() -> str:
    try:
        from functions.base.common.path_utils import get_web_root
        return get_web_root("app_skins")
    except Exception:
        return ""

def _read_json(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}

def skin_dir(skin_id) -> str:
    sid = str(skin_id or "").strip()
    if not sid or sid in (".", "..") or os.path.basename(sid) != sid:
        return ""
    root = skins_root()
    if not root:
        return ""
    d = os.path.join(root, sid)
    return d if os.path.isdir(d) else ""

def skin_meta(skin_id) -> dict:
    sd = skin_dir(skin_id)
    if not sd:
        return {}
    p = os.path.join(sd, "config.json")
    return _read_json(p) if os.path.isfile(p) else {}

def skin_profile_file(skin_id) -> str:
    sd = skin_dir(skin_id)
    if not sd:
        return ""
    for n in ("profile.png", "profile.jpg", "profile.jpeg", "profile.webp"):
        p = os.path.join(sd, n)
        if os.path.isfile(p):
            return p
    return ""

_SETTINGS_STATE = {"path": "", "mtime": -1.0}

def refresh_settings() -> bool:
    try:
        from functions.base.settings_manager import get_settings_manager
        mgr = get_settings_manager()
        path = os.path.abspath(mgr.config_path)
        mtime = os.path.getmtime(path)
    except Exception:
        return False
    if _SETTINGS_STATE["path"] == path and _SETTINGS_STATE["mtime"] == mtime:
        return False
    try:
        from functions.base.common.json_io import read_json
        fresh = read_json(path)
    except Exception:
        return False
    if not isinstance(fresh, dict) or not fresh:
        return False
    mgr.settings = fresh
    _SETTINGS_STATE["path"] = path
    _SETTINGS_STATE["mtime"] = mtime
    return True

def active_skin_id() -> str:
    refresh_settings()
    try:
        from functions.base.settings_manager import get_settings_manager
        sid = str(get_settings_manager().get_setting(SKIN_SETTING_KEY) or "").strip()
    except Exception:
        return ""
    if not sid:
        return ""
    try:
        from functions.base.user_system import load_user, _value as _user_value
        meta = skin_meta(sid)
        unlock = meta.get("unlock") if isinstance(meta.get("unlock"), dict) else {"type": "free"}
        if str(unlock.get("type") or "free").lower() == "free":
            return sid
        if sid in set(_user_value(load_user(), "unlocked_skins", [])):
            return sid
        print(f"[Skin] {sid} 尚未解锁, 本次回退默认皮肤")
        return ""
    except Exception:
        return sid

def skin_css(skin_id) -> str:
    sd = skin_dir(skin_id)
    if not sd:
        return ""
    for rel in (("css", "style.css"), ("css", "skin.css")):
        p = os.path.join(sd, *rel)
        if os.path.isfile(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    return f.read()
            except Exception:
                return ""
    return ""

def active_skin_css() -> str:
    try:
        return skin_css(active_skin_id())
    except Exception:
        return ""

def _is_css_color(value: str) -> bool:
    v = str(value or "").strip()
    if not v:
        return False
    if v.startswith("#"):
        if len(v) not in (4, 7, 9):
            return False
        try:
            int(v[1:], 16)
        except ValueError:
            return False
        return True
    return bool(re.match(r"^(rgb|rgba|hsl|hsla)\([0-9.,%\s/]+\)$", v, re.I))

def window_background(fallback: str = "#0b0e14") -> str:
    try:
        sid = active_skin_id()
        if sid:
            tc = str(skin_meta(sid).get("theme_color") or "").strip()
            if _is_css_color(tc):
                return tc
    except Exception:
        pass
    return fallback

def shared_theme_css() -> str:
    try:
        from functions.base.common.path_utils import get_web_root
        p = get_web_root("shared", "theme.css")
        if p and os.path.isfile(p):
            with open(p, "r", encoding="utf-8") as f:
                return f.read()
    except Exception as e:
        print(f"[Theme] 读取共享主题层失败: {e}")
    return ""

def full_theme_css() -> str:
    parts = [shared_theme_css()]
    sid = ""
    try:
        sid = active_skin_id()
    except Exception:
        sid = ""
    skin = skin_css(sid) if sid else ""
    if skin:
        parts.append(f"/* ===================== skin: {sid} ===================== */\n{skin}")
    return "\n".join(p for p in parts if p)

def _inject_js(css: str) -> str:
    return (
        "(function(){var d=document,id=%s,s=d.getElementById(id);"
        "if(!s){s=d.createElement('style');s.id=id;(d.head||d.documentElement).appendChild(s);}"
        "s.textContent=%s;})();" % (json.dumps(THEME_STYLE_ID), json.dumps(css))
    )

def apply_theme_to_window(window, *, show_when_ready: bool = False, fallback_ms: int = 1500) -> bool:
    def _apply():
        css = full_theme_css()
        if css:
            try:
                window.evaluate_js(_inject_js(css))
            except Exception as e:
                print(f"[Theme] 注入失败: {e}")
        if show_when_ready:
            _safe_show(window)

    ok = False
    try:
        window.events.loaded += lambda *a, **k: _apply()
        ok = True
    except Exception as e:
        print(f"[Theme] 无法监听 loaded 事件: {e}")
    if show_when_ready:
        t = threading.Timer(max(0.2, fallback_ms / 1000.0), lambda: _safe_show(window))
        t.daemon = True
        t.start()
    return ok

def _safe_show(window):
    try:
        window.show()
    except Exception:
        pass

def list_skins() -> list[dict]:
    out: list[dict] = [{
        "id": "", "name": "默认皮肤", "description": "启动器内置默认外观",
        "theme_color": "", "unlock": {"type": "free"}, "profile": "",
    }]
    root = skins_root()
    if not root or not os.path.isdir(root):
        return out
    try:
        names = sorted(os.listdir(root))
    except OSError:
        return out
    for n in names:
        if not skin_dir(n):
            continue
        meta = skin_meta(n)
        out.append({
            "id": n,
            "name": meta.get("name") or n,
            "description": meta.get("description") or "",
            "theme_color": meta.get("theme_color") or "",
            "unlock": meta.get("unlock") if isinstance(meta.get("unlock"), dict) else {"type": "free"},
            "profile": skin_profile_file(n),
        })
    return out

def theme_payload() -> dict:
    sid = ""
    try:
        sid = active_skin_id()
    except Exception:
        sid = ""
    meta = skin_meta(sid) if sid else {}
    return {
        "active_skin": sid,
        "name": (meta.get("name") or "默认皮肤") if sid else "默认皮肤",
        "theme_color": (meta.get("theme_color") or "") if sid else "",
        "css": active_skin_css(),
    }

class SkinBridge:

    def get_active_skin_css(self) -> str:
        return active_skin_css()

    def get_theme(self) -> dict:
        return theme_payload()

    def get_full_theme_css(self) -> str:
        return full_theme_css()

    def get_shared_theme_css(self) -> str:
        return shared_theme_css()

    def list_skins(self) -> list[dict]:
        return list_skins()
