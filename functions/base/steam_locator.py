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

    **顶层形状 (2026-09-25 修)**: Steam 的 vdf/acf 顶层都是 `"key" { ... }` ——
    libraryfolders.vdf 是 `"libraryfolders" { "0" { "path" ... } }`, appmanifest 是
    `"AppState" { "installdir" ... }`。旧实现只认"整份文件就是一个 { ... } 块",
    碰到真实文件会在读完第一个"键"之后就返回(那个键名当成了结果), 于是:
      · 库列表恒为空 → 只扫了 Steam 主目录, 装在第二个库(另一块盘)里的游戏永远找不到;
      · acf 里读不到 installdir → 只能靠猜目录名 "Limbus Company"/"LimbusCompany"。
    现在两种形状都支持, 返回 {顶层键: 块/值}。
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

    def parse_block():
        """当前字符是 '{' -> 解析成 dict"""
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
    # 顶层是 "键" { ... } 序列 (Steam 的真实形状)
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


def resolve_game_dir_ex(path):
    r"""把给定路径解析成"确实含 LimbusCompany.exe 的游戏目录", 并说明失败原因。

    规则 (按顺序):
      ① 传进来的就是 exe 文件本身 → 取它的所在目录
      ② 目录本身有 LimbusCompany.exe → 用它
      ③ 目录下**唯一一个**一级子目录有 exe → 用那个子目录
         (用户多半选了上一层, 例如 steamapps\\common 或游戏目录的父级)
      ④ 其它情况 (没 exe / 多候选分不清) → 解析不出来

    路径里必须有 LimbusCompany.exe 是硬要求: 拿不到这个文件就说明目录选错了,
    启动器不能把它当成有效游戏路径来用。

    Returns:
        (游戏目录 或 "", reason):
          ''          解析成功
          'empty'     路径为空
          'not_dir'   路径不存在 / 不是目录
          'no_exe'    目录本身和它的一级子目录里都没有 LimbusCompany.exe
          'ambiguous' 父目录下**有多个**含 exe 的子目录, 不能替用户猜
    """
    raw = str(path or "").strip()
    if not raw:
        return "", "empty"
    try:
        p = normalize_game_path(raw)
    except Exception:
        return "", "not_dir"
    # ① 直接指到 exe 文件本身
    try:
        if os.path.isfile(p) and os.path.basename(p).lower() == GAME_EXE.lower():
            p = os.path.dirname(p)
    except Exception:
        return "", "not_dir"
    if not p or not os.path.isdir(p):
        return "", "not_dir"
    if os.path.isfile(os.path.join(p, GAME_EXE)):
        return normalize_game_path(p), ""
    # ③ 唯一一级子目录带 exe (多个候选一律不猜, 但要能告诉用户为什么)
    try:
        hits = [d for d in os.listdir(p)
                if os.path.isfile(os.path.join(p, d, GAME_EXE))]
    except Exception:
        return "", "no_exe"
    if len(hits) == 1:
        return normalize_game_path(os.path.join(p, hits[0])), ""
    return "", ("ambiguous" if len(hits) > 1 else "no_exe")


def resolve_game_dir(path) -> str:
    """resolve_game_dir_ex 的简写: 只要目录 (解析不出返回 "")"""
    return resolve_game_dir_ex(path)[0]


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


def _acf_installdir(data):
    """从 appmanifest 里取 installdir

    真实 acf 形状是 `"AppState" { "installdir" "Limbus Company" }`, 所以键在
    AppState 里面; 这里两种都认 (顶层直接给键的老测试数据也兼容)。
    """
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
    """libraryfolders.vdf -> 库目录列表 (解析不出返回 [])"""
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
    """在 <lib>/steamapps/common 下找带 exe 的游戏目录 (manifest 缺失/目录名被改时兜底)

    先试常见目录名, 再扫一层子目录 (只认唯一命中, 多个不猜)。
    """
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
    """定位边狱巴士安装路径。

    流程: 注册表找 Steam 目录 -> 解析 libraryfolders.vdf 拿到**所有**库 ->
    每个库先按 appmanifest 的 installdir 找, 再按目录名兜底扫一遍。

    返回游戏目录 (已规范化: 统一反斜杠 / 大写盘符 / 无尾部分隔符, 见 normalize_game_path);
    找不到返回 None。
    """
    for steam_dir in _steam_install_paths():
        libs = _lib_paths_from_vdf(steam_dir)
        if steam_dir not in libs:
            libs.append(steam_dir)          # 主目录永远算一个库 (vdf 读不到时也能用)
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