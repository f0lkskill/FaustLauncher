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
  <hash1>\\<hash2>`。**`<hash1>` 才是这个资源在 Unity 缓存里的索引**，`<hash2>`
  只是某一版 bundle 的缓存名（mod 包更新或游戏重打 bundle 后会变），所以卸载时
  直接**删掉整个 `<hash1>` 目录**，把它下面所有版本的缓存一起清掉。游戏启动时会
  用游戏目录里的原版 bundle 重新解包出这层缓存，于是恢复到原样。
- `.rebank` / `.bank`: 本质也是 zip。根目录 `rebank.json` 里的 `base_bank` 指明了
  被改写的 bank（`<base_bank>.bank`，位于游戏目录 `LimbusCompany_Data\\StreamingAssets\\
  Assets\\Sound\\FMODBuilds\\Desktop`）。mods 目录里如果留着 `<base_bank>.bank.orig`
  就覆盖还原；没有备份就只能删掉 bank，交给 Steam 的完整性验证重新下发。

`_orphan` 子目录（被移出生效集合的 mod）同样会被扫到。

除了「全部强卸载」，本模块也把**单个 mod** 的两层卸载动作包装成可复用函数：

- `uninstall_resource(kind, target)` / `uninstall_package_file(path)`:
  还原一条 / 一个包（`.carra2` / `.rebank` / `.bank`）留下的资源残留；
- `uninstall_launcher_package(mod_name)`: 撤掉启动器投放到 mod loader 目录里的
  `{mod名}_` 包副本（`ModManager.unload_mod` 的薄包装）；
- `scan_mod(mod_name)` / `force_uninstall_mod(mod_name)`: 只针对这一个 mod
  的扫描与强卸载，语义与全部强卸载一致（资源回到原版，mod 包目录保留）。
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


def _carra2_targets(path: str):
    """列出 carra2 包对应的 Unity 缓存目录（按资源索引整目录删除）。

    包里写的是 `{hash1}/{hash2}`，其中 **`{hash1}` 才是这个资源在 Unity 缓存
    里的索引**，`{hash2}` 只是某一版 bundle 的缓存名，会随 mod 包更新或游戏
    版本重打而变化（实测「扭曲裁缝 罗佳」：包里 9f52a9…、磁盘 52f123…）。

    所以这里直接返回 `<缓存根>/<hash1>` 整个目录，删除时连它下面所有版本的
    缓存一起清掉 —— 只按包里那个 hash2 删，就会出现「显示还原 0 处，但
    `7a1078d78aa0ff8cf7d286e67a20c842` 还好好躺着」的情况。
    """
    pair = _carra2_target(path)
    if not pair:
        return []
    hash1_dir = os.path.join(unity_cache_root(), pair[0])
    if os.path.isdir(hash1_dir):
        return [hash1_dir]
    # 目录还不存在时保留包里的原始路径，让上层能把它记成「缺失」而不是「解析失败」
    return [os.path.join(hash1_dir, pair[1])]


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


def _launcher_mod_files(mod_name: str = None):
    """遍历启动器 `mods\\<名>\\` 下 `mod_info.json` 里**登记了文件**的 mod 包。

    判据是 `file_names` —— 它记录这个 mod 往游戏里投了哪些包（`.carra2` /
    `.rebank` / `.bank`）。启动器把这些文件复制进 APPDATA（加 `{mod名}_` 前缀）
    交给 mod loader 打补丁，所以只要登记了就是会改写游戏资源的 mod。

    文件夹型 mod（靠 `extra_files` 覆盖汉化、或自带 Installer.bat）的 `file_names`
    是空的，或者登记的是目录，这里靠 `os.path.isfile` 自然排除。

    只看启动器目录会漏掉「装了但还没启用过」的 mod，只看 APPDATA 又会漏掉
    「启用过但被清空过」的 mod，所以两边都扫，最后按目标资源去重。

    传入 `mod_name` 时只遍历这一个 mod 的目录（单 mod 强卸载用）。
    """
    root = launcher_mods_dir()
    for name in _listdir_safe(root):
        if mod_name and name != mod_name:
            continue
        mod_path = os.path.join(root, name)
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


def _iter_mod_files(mod_name: str = None):
    """遍历生效目录与 _orphan 目录下的 carra2 / rebank 包。

    已投放的包会带 `{mod名}_` 前缀，传入 `mod_name` 时只保留该 mod 的包。
    """
    roots = (mods_dir(), os.path.join(mods_dir(), ORPHAN_DIR))
    prefix = (mod_name + "_") if mod_name else None
    seen = set()
    for root in roots:
        try:
            names = os.listdir(root)
        except OSError:
            continue
        for name in sorted(names):
            if not name.lower().endswith(MOD_SUFFIXES):
                continue
            if prefix and not name.startswith(prefix):
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


def _targets_for(path: str):
    """把一个 mod 包解析成 `(kind, 需要清理的全部路径列表)`。

    carra2 会展开成 `<hash1>` 下所有缓存目录（见 :func:`_carra2_targets`），
    其它类型只有一个目标，保持与 :func:`_target_for` 一致。
    """
    kind, target = _target_for(path)
    if kind == "carra2":
        return kind, _carra2_targets(path)
    return kind, ([target] if target else [])



def scan(mod_name: str = None):
    """列出 mod 以及它们改写的目标资源位置。

    两个来源都会扫，按 `(kind, target)` 去重:
    - `launcher`: 启动器 `mods\\<名>\\` 里单文件型 mod 登记的包
    - `appdata`: `%APPDATA%\\LimbusCompanyMods`（含 `_orphan`）里已投放的包

    传入 `mod_name` 时只扫描这一个 mod（启动器目录同名 + APPDATA `{mod名}_`
    前缀的包），供单 mod 强卸载使用。

    返回的每一项: `{name, path, source, kind, target, targets, exists}`
    - `kind`: `carra2` / `rebank`
    - `target`: 被改写的资源路径（主目标）
    - `targets`: 实际要清理的全部路径（carra2 会带上同 `hash1` 下的旧缓存）
    - `exists`: 这些路径里是否有任何一个当前真的存在
    """
    items = []
    seen_targets = set()
    sources = {"launcher": 0, "appdata": 0}
    for source, paths in (("launcher", _launcher_mod_files(mod_name)),
                          ("appdata", _iter_mod_files(mod_name))):
        for path in paths:
            sources[source] += 1
            kind, targets = _targets_for(path)
            target = targets[0] if targets else None
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
                "targets": targets,
                "exists": any(_exists(kind, t) for t in targets),
            })
    return items


def scan_mod(mod_name: str):
    """只扫描一个 mod 会改写的资源；`mod_name` 为空时返回空列表。"""
    name = str(mod_name or "").strip()
    return scan(name) if name else []


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


def _uninstall_resource(kind: str, target: str) -> str:
    """还原一处被 mod 改写的资源（不判断是否存在的内部实现）。

    - `carra2`: 删掉 Unity 缓存里的整个 `<hash2>` 目录，游戏会用原版 bundle
      重新解包出这层缓存；
    - `rebank`: 有 `.bank.orig` 备份就覆盖还原，否则删除 bank 交给 Steam
      完整性验证重新下发。

    返回 `removed` / `restored`；删除失败抛 `OSError`。
    """
    if kind == "carra2":
        shutil.rmtree(target, ignore_errors=True)
        if os.path.isdir(target):
            raise OSError(f"删除失败（可能被游戏或启动器占用）: {target}")
        return "removed"
    return _restore_bank(target)


def uninstall_resource(kind: str, target):
    """对外包装：还原一处资源残留。

    只处理「当前确实存在」的目标；不存在时返回 None（没有可还原的东西）。
    返回 `removed` 或 `restored`。
    """
    if not _exists(kind, target):
        return None
    return _uninstall_resource(kind, target)


def uninstall_package_file(path: str):
    """对外包装：还原单个 mod 包（`.carra2` / `.rebank` / `.bank`）改写的资源。

    解析不出目标资源时抛 `ValueError`；目标已不存在时 `action` 为 None。
    返回 `{name, path, kind, target, action}`，方便调用方汇总。
    """
    kind, targets = _targets_for(path)
    if not targets:
        raise ValueError("无法解析资源位置")
    action = None
    for target in targets:
        if _exists(kind, target):
            action = _uninstall_resource(kind, target)
    return {
        "name": os.path.basename(path),
        "path": path,
        "kind": kind,
        "target": targets[0],
        "targets": targets,
        "action": action,
    }


def uninstall_launcher_package(mod_name: str):
    """对外包装：撤掉启动器投放到 mod loader 目录里的整个 mod 包。

    这一步与「资源残留」不同：它删的是 `%APPDATA%\\LimbusCompanyMods` 里
    `{mod名}_` 前缀的包副本（`.bank` / `.rebank` / `.src` 标记），并在 mod
    自带 `Uninstaller.bat` 时执行它 —— 也就是 `ModManager.unload_mod` 的全部
    职责。包清理失败不应该回滚已经还原的资源，所以这里只把错误交回调用方。

    返回 `(ok, error)`。
    """
    try:
        from functions.extension.mod.mod_utils import ModManager
        ModManager().unload_mod(str(mod_name))
        return True, None
    except Exception as exc:
        return False, str(exc)


def _run_uninstall(items, *, dry_run: bool = False, log=None):
    """对扫描结果逐条执行还原，返回统一的统计结构。

    `log` 是可选的日志回调（传 `print` 就能在启动器终端里看到每一处明细）；
    `removed` 里记录**每个被真正删掉/还原的路径**，方便调用方把
    `7a1078d78aa0ff8cf7d286e67a20c842` 这种缓存目录名回显给用户。
    """
    uninstalled, missing, errors, actions, removed = [], [], [], [], []
    for item in items:
        name = item["name"]
        targets = item.get("targets") or ([item["target"]] if item["target"] else [])
        if not targets:
            errors.append({"name": name, "error": "无法解析资源位置"})
            continue
        if not item["exists"]:
            missing.append(name)
            continue
        if dry_run:
            uninstalled.append(name)
            continue
        cleaned = 0
        action = None
        for target in targets:
            if not _exists(item["kind"], target):
                continue
            try:
                action = _uninstall_resource(item["kind"], target)
                cleaned += 1
                removed.append({
                    "name": name,
                    "kind": item["kind"],
                    "action": action,
                    "path": target,
                })
                if log:
                    verb = "已还原" if action == "restored" else "已删除"
                    log(f"[ModForceUninstall] {verb} {target}  <-  {name}")
            except OSError as exc:
                errors.append({"name": name, "error": str(exc)})
                if log:
                    log(f"[ModForceUninstall] 失败: {target}  ({exc})")
                action = None
                break
        if action is not None:
            actions.append({"name": name, "action": action, "count": cleaned})
            uninstalled.append(name if cleaned == 1 else f"{name}（{cleaned} 处）")

    return {
        "ok": not errors,
        "total": len(items),
        "uninstalled": uninstalled,
        "missing": missing,
        "errors": errors,
        "actions": actions,
        "removed": removed,
    }


def force_uninstall_all(*, dry_run: bool = False, log=None):
    """卸载所有 mod 对游戏资源的改写。

    `dry_run=True` 只扫描不落盘。返回:
    `{ok, total, uninstalled, missing, errors, actions, removed, unity_root, bank_dir}`
    """
    result = _run_uninstall(scan(), dry_run=dry_run, log=log)
    result["unity_root"] = unity_cache_root()
    result["bank_dir"] = game_bank_dir()
    return result


def force_uninstall_mod(mod_name: str, *, dry_run: bool = False, log=None):
    """只卸载指定 mod 对游戏资源的改写，不影响其它 mod。

    顺序:
    1. `scan_mod` 只收这个 mod 的包（启动器目录 + APPDATA `{mod名}_` 前缀）；
    2. 逐条还原资源（carra2 删缓存目录 / bank 还原或删除）；
    3. `uninstall_launcher_package` 清掉启动器投放的包副本，避免下次启动
       mod loader 又用这些副本把资源打回去。

    `dry_run=True` 只扫描不落盘。返回结构与 `force_uninstall_all` 一致，
    额外带 `mod_name` / `package_cleaned`。
    """
    name = str(mod_name or "").strip()
    result = _run_uninstall(scan_mod(name), dry_run=dry_run, log=log)
    result["mod_name"] = name
    result["package_cleaned"] = False
    if not dry_run and name:
        ok, error = uninstall_launcher_package(name)
        result["package_cleaned"] = bool(ok)
        if error:
            result["errors"].append({
                "name": name,
                "error": f"启动器 mod 包清理失败: {error}",
            })
            result["ok"] = False
    result["unity_root"] = unity_cache_root()
    result["bank_dir"] = game_bank_dir()
    return result


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
