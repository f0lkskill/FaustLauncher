"""启动器设置的唯一读写入口。

配置文件是 ``config/settings.json``，每一项都是含 name/type/default/value/
description/page 的对象。设置页、Web API、启动流程和插件统一通过
:func:`get_settings_manager` 拿同一个单例，不直接读写 JSON 文件。

已下线功能对应的键收口在 ``_RETIRED_SETTINGS``：读取恒返回关闭值、写入被
拒绝、schema 也不再暴露，避免旧配置文件把已经关掉的入口重新打开。
"""

import os
from functions.base.common.json_io import read_json, write_json
from functions.base.launcher_mode import STEAM_BINDING_KEY

#: 已下线功能对应的设置键 -> 对外强制暴露的值。
#:
#: 老版本的 config/settings.json（以及用户的旧部署）里可能还留着这些键，
#: 甚至存着 true。把它们收口在这里统一处理：设置页不再渲染，任何读取方
#: 都只能拿到“未开启”，写入请求也一律拒绝 —— 这样功能入口真正关闭，
#: 不会因为是旧配置文件就悄悄复活。
_RETIRED_SETTINGS = {
    STEAM_BINDING_KEY: False,
}


class SettingsManager:
    """内存中的设置表及其持久化。

    构造时立即载入配置；之后所有改动都只改内存，调用方显式调用
    :meth:`save_settings` 才会落盘。这样一次操作里的多次 set 只写一次文件。
    """

    def __init__(self, config_path="config/settings.json"):
        """按路径载入设置，路径相对于启动器的工作目录。

        Args:
            config_path: 设置文件路径，默认 ``config/settings.json``。
        """
        self.config_path = config_path
        self.settings = {}
        self.load_settings()

    def _is_valid_settings(self, data):
        """判断一份数据能不能当设置表用。空的 dict 一律视为损坏。"""
        return isinstance(data, dict) and len(data) > 0

    def _load_from_file(self, path):
        """从文件读设置表；读不到或格式无效时返回 None 而不是抛异常。"""
        try:
            if os.path.exists(path):
                data = read_json(path)
                if self._is_valid_settings(data):
                    return data
        except Exception as e:
            print(f"读取配置 {path} 失败: {e}")
        return None

    def load_settings(self):
        """载入配置：主文件优先，损坏时回退到 .bak，二者都没有则留空表。"""
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
        """把内存设置原子写回文件，成功返回 True。

        写入前先把当前有效文件复制成 ``.bak``，再用同目录临时文件 +
        ``os.replace`` 落盘，避免中途断电留下半截 JSON。

        Returns:
            bool: 是否写入成功；内容无效时拒绝写入并返回 False。
        """
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
        """取一个设置项的生效值，也是所有读取方唯一应该走的入口。

        Args:
            key: 设置键名。

        Returns:
            已下线键恒返回其规定的关闭值；不存在的键返回 None；其余返回
            ``value``，缺 ``value`` 时退到 ``default``。
        """
        # 总入口兜底：下线的设置项无论文件里写的是什么，都按“未开启”返回。
        if key in _RETIRED_SETTINGS:
            return _RETIRED_SETTINGS[key]
        if key in self.settings:
            return self.settings[key].get('value', self.settings[key].get('default', ''))
        return None
    
    def set_setting(self, key, value):
        """按声明的 type 转换并写入一个设置值，只改内存不落盘。

        Args:
            key: 设置键名。
            value: 新值；boolean/integer/float 会先按类型强制转换。

        Returns:
            bool: 键不存在、类型无法转换或键已下线时返回 False。
        """
        # 已下线的入口不接受写入，避免旧界面/接口把值改回 true。
        if key in _RETIRED_SETTINGS:
            return False
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
        """把单个设置项恢复为 default；没有 default 或键已下线则返回 False。"""
        if key in _RETIRED_SETTINGS:
            return False
        if key in self.settings and 'default' in self.settings[key]:
            self.settings[key]['value'] = self.settings[key]['default']
            return True
        return False
    
    def reset_all_settings(self):
        """把所有带 default 的设置项恢复默认值（不落盘）。"""
        for key in self.settings:
            if 'default' in self.settings[key]:
                self.settings[key]['value'] = self.settings[key]['default']
        return True
    
    def get_all_settings(self):
        """返回供设置页渲染的完整 schema 副本，已下线键被过滤掉。

        Returns:
            dict: ``{key: setting_info}``。返回的是新字典，调用方改动它不会
            影响管理器内部的设置表。
        """
        # 设置页拿这份数据渲染；过滤掉下线项，旧配置文件也不会把它显示出来。
        return {key: info for key, info in self.settings.items()
                if key not in _RETIRED_SETTINGS}
    
    def get_setting_info(self, key):
        """返回设置项的定义（name/type/default/...），已下线键视为不存在。"""
        if key in _RETIRED_SETTINGS:
            return None
        if key in self.settings:
            return self.settings[key]
        return None

_settings_manager = None

def get_settings_manager():
    """返回进程内唯一的设置管理器，首次调用时按默认路径载入配置。

    Returns:
        SettingsManager: 全局单例。
    """
    global _settings_manager
    if _settings_manager is None:
        _settings_manager = SettingsManager()
    return _settings_manager
