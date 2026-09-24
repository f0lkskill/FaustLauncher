#! 扩展工具 — 后端操作 (GUI 为 html/extension_tools/index.html, 经 extension_tools_window.py 的 js_api 调用)
#? 功能:
#? - 包装 Mod: 校验原始文件夹(须含 Installer.bat / Assets 文件夹 / Uninstaller.bat),
#?   复制必需结构到 mods/, 按用户填写的信息生成 icon.png 与 mod_info.json
#? - 生成插件模板: 在 addons/ 下生成 插件名/ 目录 (scr.py + icon.png + addon_info.json)
#? - 发布 Mod 信息: 压缩 Mod 本体, 图标/压缩包上传到蓝奏云 (FaustLauncher.icons / FaustLauncher.Mods),
#?   以 lz.qaiu.top 直链解析 URL 填写 dowload_url/icon_url, 再上传 mod_info 到 textdb
#? - 发布插件信息: 同样流程, 压缩包上传到蓝奏云 FaustLauncher.Addons (web_config.json → lanzou.addons_folder),
#?   再以同一套机制更新云端插件数据库 (web_config.json → webnote.addon_info)
#?   蓝奏云凭据 (phpdisk_info/ylogin) 配置于 config/web_config.json 的 lanzou 节
#?
#? Mod 与插件共用同一套核心 (INFO_KINDS 表 + upload_extension_*/publish_extension/upload_extension_info),
#? 差异只在: 本地目录/信息文件名/蓝奏云目标文件夹/云端笔记/头部计数字段。

import json
import os
import shutil
import tempfile
import zipfile

import requests

from PIL import Image, ImageDraw, ImageFont

from functions.base.web_config import get_webnote, get_lanzou_config
from functions.base.common.json_io import read_json, write_json

MODS_DIR = 'mods'
ADDONS_DIR = 'addons'
MOD_FILE_EXTS = ('.bank', '.carra2')
DEFAULT_ICON_BG = (30, 41, 59, 255)
DEFAULT_ICON_ACCENT = (99, 102, 241, 255)

PAGE_SIZE = 5  # 云端 mod 分页: 每页 5 个
TEXTDB_READ = 'https://textdb.online/{address}'
TEXTDB_UPDATE = 'https://textdb.online/update/?key={address}'
PARSER_BASE = 'https://lz.qaiu.top/parser?url='  # 蓝奏云直链解析服务 (与其他 mod 条目一致)


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
        write_json(os.path.join(target, 'addon_info.json'), info_json, indent=4)
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


def wrap_mod(source_folder, info=None, icon_path=None, extra_files=None, single_file=False):
    """包装 Mod: 校验必需文件, 复制到 mods/ 下, 按表单填写的信息生成图标与 mod_info.json

    info: {'name','desc','version','authors','file_names'} (file_names 为用户勾选)
    single_file: True=单文件 Mod 类型, 跳过 Installer.bat/Uninstaller.bat/Assets
                 必需结构检测, 仅复制勾选的 .bank/.carra2 等单文件
    返回 (成功, 消息)
    """
    source = (source_folder or '').strip()
    if not source:
        return False, '请先选择原始文件夹'
    if not os.path.isdir(source):
        return False, f'原始文件夹不存在: {source}'
    if not single_file:
        err = _validate_wrap_source(source)
        if err:
            return False, err
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
        # (单文件 Mod 跳过结构复制, 但仍做同名存在检查)
        if os.path.abspath(source) != os.path.abspath(target):
            if os.path.exists(target):
                return False, f'mods 下已存在同名 Mod: {target}'
            os.makedirs(target, exist_ok=True)
            if not single_file:
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
        info_json['settings'] = {'enable': True}
        if single_file:
            info_json['single_file'] = True
        write_json(os.path.join(target, 'mod_info.json'), info_json, indent=4)
        return True, f'Mod 包装完成: {target}'
    except Exception as e:
        return False, f'包装 Mod 失败: {e}'


# ============================================================
# 发布扩展信息到云端 (textdb) —— Mod / 插件 共用一套核心
# ============================================================

# 两类扩展的全部差异都集中在这张表里（以后再加第三类只需加一行）：
#   dir        本地目录
#   info_file  本地信息文件（发布时取 name/desc/authors/version）
#   note       web_config.json → webnote.<note> 的云端笔记
#   folder_key web_config.json → lanzou.<folder_key> 里放压缩包（图标统一放 icons_folder）
#   counter    云端首页头部里的“总数”字段名（两套笔记的字段名不一样）
INFO_KINDS = {
    'mod': {
        'dir': MODS_DIR, 'info_file': 'mod_info.json', 'note': 'mod_info',
        'label': 'Mod', 'body': 'Mod 本体',
        'folder_key': 'mods_folder', 'folder_default': 'FaustLauncher.Mods',
        'counter': 'total_mods',
    },
    'addon': {
        'dir': ADDONS_DIR, 'info_file': 'addon_info.json', 'note': 'addon_info',
        'label': '插件', 'body': '插件本体',
        'folder_key': 'addons_folder', 'folder_default': 'FaustLauncher.Addons',
        'counter': 'total_addons',
    },
}


def load_extension_info(kind, folder):
    """读取扩展目录下的信息文件, 返回 (info dict, 错误消息)

    kind: 'mod' | 'addon' (见 INFO_KINDS)
    """
    meta = INFO_KINDS.get(kind)
    if not meta:
        return None, f'未知的扩展类型: {kind}'
    label = meta['label']
    info_file = meta['info_file']
    folder = (folder or '').strip()
    if not folder:
        return None, f'请先选择 {label} 文件夹'
    if not os.path.isdir(folder):
        return None, f'{label} 文件夹不存在: {folder}'
    path = os.path.join(folder, info_file)
    if not os.path.isfile(path):
        return None, f'未找到 {info_file}: {path}'
    try:
        info = read_json(path)
    except Exception as e:
        return None, f'读取 {info_file} 失败: {e}'
    if not isinstance(info, dict):
        return None, f'{info_file} 内容不是对象格式'
    name = (info.get('name') or '').strip()
    if not name:
        return None, f'{info_file} 缺少 name 字段'
    # 兼容旧文档里的 addon_version（云端数据库字段统一叫 version）
    if not (info.get('version') or '').strip() and (info.get('addon_version') or '').strip():
        info['version'] = str(info['addon_version']).strip()
    return info, None


def load_mod_info(mod_folder):
    """读取 mod 文件夹下的 mod_info.json, 返回 (info dict, 错误消息)"""
    return load_extension_info('mod', mod_folder)


def load_addon_info(addon_folder):
    """读取插件文件夹下的 addon_info.json, 返回 (info dict, 错误消息)

    插件目录里比 Mod 多一个 settings 字段（本地启用状态），发布时不会写进云端。
    """
    return load_extension_info('addon', addon_folder)


def _fetch_note(address, label='Mod'):
    """只读拉取云端数据, 返回解析后的完整结构 (list) 或 None (笔记为空/不存在)。

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
        raise ValueError(f'云端{label}笔记结构异常 (应为 [总信息, 页1, 页2...])')
    return data


def _fetch_mod_note(address):
    """兼容旧名：拉取云端 Mod 数据。"""
    return _fetch_note(address, 'Mod')


# ============================================================
# 蓝奏云上传 (图标 + Mod 压缩包)
# ============================================================

def _lanzou_session(log=None):
    """按 web_config.json 的 lanzou 凭据登录蓝奏云, 返回 session (失败抛 RuntimeError)"""
    cfg = get_lanzou_config()
    cookie = {}
    for key in ('phpdisk_info', 'ylogin', 'ylogins'):
        if cfg.get(key):
            cookie[key] = str(cfg[key])
    if not cookie.get('phpdisk_info') or not cookie.get('ylogin'):
        raise RuntimeError('web_config.json 未配置 lanzou 凭据 (phpdisk_info/ylogin)')
    from functions.web_update.lanzou_utils import LoginByCookie
    if log:
        log('登录蓝奏云...')
    session = LoginByCookie(cookie)
    if not session:
        raise RuntimeError('蓝奏云登录失败: cookie 已失效, 请更新 web_config.json 中的 lanzou 凭据')
    return session


def _zip_folder(folder, target_zip, arc_name=None, progress=None, label='Mod'):
    """把文件夹根目录下所有内容打包为 zip (按文件数回报进度)

    zip 内所有条目置于 <arc_name>/ 顶层文件夹下（与历史包格式一致：
    下载器把 zip 解压到 mods/ （插件则是 addons/）根目录，
    顶层文件夹保证内容落进 mods/<名字>/ 、addons/<名字>/）
    """
    folder = os.path.abspath(folder)
    if not os.path.isdir(folder):
        raise RuntimeError(f'{label} 文件夹不存在: {folder}')
    arc_name = (arc_name or os.path.basename(folder.rstrip('\\/')) or label).strip().strip('/\\')
    if not arc_name:
        arc_name = label
    files = []
    for root, _dirs, fs in os.walk(folder):
        for f in fs:
            files.append(os.path.join(root, f))
    if not files:
        raise RuntimeError(f'{label} 文件夹为空, 无法打包')
    with zipfile.ZipFile(target_zip, 'w', zipfile.ZIP_DEFLATED) as zf:
        for i, full in enumerate(files):
            arc = os.path.join(arc_name, os.path.relpath(full, folder)).replace('\\', '/')
            zf.write(full, arc)
            if progress:
                progress((i + 1) / len(files) * 100, f'压缩中 {os.path.basename(full)} ({i + 1}/{len(files)})')


def _zip_mod_folder(mod_folder, target_zip, arc_name=None, progress=None):
    """兼容旧名：打包 Mod 文件夹。"""
    return _zip_folder(mod_folder, target_zip, arc_name=arc_name, progress=progress,
                       label='Mod')


def upload_extension_to_lanzou(kind, folder, log=None, progress=None):
    """压缩扩展本体 + 上传图标/压缩包 到蓝奏云，返回直链解析 URL 字典

    - kind='mod'  : 图标 → <icons_folder>，压缩包 → <mods_folder> (默认 FaustLauncher.Mods)
    - kind='addon': 图标 → <icons_folder>，压缩包 → <addons_folder> (默认 FaustLauncher.Addons)
    - 返回 {'icon_url','dowload_url','icon_share_url','mod_share_url'}
      (键名与旧版一致，插件也复用这组键，云端字段名本来就叫 dowload_url)
    - 失败抛 RuntimeError，异常对象带 partial_urls（已成功的链接，
      便于调用方继续更新数据库）
    """
    meta = INFO_KINDS.get(kind)
    if not meta:
        raise RuntimeError(f'未知的扩展类型: {kind}')
    if log is None:
        log = print
    label, body = meta['label'], meta['body']
    info, err = load_extension_info(kind, folder)
    if err:
        raise RuntimeError(err)
    name = info['name']  # type: ignore
    icon_path = os.path.join(folder, 'icon.png')
    if not os.path.isfile(icon_path):
        raise RuntimeError(f'缺少图标文件: {icon_path} '
                           f'(Mod 请先包装；插件请先生成模板/放上 icon.png)')

    cfg = get_lanzou_config()
    icons_folder = (cfg.get('icons_folder') or 'FaustLauncher.icons').strip()
    target_folder = (cfg.get(meta['folder_key']) or meta['folder_default']).strip()
    max_size_mb = int(cfg.get('max_size_mb') or 66)

    from functions.web_update.lanzou_utils import GetOrCreateFolder, UploadFile
    session = _lanzou_session(log)

    partial = {}  # 已成功的上传结果 (上传中途失败时带回)

    def _fail(msg):
        e = RuntimeError(msg)
        e.partial_urls = dict(partial)
        raise e

    tmpdir = tempfile.mkdtemp(prefix='fl_lanzou_')
    try:
        # 1. 压缩本体
        zip_path = os.path.join(tmpdir, f'{name}.zip')
        log(f'压缩{body}: {name}.zip')
        if progress:
            progress(0, f'压缩{body}...')
        _zip_folder(folder, zip_path, arc_name=name, progress=progress, label=label)
        zip_size_mb = os.path.getsize(zip_path) / 1024.0 / 1024.0
        log(f'压缩完成: {zip_size_mb:.1f} MB')
        # 压缩包超限时先记录，图标仍照常上传 (保证云端条目有图标)，到压缩包步骤才报错
        zip_too_big_msg = None
        if zip_size_mb > max_size_mb:
            zip_too_big_msg = (f'{label}包 {zip_size_mb:.1f} MB 超过蓝奏云单文件上限 {max_size_mb} MB'
                               f'（该账号实测约 66MB；可在 web_config.json 的 lanzou.max_size_mb 调整）')
            log(f'⚠ {zip_too_big_msg}（压缩包无法上传，仍会先上传图标供数据库使用）')

        # 2. 图标上传
        log(f'定位蓝奏云文件夹: {icons_folder}')
        icon_fid = GetOrCreateFolder(session, icons_folder)
        if not icon_fid:
            _fail(f'无法创建/定位蓝奏云文件夹: {icons_folder}')
        log('上传图标...')
        ret_icon = UploadFile(session, icon_path, folder_id=icon_fid,
                              progress_callback=lambda p: progress and progress(p * 100, f'上传图标 {p * 100:.0f}%'))
        if ret_icon.get('status') != 1:
            _fail(f'图标上传失败: {ret_icon.get("msg")}')
        icon_share = ret_icon.get('share_url') or ''
        partial = {
            'icon_url': PARSER_BASE + icon_share,
            'icon_share_url': icon_share,
        }

        # 3. 压缩包上传
        if zip_too_big_msg:
            _fail(zip_too_big_msg)
        log(f'定位蓝奏云文件夹: {target_folder}')
        pack_fid = GetOrCreateFolder(session, target_folder)
        if not pack_fid:
            _fail(f'无法创建/定位蓝奏云文件夹: {target_folder}')
        log('上传压缩包...')
        ret_pack = UploadFile(session, zip_path, folder_id=pack_fid, max_size_mb=max_size_mb,
                              progress_callback=lambda p: progress and progress(p * 100, f'上传压缩包 {p * 100:.0f}%'))
        if ret_pack.get('status') != 1:
            _fail(f'压缩包上传失败: {ret_pack.get("msg")}')
        pack_share = ret_pack.get('share_url') or ''

        return {
            'icon_url': PARSER_BASE + icon_share,
            'dowload_url': PARSER_BASE + pack_share,
            'icon_share_url': icon_share,
            'mod_share_url': pack_share,
        }
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def upload_mod_to_lanzou(mod_folder, log=None, progress=None):
    """压缩 Mod 本体, 图标 → 蓝奏云 <icons_folder>, 压缩包 → 蓝奏云 <mods_folder>"""
    return upload_extension_to_lanzou('mod', mod_folder, log=log, progress=progress)


def upload_addon_to_lanzou(addon_folder, log=None, progress=None):
    """压缩插件本体, 图标 → 蓝奏云 <icons_folder>, 压缩包 → 蓝奏云 <addons_folder>

    默认目标目录为 FaustLauncher.Addons（可在 web_config.json 的 lanzou.addons_folder 改）。
    """
    return upload_extension_to_lanzou('addon', addon_folder, log=log, progress=progress)


def publish_extension(kind, folder, address=None, log=None, progress=None):
    """完整发布: 蓝奏云上传 (图标+压缩包) → 直链解析 URL → 发布信息到 textdb

    蓝奏云上传失败时不会中止: 仍会将信息发布到云端数据库
    (已成功的链接会填入; 缺失的 dowload_url/icon_url 沿用云端旧值),
    返回 (False, 消息) 并在消息中同时说明上传失败原因与数据库更新结果。

    progress: 可选回调 (percent: float 0~100, text: str)
    返回 (成功, 消息)
    """
    meta = INFO_KINDS.get(kind)
    if not meta:
        return False, f'未知的扩展类型: {kind}'
    label = meta['label']
    if log is None:
        log = print
    upload_err = None
    urls = {}
    try:
        urls = upload_extension_to_lanzou(kind, folder, log=log, progress=progress)
    except Exception as e:
        upload_err = str(e)
        urls = getattr(e, 'partial_urls', None) or {}
        log(f'⚠ 蓝奏云上传失败: {upload_err}')
        log(f'继续发布{label}信息到云端（缺失链接将沿用云端旧值）...')
    if urls:
        log(f'图标链接: {urls.get("icon_url") or "(无, 沿用旧值)"}')
        log(f'下载链接: {urls.get("dowload_url") or "(无, 沿用旧值)"}')
    if progress:
        progress(100, f'更新云端{label}信息...')
    ok, msg = upload_extension_info(kind, folder, address=address, log=log, urls=urls,
                                    keep_old_urls=True)
    if upload_err:
        return False, f'上传失败: {upload_err} | 但{label}信息已更新到云端: {msg}'
    return ok, msg


def publish_mod(mod_folder, address=None, log=None, progress=None):
    """发布 Mod: 上传到蓝奏云 <mods_folder> + 更新云端 <mod_info> 数据库"""
    return publish_extension('mod', mod_folder, address=address, log=log, progress=progress)


def publish_addon(addon_folder, address=None, log=None, progress=None):
    """发布插件: 上传到蓝奏云 <addons_folder>（默认 FaustLauncher.Addons）
    + 更新云端 <addon_info> 数据库（与 Mod 完全同一套更新机制）
    """
    return publish_extension('addon', addon_folder, address=address, log=log, progress=progress)


def upload_extension_info(kind, folder, address=None, log=None, urls=None, keep_old_urls=True):
    """将扩展信息发布到云端笔记（Mod 用 <mod_info>，插件用 <addon_info>）

    - dowload_url/icon_url 取 urls（蓝奏云直链解析 URL），未提供时留空；
      keep_old_urls=True 且云端存在同名条目时，缺失的链接沿用云端旧值
    - 同名条目视为更新: 替换信息/链接并置顶，保留 download_count
    - 新条目插入第 1 页最前，并按每页 5 个重新分页；
      头部保留原有字段（total_page 重新计数，Mod 写 total_mods、插件写 total_addons）
    - 云端格式异常时中止 (不会覆盖云端)

    返回 (成功, 消息)
    """
    meta = INFO_KINDS.get(kind)
    if not meta:
        return False, f'未知的扩展类型: {kind}'
    label = meta['label']
    if log is None:
        log = print

    info, err = load_extension_info(kind, folder)
    if err:
        return False, err
    name = info['name']  # type: ignore
    if not address:
        address, _pwd = get_webnote(meta['note'])
    if not address:
        return False, f'web_config.json 未配置 {meta["note"]} 地址'

    urls = urls or {}

    try:
        log(f'读取云端{label}信息: {TEXTDB_READ.format(address=address)}\n')
        data = _fetch_note(address, label)

        # 笔记为空/不存在 -> 视为全新列表, 安全初始化 (不会覆盖已有数据)
        if data is None:
            data = [{}]
        header = dict(data[0]) if isinstance(data[0], dict) else {}

        # 检查同名条目: 存在则视为更新 (替换信息与链接, 保留 download_count)
        old_count = 0
        old_item = None
        for page in data[1:]:
            if not isinstance(page, list):
                continue
            for m in page:
                if isinstance(m, dict) and m.get('name') == name:
                    old_count = m.get('download_count') or 0
                    old_item = m

        # 缺失的链接沿用云端旧值 (上传失败后仍发布时, 保证下载链接不丢)
        dowload_url = urls.get('dowload_url') or ''
        icon_url = urls.get('icon_url') or ''
        if keep_old_urls and old_item:
            if not dowload_url:
                dowload_url = old_item.get('dowload_url') or ''
            if not icon_url:
                icon_url = old_item.get('icon_url') or ''

        # 条目字段与 Mod/插件数据库现有条目完全一致
        # (name/desc/authors/version/dowload_url/icon_url/download_count/disabled/is_new)
        item = {
            'name': name,
            'desc': (info.get('desc') or '').strip(),
            'authors': info.get('authors') or {},
            'version': (info.get('version') or '0.0.1').strip(),
            'dowload_url': dowload_url,
            'icon_url': icon_url,
            'download_count': old_count,
            'disabled': False,
            'is_new': True
        }

        # 新条目置顶, 重新按每页 5 个分页 (同名旧条目被替换)
        items = [item]
        for page in data[1:]:
            if not isinstance(page, list):
                continue
            for m in page:
                if isinstance(m, dict) and m.get('name') != name:
                    items.append(m)
        new_pages = [items[i * PAGE_SIZE:(i + 1) * PAGE_SIZE]
                     for i in range((len(items) + PAGE_SIZE - 1) // PAGE_SIZE)]
        header['total_page'] = len(new_pages)
        header[meta['counter']] = len(items)
        new_data = [header] + new_pages

        new_content = json.dumps(new_data, ensure_ascii=False, indent=4)
        log(f'上传{label}信息: {name}\n')
        ur = requests.post(TEXTDB_UPDATE.format(address=address),
                           data={'value': new_content},
                           verify=False, timeout=30)
        result = ur.json()
        if result.get('status') == 1:
            return True, f'发布成功: {name} → {TEXTDB_READ.format(address=address)}'
        return False, f'发布失败: {result}'
    except Exception as e:
        return False, f'发布失败: {e}'


def upload_mod_info(mod_folder, address=None, log=None, urls=None, keep_old_urls=True):
    """将 Mod 信息发布到 textdb (默认使用 web_config.json 中 mod_info 的地址)"""
    return upload_extension_info('mod', mod_folder, address=address, log=log, urls=urls,
                                 keep_old_urls=keep_old_urls)


def upload_addon_info(addon_folder, address=None, log=None, urls=None, keep_old_urls=True):
    """将插件信息发布到 textdb (默认使用 web_config.json 中 addon_info 的地址)

    与 upload_mod_info 完全同一套机制：同名更新、保留 download_count、
    缺失链接沿用旧值、分页与头部计数（total_addons）重算。
    """
    return upload_extension_info('addon', addon_folder, address=address, log=log, urls=urls,
                                 keep_old_urls=keep_old_urls)