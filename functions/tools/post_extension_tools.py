#! 扩展工具 — 后端操作 (GUI 为 html/extension_tools/index.html, 经 extension_tools_window.py 的 js_api 调用)
#? 功能:
#? - 包装 Mod: 校验原始文件夹(须含 Installer.bat / Assets 文件夹 / Uninstaller.bat),
#?   复制必需结构到 mods/, 按用户填写的信息生成 icon.png 与 mod_info.json
#? - 生成插件模板: 在 addons/ 下生成 插件名/ 目录 (scr.py + icon.png + addon_info.json)
#? - 发布 Mod 信息: 上传 mod_info.json 到 web_config.json 中 mod_info 指定的 textdb 笔记,
#?   字段与云端现有 mod 一致 (dowload_url/icon_url 留空)

import json
import os
import shutil

import requests

from PIL import Image, ImageDraw, ImageFont

from functions.base.web_config import get_webnote

MODS_DIR = 'mods'
ADDONS_DIR = 'addons'
MOD_FILE_EXTS = ('.bank', '.carra2')
DEFAULT_ICON_BG = (30, 41, 59, 255)
DEFAULT_ICON_ACCENT = (99, 102, 241, 255)

PAGE_SIZE = 5  # 云端 mod 分页: 每页 5 个
TEXTDB_READ = 'https://textdb.online/{address}'
TEXTDB_UPDATE = 'https://textdb.online/update/?key={address}'


# ============================================================
# 图标生成
# ============================================================

def generate_icon(path, text=''):
    """生成默认占位图标 (256x256 圆角边框 + 首字符)"""
    img = Image.new('RGBA', (256, 256), DEFAULT_ICON_BG)
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([8, 8, 247, 247], radius=24,
                           outline=DEFAULT_ICON_ACCENT, width=6)
    if text:
        try:
            font = ImageFont.truetype('msyh.ttc', 110)
        except Exception:
            font = ImageFont.load_default()
        draw.text((128, 128), text[0], font=font, fill=(226, 232, 240, 255),
                  anchor='mm')
    img.save(path)


# ============================================================
# 生成插件模板
# ============================================================

ADDON_INFO_TEMPLATE = {
    'name': '',
    'desc': '',
    'authors': {},
    'settings': {'enable': False},
    'version': '0.0.1',
}

SCR_TEMPLATE = """# 插件代码入口: 在此编写插件的加载逻辑
# 可用全局变量: ADDON_ARG (含 AddonManager / AddonName)
# 完整示例请参考 addons/example/scr.py
"""


def spawn_extension(name, info=None):
    """在 addons/ 下生成插件模板 (info 为表单填写的 addon_info 字段), 返回 (成功, 消息)"""
    name = (name or '').strip()
    if not name:
        return False, '插件名称不能为空'
    if not os.path.isdir(ADDONS_DIR):
        return False, f'未找到 addons 目录: {os.path.abspath(ADDONS_DIR)}'
    target = os.path.join(ADDONS_DIR, name)
    if os.path.exists(target):
        return False, f'插件 {name} 已存在: {target}'
    try:
        os.makedirs(target)
        # 空的 scr.py
        with open(os.path.join(target, 'scr.py'), 'w', encoding='utf-8') as f:
            f.write(SCR_TEMPLATE)
        # 图标: 用户选择的自定义图标或生成的默认图标
        if info and info.get('icon_path'):
            shutil.copy2(info['icon_path'], os.path.join(target, 'icon.png'))
        else:
            generate_icon(os.path.join(target, 'icon.png'), text=name)
        # addon_info.json (用户填写字段)
        info_json = dict(ADDON_INFO_TEMPLATE)
        info_json['name'] = name
        if info:
            info_json['desc'] = (info.get('desc') or '').strip()
            info_json['authors'] = info.get('authors') or {}
            info_json['version'] = (info.get('version') or '0.0.1').strip() or '0.0.1'
        with open(os.path.join(target, 'addon_info.json'), 'w', encoding='utf-8') as f:
            json.dump(info_json, f, ensure_ascii=False, indent=4)
        return True, f'插件模板已生成: {target}'
    except Exception as e:
        shutil.rmtree(target, ignore_errors=True)
        return False, f'生成插件模板失败: {e}'


# ============================================================
# 包装 Mod
# ============================================================

def _scan_mod_files(mod_dir):
    """扫描 mod 根目录下的单文件 (.bank/.carra2), 用于 file_names"""
    result = []
    try:
        for f in os.listdir(mod_dir):
            full = os.path.join(mod_dir, f)
            if os.path.isfile(full) and os.path.splitext(f)[1].lower() in MOD_FILE_EXTS:
                result.append(f)
    except Exception:
        pass
    return sorted(result)


def _validate_wrap_source(source_folder):
    """校验 Mod 原始文件夹, 返回错误消息 (None 表示通过)"""
    source = (source_folder or '').strip()
    if not source:
        return '请先选择原始文件夹'
    if not os.path.isdir(source):
        return f'原始文件夹不存在: {source}'
    entries = {e.lower(): e for e in os.listdir(source)}
    required = ('installer.bat', 'uninstaller.bat', 'assets')
    missing = [r for r in required if r not in entries]
    if missing:
        return '原始文件夹缺少必需内容: ' + ', '.join(missing) + \
               '\n(需要 Installer.bat / Uninstaller.bat / Assets 文件夹)'
    if not os.path.isdir(os.path.join(source, entries['assets'])):
        return 'Assets 必须是文件夹'
    return None


def wrap_mod(source_folder, info=None, icon_path=None, extra_files=None):
    """包装 Mod: 校验必需文件, 复制到 mods/ 下, 按表单填写的信息生成图标与 mod_info.json

    info: {'name','desc','version','authors','file_names'} (file_names 为用户勾选)
    返回 (成功, 消息)
    """
    err = _validate_wrap_source(source_folder)
    if err:
        return False, err

    source = source_folder.strip()
    info = info or {}
    extra_files = extra_files or info.get('extra_files') or []
    icon_path = icon_path or info.get('icon_path')
    name = (info.get('name') or os.path.basename(os.path.normpath(source))).strip()
    if not name:
        return False, '无法确定 Mod 名称'
    entries = {e.lower(): e for e in os.listdir(source)}
    target = os.path.join(MODS_DIR, name)
    try:
        if not os.path.isdir(MODS_DIR):
            os.makedirs(MODS_DIR)
        # 复制 mod 必需结构: Installer.bat / Uninstaller.bat / Assets / changes.json
        if os.path.abspath(source) != os.path.abspath(target):
            if os.path.exists(target):
                return False, f'mods 下已存在同名 Mod: {target}'
            for entry in ('installer.bat', 'uninstaller.bat', 'assets', 'changes.json'):
                real = entries.get(entry)
                if not real:
                    continue
                src_entry = os.path.join(source, real)
                dst_entry = os.path.join(target, real)
                if os.path.isdir(src_entry):
                    shutil.copytree(src_entry, dst_entry)
                else:
                    os.makedirs(os.path.dirname(dst_entry), exist_ok=True)
                    shutil.copy2(src_entry, dst_entry)
        # 用户额外勾选的文件复制到 mod 根目录
        extra_names = []
        for f in extra_files:
            if not f or not os.path.isfile(f):
                continue
            shutil.copy2(f, os.path.join(target, os.path.basename(f)))
            extra_names.append(os.path.basename(f))
        # 表单勾选的源目录单文件 (.bank/.carra2) 复制到 mod 根目录
        # (mod 加载器按 file_names 从 mod 根目录复制文件, 必须真实存在)
        file_names = sorted(set(info.get('file_names') or []) | set(extra_names))
        same_dir = os.path.abspath(source) == os.path.abspath(target)
        for fn in file_names:
            src_file = os.path.join(source, fn)
            dst_file = os.path.join(target, fn)
            if os.path.isfile(src_file) and (same_dir or os.path.abspath(src_file) != os.path.abspath(dst_file)):
                shutil.copy2(src_file, dst_file)
        # 图标: 用户选择的自定义图标, 否则生成默认
        target_icon = os.path.join(target, 'icon.png')
        if icon_path and os.path.isfile(icon_path):
            shutil.copy2(icon_path, target_icon)
        elif not os.path.exists(target_icon):
            generate_icon(target_icon, text=name)
        # mod_info.json (用户填写字段)
        info_json = dict(ADDON_INFO_TEMPLATE)
        info_json['name'] = name
        info_json['desc'] = (info.get('desc') or '').strip()
        info_json['authors'] = info.get('authors') or {}
        info_json['version'] = (info.get('version') or '0.0.1').strip() or '0.0.1'
        info_json['file_names'] = file_names
        with open(os.path.join(target, 'mod_info.json'), 'w', encoding='utf-8') as f:
            json.dump(info_json, f, ensure_ascii=False, indent=4)
        return True, f'Mod 包装完成: {target}'
    except Exception as e:
        return False, f'包装 Mod 失败: {e}'


# ============================================================
# 发布 Mod 信息到云端 (textdb)
# ============================================================

def load_mod_info(mod_folder):
    """读取 mod 文件夹下的 mod_info.json, 返回 (info dict, 错误消息)"""
    folder = (mod_folder or '').strip()
    if not folder:
        return None, '请先选择 Mod 文件夹'
    if not os.path.isdir(folder):
        return None, f'Mod 文件夹不存在: {folder}'
    path = os.path.join(folder, 'mod_info.json')
    if not os.path.isfile(path):
        return None, f'未找到 mod_info.json: {path}'
    try:
        with open(path, 'r', encoding='utf-8') as f:
            info = json.load(f)
    except Exception as e:
        return None, f'读取 mod_info.json 失败: {e}'
    if not isinstance(info, dict):
        return None, 'mod_info.json 内容不是对象格式'
    name = (info.get('name') or '').strip()
    if not name:
        return None, 'mod_info.json 缺少 name 字段'
    return info, None


def _fetch_mod_note(address):
    """只读拉取云端 mod 数据, 返回解析后的完整结构 (list) 或 None (笔记为空/不存在)。

    格式异常时抛 ValueError。
    """
    r = requests.get(TEXTDB_READ.format(address=address), verify=False, timeout=20)
    r.raise_for_status()
    text = r.text.strip()
    if not text:
        return None
    try:
        data = json.loads(text)
    except Exception as e:
        raise ValueError(f'云端笔记不是合法 JSON: {e}')
    if not isinstance(data, list) or not data or not isinstance(data[0], dict):
        raise ValueError('云端笔记结构异常 (应为 [总信息, 页1, 页2...])')
    return data


def upload_mod_info(mod_folder, address=None, log=None):
    """将 Mod 信息发布到 textdb (默认使用 web_config.json 中 mod_info 的地址)

    - 字段与云端现有 mod 一致, dowload_url/icon_url 预置空值, 由服务器侧填写
    - 新 Mod 插入第 1 页最前, 并按每页 5 个重新分页, 更新 total_page/total_mods
    - 云端格式异常或存在同名 Mod 时中止 (不会覆盖云端)

    返回 (成功, 消息)
    """
    if log is None:
        log = print

    info, err = load_mod_info(mod_folder)
    if err:
        return False, err
    name = info['name']
    if not address:
        address, _pwd = get_webnote('mod_info')
    if not address:
        return False, 'web_config.json 未配置 mod_info 地址'

    try:
        log(f'读取云端 Mod 信息: {TEXTDB_READ.format(address=address)}\n')
        data = _fetch_mod_note(address)

        # 笔记为空/不存在 -> 视为全新列表, 安全初始化 (不会覆盖已有数据)
        if data is None:
            data = [{'total_page': 0, 'total_mods': 0}]

        # 检查同名 Mod
        for page in data[1:]:
            if not isinstance(page, list):
                continue
            for m in page:
                if isinstance(m, dict) and m.get('name') == name:
                    return False, f'云端已存在同名 Mod: {name}, 已中止上传'

        # 新 Mod 条目 (dowload_url/icon_url 留空, 由服务器侧填写)
        item = {
            'name': name,
            'desc': (info.get('desc') or '').strip(),
            'authors': info.get('authors') or {},
            'version': (info.get('version') or '0.0.1').strip(),
            'dowload_url': '',
            'icon_url': '',
            'download_count': 0,
            'disabled': False,
        }

        # 新 Mod 置顶, 重新按每页 5 个分页
        mods = [item]
        for page in data[1:]:
            if isinstance(page, list):
                mods.extend(m for m in page if isinstance(m, dict))
        new_pages = [mods[i * PAGE_SIZE:(i + 1) * PAGE_SIZE]
                     for i in range((len(mods) + PAGE_SIZE - 1) // PAGE_SIZE)]
        new_data = [{'total_page': len(new_pages), 'total_mods': len(mods)}] + new_pages

        new_content = json.dumps(new_data, ensure_ascii=False, indent=4)
        log(f'上传 Mod 信息: {name}\n')
        ur = requests.post(TEXTDB_UPDATE.format(address=address),
                           data={'value': new_content},
                           verify=False, timeout=30)
        result = ur.json()
        if result.get('status') == 1:
            return True, f'发布成功: {name} → {TEXTDB_READ.format(address=address)}'
        return False, f'发布失败: {result}'
    except Exception as e:
        return False, f'发布失败: {e}'