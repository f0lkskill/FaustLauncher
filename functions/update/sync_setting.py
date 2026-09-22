# 同步两个版本的设置

CURRENT_CONFIG_FILE = "config/settings.json"
TARGET_CONFIG_FILE = "cache/new_version/FaustLauncher/config/settings.json"

import json
import os
from functions.base.common.json_io import read_json, write_json

def sync_settings():
    if not os.path.exists(CURRENT_CONFIG_FILE):
        print(f"跳过设置同步：源文件不存在 {CURRENT_CONFIG_FILE}")
        return
    if not os.path.exists(TARGET_CONFIG_FILE):
        print(f"跳过设置同步：目标文件不存在 {TARGET_CONFIG_FILE}")
        return
    
    current_config = read_json(CURRENT_CONFIG_FILE)

    target_config = read_json(TARGET_CONFIG_FILE)

    # 不能同步版本信息，否则意味着重复的更新。
    black_keys = ['version_info']
    for key, value in current_config.items():
        if key in black_keys:
            continue
        if key in target_config:
            try:
                # 同步设置值
                target_config[key]['value'] = value['value']
            except:
                pass

    write_json(TARGET_CONFIG_FILE, target_config, indent=4)