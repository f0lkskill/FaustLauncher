#! 扩展工具 — 后端操作 (GUI 为 web/extension_tools/index.html, 经 extension_tools_window.py 的 js_api 调用)

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

PAGE_SIZE = 5

PARSER_BASE = 'https://lz.qaiu.top/parser?url='

def _note_read_url(address):
    try:
        from functions.webFunc.Webnote import get_note_bases
        bases = get_note_bases()
        base = str((bases[0] if bases else '') or '').strip()
    except Exception:
        base = ''
    if not base:
        return ''
    return (base.replace('{key}', str(address)) if '{key}' in base
            else base.rstrip('/') + '/' + str(address))

def generate_icon(path, text=''):
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
        with open(os.path.join(target, 'scr.py'), 'w', encoding='utf-8') as f:
            f.write(SCR_TEMPLATE)
        if info and info.get('icon_path'):
            shutil.copy2(info['icon_path'], os.path.join(target, 'icon.png'))
        else:
            generate_icon(os.path.join(target, 'icon.png'), text=name)
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

def _scan_mod_files(mod_dir):
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
    created_target = False
    try:
        if not os.path.isdir(MODS_DIR):
            os.makedirs(MODS_DIR)
        if os.path.abspath(source) != os.path.abspath(target):
            if os.path.exists(target):
                return False, f'mods 下已存在同名 Mod: {target}'
            os.makedirs(target, exist_ok=True)
            created_target = True
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
        extra_names = []
        for f in extra_files:
            if not f or not os.path.isfile(f):
                continue
            shutil.copy2(f, os.path.join(target, os.path.basename(f)))
            extra_names.append(os.path.basename(f))
        file_names = sorted(set(info.get('file_names') or []) | set(extra_names))
        same_dir = os.path.abspath(source) == os.path.abspath(target)
        for fn in file_names:
            src_file = os.path.join(source, fn)
            dst_file = os.path.join(target, fn)
            if os.path.isfile(src_file) and not same_dir:
                shutil.copy2(src_file, dst_file)
        target_icon = os.path.join(target, 'icon.png')
        if icon_path and os.path.isfile(icon_path):
            shutil.copy2(icon_path, target_icon)
        elif not os.path.exists(target_icon):
            generate_icon(target_icon, text=name)
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
        if created_target:
            shutil.rmtree(target, ignore_errors=True)
            print(f"包装失败, 已回滚残留目录: {target}", flush=True)
        return False, f'包装 Mod 失败: {e}'

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
    if not (info.get('version') or '').strip() and (info.get('addon_version') or '').strip():
        info['version'] = str(info['addon_version']).strip()
    return info, None

def load_mod_info(mod_folder):
    return load_extension_info('mod', mod_folder)

def load_addon_info(addon_folder):
    return load_extension_info('addon', addon_folder)

def _fetch_note(address, label='Mod'):
    from functions.webFunc.Webnote import read_note_live
    text, _used, err = read_note_live(None, address)
    text = str(text or '').strip()
    if not text:
        url = _note_read_url(address)
        if url:
            try:
                probe = requests.get(url, verify=False, timeout=20)
            except Exception as e:
                raise RuntimeError(f'云端{label}笔记读取失败: {e}')
            if probe.status_code == 200 and not (probe.text or '').strip():
                return None
        raise RuntimeError(f'云端{label}笔记读取失败: {err or "内容为空"}')
    try:
        data = json.loads(text)
    except Exception as e:
        raise ValueError(f'云端笔记不是合法 JSON: {e}')
    if not isinstance(data, list) or not data or not isinstance(data[0], dict):
        raise ValueError(f'云端{label}笔记结构异常 (应为 [总信息, 页1, 页2...])')
    return data

def _fetch_mod_note(address):
    return _fetch_note(address, 'Mod')

def _lanzou_session(log=None):
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
    return _zip_folder(mod_folder, target_zip, arc_name=arc_name, progress=progress,
                       label='Mod')

def upload_extension_to_lanzou(kind, folder, log=None, progress=None):
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

    partial = {}

    def _fail(msg):
        e = RuntimeError(msg)
        e.partial_urls = dict(partial)
        raise e

    tmpdir = tempfile.mkdtemp(prefix='fl_lanzou_')
    try:
        zip_path = os.path.join(tmpdir, f'{name}.zip')
        log(f'压缩{body}: {name}.zip')
        if progress:
            progress(0, f'压缩{body}...')
        _zip_folder(folder, zip_path, arc_name=name, progress=progress, label=label)
        zip_size_mb = os.path.getsize(zip_path) / 1024.0 / 1024.0
        log(f'压缩完成: {zip_size_mb:.1f} MB')
        zip_too_big_msg = None
        if zip_size_mb > max_size_mb:
            zip_too_big_msg = (f'{label}包 {zip_size_mb:.1f} MB 超过蓝奏云单文件上限 {max_size_mb} MB'
                               f'（该账号实测约 66MB；可在 web_config.json 的 lanzou.max_size_mb 调整）')
            log(f'⚠ {zip_too_big_msg}（压缩包无法上传，仍会先上传图标供数据库使用）')

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
        if not icon_share:
            _fail('图标上传返回成功但缺少 share_url, 无法生成直链')
        partial = {
            'icon_url': PARSER_BASE + icon_share,
            'icon_share_url': icon_share,
        }

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
        if not pack_share:
            _fail('压缩包上传返回成功但缺少 share_url, 无法生成直链')

        return {
            'icon_url': PARSER_BASE + icon_share,
            'dowload_url': PARSER_BASE + pack_share,
            'icon_share_url': icon_share,
            'mod_share_url': pack_share,
        }
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

def upload_mod_to_lanzou(mod_folder, log=None, progress=None):
    return upload_extension_to_lanzou('mod', mod_folder, log=log, progress=progress)

def upload_addon_to_lanzou(addon_folder, log=None, progress=None):
    return upload_extension_to_lanzou('addon', addon_folder, log=log, progress=progress)

def publish_extension(kind, folder, address=None, log=None, progress=None):
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
    return publish_extension('mod', mod_folder, address=address, log=log, progress=progress)

def publish_addon(addon_folder, address=None, log=None, progress=None):
    return publish_extension('addon', addon_folder, address=address, log=log, progress=progress)

def upload_extension_info(kind, folder, address=None, log=None, urls=None, keep_old_urls=True):
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
        log(f'读取云端{label}信息: {address}\n')
        data = _fetch_note(address, label)

        if data is None:
            data = [{}]
        header = dict(data[0]) if isinstance(data[0], dict) else {}

        old_count = 0
        old_item = None
        for page in data[1:]:
            if not isinstance(page, list):
                continue
            for m in page:
                if isinstance(m, dict) and m.get('name') == name:
                    old_count = m.get('download_count') or 0
                    old_item = m

        dowload_url = urls.get('dowload_url') or ''
        icon_url = urls.get('icon_url') or ''
        if keep_old_urls and old_item:
            if not dowload_url:
                dowload_url = old_item.get('dowload_url') or ''
            if not icon_url:
                icon_url = old_item.get('icon_url') or ''

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
        # 依赖声明：只有本地确实写了 requires 才带上这个键，这样启动器下载插件时
        # 才知道要先把依赖装上；没有依赖的插件，云端条目里也不会多出一个空数组。
        requires = info.get('requires')
        if isinstance(requires, str):
            requires = [requires]
        requires = [str(x).strip() for x in (requires or []) if str(x).strip()]
        if requires:
            item['requires'] = requires
            log(f'{label} {name} 依赖: {", ".join(requires)}\n')
        # 依赖库自身（permanent）也照实写上去，方便界面标注成"永久启用"
        if info.get('permanent'):
            item['permanent'] = True
        provides = info.get('provides')
        if isinstance(provides, str):
            provides = [provides]
        provides = [str(x).strip() for x in (provides or []) if str(x).strip()]
        if provides:
            item['provides'] = provides

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
        from functions.webFunc.Webnote import write_note
        res = write_note(address, new_content)
        if res.get('status') == 1:
            return True, f'发布成功: {name} → {address}'
        return False, f'发布失败: {res.get("error") or res}'
    except Exception as e:
        return False, f'发布失败: {e}'

def upload_mod_info(mod_folder, address=None, log=None, urls=None, keep_old_urls=True):
    return upload_extension_info('mod', mod_folder, address=address, log=log, urls=urls,
                                 keep_old_urls=keep_old_urls)

def upload_addon_info(addon_folder, address=None, log=None, urls=None, keep_old_urls=True):
    return upload_extension_info('addon', addon_folder, address=address, log=log, urls=urls,
                                 keep_old_urls=keep_old_urls)
