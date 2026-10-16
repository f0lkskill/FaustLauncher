
import os
import sys
import hashlib
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
    try:
        os.makedirs(dst, exist_ok=True)
    except Exception as e:
        print(f"[Debug] safe_merge_dirs: os.makedirs({dst!r}) 失败: {e}")
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
                print(f"[Debug] safe_merge_dirs: 复制文件失败 src={src_item!r} dst={dst_item!r}: {e}")
                traceback.print_exc()
                raise

def apply_changes_to_data(original_data, changes):
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

STALE_HOOK_MIN_AGE = 30.0

def _is_own_interpreter_image(image: str) -> bool:
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

    def __init__(self, addon_manager:AddonManager=None, progress=None): # type: ignore

        self._settings = get_settings_manager()
        self._addon_manager = addon_manager
        self._progress = progress or (lambda text, icon=None: None)
        self._game_path: str = self._settings.get_setting('game_path') or ''

        if self._addon_manager:
            translation_source_lib.set_extend_translate_source(self._addon_manager.extend_translate_source)
            print(f"已同步插件自定义汉化: {[x.name for x in translation_source_lib.extend_translate_source]}")
        self._lang_dir = translation_source_lib.get_translation_dir()

    def launch(self):
        print("启动游戏流水线作业开始")

        steps = [
            ("复制汉化文件",      "CopyTranslation", "🚀", self._prepare_translation),
            ("应用拓展汉化修改",   "ApplyAddonPatch", "🚀", self._apply_changes),
            ("应用美化功能",      "ApplyCosmetic",   "🚀", self._apply_cosmetic_features),
            ("复制字体文件",      "CopyFonts",       "🚀", self._copy_fonts),
            ("创建零协会配置",     "ZeroAssoConfig",  "🚀", self._create_zeroasso_config),
            ("设置用户名称",      "SetUserName",     "🚀", self._set_user_name),
            ("触发插件启动事件",   "AddonEvents",     "🚀", self._fire_addon_events),
            ("启动游戏进程",      "LaunchGame",      "🚀", self._launch_game_process),
        ]

        for name, label, icon, step in steps:
            self._progress(f"正在{name}...", icon)
            try:
                step()
            except Exception as e:
                print(f"[{label}] 失败: {e}")
                traceback.print_exc()
                if name in ("复制汉化文件", "复制字体文件"):
                    try:
                        messagebox.showerror("错误", f"{name}时出错: {str(e)}\n\n已跳过该步骤, 继续启动游戏")
                    except Exception:
                        pass

        print("启动游戏流水线作业结束\n\n")

    def _prepare_translation(self):
        from functions.fancy.bubble_transfer import main as transfer_bubble
        transfer_bubble(config_path=self._lang_dir)

        target = translation_source_lib.get_game_lang_dir(self._game_path)
        print(f"[Debug] _prepare_translation: 游戏路径={self._game_path!r}")
        print(f"[Debug] _prepare_translation: 源={os.path.abspath(self._lang_dir)!r} 存在={os.path.exists(self._lang_dir)} 是目录={os.path.isdir(self._lang_dir)}")
        print(f"[Debug] _prepare_translation: 目标={target!r} 存在={os.path.exists(target)} 是目录={os.path.isdir(target)}")
        if not os.path.isdir(self._lang_dir):
            print(f"[Locale] 汉化包目录不存在: {self._lang_dir} (请先在下载中心下载当前平台汉化包), 跳过汉化文件复制")
            return
        if os.path.exists(target):
            if os.path.isdir(target):
                shutil.rmtree(target, ignore_errors=True)
            else:
                print(f"[Debug] _prepare_translation: 目标路径不是目录，正在删除文件")
                os.remove(target)
        print(f"[Debug] _prepare_translation: 开始 copytree {self._lang_dir!r} -> {target!r}")
        shutil.copytree(self._lang_dir, target, dirs_exist_ok=True)

    @staticmethod
    def _list_changes_files(dir_path):
        from functions.pages.tools.custom_translation_window import _is_layer_changes_file
        if not os.path.isdir(dir_path):
            return []
        files = [f for f in os.listdir(dir_path) if _is_layer_changes_file(f)]
        files.sort(key=lambda f: (0, f) if f.lower() == "changes.json" else (1, f.lower()))
        return files

    @staticmethod
    def _lang_folder_candidates(lang_root, preferred=None):
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

    CHANGES_BACKUP_ROOT = os.path.join('cache', 'changes_backup')

    @staticmethod
    def _resource_enabled(kind: str, info: dict) -> bool:
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

    @classmethod
    def _gc_changes_backups(cls, lang_root: str, skip_folder=None) -> dict:
        root = cls.CHANGES_BACKUP_ROOT
        stats = {"dirs": 0, "entries": 0, "freed": 0, "kept": 0}
        if not os.path.isdir(root):
            return stats
        for kind in sorted(os.listdir(root)):
            kdir = os.path.join(root, kind)
            if not os.path.isdir(kdir):
                continue
            for res in sorted(os.listdir(kdir)):
                backup_dir = os.path.join(kdir, res)
                if not os.path.isdir(backup_dir):
                    continue
                index = cls._load_backup_index(backup_dir)
                if not index:
                    continue
                changed = False
                for changes_file in list(index.keys()):
                    slot = index.get(changes_file)
                    if not isinstance(slot, dict):
                        index.pop(changes_file, None)
                        changed = True
                        continue
                    for rel in list(slot.keys()):
                        name = slot.get(rel)
                        src = os.path.join(backup_dir, str(name))
                        target = os.path.join(lang_root, *str(rel).split('/'))
                        top = str(rel).split('/')[0]
                        dead = False
                        if skip_folder and top == skip_folder:
                            dead = True
                        elif not os.path.isfile(src):
                            dead = True
                        elif not os.path.isfile(target):
                            dead = True
                        else:
                            try:
                                if os.path.getmtime(target) > os.path.getmtime(src) + 2:
                                    dead = True
                            except OSError:
                                dead = True
                        if not dead:
                            stats["kept"] += 1
                            continue
                        try:
                            size = os.path.getsize(src)
                        except OSError:
                            size = 0
                        try:
                            os.remove(src)
                            stats["freed"] += size
                        except OSError:
                            pass
                        slot.pop(rel, None)
                        stats["entries"] += 1
                        changed = True
                    if not slot:
                        index.pop(changes_file, None)
                if changed:
                    cls._save_backup_index(backup_dir, index)
                    if not index:
                        shutil.rmtree(backup_dir, ignore_errors=True)
                        stats["dirs"] += 1
        return stats

    def _apply_changes(self):
        from functions.extension.mod.mod_utils import ModManager
        from functions.pages.tools.custom_translation_window import CHANGES_PATTERN

        lang_data_dir = os.path.join(self._game_path, 'LimbusCompany_Data', 'Lang')
        mods_off = not self._settings.get_setting('enable_mods')
        try:
            cur_folder = os.path.basename(translation_source_lib.get_game_lang_dir(self._game_path))
        except Exception:
            cur_folder = None

        apply_jobs, revert_jobs = [], []
        alive = set()
        for kind in ('addons', 'mods'):
            if not os.path.isdir(kind):
                continue
            is_mods = (kind == 'mods')
            if is_mods and mods_off:
                print("[TextPatch] 设置里关闭了 Mod 功能: 不应用 mods 的文本补丁")
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
                    print(f"[TextPatch] {kind}/{res_dir} 已禁用: 不应用它的文本补丁")
                (apply_jobs if enabled else revert_jobs).append((kind, res_dir))

        for kind, res_dir in revert_jobs:
            res_path = os.path.join(kind, res_dir)
            has_snapshot = bool(self._load_backup_index(self._changes_backup_dir(kind, res_dir)))
            n = self._restore_backups(kind, res_dir, lang_data_dir, skip_folder=cur_folder)
            if n:
                print(f"[TextPatch] {kind}/{res_dir} 已禁用 -> 还原它之前改过的 {n} 个文本文件")
            elif not has_snapshot and self._list_changes_files(res_path):
                print(f"[TextPatch] {kind}/{res_dir} 已禁用且没有改动快照。")

        dirs = [os.path.join(kind, res_dir) for kind, res_dir in apply_jobs]
        dirs.append('lang')
        print(f"[Debug] _apply_changes: 需要处理的目录: {dirs}")

        ModManager.load_language('', 'lang')

        for dir_path in dirs:
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

            if kind != 'lang' and disabled_layers:
                for changes_file in changes_files:
                    m = CHANGES_PATTERN.match(changes_file)
                    marker = m.group(1)[1:] if m and m.group(1) else ""
                    if marker in disabled_layers:
                        n = self._restore_backups(kind, src_name, lang_data_dir,
                                                  only_changes_files={changes_file},
                                                  skip_folder=cur_folder)
                        if n:
                            print(f"[TextPatch] {dir_path} 的图层 {changes_file} 已禁用 -> 还原 {n} 个文本文件")

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
                    targets = self._resolve_change_targets(lang_data_dir, relative_path)
                    if not targets:
                        print(f"  警告: 游戏目录中未找到 {relative_path} (已尝试 Lang 下全部文件夹)")
                        continue
                    if len(targets) > 1:
                        print(f"  应用补丁 {relative_path} -> {len(targets)} 个文件夹")
                    for game_file in targets:
                        try:
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

        self._prune_changes_backups(alive)

        gc = self._gc_changes_backups(lang_data_dir, skip_folder=cur_folder)
        if gc["entries"]:
            print(f"[TextPatch] 已回收 {gc['entries']} 份永远无法再还原的旧快照"
                  f"（{gc['freed'] / 1048576:.1f} MB，剩 {gc['kept']} 份可用）")
        else:
            print(f"[TextPatch] 文本改动快照: {gc['kept']} 份可用，无需回收")

    def _apply_cosmetic_features(self):
        lang_path = translation_source_lib.get_game_lang_dir(self._game_path)
        lang_root = os.path.join(self._game_path, 'LimbusCompany_Data', 'Lang')

        _bubble_color = self._settings.get_setting('enable_bubble_color')
        if _bubble_color is False:
            try:
                print(f"[Cosmetic] 开启去除气泡文本颜色标签...")
                self._progress("正在去除气泡文本颜色标签...", "🚀")
                from functions.fancy.dialog_colorful import main_remove_color as remove_bubble_color
                remove_bubble_color()
            except Exception as e:
                print(f"[Cosmetic] 去除气泡文本颜色跳过: {e}")
        elif self._settings.get_setting('enable_text_gradient'):
            try:
                print(f"[Cosmetic] 开启应用对话文本渐变色...")
                self._progress("正在应用对话文本渐变色...", "🚀")
                from functions.fancy.dialog_colorful import main as handle_colorful
                handle_colorful()
            except Exception as e:
                print(f"[Cosmetic] 对话文本渐变色跳过: {e}")
        if self._settings.get_setting('enable_ego_style'):
            try:
                print(f"[Cosmetic] 开启应用 EGO 样式美化...")
                self._progress("正在应用 EGO 样式美化...", "🚀")
                from functions.fancy.EGO_colorful import main as apply_ego_style
                apply_ego_style()
            except Exception as e:
                print(f"[Cosmetic] EGO 样式跳过: {e}")

        if self._settings.get_setting('enable_skill_style'):
            try:
                print(f"[Cosmetic] 开启美化技能描述文本...")
                self._progress("正在美化技能描述文本...", "🚀")
                from functions.fancy.skill_info import total_handle
                total_handle(lang_path)
            except Exception as e:
                print(f"[Cosmetic] 技能描述美化跳过: {e}")

        if self._settings.get_setting('enable_ego_gift_style'):
            try:
                print(f"[Cosmetic] 开启美化 EGO 饰品效果...")
                self._progress("正在美化 EGO 饰品效果...", "🚀")
                from functions.fancy.skill_info import handle_EGOgift
                handle_EGOgift(lang_path)
            except Exception as e:
                print(f"[Cosmetic] EGO 饰品跳过: {e}")

        if self._settings.get_setting('enable_buff_style'):
            try:
                print(f"[Cosmetic] 开启美化 Buff 效果文本...")
                self._progress("正在美化 Buff 效果文本...", "🚀")
                from functions.fancy.skill_info import handle_buff
                handle_buff(lang_path + '/')
            except Exception as e:
                print(f"[Cosmetic] Buff 美化跳过: {e}")

        if self._settings.get_setting('enable_special_tip'):
            try:
                print(f"[Cosmetic] 开启替换战斗提示文本...")
                self._progress("正在替换战斗提示文本...", "🚀")
                from functions.fancy.hint_set import simple_replace
                simple_replace(os.path.join(lang_path, 'BattleHint.json'))
            except Exception as e:
                print(f"[Cosmetic] 战斗提示替换跳过: {e}")

        if self._settings.get_setting('enable_skill_text_gradient'):
            try:
                print(f"[Cosmetic] 开启应用技能文本渐变色...")
                self._progress("正在应用技能文本渐变色...", "🚀")
                from functions.fancy.skill_colorful import skill_color_process
                skill_color_process(lang_root + '/')
            except Exception as e:
                print(f"[Cosmetic] 技能渐变色跳过: {e}")

    def _copy_fonts(self):
        from functions.web_update.translation_source import get_game_lang_dir
        from functions.web_update.zeroasso_download import _PROJECT_ROOT as _font_root
        src = os.path.join(_font_root, 'assets', 'Font')
        if not os.path.isdir(src):
            print(f"[Font] assets/Font 不存在 ({src}), 跳过字体转移")
            return
        target = os.path.join(get_game_lang_dir(self._game_path), 'Font')
        os.makedirs(target, exist_ok=True)
        shutil.copytree(src, target, dirs_exist_ok=True)

    def _create_zeroasso_config(self):
        from functions.web_update.zeroasso_download import create_config_file
        create_config_file(self._game_path)

    @staticmethod
    def _original_uid_copy(folder: str):
        root = 'lang'
        candidates = [os.path.join(root, str(folder or ''), 'UserInfo_Friends.json')]
        try:
            for name in sorted(os.listdir(root)):
                path = os.path.join(root, name, 'UserInfo_Friends.json')
                if path not in candidates:
                    candidates.append(path)
        except OSError:
            pass
        for path in candidates:
            if not os.path.isfile(path):
                continue
            try:
                data = read_json(path)
            except Exception:  # noqa: BLE001
                continue
            if not isinstance(data, dict):
                continue
            for item in data.get('dataList', []) or []:
                if isinstance(item, dict) and item.get('id') == 'Uid_Copy':
                    return str(item.get('content') or '')
        return None

    def _set_user_name(self):
        from functions.web_update.translation_source import get_game_lang_dir
        lang_dir = get_game_lang_dir(self._game_path)
        file_path = os.path.join(lang_dir, 'UserInfo_Friends.json')
        if not os.path.exists(file_path):
            print("未找到 UserInfo_Friends.json, 跳过用户名设置")
            return

        enabled = self._settings.get_setting('enable_show_user_name')
        enabled = True if enabled is None else bool(enabled)
        name = str(self._settings.get_setting('user_name') or '').strip()
        restore = not enabled or not name
        wanted = self._original_uid_copy(os.path.basename(lang_dir)) if restore else name
        if wanted is None:
            print("[SetUserName] 需要还原原文, 但读不到汉化包里的 UserInfo_Friends.json → 保持现状")
            return

        data = read_json(file_path)
        if not isinstance(data, dict):
            print("[SetUserName] UserInfo_Friends.json 结构异常, 跳过")
            return
        target = None
        for item in data.get('dataList', []) or []:
            if isinstance(item, dict) and item.get('id') == 'Uid_Copy':
                target = item
                break
        if target is None:
            print("[SetUserName] UserInfo_Friends.json 里没有 Uid_Copy, 跳过")
            return
        if str(target.get('content') or '') == wanted:
            print(f"[SetUserName] 无需改动（{'显示用户名' if not restore else '已关闭/昵称为空'}）")
            return
        target['content'] = wanted
        write_json(file_path, data, indent=4)
        print(f"[SetUserName] Uid_Copy 已{'还原为原文' if restore else '写入昵称'}: {wanted}")

    def _fire_addon_events(self):
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
        from functions.base.load_mod import launch_game_process
        launch_game_process()
        self._start_achievement_hook()

    def _start_achievement_hook(self):
        try:
            import subprocess

            try:
                if self._settings.get_setting("enable_achievement_hook") is False:
                    print("[AchMonitor] 已关闭成就监测（设置: 启用成就监测与战斗观测）")
                    return
                else:
                    print("[AchMonitor] 已开启成就监测")
            except Exception:
                pass

            from functions.achievement.achievements import LOG_FILE as _player_log_name
            log_dir = os.path.join(os.path.expanduser("~"), "AppData", "LocalLow",
                                   "ProjectMoon", "LimbusCompany")
            game_log_path = os.path.join(log_dir, _player_log_name)

            try:
                from functions.base.common.path_utils import get_app_root
                project_root = get_app_root()
            except Exception:  # noqa: BLE001
                project_root = os.path.dirname(os.path.dirname(os.path.dirname(
                    os.path.abspath(__file__)
                )))
            main_script = os.path.join(project_root, "main.py")
            logs_dir = os.path.join(project_root, "logs")
            hook_log_path = os.path.join(logs_dir, "achievement_hook.log")

            os.makedirs(logs_dir, exist_ok=True)

            cache_dir = os.path.join(project_root, "cache", "achievement")
            os.makedirs(cache_dir, exist_ok=True)
            pid_file = os.path.join(cache_dir, "hook.pid")
            self._kill_stale_hook_child(pid_file)

            with open(hook_log_path, 'wb') as f:
                f.write(b"\xef\xbb\xbf")

            for stale_name in ("achievement_hook_child.log", "battle_watch.log"):
                stale = os.path.join(logs_dir, stale_name)
                try:
                    if os.path.isfile(stale):
                        os.remove(stale)
                        print(f"[Achievement] 已删除合并前的旧日志: {stale_name}")
                except OSError:
                    pass

            cmd = [
                sys.executable,
                main_script,
                "--achievement-hook",
                "--log", game_log_path,
                "--output", hook_log_path,
            ]
            child_env = dict(os.environ)
            child_env["FAUST_ACH_TRUNCATED"] = "1"
            child_env["PYTHONIOENCODING"] = "utf-8"
            child_env["PYTHONUTF8"] = "1"
            child_env["PYTHONUNBUFFERED"] = "1"
            try:
                proc = subprocess.Popen(
                    cmd,
                    cwd=project_root,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL,
                    env=child_env,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    bufsize=1,
                    creationflags=0x08000000 | 0x00004000,
                )
            except OSError as exc:
                print(f"[Achievement] 无法启动成就监测子进程: {exc}")
                return
            self._pump_hook_child_log(proc, hook_log_path)
            print(f"[Achievement] 成就监测子进程已拉起（launcher pid={proc.pid}；"
                  f"子进程会把自己的 PID 写进 {os.path.basename(pid_file)}）")
            self._watch_hook_child(proc, hook_log_path)
        except Exception as e:
            print(f"[Achievement] 启动成就监测失败 (不影响游戏启动): {e}")
            traceback.print_exc()

    def _pump_hook_child_log(self, proc, hook_log_path: str) -> None:
        import re as _re
        import threading as _threading

        from functions.achievement import log_sink

        dll_raw_re = _re.compile(r"^\d{2}:\d{2}:\d{2}\.\d{3}\s+DLL\b")

        def worker() -> None:
            try:
                fh = open(hook_log_path, "a", encoding="utf-8", errors="replace",
                          buffering=1)
            except OSError as exc:
                print(f"[Achievement] 无法打开成就日志 {hook_log_path}: {exc}")
                return
            try:
                stream = proc.stdout
                if stream is None:
                    return
                for raw in stream:
                    line = raw.rstrip("\r\n")
                    if not line.strip():
                        fh.write("\n")
                        continue
                    if dll_raw_re.match(line):
                        continue
                    fh.write(log_sink.format_line(line, area="AchLog") + "\n")
            except Exception:  # noqa: BLE001
                pass
            finally:
                try:
                    fh.close()
                except OSError:
                    pass

        _threading.Thread(target=worker, name="faust-ach-log", daemon=True).start()

    def _watch_hook_child(self, proc, hook_log_path: str) -> None:

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
                print(f"[Achievement] 成就监测子进程已退出（exit={code}）→ 看 {hook_log_path}"
                      f" 与 cache/achievement/hook_boot.log")
                return
            if size <= 3:
                print("[Achievement] 成就监测子进程在跑，但成就日志没有任何内容"
                      "（成就解锁与战斗观测都不会生效）→ 现场: "
                      f"{hook_log_path}（含子进程 stdout/stderr）/ "
                      "cache/achievement/hook_boot.log / cache/achievement/hook_fatal.log")

        try:
            import threading
            threading.Thread(target=worker, name="hook-child-watch", daemon=True).start()
        except Exception as exc:  # noqa: BLE001
            print(f"[Achievement] 子进程健康检查线程启动失败: {exc}")

    @staticmethod
    def _kill_stale_hook_child(pid_file: str) -> None:
        import ctypes
        from ctypes import wintypes
        try:
            with open(pid_file, "r", encoding="utf-8") as fh:
                pid = int(fh.read().strip() or 0)
        except (OSError, ValueError):
            return
        if pid <= 0 or pid == os.getpid() or pid == os.getppid():
            return
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            GameLauncher._forget_pid_file(pid_file)
            return
        try:
            buf = ctypes.create_unicode_buffer(1024)
            size = wintypes.DWORD(len(buf))
            if not kernel32.QueryFullProcessImageNameW(handle, 0, buf,
                                                       ctypes.byref(size)):
                return
            image = buf.value
            age = _process_age_seconds(kernel32, handle)
        finally:
            kernel32.CloseHandle(handle)
        if not _is_own_interpreter_image(image):
            return
        if age is not None and age < STALE_HOOK_MIN_AGE:
            print(f"[Achievement] 上一个成就监测子进程（PID {pid}）只启动了 {age:.0f}s，"
                  f"疑似重复启动留下的 → 本次不收它（避免掐死新子进程）")
            return
        try:
            os.kill(pid, 9)
            time.sleep(0.4)
        except OSError:
            pass
        GameLauncher._forget_pid_file(pid_file)

    @staticmethod
    def _forget_pid_file(pid_file: str) -> None:
        try:
            os.remove(pid_file)
        except OSError:
            pass
