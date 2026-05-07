"""游戏启动流水线 — 将启动前的准备工作拆分为清晰的步骤。"""

import os
import json
import shutil
import threading
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
        if (len(original_data) > 0 and isinstance(original_data[0], dict)
                and 'id' in original_data[0] and len(changes) > 0
                and isinstance(changes[0], dict) and 'id' in changes[0]):

            original_dict = {item['id']: item for item in original_data if 'id' in item}
            modified_ids = set()

            for change_item in changes:
                if isinstance(change_item, dict) and 'id' in change_item:
                    change_id = change_item['id']
                    modified_ids.add(change_id)
                    if change_id in original_dict:
                        original_item = original_dict[change_id]
                        if 'changes' in change_item:
                            modified_item = apply_changes_to_data(original_item, change_item['changes'])
                            result.append(modified_item)
                        else:
                            result.append(original_item)
                    else:
                        result.append(change_item.get('changes', change_item))

            for item in original_data:
                if isinstance(item, dict) and 'id' in item:
                    if item['id'] not in modified_ids:
                        result.append(item)
                else:
                    result.append(item)
            return result
        else:
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

    def __init__(self, addon_manager=None):
        self._settings = get_settings_manager()
        self._addon_manager = addon_manager
        self._game_path: str = self._settings.get_setting('game_path') or ''
        self._lang_dir = 'lang/LLC_zh-CN'

    # ── 流水线入口 ──────────────────────────────────────────────

    def launch(self):
        """按顺序执行启动流水线的所有步骤。"""
        print("\n========== 开始启动游戏流水线 ==========")

        steps = [
            ("复制汉化文件",      self._prepare_translation),
            ("应用 Mod 修改",     self._apply_mod_changes),
            ("应用美化功能",      self._apply_cosmetic_features),
            ("复制字体文件",      self._copy_fonts),
            ("创建零协会配置",     self._create_zeroasso_config),
            ("设置用户名称",      self._set_user_name),
            ("触发插件启动事件",   self._fire_addon_events),
            ("启动游戏进程",      self._launch_game_process),
        ]

        for name, step in steps:
            print(f"[{name}] 开始...")
            try:
                step()
                print(f"[{name}] 完成")
            except Exception as e:
                print(f"[{name}] 失败: {e}")
                traceback.print_exc()
                if name in ("复制汉化文件", "复制字体文件"):
                    messagebox.showerror("错误", f"{name}时出错: {str(e)}")
                    return
                # 非关键步骤失败不阻断启动

        print("========== 启动流水线结束 ==========\n")

    # ── 步骤实现 ────────────────────────────────────────────────

    def _prepare_translation(self):
        """复制 lang/LLC_zh-CN 到游戏目录。"""
        target = os.path.join(self._game_path, 'LimbusCompany_Data', 'Lang', 'LLC_zh-CN')
        print(f"[调试] _prepare_translation: 游戏路径={self._game_path!r}")
        print(f"[调试] _prepare_translation: 源={os.path.abspath(self._lang_dir)!r} 存在={os.path.exists(self._lang_dir)} 是目录={os.path.isdir(self._lang_dir)}")
        print(f"[调试] _prepare_translation: 目标={target!r} 存在={os.path.exists(target)} 是目录={os.path.isdir(target)}")
        if os.path.exists(target):
            if os.path.isdir(target):
                shutil.rmtree(target, ignore_errors=True)
            else:
                print(f"[调试] _prepare_translation: 目标路径不是目录，正在删除文件")
                os.remove(target)
        print(f"[调试] _prepare_translation: 开始 copytree {self._lang_dir!r} -> {target!r}")
        shutil.copytree(self._lang_dir, target, dirs_exist_ok=True)

    def _apply_mod_changes(self):
        """应用所有启用 mod 的 changes.json 补丁到游戏语言文件。"""
        from functions.mod.mod_ulits import ModManager

        # 收集所有需要处理的目录
        dirs = []
        if self._settings.get_setting('enable_mods'):
            for sub_dir in os.listdir('mods'):
                mod_info_path = os.path.join('mods', sub_dir, 'mod_info.json')
                if not os.path.exists(mod_info_path):
                    continue
                mod_info = json.load(open(mod_info_path, 'r', encoding='utf-8'))
                if mod_info.get('settings', {}).get('enable'):
                    dirs.append(os.path.join('mods', sub_dir))
        dirs.append('lang')

        ModManager.load_language('', self._lang_dir)

        lang_data_dir = os.path.join(self._game_path, 'LimbusCompany_Data', 'Lang')

        for dir_path in dirs:
            changes_file = os.path.join(dir_path, 'changes.json')
            if not os.path.exists(changes_file):
                continue
            with open(changes_file, 'r', encoding='utf-8') as f:
                changes_data = json.load(f)
            if not changes_data:
                continue
            for relative_path, file_changes in changes_data.items():
                game_file = os.path.join(lang_data_dir, relative_path)
                if not os.path.exists(game_file):
                    print(f"  警告: 游戏目录中未找到 {relative_path}")
                    continue
                with open(game_file, 'r', encoding='utf-8') as f:
                    original = json.load(f)
                modified = apply_changes_to_data(original, file_changes)
                with open(game_file, 'w', encoding='utf-8') as f:
                    json.dump(modified, f, ensure_ascii=False, indent=4)

    def _apply_cosmetic_features(self):
        """应用气泡渐变、EGO 样式、技能描述、提示替换、技能渐变色。"""
        lang_path = os.path.join(self._game_path, 'LimbusCompany_Data', 'Lang', 'LLC_zh-CN')
        lang_root = os.path.join(self._game_path, 'LimbusCompany_Data', 'Lang')

        if self._settings.get_setting('enable_text_gradient'):
            from functions.fancy.dialog_colorful import main as handle_colorful
            handle_colorful()

        if self._settings.get_setting('enable_ego_style'):
            from functions.fancy.EGO_colorful import main as apply_ego_style
            apply_ego_style()

        if self._settings.get_setting('enable_skill_style'):
            from functions.fancy.skill_info import handle_skill
            handle_skill(lang_path + '/')

        if self._settings.get_setting('enable_speical_tip'):
            from functions.fancy.hint_set import simple_replace
            simple_replace(os.path.join(lang_path, 'BattleHint.json'))

        if self._settings.get_setting('enable_skill_text_gradient'):
            from functions.fancy.skill_colorful import skill_color_process
            skill_color_process(lang_root + '/')

    def _copy_fonts(self):
        """复制字体文件到游戏汉化目录。"""
        target = os.path.join(self._game_path, 'LimbusCompany_Data', 'Lang', 'LLC_zh-CN', 'Font')
        os.makedirs(target, exist_ok=True)
        shutil.copytree('assets/Font', target, dirs_exist_ok=True)

    def _create_zeroasso_config(self):
        """创建零协会配置文件。"""
        from functions.dowloads.zeroasso_dow import create_config_file
        create_config_file(self._game_path)

    def _set_user_name(self):
        """将用户显示名称写入游戏的 UserInfo_Friends.json。"""
        user_name = self._settings.get_setting('user_name')
        file_path = os.path.join(self._game_path, 'LimbusCompany_Data', 'Lang', 'LLC_zh-CN', 'UserInfo_Friends.json')
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        for item in data.get('dataList', []):
            if item.get('id') == 'Uid_Copy':
                item['content'] = str(user_name)
                break
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)

    def _fire_addon_events(self):
        """在后台线程触发插件的游戏启动事件。"""
        if self._addon_manager:
            threading.Thread(target=self._addon_manager.run_game_start_event).start()

    def _launch_game_process(self):
        """调用 mod loader 启动游戏进程。"""
        from functions.base.load_mod import launch_game_process
        launch_game_process()
