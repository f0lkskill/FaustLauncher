"""皮肤 / 主题 公共读取层 (主界面与所有子 Web 窗口共用)

为什么需要这个模块
------------------
皮肤目录 ``web/app_skins/<id>/`` **不在** pywebview 的 http 根目录下
(根目录是 ``web/app``), 任何窗口都无法用相对路径取到皮肤 CSS / 素材,
只能由 Python 侧读成文本或 data URI 再下发给页面。

原先这套逻辑只写在 ``functions/pages/app/app_web.py`` 里, 只有主界面能拿到,
所以版本更新、Mod 管理器、扩展工具、自定汉化、Nyos 预设这些独立窗口
(各自一个 pywebview 进程 + 自己的 index.html) 完全用不到皮肤, 只能各自
硬编码一套配色 —— 表现就是"每个子窗口长得都不一样"。

本模块把读取逻辑抽成无 UI 依赖的公共层, 让任意子窗口的 ``js_api`` 都能
直接对外暴露 ``get_active_skin_css()`` / ``get_theme()``。

约定 (与 app_web.py 完全一致, 不要改):
    <skin>/config.json        元信息 (name / id / description / authors / theme_color / unlock)
    <skin>/css/style.css      覆盖层样式, **追加**在 web/shared/theme.css 之后合并生效
    <skin>/css/skin.css       同上 (旧命名, 兼容)
    <skin>/profile.png        玻璃窗列表卡片图
"""
from __future__ import annotations

import json
import os
import re
import threading

SKIN_SETTING_KEY = "skin"
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")

# 主题注入用的 <style> id (前端/调试可据此查当前注入内容)
THEME_STYLE_ID = "fl-theme"


def skins_root() -> str:
    """皮肤根目录 (打包后在 _internal/web/app_skins)"""
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
    """皮肤目录; 空 id 或非法 id 返回空串 (内置默认皮肤 = 空串); 拒绝目录穿越"""
    sid = str(skin_id or "").strip()
    if not sid or sid in (".", "..") or os.path.basename(sid) != sid:
        return ""
    root = skins_root()
    if not root:
        return ""
    d = os.path.join(root, sid)
    return d if os.path.isdir(d) else ""


def skin_meta(skin_id) -> dict:
    """读皮肤 config.json (失败返回空 dict)"""
    sd = skin_dir(skin_id)
    if not sd:
        return {}
    p = os.path.join(sd, "config.json")
    return _read_json(p) if os.path.isfile(p) else {}


def skin_profile_file(skin_id) -> str:
    """皮肤卡片展示图 (profile.*)"""
    sd = skin_dir(skin_id)
    if not sd:
        return ""
    for n in ("profile.png", "profile.jpg", "profile.jpeg", "profile.webp"):
        p = os.path.join(sd, n)
        if os.path.isfile(p):
            return p
    return ""


def active_skin_id() -> str:
    """当前启用的皮肤 id (空串 = 默认皮肤)

    必须一并校验解锁状态: settings.json 里可能残留一个尚未解锁的皮肤,
    直接生效会让解锁系统形同虚设。未解锁时回退默认皮肤, 但不改写用户设置
    (解锁后会自动恢复生效)。
    """
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
    """皮肤覆盖层 CSS 文本 (空 = 无覆盖)"""
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
    """当前皮肤的覆盖层 CSS 文本 (给页面启动早期调用, 避免先默认后皮肤的闪变)"""
    try:
        return skin_css(active_skin_id())
    except Exception:
        return ""


def _is_css_color(value: str) -> bool:
    """是不是一个能直接塞给 pywebview background_color 的颜色值"""
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
    """窗口创建时的底色 (pywebview 的 background_color)

    用当前皮肤 config.json 的 theme_color: 页面渲染出来之前, 系统窗口先铺一层
    底色, 如果固定写死深色, 浅色皮肤 (faust 是 #FFFFFF) 启动瞬间就会闪一下黑。
    皮肤主题色非法 / 默认皮肤时回退 fallback。
    """
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
    """子窗口共享主题层 CSS 文本 (web/shared/theme.css)

    :root 令牌与主界面 web/app/css/style.css 同源, 所以子窗口用 var(--x)
    就能自动跟着主界面/皮肤走。
    """
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
    """共享主题层 + 当前皮肤覆盖层 (子窗口一次注入这一份)"""
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
    """把「共享主题层 + 当前皮肤」注入一个 pywebview 窗口

    必须在 ``webview.start()`` 之前调用 (此时还没有 DOM, 只能注册事件)。
    页面 load 完成后注入: 注入的 <style> 追加在页面自身 <style> 之后,
    因此 :root 变量定义与皮肤覆盖规则都能生效 —— 页面本身不需要引入任何
    外链 CSS, 也不需要知道自己被套了皮肤。

    show_when_ready: 配合 ``create_window(hidden=True)`` 使用, 注入完成后再显示,
        避免"先默认配色后皮肤"的闪变; 万一 loaded 事件没到, fallback_ms 后强制显示。
    """
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
    """全部皮肤元信息 (默认皮肤在最前, id 为空串)"""
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
    """一次性打包给子窗口的主题数据

    子页面在 ``window.pywebview.api`` 就绪后调用一次即可:
        const t = await api.get_theme();
        applyTheme(t.css);
    """
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
    """给各子窗口 ``js_api`` 用的混入类

    用法::

        class MyWindowApi(SkinBridge):
            def __init__(self, ...): ...

        webview.create_window(..., js_api=MyWindowApi(...))

    前端只需 ``window.pywebview.api.get_theme()`` / ``.get_active_skin_css()``。
    """

    def get_active_skin_css(self) -> str:
        """当前皮肤覆盖层 CSS 文本 (前端作为 <style> 追加在 theme.css 之后)"""
        return active_skin_css()

    def get_theme(self) -> dict:
        """当前皮肤信息 + 覆盖层 CSS"""
        return theme_payload()

    def get_full_theme_css(self) -> str:
        """共享主题层 + 当前皮肤 (页面若想自己注入可用这个)"""
        return full_theme_css()

    def get_shared_theme_css(self) -> str:
        """仅共享主题层 CSS 文本 (web/shared/theme.css)"""
        return shared_theme_css()

    def list_skins(self) -> list[dict]:
        """全部皮肤元信息 (子窗口如需皮肤选择器可直接用)"""
        return list_skins()
