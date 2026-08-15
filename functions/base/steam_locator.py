"""Steam 游戏路径定位器 — 通过解析 Steam 的 VDF 文件自动定位边狱巴士安装路径。

原理:
1. 从注册表 (HKCU/HKLM Software\\Valve\\Steam) 读取 Steam 安装目录
2. 解析 <Steam>/steamapps/libraryfolders.vdf 得到所有库目录
3. 读取 <库>/steamapps/appmanifest_<app_id>.acf 中的 installdir 得到游戏目录名
4. 验证 <库>/steamapps/common/<installdir>/LimbusCompany.exe 存在

只依赖标准库 (winreg/ast 式手工解析), 无第三方依赖。
"""

import os

STEAM_APP_ID = "1973530"
GAME_EXE = "LimbusCompany.exe"

_APP_ID_STR = str(STEAM_APP_ID)


def _parse_vdf(text):
    """极简 VDF 解析: "key" "value" 与 "key" { ... } 嵌套 → dict (仅需 libraryfolders/acf 的子集)。

    支持 // 行注释与 \\" 转义; 解析失败抛异常, 由调用方兜底。
    """
    i = 0
    n = len(text)

    def skip_ws():
        nonlocal i
        while i < n:
            c = text[i]
            if c in ' \t\r\n':
                i += 1
            elif c == '/' and i + 1 < n and text[i + 1] == '/':
                while i < n and text[i] not in '\r\n':
                    i += 1
            else:
                break

    def read_string():
        nonlocal i
        skip_ws()
        if i >= n or text[i] != '"':
            return None
        i += 1
        out = []
        while i < n:
            c = text[i]
            if c == '"':
                i += 1
                break
            elif c == '\\' and i + 1 < n:
                out.append(text[i + 1])
                i += 2
            else:
                out.append(c)
                i += 1
        return ''.join(out)

    def parse_value():
        nonlocal i
        skip_ws()
        if i >= n:
            return None
        if text[i] == '{':
            i += 1
            d = {}
            while True:
                skip_ws()
                if i >= n:
                    break
                if text[i] == '}':
                    i += 1
                    break
                key = read_string()
                if key is None:
                    break
                val = read_string()
                if val is None:
                    val = parse_value()
                d[key] = val
            return d
        return read_string()

    return parse_value()


def _steam_install_paths():
    """Steam 安装目录候选 (注册表优先, 常见默认路径兜底), 去重保序。"""
    paths = []
    try:
        import winreg
        for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            for sub in (r'Software\Valve\Steam', r'Software\WOW6432Node\Valve\Steam'):
                try:
                    with winreg.OpenKey(root, sub) as k:
                        v, _ = winreg.QueryValueEx(k, 'SteamPath')
                        if v:
                            paths.append(str(v))
                except OSError:
                    pass
    except ImportError:
        pass
    for p in (r'C:\Program Files (x86)\Steam', r'C:\Program Files\Steam'):
        if os.path.isdir(os.path.join(p, 'steamapps')):
            paths.append(p)
    seen = set()
    out = []
    for p in paths:
        p = p.strip().rstrip('\\')
        if p and p not in seen:
            seen.add(p)
            out.append(p)
    return out


def find_steam_game_path(app_id=_APP_ID_STR, exe_name=GAME_EXE):
    """定位边狱巴士安装路径。

    返回游戏目录 (带尾部分隔符, 与 settings 中 game_path 的存储格式一致);
    找不到返回 None。
    """
    for steam_dir in _steam_install_paths():
        vdf = os.path.join(steam_dir, 'steamapps', 'libraryfolders.vdf')
        if not os.path.isfile(vdf):
            continue
        try:
            with open(vdf, 'r', encoding='utf-8', errors='replace') as f:
                data = _parse_vdf(f.read())
        except Exception:
            continue
        libs = []
        if isinstance(data, dict):
            for v in data.values():
                if isinstance(v, dict) and v.get('path'):
                    libs.append(str(v['path']))
        if not libs:
            libs = [steam_dir]
        for lib in libs:
            lib = lib.strip().rstrip('\\')
            installdir = None
            manifest = os.path.join(lib, 'steamapps', f'appmanifest_{app_id}.acf')
            if os.path.isfile(manifest):
                try:
                    with open(manifest, 'r', encoding='utf-8', errors='replace') as f:
                        m = _parse_vdf(f.read())
                    if isinstance(m, dict) and m.get('installdir'):
                        installdir = str(m['installdir'])
                except Exception:
                    pass
            if not installdir:
                # 无 manifest 时按常见目录名探测
                for d in ('Limbus Company', 'LimbusCompany'):
                    p = os.path.join(lib, 'steamapps', 'common', d)
                    if os.path.isfile(os.path.join(p, exe_name)):
                        return p + os.sep
                continue
            p = os.path.join(lib, 'steamapps', 'common', installdir)
            if os.path.isfile(os.path.join(p, exe_name)):
                return p + os.sep
    return None