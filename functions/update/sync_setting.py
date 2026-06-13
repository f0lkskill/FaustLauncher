# 同步两个版本的设置

CURRENT_COFIG_FILE = "config/settings.json"
TARGET_CONFIG_FILE = "cache/new_version/FaustLauncher/config/settings.json"

import json

def sync_settings():
    with open(CURRENT_COFIG_FILE, 'r', encoding='utf-8') as f:
        current_config = json.load(f)

    with open(TARGET_CONFIG_FILE, 'r', encoding='utf-8') as f:
        target_config = json.load(f)

    for key, value in current_config.items():
        if key == 'version_info':
            continue
        if key in target_config:
            try:
                target_config[key]['value'] = value['value']
            except:
                pass

    with open(TARGET_CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(target_config, f, indent=4, ensure_ascii=False)