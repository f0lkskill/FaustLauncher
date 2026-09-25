"""游戏启动流水线 — 将启动前的准备工作拆分为清晰的步骤。"""

import os
import sys
import hashlib
import json
import shutil
import time
import ctypes
import traceback
import tkinter.messagebox as messagebox

from functions.base.settings_manager import get_settings_manager
import functions.web_update.translation_source as translation_source_lib
from functions.extension.addon.addon_utils import AddonManager
from functions.base.common.json_io import read_json, write_json


def safe_merge_dirs(src, dst, overwrite=True):
    """安全地合并目录（支持覆盖）"""
    try:
        os.makedirs(dst, exist_ok=True)
    except Exception as e:
        print(f"[调试] safe_merge_dirs: os.makedirs({dst!r}) 失败: {e}")
        traceback.print_exc()
        raise
    for item in os.listdir(src):
        src_item = os.path.join(src, item)
        dst_item = os.path.join(dst, item)
        
        if os.path.isdir(src_item):
            safe_merge_dirs(src_item, dst_item, overwrite)
        else:
            try:
                if os.path.exists(dst_item) and overwrite:
                    os.remove(dst_item)
                shutil.copy2(src_item, dst_item)
            except Exception as e:
                print(f"[调试] safe_merge_dirs: 复制文件失败 src={src_item!r} dst={dst_item!r}: {e}")
                traceback.print_exc()
                raise


def apply_changes_to_data(original_data, changes):
    """递归应用修改到数据 — 适配包含 id 的修改记录结构"""
    if isinstance(changes, dict) and 'dataList' in changes:
        changes = changes['dataList']

    if isinstance(original_data, dict) and 'dataList' in original_data and isinstance(changes, list):
        result = original_data.copy()
        result['dataList'] = apply_changes_to_data(original_data['dataList'], changes)
        return result

    if isinstance(original_data, dict) and isinstance(changes, dict):
        result = {}
        for key, value in original_data.items():
            if key in changes:
                if isinstance(value, (dict, list)) and isinstance(changes[key], (dict, list)):
                    result[key] = apply_changes_to_data(value, changes[key])
                else:
                    result[key] = changes[key]
            else:
                result[key] = value
        return result

    elif isinstance(original_data, list) and isinstance(changes, list):
        result = []
        id_changes = {}
        for change_item in changes:
            if isinstance(change_item, dict) and 'id' in change_item and 'changes' in change_item:
                change_id = change_item['id']
                id_changes[change_id] = change_item['changes']
                id_changes[str(change_id)] = change_item['changes']

        if id_changes:
            for item in original_data:
                if isinstance(item, dict) and 'id' in item:
                    item_id = item['id']
                    change_data = id_changes.get(item_id, id_changes.get(str(item_id)))
                    if change_data is not None:
                        result.append(apply_changes_to_data(item, change_data))
                    else:
                        result.append(item)
                else:
                    result.append(item)
            return result

        for i, item in enumerate(original_data):
            if i < len(changes):
                if isinstance(item, (dict, list)) and isinstance(changes[i], (dict, list)):
                    result.append(apply_changes_to_data(item, changes[i]))
                else:
                    result.append(changes[i])
            else:
                result.append(item)
        return result
    else:
        return original_data


# “残留子进程”判定：比这个秒数还年轻的一律不杀（防重复启动互掐）
STALE_HOOK_MIN_AGE = 30.0


def _is_own_interpreter_image(image: str) -> bool:
    """远端进程映像是不是“我们自己这类解释器”。

    优先用成就侧的实现（``functions.achievement.hook._is_self_image``，它会额外把
    ``sys._base_executable`` 与 ``GetModuleFileNameW(NULL)`` 算进来），
    拿不到就退回本文件里的一份最小实现（venv 的 python.exe 可能是 py.exe launcher，
    真解释器是它拉起的子进程，光比 ``sys.executable`` 会永远不相等）。
    """
    try:
        from functions.achievement.hook import _is_self_image
        return bool(_is_self_image(image))
    except Exception:  # noqa: BLE001
        pass
    if not image:
        return False
    cand = {sys.executable, getattr(sys, "_base_executable", "") or ""}
    try:
        from ctypes import wintypes
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.GetModuleFileNameW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p,
                                         wintypes.DWORD]
        buf = ctypes.create_unicode_buffer(1024)
        if k.GetModuleFileNameW(None, buf, wintypes.DWORD(len(buf))):
            cand.add(buf.value)
    except Exception:  # noqa: BLE001
        pass
    want = {os.path.normcase(os.path.abspath(p)) for p in cand if p}
    return os.path.normcase(os.path.abspath(image)) in want


def _process_age_seconds(kernel32, handle) -> float | None:
    """进程已存活秒数（拿不到返回 None）。"""
    try:
        from ctypes import wintypes
        kernel32.GetProcessTimes.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.FILETIME),
                                             ctypes.POINTER(wintypes.FILETIME),
                                             ctypes.POINTER(wintypes.FILETIME),
                                             ctypes.POINTER(wintypes.FILETIME)]
        created = wintypes.FILETIME()
        dummy = (wintypes.FILETIME(), wintypes.FILETIME(), wintypes.FILETIME())
        if not kernel32.GetProcessTimes(handle, ctypes.byref(created),
                                        ctypes.byref(dummy[0]), ctypes.byref(dummy[1]),
                                        ctypes.byref(dummy[2])):
            return None
        ticks = (int(created.dwHighDateTime) << 32) | int(created.dwLowDateTime)
        if not ticks:
            return None
        return max(0.0, time.time() - (ticks / 1e7 - 11644473600))
    except Exception:  # noqa: BLE001
        return None


class GameLauncher:
    """游戏启动流水线。

    用法:
        launcher = GameLauncher(addon_manager)
        launcher.launch()
    """

    def __init__(self, addon_manager:AddonManager=None, progress=None): # type: ignore
        """初始化游戏启动流水线。

        Args:
            addon_manager (AddonManager, optional): 插件管理器，默认是 None。
            progress (_type_, optional): 进度回调函数, 用于推送启动进度到前端。 默认是 None.
        """

        self._settings = get_settings_manager()
        self._addon_manager = addon_manager
        self._progress = progress or (lambda text, icon=None: None)
        self._game_path: str = self._settings.get_setting('game_path') or ''

        # 同步插件自定义汉化包平台方
        if self._addon_manager:
            translation_source_lib.set_extend_translate_source(self._addon_manager.extend_translate_source)
            print(f"已同步插件自定义汉化: {[x.name for x in translation_source_lib.extend_translate_source]}")
        # 获取语言目录
        self._lang_dir = translation_source_lib.get_translation_dir()

    # ── 流水线入口 ──────────────────────────────────────────────

    def launch(self):
        """按顺序执行启动流水线的所有步骤 (每步进度经 progress 回调推送到前端)。"""
        print("========== 开始启动游戏流水线 ==========")

        steps = [
            ("复制汉化文件",      "🚀", self._prepare_translation),
            ("应用拓展汉化修改",   "🚀", self._apply_changes),
            ("应用美化功能",      "🚀", self._apply_cosmetic_features),
            ("复制字体文件",      "🚀", self._copy_fonts),
            ("创建零协会配置",     "🚀", self._create_zeroasso_config),
            ("设置用户名称",      "🚀", self._set_user_name),
            ("触发插件启动事件",   "🚀", self._fire_addon_events),
            ("启动游戏进程",      "🚀", self._launch_game_process),
        ]

        for name, icon, step in steps:
            self._progress(f"正在{name}...", icon)
            print(f"[{name}] 开始...")
            try:
                step()
                print(f"[{name}] 完成")
            except Exception as e:
                print(f"[{name}] 失败: {e}")
                traceback.print_exc()
                # 汉化/字体失败不阻断启动游戏 (如汉化包未下载), 仅提示后继续后续步骤
                if name in ("复制汉化文件", "复制字体文件"):
                    try:
                        messagebox.showerror("错误", f"{name}时出错: {str(e)}\n\n已跳过该步骤, 继续启动游戏")
                    except Exception:
                        pass
                # 非关键步骤失败不阻断启动

        print("========== 启动流水线结束 ==========\n")

    # ── 步骤实现 ────────────────────────────────────────────────

    def _prepare_translation(self):
        """复制当前平台的汉化目录到游戏目录。"""
        # 先应用有色汉化气泡文件
        from functions.fancy.bubble_transfer import main as transfer_bubble
        transfer_bubble(config_path=self._lang_dir)

        target = translation_source_lib.get_game_lang_dir(self._game_path)
        print(f"[调试] _prepare_translation: 游戏路径={self._game_path!r}")
        print(f"[调试] _prepare_translation: 源={os.path.abspath(self._lang_dir)!r} 存在={os.path.exists(self._lang_dir)} 是目录={os.path.isdir(self._lang_dir)}")
        print(f"[调试] _prepare_translation: 目标={target!r} 存在={os.path.exists(target)} 是目录={os.path.isdir(target)}")
        if not os.path.isdir(self._lang_dir):
            # 汉化包未下载 (如首次启动/刚切换平台): 跳过该步骤, 不阻断后续字体/启动
            print(f"[汉化] 汉化包目录不存在: {self._lang_dir} (请先在下载中心下载当前平台汉化包), 跳过汉化文件复制")
            return
        if os.path.exists(target):
            if os.path.isdir(target):
                shutil.rmtree(target, ignore_errors=True)
            else:
                print(f"[调试] _prepare_translation: 目标路径不是目录，正在删除文件")
                os.remove(target)
        print(f"[调试] _prepare_translation: 开始 copytree {self._lang_dir!r} -> {target!r}")
        shutil.copytree(self._lang_dir, target, dirs_exist_ok=True)

    @staticmethod
    def _list_changes_files(dir_path):
        """列出目录下所有图层数据文件 (changes.json + changes_标记.json), 主文件在前;
        changes_layers.json 是图层状态文件, 不算图层数据"""
        from functions.pages.tools.custom_translation_window import _is_layer_changes_file
        if not os.path.isdir(dir_path):
            return []
        files = [f for f in os.listdir(dir_path) if _is_layer_changes_file(f)]
        files.sort(key=lambda f: (0, f) if f.lower() == "changes.json" else (1, f.lower()))
        return files

    @staticmethod
    def _lang_folder_candidates(lang_root, preferred=None):
        """游戏 Lang 目录下所有语言文件夹 (当前平台目录优先)。

        插件/Mod 的 changes.json 路径首段写死的是某个汉化文件夹名 (如 LLC_zh-CN),
        但不同汉化平台 (零协会 LLC_zh-CN / OurPlay OurPlayHanHua / 插件自定义汉化)
        目录名不同, 写死会直接导致补丁找不到文件而失效; 这里把所有存在的文件夹都作为
        候选, 让补丁默认应用到全部文件夹。
        """
        try:
            dirs = [d for d in os.listdir(lang_root)
                    if os.path.isdir(os.path.join(lang_root, d))]
        except Exception:
            dirs = []
        ordered = []
        try:
            current = translation_source_lib.get_translation_dir_name()
        except Exception:
            current = ""
        for name in (preferred, current):
            if name and name in dirs and name not in ordered:
                ordered.append(name)
        ordered.extend(sorted(d for d in dirs if d not in ordered))
        return ordered

    def _resolve_change_targets(self, lang_root, relative_path):
        """把 changes.json 中的相对路径解析为游戏 Lang 下真实存在的文件列表。

        - 带文件夹前缀 (如 "LLC_zh-CN/Announcer.json"): 首段视为"汉化文件夹"占位符,
          默认应用到 Lang 下所有含该文件的文件夹 (全文件夹, 不再限定 LLC_zh-CN);
        - 不带文件夹前缀 (如 "Announcer.json"): 仍按 Lang 根目录解析 (向后兼容)。
        """
        rel = str(relative_path or "").replace("\\", "/").strip("/")
        parts = [p for p in rel.split("/") if p]
        if not parts:
            return []
        raw = os.path.join(lang_root, *parts)
        if len(parts) == 1:
            return [raw] if os.path.isfile(raw) else []
        rest = parts[1:]
        targets = []
        seen = set()
        for folder in self._lang_folder_candidates(lang_root, preferred=parts[0]):
            target = os.path.join(lang_root, folder, *rest)
            key = os.path.normcase(os.path.abspath(target))
            if key in seen:
                continue
            seen.add(key)
            if os.path.isfile(target):
                targets.append(target)
        if not targets and os.path.isfile(raw):
            targets.append(raw)
        return targets

    # ── changes*.json 文本补丁 (插件 / Mod / 自定义翻译) ──────────────
    CHANGES_BACKUP_ROOT = os.path.join('cache', 'changes_backup')

    @staticmethod
    def _resource_enabled(kind: str, info: dict) -> bool:
        """资源是否启用 —— 与资源管理页 (app_web.get_mods_data) 完全同一判定:

        插件 (addon) 的 settings.enable 默认 True, 目录 Mod 默认 False;
        判定不出来时按"禁用"处理 (宁可不动文本, 也不要让被禁用的资源生效)。
        """
        default = True if kind == 'addon' else False
        try:
            return bool((info or {}).get('settings', {}).get('enable', default))
        except Exception:
            return bool(default)

    @classmethod
    def _changes_backup_dir(cls, kind: str, res_dir: str) -> str:
        return os.path.join(cls.CHANGES_BACKUP_ROOT, kind, res_dir)

    @staticmethod
    def _load_backup_index(backup_dir: str) -> dict:
        """快照索引: {changes 文件名: {游戏文件相对路径: 快照文件名}}"""
        if not backup_dir:
            return {}
        p = os.path.join(backup_dir, 'index.json')
        if not os.path.isfile(p):
            return {}
        try:
            data = read_json(p)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    @staticmethod
    def _save_backup_index(backup_dir: str, index: dict) -> None:
        try:
            os.makedirs(backup_dir, exist_ok=True)
            write_json(os.path.join(backup_dir, 'index.json'), index, indent=2)
        except Exception as e:
            print(f"  警告: 写入文本补丁快照索引失败: {e}")

    @staticmethod
    def _rel_target(lang_root: str, game_file: str) -> str:
        try:
            return os.path.relpath(game_file, lang_root).replace('\\', '/')
        except Exception:
            return os.path.basename(game_file)

    @classmethod
    def _snapshot_before_patch(cls, backup_dir, index, changes_file, lang_root, game_file):
        """第一次用这个 changes 文件改这个游戏文件之前, 存一份原始内容 (禁用后用它还原)"""
        if not backup_dir:
            return False
        rel = cls._rel_target(lang_root, game_file)
        slot = index.setdefault(changes_file, {})
        if rel in slot:
            return False
        name = hashlib.md5(rel.encode('utf-8')).hexdigest()[:16] + '.json'
        try:
            os.makedirs(backup_dir, exist_ok=True)
            shutil.copy2(game_file, os.path.join(backup_dir, name))
            slot[rel] = name
            return True
        except Exception as e:
            print(f"  警告: 备份 {game_file} 失败 (禁用后可能残留文本): {e}")
            return False

    def _restore_backups(self, kind: str, res_dir: str, lang_root: str,
                         only_changes_files=None, skip_folder=None) -> int:
        """按快照还原某个资源 (或其某个图层) 之前改过的游戏文件, 返回还原个数。

        only_changes_files: 只还原这几个 changes 文件 (图层被禁用时用);
        skip_folder: 跳过这个汉化文件夹下的文件 (当前平台文件夹每次启动都会被汉化包重建,
                     快照可能比汉化包旧, 拿旧快照回写等于把新汉化顶掉)。
        """
        backup_dir = self._changes_backup_dir(kind, res_dir)
        index = self._load_backup_index(backup_dir)
        if not index:
            return 0
        restored = 0
        for cf, slot in index.items():
            if only_changes_files is not None and cf not in only_changes_files:
                continue
            for rel, name in (slot or {}).items():
                top = str(rel).split('/')[0]
                if skip_folder and top == skip_folder:
                    continue
                src = os.path.join(backup_dir, str(name))
                if not os.path.isfile(src):
                    continue
                target = os.path.join(lang_root, *str(rel).split('/'))
                if not os.path.isfile(target):
                    continue
                try:
                    # 时间戳护栏: 目标文件比快照新 -> 后来被别的插件/汉化包重写过, 别拿旧的盖新的
                    if os.path.getmtime(target) > os.path.getmtime(src) + 2:
                        print(f"  提示: {rel} 比快照新 (已被其他来源改写), 保持现状不还原")
                        continue
                    shutil.copy2(src, target)
                    restored += 1
                except Exception as e:
                    print(f"  警告: 还原 {target} 失败: {e}")
        return restored

    @classmethod
    def _prune_changes_backups(cls, alive) -> None:
        """清掉已删除资源的快照目录 (alive = {(kind, 资源目录名)})"""
        root = cls.CHANGES_BACKUP_ROOT
        if not os.path.isdir(root):
            return
        for kind in os.listdir(root):
            kdir = os.path.join(root, kind)
            if not os.path.isdir(kdir):
                continue
            for res in os.listdir(kdir):
                if (kind, res) not in alive:
                    shutil.rmtree(os.path.join(kdir, res), ignore_errors=True)

    def _apply_changes(self):
        """应用所有**已启用**资源的 changes*.json 文本补丁到游戏语言文件。

        规则 (2026-09-25 修订):
          · **先看资源是否被禁用** (与资源管理页同一判定): 禁用的资源不应用, 并且把它上次
            应用过的文本按快照还原回原始内容 —— 否则 LCTA / LCTA_AU 这类不由启动器接管的
            Lang 文件夹里的旧文本会一直留着, 表现为"禁用后文本还生效";
          · 图层: changes.json + changes_标记.json (按名称排序, 后应用者覆盖),
            changes_layers.json 里 disabled=true 的图层同样跳过并还原;
          · 顺序: 先还原 (禁用/停用图层) -> 再应用 (启用), 保证启用的最后覆盖;
          · 快照在 cache/changes_backup/<kind>/<目录>/(index.json + 原始文件)。
        """
        from functions.extension.mod.mod_utils import ModManager
        from functions.pages.tools.custom_translation_window import CHANGES_PATTERN

        lang_data_dir = os.path.join(self._game_path, 'LimbusCompany_Data', 'Lang')
        mods_off = not self._settings.get_setting('enable_mods')
        # 当前平台文件夹: 每次启动都被汉化包整目录重建, 不用 (也不该) 拿旧快照还原
        try:
            cur_folder = os.path.basename(translation_source_lib.get_game_lang_dir(self._game_path))
        except Exception:
            cur_folder = None

        # ---- 1) 扫描资源: 分成"要应用"和"要还原" ----
        apply_jobs, revert_jobs = [], []
        alive = set()
        for kind in ('addons', 'mods'):
            if not os.path.isdir(kind):
                continue
            is_mods = (kind == 'mods')
            if is_mods and mods_off:
                print("[文本补丁] 设置里关闭了 Mod 功能: 不应用 mods 的文本补丁")
            for res_dir in sorted(os.listdir(kind)):
                info_path = os.path.join(kind, res_dir, f"{kind[:-1]}_info.json")
                if not os.path.isfile(info_path):
                    continue
                alive.add((kind, res_dir))
                try:
                    info = read_json(info_path)
                except Exception as e:
                    print(f"  警告: 解析 {info_path} 失败 ({e}), 按禁用处理")
                    info = {}
                enabled = self._resource_enabled(kind[:-1], info) and not (is_mods and mods_off)
                if not enabled:
                    print(f"[文本补丁] {kind}/{res_dir} 已禁用: 不应用它的文本补丁")
                (apply_jobs if enabled else revert_jobs).append((kind, res_dir))

        # ---- 2) 先还原被禁用资源的改动 ----
        for kind, res_dir in revert_jobs:
            res_path = os.path.join(kind, res_dir)
            has_snapshot = bool(self._load_backup_index(self._changes_backup_dir(kind, res_dir)))
            n = self._restore_backups(kind, res_dir, lang_data_dir, skip_folder=cur_folder)
            if n:
                print(f"[文本补丁] {kind}/{res_dir} 已禁用 -> 还原它之前改过的 {n} 个文本文件")
            elif not has_snapshot and self._list_changes_files(res_path):
                # 修复前就应用过 (没有快照可还原): 明确告诉用户残留怎么清
                print(f"[文本补丁] 提示: {kind}/{res_dir} 已禁用且没有改动快照, 无法自动还原; "
                      f"若游戏里还能看到它的文本 (早期应用留下的), "
                      f"可在资源管理里对相关汉化插件点一次「重装」恢复原始文本")

        # ---- 3) 再应用已启用资源 (lang 的自定义翻译补丁放最后) ----
        dirs = [os.path.join(kind, res_dir) for kind, res_dir in apply_jobs]
        dirs.append('lang')
        print(f"[调试] _apply_changes: 需要处理的目录: {dirs}")

        # 载入替换文件
        ModManager.load_language('', 'lang')

        for dir_path in dirs:
            # 读取记录文件禁用状态 (不存在 = 全部参与合并)
            disabled_layers = set()
            layer_state_file = os.path.join(dir_path, 'changes_layers.json')
            if os.path.exists(layer_state_file):
                try:
                    st = read_json(layer_state_file)
                    for marker, v in (st.items() if isinstance(st, dict) else []):
                        if isinstance(v, dict) and v.get('disabled', False):
                            disabled_layers.add(marker)
                except Exception as e:
                    print(f"  警告: 解析 {layer_state_file} 失败: {e}")

            changes_files = self._list_changes_files(dir_path)
            if not changes_files:
                continue

            src_label = '插件' if dir_path.startswith('addons') else ('Mod' if dir_path.startswith('mods') else '汉化')
            src_name = os.path.basename(dir_path)
            kind = ('addons' if dir_path.startswith('addons')
                    else ('mods' if dir_path.startswith('mods') else 'lang'))
            backup_dir = None if kind == 'lang' else self._changes_backup_dir(kind, src_name)
            index = self._load_backup_index(backup_dir) # type: ignore
            index_dirty = False

            # 图层被禁用: 把那个图层之前改过的文件还原回去 (资源本身是启用的)
            if kind != 'lang' and disabled_layers:
                for changes_file in changes_files:
                    m = CHANGES_PATTERN.match(changes_file)
                    marker = m.group(1)[1:] if m and m.group(1) else ""
                    if marker in disabled_layers:
                        n = self._restore_backups(kind, src_name, lang_data_dir,
                                                  only_changes_files={changes_file},
                                                  skip_folder=cur_folder)
                        if n:
                            print(f"[文本补丁] {dir_path} 的图层 {changes_file} 已禁用 -> 还原 {n} 个文本文件")

            # 逐个来源显示: 正在应用 插件/Mod xxx 的文本补丁
            self._progress(f"正在应用 {src_label} {src_name} 的文本补丁...", "🚀")

            for changes_file in changes_files:
                m = CHANGES_PATTERN.match(changes_file)
                marker = m.group(1)[1:] if m and m.group(1) else ""
                if marker in disabled_layers:
                    print(f"  跳过禁用记录文件: {changes_file}")
                    continue

                file_path = os.path.join(dir_path, changes_file)
                try:
                    changes_data = read_json(file_path)
                except Exception as e:
                    print(f"  警告: 无法解析 {file_path}: {e}")
                    continue
                if not changes_data:
                    continue
                if not isinstance(changes_data, dict):
                    print(f"  警告: {file_path} 顶层必须是 {{\"相对路径\": 修改内容}} 对象, 实际是 {type(changes_data).__name__}, 已跳过")
                    continue
                for relative_path, file_changes in changes_data.items():
                    # 首段文件夹名视为占位符: 默认应用到 Lang 下所有文件夹 (不再限定 LLC_zh-CN)
                    targets = self._resolve_change_targets(lang_data_dir, relative_path)
                    if not targets:
                        print(f"  警告: 游戏目录中未找到 {relative_path} (已尝试 Lang 下全部文件夹)")
                        continue
                    if len(targets) > 1:
                        print(f"  应用补丁 {relative_path} -> {len(targets)} 个文件夹")
                    for game_file in targets:
                        try:
                            # 改之前先存一份原始内容 (资源被禁用时用它还原)
                            if self._snapshot_before_patch(backup_dir, index, changes_file,
                                                           lang_data_dir, game_file):
                                index_dirty = True
                            original = read_json(game_file)
                            modified = apply_changes_to_data(original, file_changes)
                            write_json(game_file, modified, indent=4)
                        except Exception as e:
                            print(f"  警告: 应用补丁 {game_file} 失败: {e}")

            if index_dirty:
                self._save_backup_index(backup_dir, index) # type: ignore

        # ---- 4) 已删除资源的快照清掉 ----
        self._prune_changes_backups(alive)

    def _apply_cosmetic_features(self):
        """应用气泡渐变、EGO 样式、技能描述、提示替换、技能渐变色 (逐项推送进度, 单项失败不中断)"""
        lang_path = translation_source_lib.get_game_lang_dir(self._game_path)
        lang_root = os.path.join(self._game_path, 'LimbusCompany_Data', 'Lang')

        # 气泡文本颜色开关 (enable_bubble_color, 默认开启):
        #   开启 -> 原版功能: 启动流程不对气泡文件做额外处理, 正常应用气泡文本渐变色;
        #   关闭 -> 对所有转移后 (游戏目录) 的气泡文件去除 <color=#xxxxxx> 颜色标签, 气泡文本恢复默认颜色
        _bubble_color = self._settings.get_setting('enable_bubble_color')
        if _bubble_color is False:
            try:
                print(f"[美化] 开启去除气泡文本颜色标签...")
                self._progress("正在去除气泡文本颜色标签...", "🚀")
                from functions.fancy.dialog_colorful import main_remove_color as remove_bubble_color
                remove_bubble_color()
            except Exception as e:
                print(f"[美化] 去除气泡文本颜色跳过: {e}")
        elif self._settings.get_setting('enable_text_gradient'):
            try:
                print(f"[美化] 开启应用对话文本渐变色...")
                self._progress("正在应用对话文本渐变色...", "🚀")
                from functions.fancy.dialog_colorful import main as handle_colorful
                handle_colorful()
            except Exception as e:
                print(f"[美化] 对话文本渐变色跳过: {e}")
        if self._settings.get_setting('enable_ego_style'):
            try:
                print(f"[美化] 开启应用 EGO 样式美化...")
                self._progress("正在应用 EGO 样式美化...", "🚀")
                from functions.fancy.EGO_colorful import main as apply_ego_style
                apply_ego_style()
            except Exception as e:
                print(f"[美化] EGO 样式跳过: {e}")

        if self._settings.get_setting('enable_skill_style'):
            try:
                print(f"[美化] 开启美化技能描述文本...")
                self._progress("正在美化技能描述文本...", "🚀")
                from functions.fancy.skill_info import total_handle
                total_handle(lang_path)
            except Exception as e:
                print(f"[美化] 技能描述美化跳过: {e}")

        if self._settings.get_setting('enable_ego_gift_style'):
            try:
                print(f"[美化] 开启美化 EGO 饰品效果...")
                self._progress("正在美化 EGO 饰品效果...", "🚀")
                from functions.fancy.skill_info import handle_EGOgift
                handle_EGOgift(lang_path)
            except Exception as e:
                print(f"[美化] EGO 饰品跳过: {e}")

        if self._settings.get_setting('enable_buff_style'):
            try:
                print(f"[美化] 开启美化 Buff 效果文本...")
                self._progress("正在美化 Buff 效果文本...", "🚀")
                from functions.fancy.skill_info import handle_buff
                handle_buff(lang_path + '/')
            except Exception as e:
                print(f"[美化] Buff 美化跳过: {e}")

        if self._settings.get_setting('enable_special_tip'):
            try:
                print(f"[美化] 开启替换战斗提示文本...")
                self._progress("正在替换战斗提示文本...", "🚀")
                from functions.fancy.hint_set import simple_replace
                simple_replace(os.path.join(lang_path, 'BattleHint.json'))
            except Exception as e:
                print(f"[美化] 战斗提示替换跳过: {e}")

        if self._settings.get_setting('enable_skill_text_gradient'):
            try:
                print(f"[美化] 开启应用技能文本渐变色...")
                self._progress("正在应用技能文本渐变色...", "🚀")
                from functions.fancy.skill_colorful import skill_color_process
                skill_color_process(lang_root + '/')
            except Exception as e:
                print(f"[美化] 技能渐变色跳过: {e}")

    def _copy_fonts(self):
        """复制字体文件到游戏汉化目录。"""
        from functions.web_update.translation_source import get_game_lang_dir
        from functions.web_update.zeroasso_download import _PROJECT_ROOT as _font_root
        src = os.path.join(_font_root, 'assets', 'Font')
        if not os.path.isdir(src):
            print(f"[字体] assets/Font 不存在 ({src}), 跳过字体转移")
            return
        target = os.path.join(get_game_lang_dir(self._game_path), 'Font')
        os.makedirs(target, exist_ok=True)
        shutil.copytree(src, target, dirs_exist_ok=True)

    def _create_zeroasso_config(self):
        """创建零协会配置文件。"""
        from functions.web_update.zeroasso_download import create_config_file
        create_config_file(self._game_path)

    def _set_user_name(self):
        """将用户显示名称写入游戏的 UserInfo_Friends.json (文件不存在时跳过)。"""
        from functions.web_update.translation_source import get_game_lang_dir
        user_name = self._settings.get_setting('user_name')
        file_path = os.path.join(get_game_lang_dir(self._game_path), 'UserInfo_Friends.json')
        if not os.path.exists(file_path):
            print("未找到 UserInfo_Friends.json, 跳过用户名设置")
            return
        data = read_json(file_path)
        for item in data.get('dataList', []):
            if item.get('id') == 'Uid_Copy':
                item['content'] = str(user_name)
                break
        write_json(file_path, data, indent=4)

    def _fire_addon_events(self):
        """逐个触发插件的游戏启动事件 (显示插件名与进度)。"""
        if not self._addon_manager:
            return
        owners = getattr(self._addon_manager, 'gamestart_owners', {}) or {}
        funcs = list(self._addon_manager.gamestart_funcs)
        total = len(funcs)
        if not total:
            return
        for i, f in enumerate(funcs):
            owner = owners.get(id(f), '未知')
            self._progress(f"正在运行 {owner} 插件启动注入函数 ({i + 1}/{total})...", "🚀")
            try:
                f()
            except Exception as e:
                print(f"执行游戏启动回调失败: {e}")

    def _launch_game_process(self):
        """调用 mod loader 启动游戏进程，并在独立进程中启动成就监测 Hook。"""
        from functions.base.load_mod import launch_game_process
        # 先启动游戏进程
        launch_game_process()
        # 启动成就监测 Hook (独立子进程, 避免主进程结束时被 kill)
        # 子进程内部会：监控 Player.log + 注入 battle_watch.dll 观测战斗事件
        print("[成就监测] 警告：本版本暂时不开放成就系统。")
        return
        self._start_achievement_hook()

    def _start_achievement_hook(self):
        """启动成就监测 Hook（独立子进程），日志写入 logs/achievement_hook.log。

        设置项 ``enable_achievement_hook``（缺省 true）可关闭；
        子进程运行期间会向游戏进程注入 ``battle_watch.dll``（只读观测）。
        """
        try:
            import subprocess

            try:
                if self._settings.get_setting("enable_achievement_hook") is False:
                    print("[成就监测] 已关闭成就监测（设置: 启用成就监测与战斗观测）")
                    return
                else:
                    print("[成就监测] 已开启成就监测")
            except Exception:
                pass

            # Player.log 在 %USERPROFILE%\AppData\LocalLow\ProjectMoon\LimbusCompany 下
            # （不要写死用户名，换个账号就会走到不存在的路径）
            from functions.achievement.achievements import LOG_FILE as _player_log_name
            log_dir = os.path.join(os.path.expanduser("~"), "AppData", "LocalLow",
                                   "ProjectMoon", "LimbusCompany")
            game_log_path = os.path.join(log_dir, _player_log_name)

            project_root = os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__)
            )))
            main_script = os.path.join(project_root, "main.py")
            logs_dir = os.path.join(project_root, "logs")
            hook_log_path = os.path.join(logs_dir, "achievement_hook.log")

            # 确保 logs 目录存在
            os.makedirs(logs_dir, exist_ok=True)

            # 先收掉上次的成就监测子进程（如果还活着），**再**清空日志：
            # 否则残留实例会按自己的旧偏移继续写被清空后的文件，日志就会出现
            # 错位/NUL 空洞（就是之前那次“日志损坏”）。
            cache_dir = os.path.join(project_root, "cache", "achievement")
            os.makedirs(cache_dir, exist_ok=True)
            pid_file = os.path.join(cache_dir, "hook.pid")
            self._kill_stale_hook_child(pid_file)

            # 清空成就日志（battle_watch.log 由子进程自己清）
            with open(hook_log_path, 'w', encoding='utf-8') as f:
                f.write("")

            self._progress("启动成就监测与战斗观测...", "🏆")

            cmd = [
                sys.executable,
                main_script,
                "--achievement-hook",
                "--log", game_log_path,
                "--output", hook_log_path,
            ]
            # 子进程的 stdout/stderr 以前是 DEVNULL：一旦它在写下第一行成就日志之前出事
            # （被重复启动的实例杀掉 / 导入期异常 / 原生崩溃），就只剩“成就日志 3 字节（BOM）”
            # 这个现象，什么都查不到。现在落到 logs/achievement_hook_child.log。
            # 排查“成就/观测不生效”的现场：
            #   logs/achievement_hook.log        成就日志（子进程自己写）
            #   logs/achievement_hook_child.log  子进程 stdout/stderr（异常/警告）
            #   cache/achievement/hook_boot.log  子进程启动面包屑（死在哪一步）
            #   cache/achievement/hook_fatal.log faulthandler（原生崩溃堆栈）
            child_log_path = os.path.join(logs_dir, "achievement_hook_child.log")
            child_log = None
            try:
                child_log = open(child_log_path, "w", encoding="utf-8-sig", errors="replace")
            except OSError as exc:
                print(f"[成就] 无法创建子进程日志 {child_log_path}: {exc}")
            try:
                proc = subprocess.Popen(
                    cmd,
                    cwd=project_root,
                    stdout=child_log if child_log is not None else subprocess.DEVNULL,
                    stderr=child_log if child_log is not None else subprocess.DEVNULL,
                    stdin=subprocess.DEVNULL,
                    # CREATE_NO_WINDOW | BELOW_NORMAL_PRIORITY_CLASS
                    # 低优先级很重要：游戏更新后子进程要在后台跑一遍 metadata 解密 +
                    # Il2CppDumper（满核 1~2 分钟），正常优先级会把整个桌面卡住。
                    creationflags=0x08000000 | 0x00004000,
                )
            finally:
                if child_log is not None:
                    try:
                        child_log.close()
                    except OSError:
                        pass
            # ⚠ 这里**不要**写 hook.pid！``proc.pid`` 是 **launcher（py.exe）的 PID**，
            # 不是跑 main.py 的那个进程 —— 本机 venv 的 ``python.exe`` 其实是
            # py.exe launcher（InternalName = Python Launcher），真解释器是它拉起的**子进程**。
            # 以前就把 ``proc.pid`` 写了进去，后果是：子进程启动时拿 hook.pid 里的 PID
            # 去“收掉上一个实例”，而里面存的正是**它自己的父进程** → 连根拔掉自己
            # （现场：成就日志 0 字节，boot 日志停在“已收掉旧实例 PID …”，
            #  启动器 1 秒后报“子进程已退出（exit=0）”）。
            # hook.pid 一律由**子进程自己**写（``hook._write_own_pid`` 写的是 os.getpid()）。
            print(f"[成就] 成就监测子进程已拉起（launcher pid={proc.pid}；"
                  f"子进程会把自己的 PID 写进 {os.path.basename(pid_file)}）")
            self._watch_hook_child(proc, hook_log_path, child_log_path)
        except Exception as e:
            print(f"[成就] 启动成就监测失败 (不影响游戏启动): {e}")
            traceback.print_exc()

    def _watch_hook_child(self, proc, hook_log_path: str, child_log_path: str) -> None:
        """子进程健康检查：起来 20s 后成就日志还只有 BOM（3 字节）就主动告警。

        以前这种情况是“静默”的：用户只看到启动器一句进度，成就日志没内容，也没提示。
        """

        def worker() -> None:
            import threading  # noqa: F401  （保持方法自足；主进程已导入也一样）
            deadline = time.time() + 20
            while time.time() < deadline and proc.poll() is None:
                time.sleep(1.0)
            try:
                size = os.path.getsize(hook_log_path)
            except OSError:
                size = -1
            code = proc.poll()
            if code is not None:
                print(f"[成就] 成就监测子进程已退出（exit={code}）→ 看 {child_log_path}"
                      f" 与 cache/achievement/hook_boot.log")
                return
            if size <= 3:
                print("[成就] 成就监测子进程在跑，但成就日志没有任何内容"
                      "（成就解锁与战斗观测都不会生效）→ 现场: "
                      f"{child_log_path} / cache/achievement/hook_boot.log / "
                      "cache/achievement/hook_fatal.log")

        try:
            import threading
            threading.Thread(target=worker, name="hook-child-watch", daemon=True).start()
        except Exception as exc:  # noqa: BLE001
            print(f"[成就] 子进程健康检查线程启动失败: {exc}")

    @staticmethod
    def _kill_stale_hook_child(pid_file: str) -> None:
        """把上次记下的成就监测子进程收掉（只认我们自己拉起的那个解释器）。

        只凭 PID 杀进程很危险（PID 会被复用），所以额外校验进程映像路径是不是
        我们自己这类解释器（``hook._is_self_image``）；校验不过一律不动。

        ⚠ 不能直接比 ``sys.executable``：venv 里的 ``python.exe`` 有可能是 py.exe
        launcher，真解释器是它拉起的子进程（映像路径不一样）—— 实测这么比会永远
        不相等，于是“上次的残留子进程”根本收不掉。
        """
        import ctypes
        from ctypes import wintypes
        try:
            with open(pid_file, "r", encoding="utf-8") as fh:
                pid = int(fh.read().strip() or 0)
        except (OSError, ValueError):
            return
        # 自己的父进程绝不动（见 hook._self_and_ancestors：venv 的解释器是
        # launcher+子进程两层，父进程名字跟自己一模一样）
        if pid <= 0 or pid == os.getpid() or pid == os.getppid():
            return
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel32.OpenProcess(0x1000, False, pid)   # QUERY_LIMITED_INFORMATION
        if not handle:
            GameLauncher._forget_pid_file(pid_file)         # 已经没了 → 清掉记录
            return
        try:
            buf = ctypes.create_unicode_buffer(1024)
            size = wintypes.DWORD(len(buf))
            if not kernel32.QueryFullProcessImageNameW(handle, 0, buf,
                                                       ctypes.byref(size)):
                return
            image = buf.value
            # ⚠ 存活时长必须在**句柄还开着**的时候读：关掉之后再 GetProcessTimes
            # 必然失败 → 下面那道 STALE_HOOK_MIN_AGE 保护就会静默失效。
            age = _process_age_seconds(kernel32, handle)
        finally:
            kernel32.CloseHandle(handle)
        if not _is_own_interpreter_image(image):
            return                                          # PID 被复用成别的程序了
        # 但“刚起来”的子进程不能收：重复点启动 / 同时开着两个启动器实例时，
        # hook.pid 已经指向**最新**那个子进程了，收掉它 = 子进程刚起就被杀，
        # 现场正是“成就日志只有 3 字节（BOM）、没有任何内容”。
        if age is not None and age < STALE_HOOK_MIN_AGE:
            print(f"[成就] 上一个成就监测子进程（PID {pid}）只启动了 {age:.0f}s，"
                  f"疑似重复启动留下的 → 本次不收它（避免掐死新子进程）")
            # ⚠ **绝不能删 pid 文件**：它是那个活实例的**唯一记录**。删了之后新子进程
            # 在 `_acquire_single_instance` 里就认不出旧实例（互斥体占着、PID 又没了）
            # → 只能“已有实例且拿不到它的 PID → 本次直接退出”，白点一次启动器。
            return
        try:
            os.kill(pid, 9)                                 # 我们自己拉起的，收掉
            time.sleep(0.4)
        except OSError:
            pass
        GameLauncher._forget_pid_file(pid_file)

    @staticmethod
    def _forget_pid_file(pid_file: str) -> None:
        """清掉 pid 记录（只在“确实已经不在了 / 确实收掉了”时调）。"""
        try:
            os.remove(pid_file)
        except OSError:
            pass
