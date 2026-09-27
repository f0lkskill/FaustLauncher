# -*- mode: python ; coding: utf-8 -*-
import os as _os, sys as _sys

_tcl_dir = _os.path.join(_os.path.dirname(_os.path.abspath(_sys.executable)), 'tcl')
if not _os.path.isdir(_tcl_dir):
    _tcl_dir = _os.path.join(_sys.prefix, 'tcl')

_datas = []
if _tcl_dir and _os.path.isdir(_tcl_dir):
    _datas.append((_tcl_dir, 'tcl'))

# 收集 pyfiglet 字体数据(banner3-D 等)
try:
    from PyInstaller.utils.hooks import collect_data_files
    _datas += collect_data_files('pyfiglet')
except Exception:
    pass

# 收集 web/ 前端页面树 (pywebview 各窗口的 HTML/CSS/JS 与皮肤素材)。
# 目标目录写 'web': onedir 布局下 PyInstaller 会把它放进 _internal/web/,
# 与 exe 同级但对用户不可见 (不再作为顶层 web/ 目录出现在发布包中)。
# 运行时由 functions.base.common.path_utils.get_web_root() 优先在 _internal 下定位。
_spec_root = _os.path.abspath(SPECPATH)
_web_src_dir = _os.path.join(_spec_root, 'web')
if _os.path.isdir(_web_src_dir):
    for _root, _dirs, _files in _os.walk(_web_src_dir):
        for _f in _files:
            _src = _os.path.join(_root, _f)
            _rel = _os.path.relpath(_root, _web_src_dir)
            _dest = 'web' if _rel == '.' else _os.path.join('web', _rel)
            _datas.append((_src, _dest))

# 显式收集 cffi, 确保 _cffi_backend 扩展模块一定被打包
# (pywebview -> pythonnet -> clr_loader 均依赖 cffi)
_cffi_datas, _cffi_binaries, _cffi_hidden = [], [], []
try:
    from PyInstaller.utils.hooks import collect_all
    _cffi_datas, _cffi_binaries, _cffi_hidden = collect_all('cffi')
except Exception:
    pass

# Web UI (pywebview winforms) 依赖收集: 后端按需加载 winforms/pythonnet,
# 静态分析无法自动追踪, 必须显式收集 webview 及其平台后端
_web_datas, _web_binaries, _web_hidden = [], [], []
try:
    from PyInstaller.utils.hooks import collect_all
    _web_datas, _web_binaries, _web_hidden = collect_all('webview')
except Exception:
    pass

# pythonnet: Python.Runtime.dll (托管 + native host) 必须完整收集, 否则打包后
# clr_loader 报 "Failed to resolve Python.Runtime.Loader.Initialize"
_py_datas, _py_binaries, _py_hidden = [], [], []
try:
    from PyInstaller.utils.hooks import collect_all
    _py_datas, _py_binaries, _py_hidden = collect_all('pythonnet')
except Exception:
    pass

_web_hidden += ['webview', 'webview.platforms.winforms',
                'clr_loader', 'clr_loader.ffi', 'clr_loader.pythonnet_core',
                'pythonnet', 'pythonnet.initialize', 'pythonnet.runtime'] + _py_hidden
_web_datas += _py_datas
_web_binaries += _py_binaries

# 云端配置 (web_config.json) 内嵌进 PYZ: 构建时读取 config/web_config.json,
# 生成 web_config_data 模块 (含 EMBEDDED_CONFIG), 编入可执行文件, 不以独立文件分发
# 注意: SPECPATH 是 spec 所在目录(绝对路径), 不是 spec 文件路径
_spec_dir = _os.path.abspath(SPECPATH)
_web_data_dir = _os.path.join(_spec_dir, 'build', 'web_config_data')
_web_config_src = _os.path.join(_spec_dir, 'config', 'web_config.json')
_web_embedded = None
try:
    with open(_web_config_src, 'r', encoding='utf-8') as _f:
        _web_cfg_text = _f.read()
    _os.makedirs(_web_data_dir, exist_ok=True)
    with open(_os.path.join(_web_data_dir, 'web_config_data.py'), 'w', encoding='utf-8') as _f:
        _f.write('# -*- coding: utf-8 -*-\n')
        _f.write('# 构建时由 FaustLauncher.spec 从 config/web_config.json 生成, 内嵌于 PYZ\n')
        _f.write('EMBEDDED_CONFIG = %r\n' % _web_cfg_text)
    _web_embedded = True
except Exception:
    _web_embedded = False


a = Analysis(
    ['main.py'],
    pathex=[_web_data_dir] if _web_embedded else [],
    binaries=_cffi_binaries + _web_binaries,
    datas=_datas + _cffi_datas + _web_datas,
    hiddenimports=_cffi_hidden + _web_hidden + (['web_config_data'] if _web_embedded else []) + [
    # hook 子系统：偏移索引（懒加载 + capstone 在 try 里 import，显式列一下更稳）
    'functions.hook',
    'functions.hook.updater',
    'functions.hook.metadata_source',
    'functions.hook.metadata_recovery',
    'functions.hook.metadata_recovery.pipeline',
    'functions.hook.metadata_recovery.universal',
    'functions.hook.metadata_recovery.universal.extract_disasm',
    'functions.hook.metadata_recovery.universal.init_locator',
    'functions.hook.metadata_recovery.universal.layouts',
    'capstone',
],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='FaustLauncher',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['assets\\images\\icon\\icon.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='FaustLauncher',
)
