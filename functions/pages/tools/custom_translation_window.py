#! 自定义汉化工具窗口 (HTML webview 版)
#? 使用 pywebview 展示: html/custom_translation/index.html (与扩展工具同一深色 GitHub 风格)
#? 功能:
#? - 文件树浏览 lang/ 目录, 搜索文件名 (重建式过滤, 无 detach/reattach 索引位移问题)
#? - 虚拟滚动条目列表 (服务端扁平化+分片拉取, 支持数十万级条目), 编辑叶子值
#? - 两种编辑模式: 表单树视图 / 直接编辑 JSON 原文, 可自由切换
#? - 多个 changes 文件 (图层): changes.json + changes_标记.json, 重名警告,
#?   图层可见性切换 (PS 式, 影响编辑器合并视图与启动加载), 当前编辑目标层
#? 后端逻辑全部位于 TranslationEngine (可独立测试)
#? pywebview 6 要求 webview.start() 运行在主线程, 与 tkinter 主循环互斥,
#? 故以独立子进程方式拉起窗口 (与扩展工具同一模式):
#? - 源码模式: 用 pythonw 运行本脚本子进程
#? - 打包模式 (sys.frozen): 用自身 exe 以 --custom-translation-window 参数二次启动

import base64
import json
import os
import re
import subprocess
import sys

if getattr(sys, "frozen", False):
    _PROJECT_ROOT = os.path.dirname(os.path.abspath(sys.executable))
else:
    _PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

HTML_PATH = os.path.join(_PROJECT_ROOT, "html", "custom_translation", "index.html")

# changes 文件命名: changes.json 或 changes_标记.json (changes_layers.json 是图层状态文件, 不属于 changes)
CHANGES_PATTERN = re.compile(r"^changes(_[^/\\]+)?\.json$", re.IGNORECASE)
# 图层状态文件 (不属于 changes 文件)
LAYER_STATE_FILE = "changes_layers.json"
# 默认层 (changes.json) 颜色
_MAIN_LAYER_COLOR = "#f59e0b"
# 扩展图层调色板 (独特颜色标识)
_LAYER_COLORS = ["#f97316", "#eab308", "#22c55e", "#06b6d4",
                 "#3b82f6", "#8b5cf6", "#ec4899", "#f43f5e"]


def _is_changes_file(fname: str) -> bool:
    """判断文件名是否为 changes 文件家族 (含图层状态文件, 均需从文件树隐藏)"""
    return bool(CHANGES_PATTERN.match(fname))


def _is_layer_changes_file(fname: str) -> bool:
    """判断文件名是否为真正的图层数据文件 (排除 changes_layers.json 状态文件)"""
    return _is_changes_file(fname) and fname.lower() != LAYER_STATE_FILE
# 键黑名单 (表单模式默认隐藏)
HIDDEN_KEYS = {"id", "usage", "personalityid", "voicefile"}
# 非法标记字符
_ILLEGAL_MARKER = set('\\/:*?"<>|')
# 默认分页大小
PAGE_SIZE = 500


def _safe_marker(marker: str) -> str:
    """标记校验: 非空、无非法字符、不能与 changes_layers 冲突"""
    marker = (marker or "").strip()
    if not marker:
        return "标记不能为空"
    if marker.lower() == LAYER_STATE_FILE.replace(".json", "") or marker.lower() == "layers":
        return "标记名不能为 layers"
    if any(ch in _ILLEGAL_MARKER for ch in marker):
        return "标记不能包含 \\ / : * ? \" < > | 字符"
    if marker.lower() == "changes":
        return "标记不能为 changes"
    return ""


def _deep_copy(data):
    if isinstance(data, dict):
        return {k: _deep_copy(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [_deep_copy(v) for v in data]
    return data


def _normalize_path(path: str) -> str:
    return path.replace("\\", "/")


def _recursive_apply(original, changes):
    """把补丁递归应用到数据 (与 game_launcher.apply_changes_to_data 语义一致)"""
    if isinstance(original, dict) and isinstance(changes, dict):
        for k, v in changes.items():
            if k in original:
                if isinstance(original[k], (dict, list)) and isinstance(v, (dict, list)):
                    _recursive_apply(original[k], v)
                else:
                    original[k] = v
    elif isinstance(original, list) and isinstance(changes, list):
        id_map = {}
        for idx, item in enumerate(original):
            if isinstance(item, dict) and "id" in item:
                id_map[item["id"]] = idx
        for key, value in list(id_map.items()):
            id_map[str(key)] = value
        for idx, change in enumerate(changes):
            if isinstance(change, dict) and "id" in change and "changes" in change:
                target_id = change["id"]
                change_data = change.get("changes", {})
                target_idx = id_map.get(target_id, id_map.get(str(target_id)))
                if target_idx is not None:
                    orig_item = original[target_idx]
                    if isinstance(orig_item, (dict, list)) and isinstance(change_data, (dict, list)):
                        _recursive_apply(orig_item, change_data)
                    else:
                        original[target_idx] = change_data
            elif idx < len(original):
                if isinstance(original[idx], (dict, list)) and isinstance(change, (dict, list)):
                    _recursive_apply(original[idx], change)
                else:
                    original[idx] = change


def _compute_diff(original, modified, _count=None):
    """计算差异; 返回 (patch or None, 叶子修改数)"""
    if isinstance(original, dict) and isinstance(modified, dict):
        changes = {}
        for k, v in modified.items():
            if k in original:
                sub, n = _compute_diff(original[k], v, _count)
                if sub is not None:
                    changes[k] = sub
            else:
                changes[k] = v
                if _count is not None:
                    _count[0] += 1
        return (changes if changes else None, _count[0] if _count is not None else -1)
    elif isinstance(original, list) and isinstance(modified, list):
        has_ids = all(isinstance(it, dict) and "id" in it for it in original)
        if has_ids:
            id_to_orig = {item["id"]: item for item in original}
            changes_list = []
            for item in modified:
                if not isinstance(item, dict) or "id" not in item:
                    continue
                item_id = item["id"]
                if item_id in id_to_orig:
                    sub, n = _compute_diff(id_to_orig[item_id], item, _count)
                    if sub is not None:
                        changes_list.append({"id": item_id, "changes": sub, "action": "modified"})
            return (changes_list if changes_list else None, _count[0] if _count is not None else -1)
        else:
            changes_list = []
            min_len = min(len(original), len(modified))
            for i in range(min_len):
                sub, n = _compute_diff(original[i], modified[i], _count)
                if sub is not None:
                    changes_list.append(sub)
            return (changes_list if changes_list else None, _count[0] if _count is not None else -1)
    else:
        if original != modified:
            if _count is not None:
                _count[0] += 1
            return (modified, _count[0] if _count is not None else -1)
        return (None, _count[0] if _count is not None else -1)


def _coerce_value(original, raw):
    """按原始值类型把用户输入字符串转成对应类型; 失败抛 ValueError"""
    if isinstance(original, bool):
        lower = str(raw).strip().lower()
        if lower not in ("true", "false"):
            raise ValueError("布尔值必须为 true 或 false")
        return lower == "true"
    if isinstance(original, int):
        return int(str(raw).strip())
    if isinstance(original, float):
        return float(str(raw).strip())
    return str(raw)


def _resolve_parts(container, path_str):
    """把扁平路径解析为逐层导航段列表 (支持键名本身含 / 的 dict 键: 整串优先匹配)"""
    if isinstance(container, dict):
        if path_str in container:
            return [path_str], True
        if "/" in path_str:
            head, rest = path_str.split("/", 1)
            if head in container:
                sub, ok = _resolve_parts(container[head], rest)
                if ok:
                    return [head] + sub, True
        return [], False
    if isinstance(container, list):
        if path_str.startswith("[") and "]" in path_str:
            end = path_str.index("]")
            idx_str = path_str[1:end]
            rest = path_str[end + 1:]
            if rest.startswith("/"):
                rest = rest[1:]
            if not idx_str.isdigit():
                return [], False
            idx = int(idx_str)
            if 0 <= idx < len(container):
                if not rest:
                    return [f"[{idx}]"], True
                sub, ok = _resolve_parts(container[idx], rest)
                if ok:
                    return [f"[{idx}]"] + sub, True
    return [], False


def _diff_has_path(diff, nav):
    """diff 结构 (action/changes 标记) 中是否存在该路径的修改"""
    if not nav:
        return bool(diff)
    if isinstance(diff, dict):
        if "action" in diff and isinstance(diff.get("changes"), dict):
            action = diff.get("action")
            if action in ("added", "deleted", "replaced"):
                return True
            if action == "modified":
                return _diff_has_path(diff["changes"], nav)
            return False
        if nav in diff:
            return True
        if "/" in nav:
            head, rest = nav.split("/", 1)
            if head in diff:
                return _diff_has_path(diff[head], rest)
        return False
    if isinstance(diff, list):
        if nav.startswith("[") and "]" in nav:
            end = nav.index("]")
            idx_str = nav[1:end]
            rest = nav[end + 1:]
            if rest.startswith("/"):
                rest = rest[1:]
            if not idx_str.isdigit():
                return False
            idx = int(idx_str)
            if 0 <= idx < len(diff):
                if not rest:
                    return True
                return _diff_has_path(diff[idx], rest)
        return False
    return True


def _patch_has_value(patch, kw):
    """patch 中是否存在某个标量修改值包含关键字 (搜索全部修改记录的值)"""
    if isinstance(patch, dict):
        if "action" in patch and isinstance(patch.get("changes"), dict):
            action = patch.get("action")
            if action in ("added", "deleted", "replaced"):
                for k, v in patch.items():
                    if k == "changes":
                        if _patch_has_value(v, kw):
                            return True
                    elif k != "action" and not isinstance(v, (dict, list)):
                        if kw in str(v).lower():
                            return True
                return False
            if action == "modified":
                return _patch_has_value(patch.get("changes") or {}, kw)
            return False
        for v in patch.values():
            if isinstance(v, (dict, list)):
                if _patch_has_value(v, kw):
                    return True
            elif kw in str(v).lower():
                return True
    elif isinstance(patch, list):
        for it in patch:
            if isinstance(it, (dict, list)):
                if _patch_has_value(it, kw):
                    return True
            elif kw in str(it).lower():
                return True
    return False


def _replace_in_data(data, kw, replacement, count):
    """递归替换数据中所有字符串值 (不区分大小写, 仅替换值不替换键)"""
    if isinstance(data, dict):
        for k, v in list(data.items()):
            if isinstance(v, (dict, list)):
                _replace_in_data(v, kw, replacement, count)
            elif isinstance(v, str) and kw in v.lower():
                data[k] = re.sub(re.escape(kw), lambda m: replacement, v, flags=re.IGNORECASE)
                count[0] += 1
    elif isinstance(data, list):
        for i, it in enumerate(data):
            if isinstance(it, (dict, list)):
                _replace_in_data(it, kw, replacement, count)
            elif isinstance(it, str) and kw in it.lower():
                data[i] = re.sub(re.escape(kw), lambda m: replacement, it, flags=re.IGNORECASE)
                count[0] += 1


def _diff_remove_aligned(diff, original, parts):
    """按原始数据对齐的路径段导航删除 diff 中的修改 (list 位置用 id 定位, 应对索引位移;
    未命中时严格返回原引用, 上层不会误判命中)。
    返回 (新diff或None, 是否命中)"""
    if not parts:
        return None, True
    part = parts[0]
    rest = parts[1:]
    if isinstance(diff, dict):
        if "action" in diff and isinstance(diff.get("changes"), dict):
            action = diff.get("action")
            if action == "modified":
                ch, hit = _diff_remove_aligned(diff["changes"], original, parts)
                if not hit:
                    return diff, False
                if ch is None or not ch:
                    return None, True
                out = dict(diff)
                out["changes"] = ch
                return out, True
            if action in ("added", "deleted", "replaced"):
                return None, True
            return diff, False
        if part in diff:
            if not rest:
                out = dict(diff)
                out.pop(part, None)
                return (out or None), True
            sub_orig = original.get(part) if isinstance(original, dict) else None
            sub, hit = _diff_remove_aligned(diff[part], sub_orig, rest)
            if not hit:
                return diff, False
            out = dict(diff)
            if sub is None or not sub:
                out.pop(part, None)
            else:
                out[part] = sub
            return (out or None), True
        return diff, False
    if isinstance(diff, list):
        if part.startswith("[") and part.endswith("]"):
            # 无 id 包装的纯值列表 diff: 元素按位置对应, 删除单个元素会导致后续错位
            # (位置语义无法安全移除, 直接删除整个列表的修改记录)
            wrapped = all(isinstance(it, dict) and "id" in it and "changes" in it
                          for it in diff)
            if not wrapped:
                return None, True
            idx = int(part[1:-1])
            real_idx = idx
            # 用原始数据对应项的 id 在 diff 中定位 (索引可能因先前删除而位移)
            if isinstance(original, list) and 0 <= idx < len(original):
                oitem = original[idx]
                if isinstance(oitem, dict) and "id" in oitem:
                    for i, item in enumerate(diff):
                        if isinstance(item, dict) and item.get("id") == oitem["id"]:
                            real_idx = i
                            break
            if not (0 <= real_idx < len(diff)):
                return diff, False
            item = diff[real_idx]
            if not rest:
                out = list(diff)
                out.pop(real_idx)
                return (out or None), True
            if isinstance(item, dict) and "changes" in item:
                sub_orig = original[idx] if (isinstance(original, list) and 0 <= idx < len(original)) else None
                ch, hit = _diff_remove_aligned(item["changes"], sub_orig, rest)
                if not hit:
                    return diff, False
                out = list(diff)
                if ch is None or not ch:
                    out.pop(real_idx)
                else:
                    new_item = dict(item)
                    new_item["changes"] = ch
                    out[real_idx] = new_item
                return (out or None), True
            return diff, False
        return diff, False
    return diff, False


def _diff_leaf_paths(diff, original, prefix=""):
    """收集 diff 中所有修改叶子的路径字符串列表 (相对 diff 根);
    list 位置用原始数据对齐的索引 (diff 项顺序/数量可能与原始数据不同)"""
    out = []
    if isinstance(diff, dict):
        if "action" in diff and isinstance(diff.get("changes"), dict):
            action = diff.get("action")
            if action == "modified":
                out.extend(_diff_leaf_paths(diff["changes"], original, prefix))
            elif action in ("added", "deleted", "replaced"):
                out.append(prefix or "root")
            return out
        for k, v in diff.items():
            sub = prefix + "/" + k if prefix else k
            sub_orig = original.get(k) if isinstance(original, dict) else None
            if isinstance(v, (dict, list)):
                out.extend(_diff_leaf_paths(v, sub_orig, sub))
            else:
                out.append(sub)
    elif isinstance(diff, list):
        for i, item in enumerate(diff):
            oidx = i
            if isinstance(item, dict) and "id" in item and isinstance(original, list):
                for oi, oitem in enumerate(original):
                    if isinstance(oitem, dict) and oitem.get("id") == item["id"]:
                        oidx = oi
                        break
            sub = prefix + "/[" + str(oidx) + "]" if prefix else "[" + str(oidx) + "]"
            sub_orig = original[oidx] if (isinstance(original, list) and 0 <= oidx < len(original)) else None
            if isinstance(item, (dict, list)):
                out.extend(_diff_leaf_paths(item, sub_orig, sub))
            else:
                out.append(sub)
    else:
        out.append(prefix)
    return out


def _diff_union(a, b):
    """合并两棵 patch 树 (b 优先); list 按 id 对齐合并。
    用于保存到图层时保留该图层原有的、本次净差异未涉及的修改"""
    if b is None:
        return a
    if a is None:
        return b
    if isinstance(a, dict) and isinstance(b, dict):
        if ("action" in a) != ("action" in b):
            return b
        if "action" in a and "action" in b:
            if a.get("action") == "modified" and b.get("action") == "modified":
                merged = _diff_union(a.get("changes") or {}, b.get("changes") or {})
                if not merged:
                    return None
                return {"id": b.get("id", a.get("id")), "changes": merged, "action": "modified"}
            return b
        out = {}
        for k in dict.fromkeys(list(a.keys()) + list(b.keys())):
            if k in a and k in b:
                m = _diff_union(a[k], b[k])
                if m is not None:
                    out[k] = m
            elif k in a:
                out[k] = a[k]
            else:
                out[k] = b[k]
        return out or None
    if isinstance(a, list) and isinstance(b, list):
        by_id_a = {it["id"]: it for it in a if isinstance(it, dict) and "id" in it}
        by_id_b = {it["id"]: it for it in b if isinstance(it, dict) and "id" in it}
        if by_id_a or by_id_b:
            out = []
            for iid in dict.fromkeys(list(by_id_a.keys()) + list(by_id_b.keys())):
                ia, ib = by_id_a.get(iid), by_id_b.get(iid)
                if ia and ib:
                    m = _diff_union(ia, ib)
                    if m is not None:
                        out.append(m)
                elif ia:
                    out.append(ia)
                else:
                    out.append(ib)
            return out or None
        return b
    return b


def _navigate_and_delete(data, path_parts):
    """按路径删除键/元素; 返回是否成功"""
    if not path_parts:
        return False
    parent = data
    for part in path_parts[:-1]:
        if part.startswith("[") and part.endswith("]"):
            idx = int(part[1:-1])
            if isinstance(parent, list) and 0 <= idx < len(parent):
                parent = parent[idx]
            else:
                return False
        else:
            if isinstance(parent, dict) and part in parent:
                parent = parent[part]
            else:
                return False
    last = path_parts[-1]
    if last.startswith("[") and last.endswith("]"):
        idx = int(last[1:-1])
        if isinstance(parent, list) and 0 <= idx < len(parent):
            parent.pop(idx)
            return True
        return False
    if isinstance(parent, dict) and last in parent:
        parent.pop(last)
        return True
    return False


def _navigate_get(data, path_parts):
    """按路径读取值; 返回 (值, 是否存在)"""
    if not path_parts:
        return None, False
    cur = data
    for part in path_parts:
        if part.startswith("[") and part.endswith("]"):
            if not isinstance(cur, list):
                return None, False
            idx = int(part[1:-1])
            if not (0 <= idx < len(cur)):
                return None, False
            cur = cur[idx]
        else:
            if not isinstance(cur, dict) or part not in cur:
                return None, False
            cur = cur[part]
    return cur, True


def _navigate_and_set(data, path_parts, value):
    """按路径导航并写入; 返回是否成功"""
    if not path_parts:
        return False
    parent = data
    for part in path_parts[:-1]:
        if part.startswith("[") and part.endswith("]"):
            idx_str = part[1:-1]
            try:
                idx = int(idx_str)
                if isinstance(parent, list) and 0 <= idx < len(parent):
                    parent = parent[idx]
                else:
                    return False
            except ValueError:
                if isinstance(parent, list):
                    found = None
                    for item in parent:
                        if isinstance(item, dict) and str(item.get("id")) == idx_str:
                            found = item
                            break
                    if found is not None:
                        parent = found
                    else:
                        return False
                else:
                    return False
        else:
            if isinstance(parent, dict) and part in parent:
                parent = parent[part]
            else:
                return False
    last = path_parts[-1]
    if last.startswith("[") and last.endswith("]"):
        idx_str = last[1:-1]
        try:
            idx = int(idx_str)
            if isinstance(parent, list) and 0 <= idx < len(parent):
                parent[idx] = value
                return True
        except ValueError:
            return False
    elif isinstance(parent, dict):
        parent[last] = value
        return True
    return False


class TranslationEngine:
    """自定义汉化核心逻辑 (多层 changes 文件 / 图层可见性 / 合并视图 / diff)"""

    def __init__(self, lang_dir: str = "lang"):
        self.lang_dir = lang_dir
        os.makedirs(self.lang_dir, exist_ok=True)
        self._layers = None          # marker -> {relative: patch}
        self._layer_files = {}       # marker -> 文件绝对路径
        self._state = {}             # marker -> {'disabled': bool, 'color': str}
        self._active = ""            # 当前编辑目标层
        self.current_relative = None
        self.original_data = None
        self.modified_data = None
        self.saved_view = None       # 所有可见层合并结果 (未写入层的临时修改基准)
        self._flat_cache = None
        self._search_cache = None    # rel -> 原文小写全文 (值搜索用, 首次搜索时构建)
        self._filters = {"keyword": "", "only_modified": False,
                         "show_hidden": False, "hidden_layers": [],
                         "collapsed": []}
        self._load_state()
        self._load_layers()
        self._ensure_layer_colors()

    # ── 图层文件管理 ──────────────────────────────────────

    def _load_state(self):
        self._state = {}
        self._active = ""
        try:
            path = os.path.join(self.lang_dir, LAYER_STATE_FILE)
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    for m, v in data.items():
                        if isinstance(v, dict):
                            self._state[m] = {
                                "disabled": bool(v.get("disabled", False)),
                                "color": v.get("color"),
                            }
                        elif isinstance(v, bool):
                            self._state[m] = {"disabled": v, "color": None}
                    self._active = data.get("active", "") if isinstance(data.get("active"), str) else ""
        except Exception as e:
            print(f"[自定义汉化] 加载修改记录状态失败: {e}")

    def _save_state(self):
        try:
            # 只持久化颜色与禁用状态; 隐藏/显示属于纯前端编辑显示辅助, 不记录
            data = {m: {"disabled": bool(s.get("disabled", False)),
                        "color": s.get("color")} for m, s in self._state.items()}
            data["active"] = self._active
            with open(os.path.join(self.lang_dir, LAYER_STATE_FILE), "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
        except Exception as e:
            print(f"[自定义汉化] 保存修改记录状态失败: {e}")

    def _layer_color(self, marker: str) -> str:
        return (self._state.get(marker) or {}).get("color") or _MAIN_LAYER_COLOR

    def _assign_layer_color(self, marker: str):
        """为图层分配独特颜色并持久化 (主层固定金色)"""
        st = self._state.setdefault(marker, {})
        if marker == "":
            st["color"] = _MAIN_LAYER_COLOR
            return
        if st.get("color"):
            return
        used = {self._state.get(m, {}).get("color") for m in self._state if m != marker}
        for c in _LAYER_COLORS:
            if c not in used:
                st["color"] = c
                return
        st["color"] = _LAYER_COLORS[len(self._layers) % len(_LAYER_COLORS)]

    def _ensure_layer_colors(self):
        """为没有颜色的图层分配调色板颜色并持久化"""
        for marker in self._layers:
            self._assign_layer_color(marker)
        self._save_state()

    def _load_layers(self):
        self._layers = {}
        self._layer_files = {}
        try:
            if not os.path.isdir(self.lang_dir):
                return
            for fname in sorted(os.listdir(self.lang_dir)):
                if not _is_layer_changes_file(fname):
                    continue
                m = CHANGES_PATTERN.match(fname)
                marker = m.group(1)[1:] if m.group(1) else ""
                path = os.path.join(self.lang_dir, fname)
                self._layer_files[marker] = path
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if isinstance(data, dict):
                        self._layers[marker] = data
                    else:
                        print(f"[自定义汉化] 跳过非对象图层文件: {fname}")
                        self._layers[marker] = {}
                except Exception as e:
                    print(f"[自定义汉化] 解析图层文件失败 {fname}: {e}")
                    self._layers[marker] = {}
            for m in list(self._state.keys()):
                if m not in self._layer_files:
                    del self._state[m]
            # 主层 (changes.json) 始终存在, 即使磁盘文件尚未创建
            self._layers.setdefault("", {})
            self._layer_files.setdefault("", self._layer_path(""))
        except Exception as e:
            print(f"[自定义汉化] 加载图层失败: {e}")

    def _layer_path(self, marker: str) -> str:
        fname = "changes.json" if marker == "" else f"changes_{marker}.json"
        return os.path.join(self.lang_dir, fname)

    def _persist_layer(self, marker: str):
        path = self._layer_path(marker)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        data = self._layers.get(marker, {})
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)

    def _persist_all_layers(self):
        for marker in self._layers:
            self._persist_layer(marker)

    def layer_order(self):
        """图层应用/显示顺序: changes.json(主) 在前, changes_*.json 按标记排序"""
        markers = [m for m in self._layers if m == ""] + \
                  sorted(m for m in self._layers if m != "")
        return markers

    def is_disabled(self, marker: str) -> bool:
        """禁用 = 不参与合并视图 (持久化); 隐藏/显示只是前端编辑显示辅助, 与数据无关"""
        return bool(self._state.get(marker, {}).get("disabled", False))

    def list_layers(self):
        result = []
        for marker in self.layer_order():
            name = "默认 (changes.json)" if marker == "" else f"changes_{marker}.json"
            count = 0
            for rel, patch in (self._layers.get(marker) or {}).items():
                if patch:
                    count += 1
            result.append({"marker": marker, "name": name,
                           "disabled": self.is_disabled(marker),
                           "active": marker == self._active,
                           "count": count,
                           "color": self._layer_color(marker)})
        return result

    def create_layer(self, marker: str):
        err = _safe_marker(marker)
        if err:
            return {"ok": False, "msg": err}
        if marker in self._layers:
            return {"ok": False, "msg": f"重名警告: changes_{marker}.json 已存在"}
        if os.path.exists(self._layer_path(marker)):
            return {"ok": False, "msg": f"重名警告: changes_{marker}.json 已存在"}
        self._layers[marker] = {}
        self._layer_files[marker] = self._layer_path(marker)
        self._assign_layer_color(marker)
        self._active = marker
        self._save_state()
        self._persist_layer(marker)
        return {"ok": True, "msg": f"已创建 changes_{marker}.json，并设为编辑目标"}

    def rename_layer(self, old_marker: str, new_marker: str):
        if old_marker == "":
            return {"ok": False, "msg": "默认 changes.json 不允许重命名"}
        err = _safe_marker(new_marker)
        if err:
            return {"ok": False, "msg": err}
        if old_marker not in self._layers:
            return {"ok": False, "msg": f"修改记录文件不存在: {old_marker}"}
        if new_marker in self._layers:
            return {"ok": False, "msg": f"重名警告: changes_{new_marker}.json 已存在"}
        if os.path.exists(self._layer_path(new_marker)):
            return {"ok": False, "msg": f"重名警告: changes_{new_marker}.json 已存在"}
        old_path = self._layer_path(old_marker)
        new_path = self._layer_path(new_marker)
        try:
            if os.path.exists(old_path):
                os.rename(old_path, new_path)
            self._layers[new_marker] = self._layers.pop(old_marker)
            self._layer_files.pop(old_marker, None)
            self._layer_files[new_marker] = new_path
            if self._state.get(old_marker):
                self._state[new_marker] = self._state.pop(old_marker)
            if self._active == old_marker:
                self._active = new_marker
            self._save_state()
            return {"ok": True, "msg": f"已重命名为 changes_{new_marker}.json"}
        except Exception as e:
            return {"ok": False, "msg": f"重命名失败: {e}"}

    def delete_layer(self, marker: str):
        if marker == "":
            return {"ok": False, "msg": "默认 changes.json 不允许删除"}
        if marker not in self._layers:
            return {"ok": False, "msg": f"修改记录文件不存在: {marker}"}
        try:
            path = self._layer_path(marker)
            if os.path.exists(path):
                os.remove(path)
            self._layers.pop(marker, None)
            self._layer_files.pop(marker, None)
            self._state.pop(marker, None)
            if self._active == marker:
                self._active = ""
            self._save_state()
            return {"ok": True, "msg": f"已删除 changes_{marker}.json"}
        except Exception as e:
            return {"ok": False, "msg": f"删除失败: {e}"}

    def set_layer_disabled(self, marker: str, disabled: bool):
        """禁用/启用修改记录文件: 禁用后其修改不参与合并视图 (持久化)"""
        if marker not in self._layers:
            return {"ok": False, "msg": f"修改记录不存在: {marker}"}
        s = self._state.setdefault(marker, {})
        s["disabled"] = bool(disabled)
        self._save_state()
        self._remerge_current()
        # 视图级操作: 重新对齐"已保存"基准, 避免误报未保存修改
        if self.modified_data is not None:
            self.saved_view = _deep_copy(self.modified_data)
        return {"ok": True, "disabled": bool(disabled)}

    def set_active_layer(self, marker: str):
        if marker not in self._layers:
            return {"ok": False, "msg": f"修改记录文件不存在: {marker}"}
        self._active = marker
        self._save_state()
        return {"ok": True}

    # ── 文件/合并视图 ──────────────────────────────────────

    def _merge_relative(self, relative: str, skip_layer: str = None):
        """把 (除 skip_layer 外的) 修改记录补丁依次应用到原始数据, 返回合并结果。
        始终包含全部记录文件 (禁用状态除外); 隐藏/显示只是前端显示辅助, 不影响合并"""
        result = _deep_copy(self.original_data)
        for marker in self.layer_order():
            if marker == skip_layer:
                continue
            if self.is_disabled(marker):
                continue
            patch = (self._layers.get(marker) or {}).get(relative)
            if patch:
                _recursive_apply(result, patch)
        return result

    def _changes_colors_for_relative(self, relative: str):
        """返回修改过该文件的记录文件颜色 (按应用顺序, 不含禁用记录)"""
        colors = []
        for marker in self.layer_order():
            if self.is_disabled(marker):
                continue
            patches = (self._layers or {}).get(marker) or {}
            if patches.get(relative):
                colors.append(self._layer_color(marker))
        return colors

    def _has_changes_for_relative(self, relative: str) -> bool:
        for marker, patches in (self._layers or {}).items():
            if patches.get(relative):
                return True
        return False

    def open_file(self, relative: str):
        relative = _normalize_path(relative)
        full = os.path.abspath(os.path.join(self.lang_dir, relative))
        lang_abs = os.path.abspath(self.lang_dir)
        if os.path.commonpath([full, lang_abs]) != lang_abs or not os.path.isfile(full):
            return {"ok": False, "msg": f"文件不存在: {relative}"}
        try:
            with open(full, "r", encoding="utf-8") as f:
                loaded = json.load(f)
        except Exception as e:
            return {"ok": False, "msg": f"解析失败: {e}"}
        if not isinstance(loaded, (dict, list)):
            return {"ok": False, "msg": "文件顶层必须是对象或数组"}
        self.original_data = loaded
        self.current_relative = relative
        self.modified_data = _deep_copy(loaded)
        for marker in self.layer_order():
            if self.is_disabled(marker):
                continue
            patch = (self._layers.get(marker) or {}).get(relative)
            if patch:
                _recursive_apply(self.modified_data, patch)
        # 已保存视图 (全部记录文件合并结果): 与当前视图的差异 = 未写入修改记录的临时修改
        self.saved_view = _deep_copy(self.modified_data)
        self._invalidate_flat()
        return {"ok": True, "relative": relative}

    def _remerge_current(self):
        if self.current_relative is None or self.original_data is None:
            return
        self.modified_data = self._merge_relative(self.current_relative)
        self._invalidate_flat()

    # ── 扁平化 (分页切片) ──────────────────────────────────

    def _invalidate_flat(self):
        self._flat_cache = None

    def _flatten(self):
        """扁平化 merged 视图 → 紧凑条目列表 (带过滤/折叠)"""
        entries = []
        collapsed = set(self._filters.get("collapsed") or [])
        keyword = (self._filters.get("keyword") or "").strip().lower()
        only_modified = bool(self._filters.get("only_modified"))
        show_hidden = bool(self._filters.get("show_hidden"))
        hidden_layers = set(self._filters.get("hidden_layers") or [])
        saved = self.saved_view

        def hidden_only_source(path):
            """该叶子路径的修改是否全部来自"前端隐藏"的记录文件"""
            if not hidden_layers:
                return False
            nav = path[5:] if path.startswith("root/") else path
            sources = []
            for marker in self.layer_order():
                if self.is_disabled(marker):
                    continue
                patch = (self._layers.get(marker) or {}).get(self.current_relative)
                if patch and _diff_has_path(patch, nav):
                    sources.append(marker)
            if not sources:
                return False
            return all(m in hidden_layers for m in sources)

        def walk(current, original, saved_v, title, depth, path, dict_key=None,
                 list_index=None, id_value=None, is_root=False):
            is_container = isinstance(current, (dict, list))
            if not is_container and dict_key is not None:
                if not show_hidden and dict_key in HIDDEN_KEYS:
                    return
            if not is_container:
                is_modified = (original != current)
                if only_modified and not is_modified:
                    return
                text_to_search = " ".join([
                    str(dict_key) if dict_key is not None else "",
                    str(current),
                    str(id_value) if id_value is not None else "",
                ]).lower()
                if keyword and keyword not in text_to_search:
                    return

            expanded = path not in collapsed
            entry = {
                "p": path,
                "t": title,
                "d": depth,
                "c": 1 if is_container else 0,
                "e": 1 if expanded else 0,
                "m": 1 if (not is_container and original != current) else 0,
                "u": 1 if (not is_container and saved_v != current) else 0,
                "i": 1 if (dict_key == "id") else 0,
            }
            if not is_container and entry["m"]:
                entry["h"] = 1 if hidden_only_source(path) else 0
            if not is_container and (entry["m"] or entry["u"]):
                entry["o"] = str(original)
            if is_container:
                entry["n"] = len(current)
                entries.append(entry)
                force_expand = bool(keyword) or only_modified
                if not force_expand and not expanded and not is_root:
                    return
                has_visible_child = False
                if isinstance(current, dict):
                    for k, v in current.items():
                        if not show_hidden and k in HIDDEN_KEYS and not isinstance(v, (dict, list)):
                            continue
                        orig_v = original.get(k) if isinstance(original, dict) else None
                        child_saved = saved_v.get(k) if isinstance(saved_v, dict) else None
                        before = len(entries)
                        walk(v, orig_v, child_saved, str(k), depth + 1, path + "/" + str(k),
                             dict_key=k, id_value=(v if k == "id" else None))
                        if len(entries) > before:
                            has_visible_child = True
                else:
                    for i, item in enumerate(current):
                        orig_item = original[i] if (isinstance(original, list)
                                                    and i < len(original)) else None
                        saved_item = saved_v[i] if (isinstance(saved_v, list)
                                                  and i < len(saved_v)) else None
                        sub_id = None
                        if isinstance(item, dict) and "id" in item:
                            sub_id = str(item["id"])
                        if isinstance(item, dict) and sub_id is not None:
                            sub_title = f"[{i + 1}] id = {sub_id}"
                        elif isinstance(item, dict):
                            keys = ", ".join(list(item.keys())[:4])
                            if len(item) > 4:
                                keys += "..."
                            sub_title = f"[{i + 1}] {{ {keys} }}"
                        elif isinstance(item, list):
                            sub_title = f"[{i + 1}] [ ... {len(item)} 项 ]"
                        else:
                            sub_title = f"[{i + 1}] {str(item)[:50]}"
                        before = len(entries)
                        walk(item, orig_item, saved_item, sub_title, depth + 1,
                             path + f"/[{i}]", list_index=i, id_value=sub_id)
                        if len(entries) > before:
                            has_visible_child = True
                if not has_visible_child and not is_root:
                    entries.pop()
            else:
                entry["v"] = str(current)
                entries.append(entry)

        if self.current_relative is not None and isinstance(self.modified_data, (dict, list)):
            walk(self.modified_data, self.original_data, saved, "JSON 内容", 0, "root", is_root=True)
        return entries

    def get_entries(self, start: int, count: int, filters: dict = None):
        if filters is not None:
            self._filters = {
                "keyword": (filters.get("keyword") or "").strip().lower(),
                "only_modified": bool(filters.get("only_modified")),
                "show_hidden": bool(filters.get("show_hidden")),
                "hidden_layers": filters.get("hidden_layers") or [],
                "collapsed": filters.get("collapsed") or [],
            }
            self._invalidate_flat()
        if self._flat_cache is None:
            self._flat_cache = self._flatten()
            self._flat_cache_total_modified = sum(1 for e in self._flat_cache if e.get("m"))
            self._flat_cache_total_unsaved = sum(1 for e in self._flat_cache if e.get("u"))
        total = len(self._flat_cache)
        start = max(0, int(start))
        count = max(1, int(count))
        return {
            "entries": self._flat_cache[start:start + count],
            "total": total,
            "modified_count": getattr(self, "_flat_cache_total_modified", 0),
            "unsaved_count": getattr(self, "_flat_cache_total_unsaved", 0),
        }

    def unsaved_count(self):
        """当前文件中未写入修改记录的临时修改数量"""
        if self.current_relative is None or self.saved_view is None:
            return {"count": 0}
        saved_filters = self._filters
        self._filters = {"keyword": "", "only_modified": False,
                         "show_hidden": False, "collapsed": []}
        try:
            self._flat_cache = None
            entries = self._flatten()
            return {"count": sum(1 for e in entries if e.get("u"))}
        finally:
            self._filters = saved_filters
            self._invalidate_flat()

    def all_container_paths(self):
        """当前过滤视图下所有容器条目的路径 (用于全部折叠)"""
        saved = self._filters
        self._filters = dict(saved, collapsed=[])
        try:
            self._flat_cache = None
            entries = self._flatten()
            return [e["p"] for e in entries if e.get("c")]
        finally:
            self._filters = saved
            self._invalidate_flat()

    # ── 编辑 ──────────────────────────────────────────────

    def set_value(self, path: str, raw):
        if self.current_relative is None or self.modified_data is None:
            return {"ok": False, "msg": "请先打开一个文件"}
        nav_path = path
        if nav_path == "root":
            nav_path = ""
        elif nav_path.startswith("root/"):
            nav_path = nav_path[len("root/"):]
        if not nav_path:
            return {"ok": False, "msg": "无效路径"}
        parts, ok = _resolve_parts(self.modified_data, nav_path)
        if not ok or not parts:
            return {"ok": False, "msg": "无法定位字段，请重新加载文件"}
        # 找到原值用于类型强制转换
        current = self.modified_data
        for part in parts:
            if part.startswith("[") and part.endswith("]"):
                current = current[int(part[1:-1])]
            else:
                current = current[part]
        try:
            value = _coerce_value(current, raw)
        except ValueError as e:
            return {"ok": False, "msg": str(e)}
        if not _navigate_and_set(self.modified_data, parts, value):
            return {"ok": False, "msg": "无法定位到要修改的字段，请尝试重新加载文件"}
        self._invalidate_flat()
        return {"ok": True, "path": path}

    def remove_field(self, path: str):
        """撤销该字段的全部修改: 删除所有图层中该字段的修改记录, 并恢复未写入图层的临时修改"""
        if self.current_relative is None or self.modified_data is None:
            return {"ok": False, "msg": "请先打开一个文件"}
        nav_path = path
        if nav_path == "root":
            nav_path = ""
        elif nav_path.startswith("root/"):
            nav_path = nav_path[len("root/"):]
        if not nav_path:
            return {"ok": False, "msg": "无效路径"}
        # 用原始数据解析路径段 (list 索引以原始数据为准, 应对先前删除导致的位移)
        parts, ok = _resolve_parts(self.original_data, nav_path)
        orig_ref = self.original_data
        if not ok or not parts:
            parts, ok = _resolve_parts(self.modified_data, nav_path)
            orig_ref = None
        if not ok or not parts:
            return {"ok": False, "msg": "无法定位该字段的路径，请尝试重新加载文件"}
        # 捕获未保存的临时修改 (层记录删除后 remerge 会重建视图, 需在合并前比较)
        had_unsaved = False
        cur, has_cur = _navigate_get(self.modified_data, parts)
        sv, has_sv = _navigate_get(self.saved_view, parts)
        had_unsaved = has_cur != has_sv or (has_cur and has_sv and cur != sv)
        removed = []
        for marker in self.layer_order():
            patches = self._layers.get(marker) or {}
            patch = patches.get(self.current_relative)
            if not patch:
                continue
            new_patch, hit = _diff_remove_aligned(patch, orig_ref, parts)
            if not hit:
                continue
            if new_patch is None or not new_patch:
                patches.pop(self.current_relative, None)
            else:
                patches[self.current_relative] = new_patch
            self._persist_layer(marker)
            removed.append(self._layer_name(marker))
        self._remerge_current()
        self.saved_view = _deep_copy(self.modified_data)
        if had_unsaved:
            removed.append("临时修改")
        if not removed:
            return {"ok": False, "msg": "该字段没有可撤销的修改"}
        self._invalidate_flat()
        return {"ok": True, "msg": f"已撤销字段 '{path}' 的修改 ({', '.join(removed)})"}

    def _compute_and_save(self, relative: str, marker: str):
        """把当前合并视图相对 (除 marker 外其他记录文件) 的净差异写入 marker 记录文件;
        基准包含全部记录文件, 避免覆盖其他记录文件的修改。
        归一化: 本次保存涉及的字段路径从其他记录文件移除 (同字段只保留目标文件)"""
        base = self._merge_relative(relative, skip_layer=marker)
        count = [0]
        diff, _ = _compute_diff(base, self.modified_data, count)
        patches = self._layers.setdefault(marker, {})
        if diff is None:
            patches.pop(relative, None)
        else:
            old = patches.get(relative)
            patches[relative] = _diff_union(old, diff) if old else diff
        self._persist_layer(marker)
        # 归一化: 其他记录文件中同字段的旧记录移除, 避免来源标识显示多个文件
        if diff is not None and self.original_data is not None:
            leaf_paths = _diff_leaf_paths(diff, self.original_data)
            for omarker in self.layer_order():
                if omarker == marker:
                    continue
                opatches = self._layers.get(omarker) or {}
                opatch = opatches.get(relative)
                if not opatch:
                    continue
                new_opatch = opatch
                for leaf in leaf_paths:
                    parts, ok = _resolve_parts(self.original_data, leaf)
                    if not ok or not parts:
                        continue
                    sub, hit = _diff_remove_aligned(new_opatch, self.original_data, parts)
                    if hit:
                        new_opatch = sub
                if new_opatch is not opatch:
                    if new_opatch is None or not new_opatch:
                        opatches.pop(relative, None)
                    else:
                        opatches[relative] = new_opatch
                    self._persist_layer(omarker)
        return count[0]

    def compute_and_save(self):
        if self.current_relative is None or self.modified_data is None:
            return {"ok": False, "msg": "请先打开一个文件"}
        n = self._compute_and_save(self.current_relative, self._active)
        self._remerge_current()
        self.saved_view = _deep_copy(self.modified_data)
        name = self._layer_name(self._active)
        return {"ok": True,
                "msg": f"已写入编辑目标 {name} ({n} 处修改)", "count": n}

    def save_all(self):
        if self.current_relative is None or self.modified_data is None:
            return {"ok": False, "msg": "请先打开一个文件"}
        n = self._compute_and_save(self.current_relative, self._active)
        self._remerge_current()
        self.saved_view = _deep_copy(self.modified_data)
        name = self._layer_name(self._active)
        return {"ok": True,
                "msg": f"已写入编辑目标 {name} ({n} 处修改)"}

    def reset_current(self):
        if self.current_relative is None:
            return {"ok": False, "msg": "请先打开一个文件"}
        for marker in self._layers:
            self._layers[marker].pop(self.current_relative, None)
        self._persist_all_layers()
        if self.original_data is not None:
            self.modified_data = _deep_copy(self.original_data)
            self.saved_view = _deep_copy(self.modified_data)
            self._invalidate_flat()
        return {"ok": True, "msg": "当前文件的修改已撤销"}

    def reset_all(self):
        for marker in self._layers:
            self._layers[marker] = {}
        self._persist_all_layers()
        if self.original_data is not None:
            self.modified_data = _deep_copy(self.original_data)
            self.saved_view = _deep_copy(self.modified_data)
            self._invalidate_flat()
        return {"ok": True, "msg": "所有修改记录已清空"}

    def _layer_name(self, marker: str) -> str:
        return "changes.json" if marker == "" else f"changes_{marker}.json"

    # ── 文件树 ────────────────────────────────────────────

    def get_tree(self):
        nodes = []

        def build(rel_dir):
            try:
                items = sorted(os.listdir(rel_dir), key=lambda x: x.lower())
            except OSError:
                return []
            result = []
            dirs = []
            files = []
            for item in items:
                if item.startswith("_"):
                    continue
                item_path = os.path.join(rel_dir, item)
                if os.path.isdir(item_path):
                    dirs.append(item)
                elif item.lower().endswith(".json") and not _is_changes_file(item):
                    files.append(item)
            for d in dirs:
                children = build(os.path.join(rel_dir, d))
                rel_path = _normalize_path(os.path.relpath(os.path.join(rel_dir, d), self.lang_dir))
                result.append({"name": d, "type": "dir", "path": rel_path, "children": children})
            for f in files:
                relative = _normalize_path(os.path.relpath(os.path.join(rel_dir, f), self.lang_dir))
                colors = self._changes_colors_for_relative(relative)
                result.append({"name": f, "type": "file", "path": relative,
                               "has_changes": len(colors) > 0,
                               "colors": colors})
            return result

        return {"root": "lang", "nodes": build(self.lang_dir)}

    def search_values(self, keyword: str):
        """全局搜索: 像文件内搜索那样逐文件处理 — 匹配每个 JSON 原文(键/id/值, 含未修改内容)
        以及全部修改记录文件中的值, 返回匹配的文件路径列表 (包含匹配, 不区分大小写)"""
        kw = (keyword or "").strip().lower()
        if not kw:
            return {"ok": True, "paths": []}
        matches = set()
        # 1) 各文件原文 (首次搜索时全量缓存, lang 源文件只读不变化)
        if self._search_cache is None:
            cache = {}
            for root, dirs, files in os.walk(self.lang_dir):
                dirs[:] = [d for d in dirs if not d.startswith("_")]
                for fn in files:
                    if not fn.lower().endswith(".json") or _is_changes_file(fn):
                        continue
                    rel = _normalize_path(os.path.relpath(os.path.join(root, fn), self.lang_dir))
                    try:
                        with open(os.path.join(root, fn), "r", encoding="utf-8") as f:
                            cache[rel] = f.read().lower()
                    except Exception:
                        continue
            self._search_cache = cache
        for rel, text in self._search_cache.items():
            if kw in text:
                matches.add(rel)
        # 2) 各修改记录文件中的值 (译文/新增内容可能不在原文中)
        for patches in (self._layers or {}).values():
            for relative, patch in patches.items():
                if relative not in matches and _patch_has_value(patch, kw):
                    matches.add(relative)
        return {"ok": True, "paths": sorted(matches)}

    def _replace_in_relative(self, relative, kw, replacement):
        """对单个文件执行值替换: 以全部修改记录合并结果为基准递归替换字符串值,
        净差异写入 active 层并归一化其他记录文件同字段。返回替换次数"""
        full = os.path.join(self.lang_dir, *relative.split("/"))
        try:
            with open(full, "r", encoding="utf-8") as f:
                original = json.load(f)
        except Exception:
            return 0
        if not isinstance(original, (dict, list)):
            return 0
        # 临时以该文件为当前文件, 复用修改记录合并/对齐逻辑
        self.original_data = original
        self.current_relative = relative
        base = self._merge_relative(relative)
        new_data = _deep_copy(base)
        count = [0]
        _replace_in_data(new_data, kw, replacement, count)
        if count[0] == 0:
            return 0
        diff_base = self._merge_relative(relative, skip_layer=self._active)
        diff, _ = _compute_diff(diff_base, new_data, [0])
        if diff is not None:
            marker = self._active
            patches = self._layers.setdefault(marker, {})
            old = patches.get(relative)
            patches[relative] = _diff_union(old, diff) if old else diff
            self._persist_layer(marker)
            leaf_paths = _diff_leaf_paths(diff, original)
            for omarker in self.layer_order():
                if omarker == marker:
                    continue
                opatches = self._layers.get(omarker) or {}
                opatch = opatches.get(relative)
                if not opatch:
                    continue
                new_opatch = opatch
                for leaf in leaf_paths:
                    parts, ok = _resolve_parts(original, leaf)
                    if not ok or not parts:
                        continue
                    sub, hit = _diff_remove_aligned(new_opatch, original, parts)
                    if hit:
                        new_opatch = sub
                if new_opatch is not opatch:
                    if new_opatch is None or not new_opatch:
                        opatches.pop(relative, None)
                    else:
                        opatches[relative] = new_opatch
                    self._persist_layer(omarker)
        return count[0]

    def _clear_current_state(self):
        """批量替换后不保留"当前文件"状态 (前端会重新加载)"""
        self.original_data = None
        self.current_relative = None
        self.modified_data = None
        self.saved_view = None
        self._invalidate_flat()

    def replace_values(self, keyword, replacement):
        """值替换: 只处理当前值搜索命中的文件。
        对每个匹配文件: 以全部修改记录合并结果为基准递归替换字符串值 (不区分大小写),
        净差异写入 active 层并归一化其他记录文件同字段 (与 _compute_and_save 同机制)"""
        kw = (keyword or "").strip().lower()
        if not kw:
            return {"ok": False, "msg": "请先进行值搜索"}
        if not isinstance(replacement, str):
            replacement = str(replacement or "")
        paths = self.search_values(kw)["paths"]
        if not paths:
            return {"ok": True, "msg": "没有匹配的文件", "count": 0, "files": 0}
        total = 0
        files = 0
        for relative in paths:
            n = self._replace_in_relative(relative, kw, replacement)
            if n > 0:
                total += n
                files += 1
        self._clear_current_state()
        return {"ok": True, "msg": f"已替换 {total} 处 (涉及 {files} 个文件)",
                "count": total, "files": files}

    def replace_current_values(self, keyword, replacement):
        """局部值替换: 只处理当前正在编辑的文件"""
        kw = (keyword or "").strip().lower()
        if not kw:
            return {"ok": False, "msg": "请输入待替换值"}
        if not isinstance(replacement, str):
            replacement = str(replacement or "")
        if self.current_relative is None:
            return {"ok": False, "msg": "请先打开一个文件"}
        relative = self.current_relative
        n = self._replace_in_relative(relative, kw, replacement)
        self._clear_current_state()
        return {"ok": True, "msg": f"已替换 {n} 处" if n else "当前文件中没有匹配的内容",
                "count": n}

    def get_raw_json(self):
        if self.modified_data is None:
            return {"ok": False, "msg": "请先打开一个文件"}
        return {"ok": True, "text": json.dumps(self.modified_data, ensure_ascii=False, indent=2)}

    def apply_raw_json(self, text):
        if self.current_relative is None:
            return {"ok": False, "msg": "请先打开一个文件"}
        try:
            data = json.loads(text)
        except Exception as e:
            return {"ok": False, "msg": f"JSON 解析失败: {e}"}
        if not isinstance(data, (dict, list)):
            return {"ok": False, "msg": "JSON 顶层必须是对象或数组"}
        self.modified_data = data
        self._invalidate_flat()
        return {"ok": True, "msg": "JSON 已应用"}

    def open_changes_dir(self):
        try:
            os.startfile(os.path.abspath(self.lang_dir))  # type: ignore
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "msg": f"打开目录失败: {e}"}


# ============================================================
# pywebview js_api
# ============================================================

class CustomTranslationApi:
    """pywebview js_api: 前端 ↔ TranslationEngine 桥接"""

    def __init__(self):
        self.engine = TranslationEngine()

    def assets(self):
        try:
            icon_path = os.path.join(_PROJECT_ROOT, "assets", "images", "icon", "icon.png")
            with open(icon_path, "rb") as f:
                return {"bg": "data:image/png;base64," + base64.b64encode(f.read()).decode("ascii")}
        except Exception:
            return {"bg": None}

    def get_tree(self):
        try:
            return self.engine.get_tree()
        except Exception as e:
            return {"root": "lang", "nodes": [], "error": str(e)}

    def search_values(self, keyword):
        try:
            return self.engine.search_values(keyword)
        except Exception as e:
            return {"ok": False, "paths": [], "error": str(e)}

    def replace_values(self, keyword, replacement):
        try:
            return self.engine.replace_values(keyword, replacement)
        except Exception as e:
            return {"ok": False, "msg": f"替换失败: {e}"}

    def replace_current_values(self, keyword, replacement):
        try:
            return self.engine.replace_current_values(keyword, replacement)
        except Exception as e:
            return {"ok": False, "msg": f"替换失败: {e}"}

    def list_layers(self):
        try:
            return {"layers": self.engine.list_layers()}
        except Exception as e:
            return {"layers": [], "error": str(e)}

    def create_layer(self, marker):
        try:
            return self.engine.create_layer(marker or "")
        except Exception as e:
            return {"ok": False, "msg": f"创建失败: {e}"}

    def rename_layer(self, old_marker, new_marker):
        try:
            return self.engine.rename_layer(old_marker or "", new_marker or "")
        except Exception as e:
            return {"ok": False, "msg": f"重命名失败: {e}"}

    def delete_layer(self, marker):
        try:
            return self.engine.delete_layer(marker or "")
        except Exception as e:
            return {"ok": False, "msg": f"删除失败: {e}"}

    def set_layer_disabled(self, marker, disabled):
        try:
            return self.engine.set_layer_disabled(marker or "", bool(disabled))
        except Exception as e:
            return {"ok": False, "msg": str(e)}

    def set_active_layer(self, marker):
        try:
            return self.engine.set_active_layer(marker or "")
        except Exception as e:
            return {"ok": False, "msg": str(e)}

    def open_file(self, relative):
        try:
            return self.engine.open_file(relative or "")
        except Exception as e:
            return {"ok": False, "msg": f"打开失败: {e}"}

    def get_entries(self, start, count, filters=None):
        try:
            return self.engine.get_entries(start or 0, count or 200, filters)
        except Exception as e:
            return {"entries": [], "total": 0, "modified_count": 0, "error": str(e)}

    def all_container_paths(self):
        try:
            return {"paths": self.engine.all_container_paths()}
        except Exception as e:
            return {"paths": [], "error": str(e)}

    def set_value(self, path, raw):
        try:
            return self.engine.set_value(path or "", raw)
        except Exception as e:
            return {"ok": False, "msg": str(e)}

    def remove_field(self, path):
        try:
            return self.engine.remove_field(path or "")
        except Exception as e:
            return {"ok": False, "msg": str(e)}

    def compute_and_save(self):
        try:
            return self.engine.compute_and_save()
        except Exception as e:
            return {"ok": False, "msg": f"保存失败: {e}"}

    def save_all(self):
        try:
            return self.engine.save_all()
        except Exception as e:
            return {"ok": False, "msg": f"保存失败: {e}"}

    def reset_current(self):
        try:
            return self.engine.reset_current()
        except Exception as e:
            return {"ok": False, "msg": str(e)}

    def reset_all(self):
        try:
            return self.engine.reset_all()
        except Exception as e:
            return {"ok": False, "msg": str(e)}

    def unsaved_count(self):
        try:
            return self.engine.unsaved_count()
        except Exception as e:
            return {"count": 0, "error": str(e)}

    def get_raw_json(self):
        try:
            return self.engine.get_raw_json()
        except Exception as e:
            return {"ok": False, "msg": str(e)}

    def apply_raw_json(self, text):
        try:
            return self.engine.apply_raw_json(text or "")
        except Exception as e:
            return {"ok": False, "msg": str(e)}

    def open_changes_dir(self):
        try:
            return self.engine.open_changes_dir()
        except Exception as e:
            return {"ok": False, "msg": str(e)}


# ============================================================
# 窗口启动
# ============================================================

def _center_xy(width, height):
    try:
        import ctypes
        u = ctypes.windll.user32
        screen_w = u.GetSystemMetrics(0)
        screen_h = u.GetSystemMetrics(1)
        return max((screen_w - width) // 2, 0), max((screen_h - height) // 2, 0)
    except Exception:
        return None, None


def _error_dialog(title, text):
    import ctypes
    try:
        ctypes.windll.user32.MessageBoxW(None, text, title, 0x10)
    except Exception:
        pass


def _write_error_log(exc_info):
    try:
        with open(os.path.join(_PROJECT_ROOT, "custom_translation_window_error.log"),
                  "a", encoding="utf-8") as f:
            f.write(exc_info)
    except Exception:
        pass


def run_custom_translation_window(debug: bool = False):
    """子进程入口: 直接运行自定义汉化 pywebview 窗口"""
    try:
        import webview
    except BaseException as e:
        import traceback
        _write_error_log("import webview failed:\n" + traceback.format_exc())
        _error_dialog("自定义汉化", f"未安装 pywebview 依赖:\n{type(e).__name__}: {e}")
        raise SystemExit(1)

    if not os.path.exists(HTML_PATH):
        _error_dialog("自定义汉化", f"找不到页面文件:\n{HTML_PATH}")
        raise SystemExit(1)

    width, height = 1280, 800
    window_kwargs = dict(
        title="自定义汉化工具",
        url=HTML_PATH,
        js_api=CustomTranslationApi(),
        width=width,
        height=height,
        min_size=(960, 640),
        background_color="#060f22",
    )
    x, y = _center_xy(width, height)
    if x is not None and y is not None:
        window_kwargs["x"] = x
        window_kwargs["y"] = y

    try:
        webview.create_window(**window_kwargs)
        webview.start(debug=debug)
    except BaseException as e:
        import traceback
        _write_error_log(traceback.format_exc())
        _error_dialog("自定义汉化", f"无法启动窗口:\n{type(e).__name__}: {e}")
        raise SystemExit(1)


def open_custom_translation_window(root=None):
    """非阻塞拉起自定义汉化窗口 (与扩展工具同一模式, 立即返回)

    Returns:
        True: 窗口成功拉起; None: 拉起失败
    """
    if getattr(sys, "frozen", False):
        cmd = [os.path.abspath(sys.executable), "--custom-translation-window"]
    else:
        script = os.path.join(_PROJECT_ROOT, "functions", "pages", "tools",
                              "custom_translation_window.py")
        if not os.path.exists(script):
            print("[自定义汉化] 找不到窗口脚本, 已跳过")
            return None
        pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
        if not os.path.exists(pythonw):
            pythonw = sys.executable
        cmd = [pythonw, script]

    try:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.Popen(cmd, cwd=_PROJECT_ROOT, creationflags=flags)
    except Exception as e:
        print(f"[自定义汉化] 无法启动窗口进程: {e}")
        return None
    return True


if __name__ == "__main__":
    run_custom_translation_window(debug="--debug" in sys.argv)
