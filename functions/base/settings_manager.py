import os
from functions.base.common.json_io import read_json, write_json

class SettingsManager:
    def __init__(self, config_path="config/settings.json"):
        self.config_path = config_path
        self.settings = {}
        self.load_settings()

    def _is_valid_settings(self, data):
        return isinstance(data, dict) and len(data) > 0

    def _load_from_file(self, path):
        try:
            if os.path.exists(path):
                data = read_json(path)
                if self._is_valid_settings(data):
                    return data
        except Exception as e:
            print(f"读取配置 {path} 失败: {e}")
        return None

    def load_settings(self):
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
        if not self._is_valid_settings(self.settings):
            print("警告: 配置内容无效，拒绝保存，避免覆盖有效配置文件")
            return False
        try:
            os.makedirs(os.path.dirname(self.config_path), exist_ok=True)

            if os.path.exists(self.config_path):
                try:
                    current = read_json(self.config_path)
                    if self._is_valid_settings(current):
                        write_json(self.config_path + '.bak', current, indent=4)
                except Exception:
                    pass

            dir_name = os.path.dirname(self.config_path) or '.'
            tmp_path = os.path.join(dir_name, f'.settings_{os.getpid()}.tmp')
            try:
                write_json(tmp_path, self.settings, indent=4, fsync=True)
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
        if key in self.settings:
            return self.settings[key].get('value', self.settings[key].get('default', ''))
        return None
    
    def set_setting(self, key, value):
        
        if key in self.settings:
            setting_type = self.settings[key].get('type', 'string')
            try:
                if setting_type == 'boolean':
                    value = bool(value)
                elif setting_type == 'integer':
                    value = int(value)
                elif setting_type == 'float':
                    value = float(value)
                
                self.settings[key]['value'] = value
                return True
            except (ValueError, TypeError):
                return False
        return False
    
    def reset_setting(self, key):
        if key in self.settings and 'default' in self.settings[key]:
            self.settings[key]['value'] = self.settings[key]['default']
            return True
        return False
    
    def reset_all_settings(self):
        for key in self.settings:
            if 'default' in self.settings[key]:
                self.settings[key]['value'] = self.settings[key]['default']
        return True
    
    def get_all_settings(self):
        return self.settings
    
    def get_setting_info(self, key):
        if key in self.settings:
            return self.settings[key]
        return None

_settings_manager = None

def get_settings_manager():
    global _settings_manager
    if _settings_manager is None:
        _settings_manager = SettingsManager()
    return _settings_manager
