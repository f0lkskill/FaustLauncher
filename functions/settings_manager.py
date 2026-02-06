import json
import os
from pathlib import Path

class SettingsManager:
    def __init__(self, config_path="config/settings.json"):
        self.config_path = config_path
        self.settings = {}
        self.load_settings()
    
    def load_settings(self):
        """加载设置文件"""
        try:
            if os.path.exists(self.config_path):
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    self.settings = json.load(f)
        except Exception as e:
            print(f"加载设置失败: {e}")
    
    def save_settings(self):
        """保存设置到文件"""
        try:
            # 确保目录存在
            os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(self.settings, f, indent=4, ensure_ascii=False)
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