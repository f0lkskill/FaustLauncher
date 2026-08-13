import json
import os
from pathlib import Path

class SettingsManager:
    def __init__(self, config_path="config/settings.json"):
        self.config_path = config_path
        self.settings = {}
        self.load_settings()

    # ── 防损坏读写 ────────────────────────────────────────────

    def _is_valid_settings(self, data):
        """校验配置数据结构是否有效（顶层必须是非空 dict）。"""
        return isinstance(data, dict) and len(data) > 0

    def _load_from_file(self, path):
        """尝试从指定文件读取配置，文件缺失、解析失败或结构无效时返回 None。"""
        try:
            if os.path.exists(path):
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                if self._is_valid_settings(data):
                    return data
        except Exception as e:
            print(f"读取配置 {path} 失败: {e}")
        return None

    def load_settings(self):
        """加载设置文件。

        主文件损坏或为空时，自动从上次的备份 (.bak) 恢复并回写主文件，
        保证意外关机导致的损坏不会丢失用户配置。
        """
        loaded = self._load_from_file(self.config_path)
        if loaded is not None:
            self.settings = loaded
            return

        backup_path = self.config_path + '.bak'
        loaded = self._load_from_file(backup_path)
        if loaded is not None:
            print(f"配置主文件损坏或为空，已从备份恢复: {backup_path}")
            self.settings = loaded
            self.save_settings()
            return

        print("警告: 配置损坏且无可用备份，请检查 config/settings.json")
        self.settings = {}

    def save_settings(self):
        """原子化保存设置到文件，防止断电/崩溃导致配置损坏。

        流程: 备份当前有效配置 → 写入临时文件并刷盘 → 原子替换原文件。
        若内存中的配置无效，拒绝保存，避免用空配置覆盖有效文件。
        """
        if not self._is_valid_settings(self.settings):
            print("警告: 配置内容无效，拒绝保存，避免覆盖有效配置文件")
            return False
        try:
            # 确保目录存在
            os.makedirs(os.path.dirname(self.config_path), exist_ok=True)

            # 备份当前有效配置（断电时至少保留上一次的完整版本）
            if os.path.exists(self.config_path):
                try:
                    with open(self.config_path, 'r', encoding='utf-8') as f:
                        current = json.load(f)
                    if self._is_valid_settings(current):
                        with open(self.config_path + '.bak', 'w', encoding='utf-8') as f:
                            json.dump(current, f, indent=4, ensure_ascii=False)
                except Exception:
                    pass  # 当前主文件无效时静默跳过备份（如自动恢复场景）

            # 写入临时文件并刷盘，再原子替换，避免写入中断损坏主文件
            dir_name = os.path.dirname(self.config_path) or '.'
            tmp_path = os.path.join(dir_name, f'.settings_{os.getpid()}.tmp')
            try:
                with open(tmp_path, 'w', encoding='utf-8') as f:
                    json.dump(self.settings, f, indent=4, ensure_ascii=False)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp_path, self.config_path)
            finally:
                if os.path.exists(tmp_path):
                    try:
                        os.remove(tmp_path)
                    except OSError:
                        pass
            return True
        except Exception as e:
            print(f"保存设置失败: {e}")
            return False
    
    def get_setting(self, key):
        """获取设置项的值"""
        if key in self.settings:
            return self.settings[key].get('value', self.settings[key].get('default', ''))
        return None
    
    def set_setting(self, key, value):
        """设置设置项的值"""
        # print(f"设置 {key} 为 {value}")
        
        if key in self.settings:
            # 根据类型转换值
            setting_type = self.settings[key].get('type', 'string')
            try:
                if setting_type == 'boolean':
                    value = bool(value)
                elif setting_type == 'integer':
                    value = int(value)
                elif setting_type == 'float':
                    value = float(value)
                # string类型不需要转换
                
                self.settings[key]['value'] = value
                return True
            except (ValueError, TypeError):
                return False
        return False
    
    def reset_setting(self, key):
        """重置设置项为默认值"""
        if key in self.settings and 'default' in self.settings[key]:
            # 将default的值设置为value的值（还原设置）
            self.settings[key]['value'] = self.settings[key]['default']
            return True
        return False
    
    def reset_all_settings(self):
        """重置所有设置为默认值"""
        for key in self.settings:
            if 'default' in self.settings[key]:
                # 将default的值设置为value的值（还原设置）
                self.settings[key]['value'] = self.settings[key]['default']
        return True
    
    def get_all_settings(self):
        """获取所有设置项"""
        return self.settings
    
    def get_setting_info(self, key):
        """获取设置项的详细信息"""
        if key in self.settings:
            return self.settings[key]
        return None

# 全局设置管理器实例
_settings_manager = None

def get_settings_manager():
    """获取全局设置管理器实例"""
    global _settings_manager
    if _settings_manager is None:
        _settings_manager = SettingsManager()
    return _settings_manager