"""游戏启动流水线 — 将启动前的准备工作拆分为清晰的步骤。"""

import os
import sys
import json
import shutil
import time
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
            translation_source_lib.extend_translate_source = self._addon_manager.extend_translate_source
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

    def _apply_changes(self):
        """应用所有启用 mod 和 插件 的 changes*.json 补丁到游戏语言文件。
        支持多个修改记录图层: changes.json + changes_标记.json (按名称排序, 后应用者覆盖);
        changes_layers.json 中 visible=false 的图层跳过 (编辑器里的 PS 式图层可见性)。"""
        from functions.extension.mod.mod_utils import ModManager
        from functions.pages.tools.custom_translation_window import CHANGES_PATTERN

        # 收集所有需要处理的目录
        dirs = []
        for dir in ['addons', 'mods']:
            if self._settings.get_setting('enable_mods'):
                for sub_dir in os.listdir(dir):
                    info_path = os.path.join(dir, sub_dir, f'{dir.replace("s", "")}_info.json')
                    if not os.path.exists(info_path):
                        continue
                    info = read_json(info_path)
                    if info.get('settings', {}).get('enable'):
                        dirs.append(os.path.join(dir, sub_dir))
                    
        #TODO 有点奇怪，先空着。
        dirs.append('lang')
        
        print(f"[调试] _apply_changes: 需要处理的目录: {dirs}")

        # 载入替换文件
        ModManager.load_language('', 'lang')

        lang_data_dir = os.path.join(self._game_path, 'LimbusCompany_Data', 'Lang')

        for dir_path in dirs:
            # 读取记录文件禁用状态 (不存在 = 全部参与合并)
            disabled_layers = set()
            layer_state_file = os.path.join(dir_path, 'changes_layers.json')
            if os.path.exists(layer_state_file):
                try:
                    st = read_json(layer_state_file)
                    for marker, v in (st.items() if isinstance(st, dict) else []):
                        disabled = v.get('disabled', False) if isinstance(v, dict) else False
                        if disabled:
                            disabled_layers.add(marker)
                except Exception as e:
                    print(f"  警告: 解析 {layer_state_file} 失败: {e}")

            changes_files = self._list_changes_files(dir_path)
            if not changes_files:
                continue

            # 逐个来源显示: 正在应用 插件/Mod xxx 的文本补丁
            src_label = '插件' if dir_path.startswith('addons') else ('Mod' if dir_path.startswith('mods') else '汉化')
            src_name = os.path.basename(dir_path)
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
                            original = read_json(game_file)
                            modified = apply_changes_to_data(original, file_changes)
                            write_json(game_file, modified, indent=4)
                        except Exception as e:
                            print(f"  警告: 应用补丁 {game_file} 失败: {e}")

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
                    self._progress("已关闭成就监测（设置: 启用成就监测与战斗观测）", "🏆")
                    return
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
            # 每次启动前清空上次的日志（两个日志都清：battle_watch.log 由子进程自己清）
            with open(hook_log_path, 'w', encoding='utf-8') as f:
                f.write("")

            # 上一次的成就监测子进程如果还活着（上次没退干净），先收掉：
            # 否则新实例会撞上“共享内存已存在”而静默不注入，看起来就像功能坏了。
            cache_dir = os.path.join(project_root, "cache", "achievement")
            os.makedirs(cache_dir, exist_ok=True)
            pid_file = os.path.join(cache_dir, "hook.pid")
            self._kill_stale_hook_child(pid_file)

            self._progress("启动成就监测与战斗观测...", "🏆")

            cmd = [
                sys.executable,
                main_script,
                "--achievement-hook",
                "--log", game_log_path,
                "--output", hook_log_path,
            ]
            proc = subprocess.Popen(
                cmd,
                cwd=project_root,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                creationflags=0x08000000,  # CREATE_NO_WINDOW
            )
            try:
                with open(pid_file, "w", encoding="utf-8") as fh:
                    fh.write(str(proc.pid))
            except OSError:
                pass
        except Exception as e:
            print(f"[成就] 启动成就监测失败 (不影响游戏启动): {e}")
            traceback.print_exc()

    @staticmethod
    def _kill_stale_hook_child(pid_file: str) -> None:
        """把上次记下的成就监测子进程收掉（只认我们自己拉起的那个解释器）。

        只凭 PID 杀进程很危险（PID 会被复用），所以额外校验进程映像路径 ==
        ``sys.executable`` —— 它就是我们用同一个解释器拉起的脚本子进程；
        校验不过一律不动。
        """
        import ctypes
        from ctypes import wintypes
        try:
            with open(pid_file, "r", encoding="utf-8") as fh:
                pid = int(fh.read().strip() or 0)
        except (OSError, ValueError):
            return
        try:
            os.remove(pid_file)
        except OSError:
            pass
        if pid <= 0 or pid == os.getpid():
            return
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel32.OpenProcess(0x1000, False, pid)   # QUERY_LIMITED_INFORMATION
        if not handle:
            return                                          # 已经没了
        try:
            buf = ctypes.create_unicode_buffer(1024)
            size = wintypes.DWORD(len(buf))
            if not kernel32.QueryFullProcessImageNameW(handle, 0, buf,
                                                       ctypes.byref(size)):
                return
            image = buf.value
        finally:
            kernel32.CloseHandle(handle)
        if os.path.normcase(image) != os.path.normcase(sys.executable):
            return                                          # PID 被复用成别的程序了
        try:
            os.kill(pid, 9)                                 # 我们自己拉起的，收掉
            time.sleep(0.4)
        except OSError:
            pass
