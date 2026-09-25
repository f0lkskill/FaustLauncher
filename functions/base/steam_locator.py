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


def normalize_game_path(path):
    r"""把游戏路径规范成统一、友好的形式 (显示与存储都用它)

    - 统一分隔符: Steam 的 libraryfolders.vdf 里库路径写的是正斜杠 ('d:/steam'),
      直接 os.path.join 的结果就是 'd:/steam\steamapps\common\Limbus Company' 这种混搭
    - 去掉结尾分隔符: 尾部的反斜杠贴着引号时会变成转义 ('...Company\' 里那个 \' 会把引号吃掉),
      放进 f-string / JS 字符串都是隐患
    - 盘符大写: 显示更规整 ('d:/steam' -> 'D:\steam'); Windows 路径大小写不敏感,
      且项目里所有消费方都走 os.path.join, 没有大小写敏感的字符串比较
    """
    if not path:
        return path
    p = os.path.normpath(str(path))
    if len(p) >= 2 and p[1] == ':' and p[0].isalpha():
        p = p[0].upper() + p[1:]
    return p


def resolve_game_dir(path) -> str:
    r"""把给定路径解析成"确实含 LimbusCompany.exe 的游戏目录", 解析不出返回 ""。

    规则 (按顺序):
      ① 传进来的就是 exe 文件本身 → 取它的所在目录
      ② 目录本身有 LimbusCompany.exe → 用它
      ③ 目录下**唯一一个**一级子目录有 exe → 用那个子目录
         (用户多半选了上一层, 例如 steamapps\\common 或游戏目录的父级)
      ④ 其它情况 (没 exe / 多候选分不清) → ""

    路径里必须有 LimbusCompany.exe 是硬要求: 拿不到这个文件就说明目录选错了,
    启动器不能把它当成有效游戏路径来用。
    """
    raw = str(path or "").strip()
    if not raw:
        return ""
    try:
        p = normalize_game_path(raw)
    except Exception:
        return ""
    # ① 直接指到 exe 文件本身
    try:
        if os.path.isfile(p) and os.path.basename(p).lower() == GAME_EXE.lower():
            p = os.path.dirname(p)
    except Exception:
        return ""
    if not p or not os.path.isdir(p):
        return ""
    if os.path.isfile(os.path.join(p, GAME_EXE)):
        return normalize_game_path(p)
    # ③ 唯一一级子目录带 exe (多个候选一律不猜)
    try:
        hits = [d for d in os.listdir(p)
                if os.path.isfile(os.path.join(p, d, GAME_EXE))]
    except Exception:
        return ""
    if len(hits) == 1:
        return normalize_game_path(os.path.join(p, hits[0]))
    return ""


def is_valid_game_path(path) -> bool:
    """游戏路径是否可用: 非空 + 目录存在 + 里面有 LimbusCompany.exe

    硬校验: 找不到 LimbusCompany.exe 的路径一律无效 (含 Steam 自动检测到的路径,
    见 resolve_game_dir)。
    """
    return bool(resolve_game_dir(path))


def has_game_exe(path) -> bool:
    """目录**本身**是否存在 LimbusCompany.exe (不递归, 仅供界面提示)"""
    try:
        return os.path.isfile(os.path.join(normalize_game_path(path), GAME_EXE))
    except Exception:
        return False


def find_steam_game_path(app_id=_APP_ID_STR, exe_name=GAME_EXE):
    """定位边狱巴士安装路径。

    返回游戏目录 (已规范化: 统一反斜杠 / 大写盘符 / 无尾部分隔符, 见 normalize_game_path);
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
                        return normalize_game_path(p)
                continue
            p = os.path.join(lib, 'steamapps', 'common', installdir)
            if os.path.isfile(os.path.join(p, exe_name)):
                return normalize_game_path(p)
    return None