"""云端皮肤仓库: 云端皮肤清单 + 本地皮肤目录 + 皮肤包下载解压。

为什么要有这个模块
------------------
皮肤包里的背景图动辄几十 MB, 不适合继续塞进启动器安装包。现在拆成两半:

* **云端皮肤清单** (笔记 ``FaustLauncher.themes``): 每个条目含 ``id``、名字、
  简介、作者、主题色、解锁条件、封面图 ``icon_url``、皮肤包下载地址 ``url``、
  ``version``。展示层面的一切都来自它 —— 启动器只管读取和渲染。
* **本地皮肤目录**: 只存放已下载/自带的皮肤包本身。

读取云端走 :class:`functions.webFunc.Webnote.Note` —— 与下载中心 / 资源管理
完全同一条链路 (多线路重试、IPv4 与 DoH 兜底、磁盘缓存), 不另写网络代码。

云端清单什么时候读
------------------
**只在启动时读一次** (:func:`prefetch`), 之后 ``get_skins`` / 切换皮肤等所有
界面请求都只读内存, 和插件、Mod 的云端资源缓存 (``page_loader._cloud_sync_cache``)
是同一套策略 —— 笔记只有几百字节, 但每点一次皮肤都去访问一次云端毫无必要。

皮肤目录为什么不是一个固定路径
------------------------------
源码运行: ``<仓库>/web/app_skins``。
打包运行: PyInstaller 把整个 ``web/`` 收进 ``_internal``, 于是皮肤在
``<exe>/_internal/web/app_skins`` (:func:`functions.base.common.path_utils.get_web_root`
的第一候选)。安装包本身**不再内置任何皮肤包**, 下载的皮肤就解压进这个目录,
升级时由 ``tools/build_temp/updater.vbs`` 第 2.4 步把它补回来。

``_internal`` 也可能只读 (装在 Program Files), 这时按「皮肤目录 →
``<exe>/app_skins``」的顺序挑第一个**真的能写**的落点; 读取时两个根目录合并。
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tempfile
import threading
import time

from functions.base.common import icon_cache, icon_fetch

_FROZEN = bool(getattr(sys, "frozen", False))

if _FROZEN:
    _PROJECT_ROOT = os.path.dirname(os.path.abspath(sys.executable))
else:
    _PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

#: 云端皮肤清单所在的笔记名; ``web_config.json`` 的 ``webnote.themes`` 可覆盖。
THEMES_NOTE = "FaustLauncher.themes"

#: 云端皮肤清单在启动时预取一次 (与插件/Mod 云端资源缓存同一策略), 这里只在
#: 预取完成/显式强制刷新时通知界面重绘。

#: 云端封面图的磁盘缓存 (与下载中心 ``cache/icons`` 同一套缩略/退避策略)。
ICON_CACHE_DIR = os.path.join(_PROJECT_ROOT, "cache", "theme_icons")

#: 封面图显示在皮肤卡片里, 比下载中心的 128px 图标大, 留 2 倍屏余量。
ICON_MAX_EDGE = 320

#: 皮肤包上限, 超过基本可以断定链接指错了 (比如指到资源整合包)。
MAX_PACK_BYTES = 256 * 1024 * 1024

#: 云端清单里缺 ``unlock`` 时的兜底 (只用于展示, 不当成"放行")。
_DEFAULT_UNLOCK = {"type": "free", "description": "免费皮肤，无需任何解锁条件"}

#: 本地 config.json 丢失时的兜底显示名 (见 :func:`_fallback_name`)。

#: 云端 JSON 里的对象块与"键: 字符串值"对。实测云端会漏写逗号
#: (``"icon_url": "..."`` 换行直接接 ``"description"``), 标准解析必失败,
#: 所以逐字段扫描兜底 —— 皮肤条目是扁平结构, 没有嵌套大括号。
_OBJECT_RE = re.compile(r"\{[^{}]*\}")
_FIELD_RE = re.compile(r'"([^"\\]+)"\s*:\s*"((?:[^"\\]|\\.)*)"')

#: 扫描结果的 3 秒缓存, 避免一次 ``get_skins`` 里反复读同一批 config.json。
_SCAN = {"at": 0.0, "items": {}}
_SCAN_LOCK = threading.Lock()

#: 可写皮肤根目录 (首次探测后固定, 探测本身会写一个临时文件)。
_WRITABLE = {"path": "", "ready": False}
_WRITABLE_LOCK = threading.Lock()

#: 云端清单缓存: 启动时预取一次, 之后所有界面请求都只读这里 (与插件/Mod 云端
#: 资源缓存 ``page_loader._cloud_sync_cache`` 同一策略), ``refreshing`` 表示预取在路上。
_THEMES = {"at": 0.0, "items": [], "error": "", "refreshing": False}
_THEMES_LOCK = threading.Lock()
_PREFETCH_LOCK = threading.Lock()

#: 云端清单在后台刷新完成后回调 (由 AppApi 挂上去推事件给前端)。
_CHANGE_HOOK = {"fn": None}

#: 云端封面图的 url -> data-uri 内存缓存。
_ICON_URI = {}
_ICON_URI_LOCK = threading.Lock()

#: 皮肤包链接是否可下载 (url -> bool), 每次启动预取后探测一次。
_REACH = {}
_REACH_LOCK = threading.Lock()

#: 下载进度节流: 4 次/秒足够顺滑, 又不会把 JS 桥刷爆。
_PROGRESS_AT = {}  # 皮肤 id -> 上次推送进度的时间 (节流用)


# ---------------- 云端皮肤信息 ----------------

def catalog_entry(skin_id) -> dict:
    """取云端清单里的该皮肤条目; 清单里没有时返回空 dict。"""
    sid = str(skin_id or "").strip()
    if not sid:
        return {}
    item = cloud_theme_map().get(sid)
    return dict(item) if isinstance(item, dict) else {}


def catalog_unlock(skin_id) -> dict:
    """该皮肤的解锁条件 (云端 ``unlock`` 字段); 缺失时按免费处理。"""
    unlock = catalog_entry(skin_id).get("unlock")
    if isinstance(unlock, dict) and unlock:
        return dict(unlock)
    return dict(_DEFAULT_UNLOCK)


def is_free_skin(skin_id) -> bool:
    """是否无需解锁 (``unlock.type == 'free'``)。"""
    return str(catalog_unlock(skin_id).get("type") or "free").lower() == "free"


# ---------------- 本地皮肤目录 ----------------

def builtin_root() -> str:
    """随安装包发布的皮肤目录 (打包后是 ``_internal/web/app_skins``)。

    目录不存在时顺手建一个: 构建脚本只把皮肤包的**内容**剔出发布包, 目录本身要
    留着当下载落点。老产物或被人手动删过时, 缺了它会退回 exe 同级目录, 装在
    Program Files 下那里不可写, 表现就是"皮肤下载不下来"。
    """
    try:
        from functions.base.common.path_utils import get_web_root
        root = get_web_root("app_skins")
    except Exception:
        return ""
    if root and not os.path.isdir(root):
        try:
            os.makedirs(root, exist_ok=True)
        except OSError:
            pass
    return root


def user_root() -> str:
    """皮肤目录 —— 下载落点与读取目录, 源码版与构建版是同一个位置。

    * 源码仓库版: ``web/app_skins``;
    * 构建版: ``_internal/web/app_skins`` (由 ``path_utils.get_web_root`` 定位)。

    构建版也放这里而不是 %APPDATA%: 升级时整个 ``_internal`` 会被换掉, 但
    ``tools/build_temp/updater.vbs`` 第 2.4 步会把旧目录里的皮肤目录原样补回来,
    所以没必要再另开一个用户目录。
    """
    return builtin_root()


def _can_write(folder: str) -> bool:
    """写一个探测文件来确认目录可写 (Windows 上 ``os.access`` 对 ACL 不可靠)。"""
    probe = os.path.join(folder, ".fl_skin_write_test")
    try:
        os.makedirs(folder, exist_ok=True)
        with open(probe, "w", encoding="utf-8") as f:
            f.write("ok")
        os.remove(probe)
        return True
    except OSError:
        return False


def writable_root() -> str:
    """下载皮肤的落盘目录; 一个都写不进去时返回空串。

    首选皮肤目录; 装在 Program Files 等写不进去的位置时 (内置目录只读),
    才退到 ``<exe>/app_skins`` —— 它同样不会被升级覆盖, 只是用户看不见。
    """
    with _WRITABLE_LOCK:
        if _WRITABLE["ready"]:
            return _WRITABLE["path"]
        candidates = [user_root()]
        if _FROZEN:
            candidates.append(os.path.join(_PROJECT_ROOT, "app_skins"))
        chosen = ""
        for folder in candidates:
            if folder and _can_write(folder):
                chosen = folder
                break
        _WRITABLE["path"] = chosen
        _WRITABLE["ready"] = True
        if chosen:
            print(f"[Skin] 下载皮肤将安装到: {chosen}")
        else:
            print("[Skin] 警告: 没有可写的皮肤目录, 无法下载皮肤")
        return chosen


def skin_roots() -> list:
    """所有皮肤根目录。两者在正常情况下相同, 只有内置目录只读时才会分叉。"""
    roots = []
    for folder in (user_root(), builtin_root()):
        if folder and folder not in roots:
            roots.append(folder)
    return roots


def _read_json(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _scan_local() -> dict:
    """扫描全部皮肤根目录 (内置在前, 可写在后覆盖同名 id)。"""
    found = {}
    for root in reversed(skin_roots()):
        try:
            names = sorted(os.listdir(root))
        except OSError:
            continue
        for name in names:
            folder = os.path.join(root, name)
            if not os.path.isdir(folder) or os.path.basename(name) != name:
                continue
            meta = _read_json(os.path.join(folder, "config.json"))
            sid = str(meta.get("id") or "").strip()
            if not sid:
                # 没有 config.json 或没写 id 的目录不算皮肤 (素材包目录等)
                continue
            found[sid] = {
                "id": sid,
                "dir": folder,
                "meta": meta,
                "version": str(meta.get("version") or "").strip(),
                "root": root,
            }
    return found


def local_skins(force: bool = False) -> dict:
    """本地已安装皮肤: ``{皮肤 id: {dir, meta, version, root}}``。

    结果缓存 3 秒 —— 界面渲染一次会问很多次"这个皮肤在哪", 每次都扫盘太浪费。
    ``force=True`` 用于安装/删除之后立即失效缓存。
    """
    now = time.time()
    with _SCAN_LOCK:
        if not force and _SCAN["items"] and now - _SCAN["at"] < 3.0:
            return _SCAN["items"]
        items = _scan_local()
        _SCAN["at"] = now
        _SCAN["items"] = items
        # 顺手校准云端清单的 version: 缓存过的旧笔记里可能既没版本号也没有 url,
        # 校准后版本号也能精确; 这一项必须是"刚扫出来的"结果
        _sync_themes_version(items)
        return items


def _sync_themes_version(installed: dict) -> None:
    """云端条目缺 ``version``/``url`` 时, 用本地同 id 皮肤补上这两项。

    云端笔记漏写字段是常态 (实测 ``url`` 整段缺失), 缺版本号会让每点一次皮肤
    都判定成"需要下载"。这里只补本地已安装的那几个, 不影响未安装皮肤的判定。
    """
    if not installed:
        return
    with _THEMES_LOCK:
        items = list(_THEMES["items"])
        if not items:
            return
        changed = False
        for theme in items:
            info = installed.get(theme.get("id"))
            if not info:
                continue
            version = str(info.get("version") or "").strip()
            if version and not theme.get("version"):
                theme["version"] = version
                changed = True
        if changed:
            _THEMES["items"] = items


def invalidate() -> None:
    """清掉本地扫描缓存 (装完/删完皮肤后调用)。"""
    with _SCAN_LOCK:
        _SCAN["at"] = 0.0
        _SCAN["items"] = {}


def local_skin_dir(skin_id) -> str:
    """本地皮肤目录的绝对路径; 没安装返回空串。"""
    sid = str(skin_id or "").strip()
    if not sid or sid in (".", "..") or os.path.basename(sid) != sid:
        return ""
    item = local_skins().get(sid)
    return str(item.get("dir") or "") if item else ""


def local_skin_meta(skin_id) -> dict:
    """本地皮肤的 config.json 内容 (没装返回空 dict)。"""
    sid = str(skin_id or "").strip()
    item = local_skins().get(sid)
    return dict(item["meta"]) if item else {}


def local_skin_version(skin_id) -> str:
    """本地皮肤的版本号; 没写版本时返回空串。"""
    return str(local_skins().get(str(skin_id or "").strip(), {}).get("version") or "")


# ---------------- 云端皮肤清单 ----------------

def _fetch_note_text(force: bool) -> str:
    """读云端清单文本 (失败返回空串, 错误只打日志)。

    ``Note`` 自带"磁盘缓存失效后回落旧缓存"的行为, 所以网络不通时这里仍能拿到
    上次的清单文本。
    """
    try:
        from functions.webFunc import Note
        from functions.base.web_config import get_webnote
    except Exception as exc:  # noqa: BLE001 - 云端模块不可用时皮肤功能降级为本地模式
        print(f"[Skin] 云端笔记模块不可用: {exc}")
        return ""

    address = ""
    try:
        address = str(get_webnote("themes")[0] or "").strip()
    except Exception:
        address = ""

    note = Note("themes", address or THEMES_NOTE, read_only=True)
    try:
        info = note.fetch_note_info(allow_refresh=force)
    except Exception as exc:  # noqa: BLE001
        print(f"[Skin] 读取云端皮肤清单失败: {type(exc).__name__}: {exc}")
        return ""
    return str(info.get("note_content") or "")


def _loads_lenient(text: str) -> list:
    """把云端纯文本解析成 dict 列表, 容忍缺逗号的非法 JSON。"""
    body = str(text or "").strip()
    if not body:
        return []
    try:
        data = json.loads(body)
        return data if isinstance(data, list) else [data]
    except Exception:
        pass

    items = []
    for block in _OBJECT_RE.findall(body):
        entry = {}
        for key, raw in _FIELD_RE.findall(block):
            try:
                entry[key] = json.loads('"' + raw + '"')
            except Exception:
                entry[key] = raw
        if entry:
            items.append(entry)
    return items


def _normalize_theme(entry: dict) -> dict:
    """云端条目 -> 统一结构; 缺 id 的条目直接丢弃。

    展示用的名字 / 主题色 / 描述 / 作者 / 解锁条件全部照抄云端, 云端没写的
    字段留空, 由界面决定显示成"未知"还是不显示。
    """
    sid = str(entry.get("id") or entry.get("name") or "").strip()
    if not sid:
        return {}
    authors = entry.get("authors")
    unlock = entry.get("unlock")
    return {
        "id": sid,
        "name": str(entry.get("name") or sid),
        "url": str(entry.get("url") or entry.get("download") or "").strip(),
        "icon_url": str(entry.get("icon_url") or entry.get("icon") or "").strip(),
        "description": str(entry.get("description") or ""),
        "version": str(entry.get("version") or "").strip(),
        "theme_color": str(entry.get("theme_color") or "").strip(),
        "authors": dict(authors) if isinstance(authors, dict) else {},
        "unlock": dict(unlock) if isinstance(unlock, dict) and unlock else dict(_DEFAULT_UNLOCK),
    }


def parse_themes(text: str) -> list:
    """解析云端清单文本, 返回去重后的条目列表。"""
    items = []
    seen = set()
    for entry in _loads_lenient(text):
        if not isinstance(entry, dict):
            continue
        theme = _normalize_theme(entry)
        if not theme or theme["id"] in seen:
            continue
        seen.add(theme["id"])
        items.append(theme)
    return items


def _disk_cached_text() -> str:
    """上次成功落盘的清单文本 (离线时先用它把界面撑起来)。"""
    try:
        from functions.webFunc.Webnote import cache_read
        text, _age = cache_read(THEMES_NOTE)
        return text or ""
    except Exception:
        return ""


def _pub_state() -> dict:
    """对外快照 ``{"items", "error", "refreshing"}``。"""
    with _THEMES_LOCK:
        return {
            "items": list(_THEMES["items"]),
            "error": str(_THEMES["error"] or ""),
            "refreshing": bool(_THEMES["refreshing"]),
        }


def prefetch(wait: bool = False) -> dict:
    """启动时预取云端皮肤清单 —— 整个进程只联网这一次。

    与下载中心的 ``page_loader._cloud_sync_cache`` 同一套思路: 启动拉一次,
    之后所有界面请求 (``get_skins``) 都只读内存, 不再重复访问云端笔记。
    已有内存数据时直接返回; ``wait=True`` 同步等待首次拉取 (启动预热用)。

    返回 ``{"items", "error", "refreshing"}``。
    """
    state = _pub_state()
    if state["items"]:
        return state

    with _PREFETCH_LOCK:
        state = _pub_state()
        if state["items"] or state["refreshing"]:
            return state
        with _THEMES_LOCK:
            _THEMES["refreshing"] = True

    def _work():
        try:
            text = _fetch_note_text(False)
            items = parse_themes(text) if text.strip() else []
            with _THEMES_LOCK:
                if items:
                    _THEMES.update({"at": time.time(), "items": items, "error": ""})
                    print(f"[Skin] 云端皮肤清单已就绪: {len(items)} 个")
                else:
                    _THEMES["error"] = "云端皮肤清单获取失败 (可能离线)"
            if items:
                _fire_change()      # 先让界面看到列表, 链接探测随后在后台补
                _warm_reach(items)
                _local_theme_icons({it.get("id"): it for it in items})
        except Exception as exc:  # noqa: BLE001
            with _THEMES_LOCK:
                _THEMES["error"] = f"{type(exc).__name__}: {exc}"
            print(f"[Skin] 预取云端皮肤清单失败: {type(exc).__name__}: {exc}")
        finally:
            with _THEMES_LOCK:
                _THEMES["refreshing"] = False
            _fire_change()

    if wait:
        _work()
    else:
        threading.Thread(target=_work, name="faust-skin-themes", daemon=True).start()
    return _pub_state()


def _fire_change() -> None:
    hook = _CHANGE_HOOK.get("fn")
    if not callable(hook):
        return
    try:
        hook()
    except Exception as exc:  # noqa: BLE001 - 通知失败不影响皮肤功能
        print(f"[Skin] 皮肤清单变更通知失败: {exc}")


def set_change_hook(fn) -> None:
    """注册"云端清单预取完成/更新了"的回调 (AppApi 用它推事件给前端)。"""
    _CHANGE_HOOK["fn"] = fn


def cloud_themes(force: bool = False, wait: bool = False) -> dict:
    """云端皮肤清单, 返回 ``{"items": [...], "error": str}``。

    缓存策略与插件/Mod 云端资源一致 —— **只认启动时那一次**:

    * 内存里已有清单: 直接返回, 无论界面调用多少次都不联网;
    * 内存里没有 (启动预取还在路上 / 失败了): 读笔记的磁盘缓存先顶上, 并补一次预取;
    * ``force=True``: 用户明确要求重拉 (例如下载前要最新版本号);
    * ``wait``: 首次预取是否同步等待 —— 新皮肤尚未下载时才用, 需要一份尽量新的版本号。
    """
    state = _pub_state()
    if state["items"] and not force:
        return {"items": state["items"], "error": state["error"]}

    if force:
        text = _fetch_note_text(True)
        items = parse_themes(text) if text.strip() else []
        if items:
            with _THEMES_LOCK:
                _THEMES.update({"at": time.time(), "items": items, "error": ""})
            threading.Thread(target=_warm_reach, args=(items,),
                             name="faust-skin-reach", daemon=True).start()
            return {"items": items, "error": ""}
        state = _pub_state()
        return {"items": state["items"], "error": state["error"] or "云端皮肤清单暂时获取失败"}

    if state["refreshing"]:
        if not wait:
            return {"items": [], "error": "正在获取云端皮肤清单"}
        # 预取正在路上: 等它结束, 别让这一次调用再去敲一遍云端笔记
        for _ in range(120):
            time.sleep(0.25)
            state = _pub_state()
            if not state["refreshing"]:
                break
        if state["items"]:
            return {"items": state["items"], "error": state["error"]}

    # 进程内还没有数据: 先用上次落盘的清单把界面撑起来, 预取继续在后台跑。
    disk_items = parse_themes(_disk_cached_text())
    if disk_items:
        with _THEMES_LOCK:
            if not _THEMES["items"]:
                _THEMES.update({"at": time.time(), "items": disk_items})
        _refresh_if_idle()
        return {"items": disk_items, "error": ""}

    state = prefetch(wait=wait)
    return {"items": state["items"], "error": state["error"]}


def _refresh_if_idle() -> None:
    """后台补一次预取 (已有数据时不重复发起)。"""
    if not _pub_state()["refreshing"]:
        threading.Thread(target=prefetch, name="faust-skin-themes", daemon=True).start()


def cloud_theme_map(wait: bool = False) -> dict:
    """``{皮肤 id: 云端条目}`` (名字/主题色/解锁条件等展示字段都以这里为准)。"""
    items = cloud_themes(wait=wait)["items"]
    if items:
        _sync_themes_version(local_skins())
    return {item["id"]: item for item in items}


def cloud_theme(skin_id, wait: bool = False) -> dict:
    """单个皮肤的云端条目 (没有返回空 dict)。

    本地已有清单时直接用清单判断是否要下载; 只有清单里根本没有这款皮肤
    (多半是用户新点的云端皮肤, 而启动预取还没完成) 才带着 ``wait`` 等预取。
    """
    sid = str(skin_id or "").strip()
    theme = cloud_theme_map().get(sid)
    if theme:
        return theme
    if not wait:
        return {}
    return cloud_theme_map(wait=True).get(sid, {})


# ---------------- 云端封面图 ----------------

def theme_icon_uri(skin_id: str, icon_url: str) -> str:
    """云端封面图 -> ``data:image/png;base64,...``。

    复用下载中心那套图标缓存: 先找磁盘缓存, 没有再按「已知直链 → 包装 URL 直连」
    取图, 缩到 :data:`ICON_MAX_EDGE` 后落盘; 失败记入 60 秒退避表, 避免每次
    重绘都去重试一个坏链接。
    """
    url = str(icon_url or "").strip()
    if not url:
        return ""
    with _ICON_URI_LOCK:
        if url in _ICON_URI:
            return _ICON_URI[url]

    uri = ""
    try:
        cached = icon_cache.find_cached_icon(url, skin_id, ICON_CACHE_DIR)
        if cached:
            uri = icon_fetch.data_uri(cached)
        elif not icon_cache.icon_failed_recently(url):
            data = icon_fetch.download_image(url, timeout=12.0)
            if data:
                icon_cache.note_icon_success(url)
                path = icon_cache.save_icon(
                    data, url, skin_id, ICON_CACHE_DIR, max_edge=ICON_MAX_EDGE)
                if path:
                    uri = icon_fetch.data_uri(path)
            else:
                icon_cache.note_icon_failure(url)
    except Exception as exc:  # noqa: BLE001 - 封面图拿不到就用占位图, 不影响列表
        print(f"[Skin] 云端封面图获取失败({skin_id}): {type(exc).__name__}: {exc}")

    if uri:
        with _ICON_URI_LOCK:
            if len(_ICON_URI) > 64:
                _ICON_URI.clear()
            _ICON_URI[url] = uri
    return uri


def _local_theme_icons(themes):
    """后台把已安装皮肤要用的封面图先缓存一遍 (只算云端图, 本地图由前端按需读)。

    已安装的卡片前端直接读本地 ``profile.*``, 但抽屉和用户页还会用到云端
    ``icon_url``; 提前取好, 列表和抽屉就不会各等一次几秒的远程拉图。
    """
    installed = local_skins()
    for sid, theme in (themes or {}).items():
        if sid not in installed:
            continue
        url = str(theme.get("icon_url") or "")
        if not url:
            continue
        try:
            theme_icon_uri(sid, url)
        except Exception:
            pass


# ---------------- 版本判断与安装 ----------------

def _norm_version(value) -> str:
    return str(value or "").strip().lower().lstrip("v").strip()


def same_version(local_version, cloud_version) -> bool:
    """本地与云端版本是否一致。

    云端没写版本 = 无从比较, 视为一致 (否则每次点开都要重下一遍);
    本地没写版本而云端有 = 不一致 (老皮肤包需要补一次)。
    """
    cloud = _norm_version(cloud_version)
    local = _norm_version(local_version)
    if not cloud:
        return True
    if not local:
        return False
    return local == cloud


def _warm_reach(items) -> None:
    """后台预热"未安装皮肤"的链接探测, 免得打开玻璃窗时现等。

    探测本身是纯网络往返 (蓝奏解析链接 head 一次要一秒多), 结果按 url 缓存,
    这里提前跑一遍, 列表渲染时就只剩查表。
    """
    for item in items or ():
        url = str(item.get("url") or "")
        if not url:
            continue
        try:
            _check_reachable(url)
        except Exception:
            pass


def _check_reachable(url: str) -> bool:
    """确认皮肤包是否真的可下载 —— 只用来给卡片打"暂未发布"标记。

    云端笔记里先写好条目、链接后补是常态, 此时点进去只会得到一句下载失败;
    与其让用户白等, 不如在列表里就标出来。结果按 url 缓存, 只在启动预取后做一次。
    """
    if not url:
        return False
    with _REACH_LOCK:
        if url in _REACH:
            return _REACH[url]
    ok = False
    try:
        import requests

        headers = {"User-Agent": "FaustLauncher"}
        code = 0
        try:
            resp = requests.head(url, timeout=(8, 15), allow_redirects=True,
                                 verify=False, headers=headers)
            code = int(resp.status_code)
            resp.close()
        except Exception:
            code = 0
        if code == 0 or code >= 400:
            resp = requests.get(url, timeout=(8, 20), stream=True, allow_redirects=True,
                                verify=False, headers=headers)
            with resp:
                code = int(resp.status_code)
        ok = 200 <= code < 400
    except Exception as exc:  # noqa: BLE001 - 探测失败只影响标记, 不阻断
        print(f"[Skin] 探测皮肤包链接失败: {type(exc).__name__}: {exc}")
        ok = False
    with _REACH_LOCK:
        _REACH[url] = ok
    return ok


def entry_list() -> list:
    """界面用的皮肤列表: 已安装的在前, 云端未安装的追加在后面。

    每项含展示所需字段, 但不含图片 data-uri (由调用方按需取, 避免一次渲染
    把几十张图全塞进 JS 桥):
    ``{id, installed, cloud, publishable, version, cloud_version, needs_install,
    needs_update, name, description, authors, theme_color, unlock, dir, icon_url}``
    """
    local = local_skins()
    themes = cloud_theme_map()
    items = []
    for sid, info in local.items():
        meta = info["meta"]
        theme = themes.get(sid) or {}
        version = str(info["version"] or "")
        cloud_version = str(theme.get("version") or "")
        items.append({
            "id": sid,
            "installed": True,
            "cloud": bool(theme),
            "publishable": True,
            "version": version,
            "cloud_version": cloud_version,
            "needs_install": False,
            "needs_update": bool(theme) and not same_version(version, cloud_version),
            "name": str(theme.get("name") or meta.get("name") or sid),
            "description": str(theme.get("description") or meta.get("description") or ""),
            "authors": _pick_authors(theme, meta),
            "theme_color": str(theme.get("theme_color") or meta.get("theme_color") or ""),
            "unlock": _pick_unlock(theme, meta),
            "dir": info["dir"],
            "icon_url": str(theme.get("icon_url") or ""),
        })

    for sid, theme in themes.items():
        if sid in local:
            continue
        items.append({
            "id": sid,
            "installed": False,
            "cloud": True,
            "version": "",
            "cloud_version": str(theme.get("version") or ""),
            "needs_install": True,
            "needs_update": False,
            "name": str(theme.get("name") or sid),
            "description": str(theme.get("description") or ""),
            "authors": dict(theme.get("authors") or {}),
            "theme_color": str(theme.get("theme_color") or ""),
            "unlock": dict(theme.get("unlock") or _DEFAULT_UNLOCK),
            "dir": "",
            "icon_url": str(theme.get("icon_url") or ""),
        })

    items.sort(key=lambda item: (not item["installed"], str(item["name"])))
    for item in items:
        # 只给"还没下过"的条目探测链接: 已安装的皮肤不需要, 而 head 一次
        # 蓝奏解析链接要 1 秒多, 挂进列表里就变成了进玻璃窗要等几秒
        if item["installed"]:
            item["publishable"] = True
            continue
        try:
            item["publishable"] = _check_reachable(
                str(themes.get(item["id"], {}).get("url") or ""))
        except Exception:
            item["publishable"] = False
    return items


def _pick_authors(theme: dict, meta: dict) -> dict:
    """作者信息: 云端优先, 云端没写时用本地 config.json 的。"""
    authors = theme.get("authors")
    if isinstance(authors, dict) and authors:
        return dict(authors)
    local = meta.get("authors")
    return dict(local) if isinstance(local, dict) else {}


def _pick_unlock(theme: dict, meta: dict) -> dict:
    """解锁条件: 云端优先, 云端没写时用本地 config.json 的, 都没有按免费。"""
    unlock = theme.get("unlock")
    if isinstance(unlock, dict) and unlock:
        return dict(unlock)
    local = meta.get("unlock")
    if isinstance(local, dict) and local:
        return dict(local)
    return dict(_DEFAULT_UNLOCK)


def _notify(progress, task: str, event: str, done: int = 0, total: int = 0,
            speed=0, percent=None, text: str = "", force: bool = False) -> None:
    """把下载进度推给界面 (以任务名为单位节流到 5 次/秒)。

    事件形状与下载中心的 ``HeadlessDownloadGUI`` 完全一致 (``task`` / ``text`` /
    ``percent`` / ``downloaded`` / ``total`` / ``speed``), 前端下载抽屉的
    ``updateDownloadTask`` 不需要为皮肤开特例。

    节流键必须带上任务名: 否则同一时刻先跑的另一个皮肤 (或上一轮的收尾事件)
    会把时间戳占掉, 新任务的进度就被整段吞掉。
    """
    if progress is None:
        return
    now = time.time()
    # 状态行是给用户看的阶段提示, 不受节流影响 (它们本来就很少)
    if event == "status":
        force = True
    if not force and now - _PROGRESS_AT.get(task, 0.0) < 0.2:
        return
    _PROGRESS_AT[task] = now
    if percent is None:
        percent = int(done * 100 / total) if total else 0
    # 每一类事件都给齐全部键: 前端按事件类型挑着读, 缺键会直接报错
    payload = {
        "event": event,
        "task": task,
        "text": str(text or ""),
        "percent": max(0.0, min(100.0, round(float(percent), 1))),
        "downloaded": int(done or 0),
        "total": int(total or 0),
        "speed": round(float(speed or 0), 1),
    }
    try:
        progress(payload)
    except Exception:
        pass


def _work_root() -> str:
    """下载/解压的中转目录 (与缓存同盘, 装完即删)。"""
    folder = os.path.join(_PROJECT_ROOT, "cache", "skin_tmp")
    os.makedirs(folder, exist_ok=True)
    return folder


def _locate_skin_dir(folder: str) -> str:
    """在解压结果里找出真正的皮肤目录。

    皮肤包有两种常见结构: 顶层就是 ``config.json``, 或者多套一层皮肤名目录
    (``naiwa/config.json``)。这里按层往下找, 最多 3 层, 找到 config.json 为止。
    """
    if not os.path.isdir(folder):
        return ""
    level = [folder]
    for _depth in range(3):
        next_level = []
        for base in level:
            if os.path.isfile(os.path.join(base, "config.json")):
                return base
            try:
                names = sorted(os.listdir(base))
            except OSError:
                continue
            for name in names:
                sub = os.path.join(base, name)
                if os.path.isdir(sub):
                    next_level.append(sub)
        level = next_level
        if not level:
            break
    return ""


def _promote_root(folder: str) -> str:
    """皮肤内容就在解压根目录时的清场: 只留皮肤自身的内容, 其余一并删掉。

    ``download_and_extract_mod`` 会把压缩包解到指定目录 (再删压缩包), 包里
    没有外层目录时, 解压产物和下载残留混在同一层 —— 直接整体搬走会把残留
    也带进皮肤目录, 所以在原地挑出皮肤内容, 把根目录本身当作来源。
    """
    keep = {"config.json", "css", "assets", "source", "shared", "CREDITS.md"}
    for name in os.listdir(folder):
        if name in keep:
            continue
        path = os.path.join(folder, name)
        try:
            if os.path.isdir(path):
                shutil.rmtree(path, ignore_errors=True)
            else:
                os.remove(path)
        except OSError:
            pass
    return os.path.normpath(folder)


def _replace_dir(source: str, target: str) -> None:
    """用 source 整个替换 target (先删旧目录, 再搬过去)。"""
    if os.path.isdir(target):
        shutil.rmtree(target, ignore_errors=True)
    elif os.path.isfile(target):
        try:
            os.remove(target)
        except OSError:
            pass
    parent = os.path.dirname(target)
    if parent:
        os.makedirs(parent, exist_ok=True)
    try:
        shutil.move(source, target)
    except OSError:
        shutil.copytree(source, target, dirs_exist_ok=True)


def _stamp_config(folder: str, skin_id: str, theme: dict) -> None:
    """把 id / version 写回 config.json, 下次版本检查才有依据。"""
    path = os.path.join(folder, "config.json")
    meta = _read_json(path)
    if not meta:
        return
    changed = False
    if str(meta.get("id") or "") != skin_id:
        meta["id"] = skin_id
        changed = True
    version = str(theme.get("version") or "").strip()
    if version and str(meta.get("version") or "").strip() != version:
        meta["version"] = version
        changed = True
    if not changed:
        return
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=4)
    except OSError as exc:
        print(f"[Skin] 写入皮肤配置失败: {path} ({exc})")


class ProgressSink:
    """下载进度接收器 —— 与下载中心的 ``HeadlessDownloadGUI`` 接口一致。

    ``functions.web_update.zeroasso_download`` 里的下载/解压链路是按这个最小
    接口写的 (``current_file_var.set`` + ``update_progress`` + ``is_downloading``),
    插件/Mod 用的正是它; 皮肤走同一个入口, 进度事件就能直接灌进原生下载抽屉。

    ``cb`` 收到的是下载抽屉那种形状的事件字典:
    ``{"event": "status"|"progress", "task", "text", "percent", "downloaded",
    "total", "speed"}`` —— 前端 ``updateDownloadTask`` 原样能吃。
    """

    def __init__(self, skin_id: str, cb=None, task: str = ""):
        self.skin_id = skin_id
        self.task = task or skin_id
        self.cb = cb
        self.is_downloading = True
        self._total = 0
        self._animated = 0.0
        self.state = {"percent": 0, "message": ""}
        # 下载链路里的"当前阶段"文案 (open_download_source / 解压) 都写到这
        self.current_file_var = _TextSink(self._on_stage)

    def _on_stage(self, text: str) -> None:
        """下载链路换阶段: 抽屉里那行小字跟着变。"""
        message = str(text)
        self.state["message"] = message
        _notify(self.cb, self.task, "status", text=message, force=True)

    def update_progress(self, percent, downloaded, total, speed):
        """下载中心 GUI 的进度回调 (percent 走 0-100, 速度单位 KB/s)。"""
        raw = float(percent or 0)
        # 与下载中心一致做平滑: 回调本身 100ms 一次, 但到达值直接上屏会一顿一顿
        self._animated += (raw - self._animated) * 0.35 if raw > self._animated else 0.0
        if raw >= 99.9:
            self._animated = raw
        total = total or self._total
        if total:
            self._total = total
        self.state["percent"] = float(percent or 0)
        # 解压阶段也会走到这里 (传进来的恒是 100): 没有进度可画, 只报阶段文案,
        # 别让抽屉里的进度条刚跑到 100% 又被拉回去
        if total and downloaded and downloaded >= total:
            _notify(self.cb, self.task, "progress", done=downloaded, total=total,
                    speed=speed, percent=100.0)
            return
        _notify(self.cb, self.task, "progress", done=downloaded, total=total,
                speed=speed, percent=self._animated)

    def reset(self, message: str) -> None:
        """换到下一阶段 (解压等) 时把进度条拉回 0 并换文案。"""
        self.state["percent"] = 0.0
        self._animated = 0.0
        self._total = 0
        self._on_stage(message)


class _TextSink:
    """替代 tkinter 的 ``StringVar``: 下载链路里的"当前阶段"文案落到这里。"""

    def __init__(self, on_set=None):
        self._value = ""
        self._on_set = on_set

    def set(self, value):
        self._value = str(value)
        if self._on_set is not None:
            self._on_set(self._value)

    def get(self):
        return self._value


def _fmt_bytes(size) -> str:
    value = float(size or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


def _install_from_cloud(skin_id: str, theme: dict, progress) -> dict:
    """下载 -> 解压 -> 落到用户皮肤目录 (与插件/Mod 同一条下载链路)。"""
    root = writable_root()
    if not root:
        return {"ok": False, "installed": False, "error": "没有可写的皮肤目录"}

    work = ""
    sink = ProgressSink(skin_id, progress, task=str(theme.get("name") or skin_id))
    try:
        from functions.web_update.zeroasso_download import download_and_extract_mod

        work = tempfile.mkdtemp(prefix="fl_skin_", dir=_work_root())
        archive = os.path.join(work, f"{skin_id}.zip")
        sink.reset("正在连接下载地址")
        ok = download_and_extract_mod(
            sink, work, [{
                "url": theme.get("url") or "",
                "name": theme.get("name") or "皮肤包",
                "temp_filename": f"{skin_id}.zip",
            }])
        if not ok:
            print(f"[Skin] 皮肤包下载/解压失败: {skin_id}")
            return {"ok": False, "installed": False, "error": "皮肤包下载失败"}

        source = _locate_skin_dir(work)
        if not source:
            return {"ok": False, "installed": False, "error": "皮肤包里没有 config.json"}
        if source == os.path.normpath(work):
            # 7-Zip 会就地解压并删掉压缩包, 两者同目录; 先搬到子目录再清场
            os.remove(archive) if os.path.isfile(archive) else None
            source = _promote_root(work)

        target = os.path.join(root, skin_id)
        _replace_dir(source, target)
        _stamp_config(target, skin_id, theme)
        invalidate()
        # 版本以实际装上去的 config.json 为准: 云端没写版本时也能正确记录
        version = str((local_skin_meta(skin_id) or {}).get("version") or theme.get("version") or "")
        print(f"[Skin] {skin_id} 已安装: {target} (版本 {version or '未知'})")
        return {
            "ok": True,
            "installed": True,
            "downloaded": True,
            "version": version,
            "dir": target,
        }
    except Exception as exc:  # noqa: BLE001 - 任何一步失败都转成前端能显示的提示
        print(f"[Skin] 安装 {skin_id} 失败: {type(exc).__name__}: {exc}")
        return {"ok": False, "installed": False, "error": f"{type(exc).__name__}: {exc}"}
    finally:
        if work:
            shutil.rmtree(work, ignore_errors=True)


def ensure_skin_installed(skin_id, progress=None) -> dict:
    """确保该皮肤在本地可用 —— 用户点开皮肤时调用。

    判定顺序:

    1. 本地没有、云端也没有 -> 本地皮肤 (源码里手放的), 直接用;
    2. 本地已有且版本与云端一致 -> 不下载;
    3. 其余 (未安装 / 版本不一致) -> 取云端地址下载并解压。

    返回 ``{"ok", "installed", "downloaded", "version", "name", "error"}``
    (``name`` 是云端显示名, 前端用它给下载抽屉里那一行起名)。
    """
    sid = str(skin_id or "").strip()
    if not sid:
        return {"ok": True, "installed": True, "downloaded": False, "default": True}

    local = local_skins().get(sid)
    # 清单里有这款皮肤 (哪怕已过期) 就直接按它判断, 不在点击时再联网 ——
    # 只有清单里根本没有的肤色 (用户刚点的云端新皮肤) 才等预取把清单拉全。
    theme = cloud_theme(sid, wait=not cloud_themes()["items"])
    name = str((theme or {}).get("name") or (local or {}).get("meta", {}).get("name") or sid)
    if not theme:
        if local:
            return {
                "ok": True, "installed": True, "downloaded": False, "name": name,
                "version": local["version"], "local_only": True,
            }
        return {"ok": False, "installed": False, "name": name,
                "error": "云端没有该皮肤的信息"}

    if local and same_version(local["version"], theme.get("version")):
        return {
            "ok": True, "installed": True, "downloaded": False, "name": name,
            "version": local["version"],
        }

    if not theme.get("url"):
        return {"ok": False, "installed": False, "name": name,
                "error": "云端没有该皮肤的下载地址"}

    print(f"[Skin] {sid} 需要下载: 本地 {local['version'] if local else '未安装'} "
          f"-> 云端 {theme.get('version') or '未知'}")
    result = _install_from_cloud(sid, theme, progress)
    result["name"] = name
    if not result.get("ok"):
        return result

    # 云端没写版本号时, 用装上去的 config.json 把清单补齐, 否则下次点击又判定"要下载"
    installed = str(result.get("version") or "")
    with _THEMES_LOCK:
        for item in _THEMES["items"]:
            if item.get("id") == sid and installed and not item.get("version"):
                item["version"] = installed
    return result
