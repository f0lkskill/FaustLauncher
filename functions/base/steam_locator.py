
import os

STEAM_APP_ID = "1973530"
GAME_EXE = "LimbusCompany.exe"

_APP_ID_STR = str(STEAM_APP_ID)

def _parse_vdf(text):
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

    def parse_block():
        nonlocal i
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
                skip_ws()
                val = parse_block() if (i < n and text[i] == '{') else None
            d[key] = val
        return d

    skip_ws()
    if i < n and text[i] == '{':
        return parse_block()
    root = {}
    while True:
        skip_ws()
        if i >= n:
            break
        key = read_string()
        if key is None:
            break
        skip_ws()
        if i < n and text[i] == '{':
            root[key] = parse_block()
        else:
            val = read_string()
            if val is None:
                break
            root[key] = val
    return root

def _steam_install_paths():
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

def normalize_game_path(path):
    if not path:
        return path
    p = os.path.normpath(str(path))
    if len(p) >= 2 and p[1] == ':' and p[0].isalpha():
        p = p[0].upper() + p[1:]
    return p

def resolve_game_dir_ex(path):
    raw = str(path or "").strip()
    if not raw:
        return "", "empty"
    try:
        p = normalize_game_path(raw)
    except Exception:
        return "", "not_dir"
    try:
        if os.path.isfile(p) and os.path.basename(p).lower() == GAME_EXE.lower():
            p = os.path.dirname(p)
    except Exception:
        return "", "not_dir"
    if not p or not os.path.isdir(p):
        return "", "not_dir"
    if os.path.isfile(os.path.join(p, GAME_EXE)):
        return normalize_game_path(p), ""
    try:
        hits = [d for d in os.listdir(p)
                if os.path.isfile(os.path.join(p, d, GAME_EXE))]
    except Exception:
        return "", "no_exe"
    if len(hits) == 1:
        return normalize_game_path(os.path.join(p, hits[0])), ""
    return "", ("ambiguous" if len(hits) > 1 else "no_exe")

def resolve_game_dir(path) -> str:
    return resolve_game_dir_ex(path)[0]

def is_valid_game_path(path) -> bool:
    return bool(resolve_game_dir(path))

def has_game_exe(path) -> bool:
    try:
        return os.path.isfile(os.path.join(normalize_game_path(path), GAME_EXE))
    except Exception:
        return False

def _acf_installdir(data):
    if not isinstance(data, dict):
        return ""
    node = data.get('AppState')
    if not isinstance(node, dict):
        node = data
    for key in ('installdir', 'Installdir', 'installDir'):
        v = node.get(key)
        if v:
            return str(v)
    return ""

def _lib_paths_from_vdf(steam_dir):
    vdf = os.path.join(steam_dir, 'steamapps', 'libraryfolders.vdf')
    if not os.path.isfile(vdf):
        return []
    try:
        with open(vdf, 'r', encoding='utf-8', errors='replace') as f:
            data = _parse_vdf(f.read())
    except Exception:
        return []
    if not isinstance(data, dict):
        return []
    node = data.get('libraryfolders')
    if not isinstance(node, dict):
        node = data
    libs = []
    for v in node.values():
        if isinstance(v, dict) and v.get('path'):
            libs.append(str(v['path']))
    return libs

def _find_exe_in_common(lib, exe_name=GAME_EXE):
    common = os.path.join(lib, 'steamapps', 'common')
    for d in ('Limbus Company', 'LimbusCompany'):
        p = os.path.join(common, d)
        if os.path.isfile(os.path.join(p, exe_name)):
            return p
    try:
        hits = [d for d in os.listdir(common)
                if os.path.isfile(os.path.join(common, d, exe_name))]
    except Exception:
        return None
    if len(hits) == 1:
        return os.path.join(common, hits[0])
    return None

def find_steam_game_path(app_id=_APP_ID_STR, exe_name=GAME_EXE):
    for steam_dir in _steam_install_paths():
        libs = _lib_paths_from_vdf(steam_dir)
        if steam_dir not in libs:
            libs.append(steam_dir)
        for lib in libs:
            lib = str(lib).strip().rstrip('\\/')
            if not lib:
                continue
            installdir = None
            manifest = os.path.join(lib, 'steamapps', f'appmanifest_{app_id}.acf')
            if os.path.isfile(manifest):
                try:
                    with open(manifest, 'r', encoding='utf-8', errors='replace') as f:
                        installdir = _acf_installdir(_parse_vdf(f.read())) or None
                except Exception:
                    installdir = None
            if installdir:
                p = os.path.join(lib, 'steamapps', 'common', installdir)
                if os.path.isfile(os.path.join(p, exe_name)):
                    return normalize_game_path(p)
            p = _find_exe_in_common(lib, exe_name)
            if p:
                return normalize_game_path(p)
    return None
