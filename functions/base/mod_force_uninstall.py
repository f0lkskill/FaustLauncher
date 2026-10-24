"""全部 Mod 强卸载：把 mod 改写过的游戏资源还原成原始状态。

用户语义里的「强卸载」= 把 mod loader 打过的补丁撤掉，让游戏回到没有 mod 的样子。
mod 包本身保留在磁盘上（否则用户连自己装过什么都不知道），但资源会回到原版，
下次启动器启动时 mod loader 会因为找不到被打补丁的资源而加载失败——这正是提示
用户「先去 Steam 做完整性验证」的原因。

扫描范围覆盖启动器环境里的**所有单文件型 mod**：
1. 启动器 `mods\\<名>\\mod_info.json` 里 `file_names` 登记的单文件 mod（源）；
2. `%APPDATA%\\LimbusCompanyMods`（含 `_orphan`）里已投放的包（启动器把源复制过去
   并加 `{mod名}_` 前缀，重复的按目标资源去重）。
文件夹型 mod（靠 `extra_files` 覆盖汉化、或自带 Installer.bat）不产生 bundle/bank
改写，不在扫描范围内。

两类 mod 的落地位置完全不同，卸载动作也不一样:

- `.carra2`: 本质是 zip。包内路径形如 `<hash1>/<hash2>/<xxx>`，对应 Unity 的
  bundle 缓存 `%LOCALAPPDATA%\\..\\LocalLow\\Unity\\ProjectMoon_LimbusCompany\\
  <hash1>\\<hash2>`。游戏启动时会用游戏目录里的原版 bundle 重新解包出这层缓存，
  所以**删掉整个 <hash2> 目录**就等于恢复原样。
- `.rebank` / `.bank`: 本质也是 zip。根目录 `rebank.json` 里的 `base_bank` 指明了
  被改写的 bank（`<base_bank>.bank`，位于游戏目录 `LimbusCompany_Data\\StreamingAssets\\
  Assets\\Sound\\FMODBuilds\\Desktop`）。mods 目录里如果留着 `<base_bank>.bank.orig`
  就覆盖还原；没有备份就只能删掉 bank，交给 Steam 的完整性验证重新下发。

`_orphan` 子目录（被移出生效集合的 mod）同样会被扫到。
"""

import json
import os
import shutil
import zipfile

from functions.base.settings_manager import get_settings_manager

CARRA_EXT = ".carra2"
REBANK_EXT = ".rebank"
BANK_EXT = ".bank"
MOD_SUFFIXES = (CARRA_EXT, REBANK_EXT, BANK_EXT)
ORPHAN_DIR = "_orphan"
MANIFEST_NAME = "launcher_manifest.json"
BANK_ORIG_SUFFIX = ".bank.orig"
REBANK_MANIFEST = "rebank.json"

_DESKTOP_BANK = os.path.join(
    "LimbusCompany_Data", "StreamingAssets", "Assets", "Sound",
    "FMODBuilds", "Desktop",
)


def mods_dir() -> str:
    """mod loader 的存放目录。"""
    return os.path.join(os.getenv("APPDATA", ""), "LimbusCompanyMods")


def unity_cache_root() -> str:
    """Unity 的 bundle 缓存根目录（ProjectMoon_LimbusCompany）。"""
    appdata = os.getenv("APPDATA", "")
    return os.path.normpath(
        os.path.join(appdata, "..", "LocalLow", "Unity", "ProjectMoon_LimbusCompany")
    )


def game_bank_dir() -> str:
    """游戏里 FMOD bank 所在的目录；游戏路径没配置时返回空串。"""
    game_path = get_settings_manager().get_setting("game_path") or ""
    if not game_path:
        return ""
    return os.path.join(game_path, _DESKTOP_BANK)


def _carra2_target(path: str):
    """从 carra2 包里取出 (hash1, hash2)。"""
    try:
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
    except (OSError, zipfile.BadZipFile):
        return None
    for name in names:
        parts = name.replace("\\", "/").split("/")
        if len(parts) >= 2 and parts[0] and parts[1]:
            return parts[0], parts[1]
    return None


def _rebank_target(path: str):
    """从 rebank 包里读出 base_bank（例如 Voice_Default_S2_4.assets）。"""
    try:
        with zipfile.ZipFile(path) as zf:
            raw = zf.read(REBANK_MANIFEST)
    except (OSError, KeyError, zipfile.BadZipFile):
        return None
    try:
        info = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    base = str(info.get("base_bank") or "").strip()
    return base or None


def _listdir_safe(path: str):
    try:
        return sorted(os.listdir(path))
    except OSError:
        return []


def launcher_mods_dir() -> str:
    """启动器自己的 `mods` 目录（打包后是 exe 同级，开发时是仓库根）。"""
    from functions.base.common.path_utils import get_app_root
    return os.path.join(get_app_root(create=False), "mods")


def _launcher_mod_files():
    """遍历启动器 `mods\\<名>\\` 下 `mod_info.json` 里**登记了文件**的 mod 包。

    判据是 `file_names` —— 它记录这个 mod 往游戏里投了哪些包（`.carra2` /
    `.rebank` / `.bank`）。启动器把这些文件复制进 APPDATA（加 `{mod名}_` 前缀）
    交给 mod loader 打补丁，所以只要登记了就是会改写游戏资源的 mod。

    文件夹型 mod（靠 `extra_files` 覆盖汉化、或自带 Installer.bat）的 `file_names`
    是空的，或者登记的是目录，这里靠 `os.path.isfile` 自然排除。

    只看启动器目录会漏掉「装了但还没启用过」的 mod，只看 APPDATA 又会漏掉
    「启用过但被清空过」的 mod，所以两边都扫，最后按目标资源去重。
    """
    root = launcher_mods_dir()
    for mod_name in _listdir_safe(root):
        mod_path = os.path.join(root, mod_name)
        info_path = os.path.join(mod_path, "mod_info.json")
        if not os.path.isfile(info_path):
            continue
        try:
            with open(info_path, "r", encoding="utf-8") as fp:
                info = json.load(fp)
        except (OSError, ValueError):
            continue
        for file_name in info.get("file_names") or []:
            path = os.path.join(mod_path, str(file_name))
            if os.path.isfile(path) and path.lower().endswith(MOD_SUFFIXES):
                yield path


def _iter_mod_files():
    """遍历生效目录与 _orphan 目录下的 carra2 / rebank 包。"""
    roots = (mods_dir(), os.path.join(mods_dir(), ORPHAN_DIR))
    seen = set()
    for root in roots:
        try:
            names = os.listdir(root)
        except OSError:
            continue
        for name in sorted(names):
            if not name.lower().endswith(MOD_SUFFIXES):
                continue
            path = os.path.join(root, name)
            if path in seen or not os.path.isfile(path):
                continue
            seen.add(path)
            yield path


def _bank_target(base: str):
    """把 `Voice_Default_S2_4.assets` 这样的 bank 名换成游戏里的绝对路径。"""
    bank_dir = game_bank_dir()
    if not bank_dir or not base:
        return None
    return os.path.join(bank_dir, base + BANK_EXT)


def _exists(kind: str, target) -> bool:
    if not target:
        return False
    return os.path.isdir(target) if kind == "carra2" else os.path.isfile(target)


def _target_for(path: str):
    """把一个 mod 包解析成 `(kind, 被改写的目标路径)`；解析不出目标时为 None。"""
    lower = path.lower()
    if lower.endswith(CARRA_EXT):
        pair = _carra2_target(path)
        if not pair:
            return "carra2", None
        return "carra2", os.path.join(unity_cache_root(), pair[0], pair[1])
    if lower.endswith(BANK_EXT):
        return "rebank", _bank_target(os.path.splitext(os.path.basename(path))[0])
    base = _rebank_target(path)
    return "rebank", (_bank_target(base) if base else None)


def scan():
    """列出所有 mod 以及它们改写的目标资源位置。

    两个来源都会扫，按 `(kind, target)` 去重:
    - `launcher`: 启动器 `mods\\<名>\\` 里单文件型 mod 登记的包
    - `appdata`: `%APPDATA%\\LimbusCompanyMods`（含 `_orphan`）里已投放的包

    返回的每一项: `{name, path, source, kind, target, exists}`
    - `kind`: `carra2` / `rebank`
    - `target`: 被改写的资源路径（`exists` 表示当前是否真的存在）
    """
    items = []
    seen_targets = set()
    sources = {"launcher": 0, "appdata": 0}
    for source, paths in (("launcher", _launcher_mod_files()),
                          ("appdata", _iter_mod_files())):
        for path in paths:
            sources[source] += 1
            kind, target = _target_for(path)
            key = (kind, target)
            # 同一个包可能在启动器目录与 APPDATA 各存一份，按目标资源去重
            if target and key in seen_targets:
                continue
            if target:
                seen_targets.add(key)
            name = os.path.basename(path)
            if source == "launcher":
                name = os.path.basename(os.path.dirname(path)) + "/" + name
            items.append({
                "name": name,
                "path": path,
                "source": source,
                "kind": kind,
                "target": target,
                "exists": _exists(kind, target),
            })
    return items


def _restore_bank(target: str) -> str:
    """还原一条 bank：优先用 mods 目录里的 .bank.orig 备份，否则删除。

    返回实际做的事，`restored` 或 `removed`。
    """
    base = os.path.basename(target)[: -len(".bank")]
    backup = os.path.join(mods_dir(), base + BANK_ORIG_SUFFIX)
    if os.path.isfile(backup):
        shutil.copy2(backup, target)
        return "restored"
    os.remove(target)
    return "removed"


def force_uninstall_all(*, dry_run: bool = False):
    """卸载所有 mod 对游戏资源的改写。

    `dry_run=True` 只扫描不落盘。返回:
    `{ok, total, uninstalled, missing, errors, unity_root, bank_dir}`
    """
    items = scan()
    uninstalled, missing, errors = [], [], []
    actions = []
    bank_dir = game_bank_dir()

    for item in items:
        name = item["name"]
        target = item["target"]
        if not target:
            errors.append({"name": name, "error": "无法解析资源位置"})
            continue
        if not item["exists"]:
            missing.append(name)
            continue
        if dry_run:
            uninstalled.append(name)
            continue
        try:
            if item["kind"] == "carra2":
                shutil.rmtree(target, ignore_errors=True)
                if os.path.isdir(target):
                    raise OSError(f"删除失败（可能被游戏或启动器占用）: {target}")
                actions.append({"name": name, "action": "removed"})
            else:
                actions.append({"name": name, "action": _restore_bank(target)})
            uninstalled.append(name)
        except OSError as exc:
            errors.append({"name": name, "error": str(exc)})

    return {
        "ok": not errors,
        "total": len(items),
        "uninstalled": uninstalled,
        "missing": missing,
        "errors": errors,
        "actions": actions,
        "unity_root": unity_cache_root(),
        "bank_dir": bank_dir,
    }


def _describe(result) -> str:
    lines = [
        f"扫描到 {result['total']} 个 mod",
        f"已卸载 {len(result['uninstalled'])} 个",
    ]
    if result["missing"]:
        lines.append(f"资源已不存在 {len(result['missing'])} 个")
    if result["errors"]:
        lines.append(f"失败 {len(result['errors'])} 个")
    return " | ".join(lines)


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    plan = scan()
    for item in plan:
        flag = "存在" if item["exists"] else "缺失"
        print(f"[{item['kind']:7}] {item['source']:8} {flag} {item['name']}")
        print(f"          -> {item['target']}")
    print()
    print(_describe(force_uninstall_all(dry_run=True)))
