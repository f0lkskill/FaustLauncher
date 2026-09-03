"""游戏启动流水线 — 将启动前的准备工作拆分为清晰的步骤。"""

import os
import json
import shutil
import traceback
import tkinter.messagebox as messagebox

from functions.base.settings_manager import get_settings_manager


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

    def __init__(self, addon_manager=None, progress=None):
        self._settings = get_settings_manager()
        self._addon_manager = addon_manager
        self._progress = progress or (lambda text, icon=None: None)
        self._game_path: str = self._settings.get_setting('game_path') or ''
        from functions.web_update.translation_source import get_translation_dir
        self._lang_dir = get_translation_dir()

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
        from functions.web_update.translation_source import get_game_lang_dir
        target = get_game_lang_dir(self._game_path)
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

    def _apply_changes(self):
        """应用所有启用 mod 和 插件 的 changes*.json 补丁到游戏语言文件。
        支持多个修改记录图层: changes.json + changes_标记.json (按名称排序, 后应用者覆盖);
        changes_layers.json 中 visible=false 的图层跳过 (编辑器里的 PS 式图层可见性)。"""
        from functions.extension.mod.mod_utils import ModManager
        from functions.pages.tools.custom_translation_window import CHANGES_PATTERN
        import re

        # 收集所有需要处理的目录
        dirs = []
        for dir in ['addons', 'mods']:
            if self._settings.get_setting('enable_mods'):
                for sub_dir in os.listdir(dir):
                    info_path = os.path.join(dir, sub_dir, f'{dir.replace("s", "")}_info.json')
                    if not os.path.exists(info_path):
                        continue
                    info = json.load(open(info_path, 'r', encoding='utf-8'))
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
                    with open(layer_state_file, 'r', encoding='utf-8') as f:
                        st = json.load(f)
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
                    with open(file_path, 'r', encoding='utf-8') as f:
                        changes_data = json.load(f)
                except Exception as e:
                    print(f"  警告: 无法解析 {file_path}: {e}")
                    continue
                if not changes_data:
                    continue
                if not isinstance(changes_data, dict):
                    print(f"  警告: {file_path} 顶层必须是 {{\"相对路径\": 修改内容}} 对象, 实际是 {type(changes_data).__name__}, 已跳过")
                    continue
                for relative_path, file_changes in changes_data.items():
                    try:
                        game_file = os.path.join(lang_data_dir, relative_path)
                        if not os.path.exists(game_file):
                            print(f"  警告: 游戏目录中未找到 {relative_path}")
                            continue
                        with open(game_file, 'r', encoding='utf-8') as f:
                            original = json.load(f)
                        modified = apply_changes_to_data(original, file_changes)
                        with open(game_file, 'w', encoding='utf-8') as f:
                            json.dump(modified, f, ensure_ascii=False, indent=4)
                    except Exception as e:
                        print(f"  警告: 应用补丁 {relative_path} 失败: {e}")

    def _apply_cosmetic_features(self):
        """应用气泡渐变、EGO 样式、技能描述、提示替换、技能渐变色 (逐项推送进度, 单项失败不中断)"""
        from functions.web_update.translation_source import get_game_lang_dir
        lang_path = get_game_lang_dir(self._game_path)
        lang_root = os.path.join(self._game_path, 'LimbusCompany_Data', 'Lang')

        if self._settings.get_setting('enable_text_gradient'):
            try:
                self._progress("正在应用对话文本渐变色...", "🚀")
                from functions.fancy.dialog_colorful import main as handle_colorful
                handle_colorful()
            except Exception as e:
                print(f"[美化] 对话文本渐变色跳过: {e}")

        if self._settings.get_setting('enable_ego_style'):
            try:
                self._progress("正在应用 EGO 样式美化...", "🚀")
                from functions.fancy.EGO_colorful import main as apply_ego_style
                apply_ego_style()
            except Exception as e:
                print(f"[美化] EGO 样式跳过: {e}")

        if self._settings.get_setting('enable_skill_style'):
            try:
                self._progress("正在美化技能描述文本...", "🚀")
                from functions.fancy.skill_info import total_handle
                total_handle(lang_path + '/')
            except Exception as e:
                print(f"[美化] 技能描述美化跳过: {e}")

        if self._settings.get_setting('enable_ego_gift_style'):
            try:
                self._progress("正在美化 EGO 饰品效果...", "🚀")
                from functions.fancy.skill_info import handle_EGOgift
                handle_EGOgift(lang_path + '/')
            except Exception as e:
                print(f"[美化] EGO 饰品跳过: {e}")

        if self._settings.get_setting('enable_buff_style'):
            try:
                self._progress("正在美化 Buff 效果文本...", "🚀")
                from functions.fancy.skill_info import handle_buff
                handle_buff(lang_path + '/')
            except Exception as e:
                print(f"[美化] Buff 美化跳过: {e}")

        if self._settings.get_setting('enable_special_tip'):
            try:
                self._progress("正在替换战斗提示文本...", "🚀")
                from functions.fancy.hint_set import simple_replace
                simple_replace(os.path.join(lang_path, 'BattleHint.json'))
            except Exception as e:
                print(f"[美化] 战斗提示替换跳过: {e}")

        if self._settings.get_setting('enable_skill_text_gradient'):
            try:
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
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        for item in data.get('dataList', []):
            if item.get('id') == 'Uid_Copy':
                item['content'] = str(user_name)
                break
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)

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
        """调用 mod loader 启动游戏进程。"""
        from functions.base.load_mod import launch_game_process
        launch_game_process()
