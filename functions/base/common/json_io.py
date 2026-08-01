import json


def read_json(path):
    """读取JSON文件"""
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def write_json(path, data, indent=4):
    """写入JSON文件"""
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=indent)
