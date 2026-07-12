# 同步两个版本的设置

CURRENT_COFIG_FILE = "config/settings.json"
TARGET_CONFIG_FILE = "cache/new_version/FaustLauncher/config/settings.json"

import json

def sync_settings():
    with open(CURRENT_COFIG_FILE, 'r', encoding='utf-8') as f:
        current_config = json.load(f)

    with open(TARGET_CONFIG_FILE, 'r', encoding='utf-8') as f:
        target_config = json.load(f)

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

    with open(TARGET_CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(target_config, f, indent=4, ensure_ascii=False)