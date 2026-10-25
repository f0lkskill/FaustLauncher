"""Mod（资源包）的加载与卸载核心实现。

本模块负责把「启动器 mods 目录里的 Mod 包」投放成「游戏真正读取的资源」，
以及反过来把投放出去的东西清理干净。理解下面两个目录，才能看懂本文件：

1. **Mod 源目录**（启动器目录）：`<启动器根目录>/mods/<Mod名>/`
   - `mod_info.json`：Mod 元信息，关键字段有 `file_names`（要投放的包）与
     `settings.enable`（是否启用）；
   - `Installer.bat` / `Uninstaller.bat`：可选的安装/卸载脚本；
   - `extra_files/`：可选的本地化文本，会被复制进游戏 `lang/` 目录；
   - 以及 Mod 自带的资源文件（`.bank` / `.carra2` 等）。

2. **投放目录**（单文件 Mod 目录）：`%APPDATA%/LimbusCompanyMods`
   由 :func:`get_mod_root_dir` 给出。投放时会做**重命名**，统一加上
   `{Mod名}_` 前缀，避免不同 Mod 的同名资源互相覆盖：
   - `<Mod名>_<文件名>`：原样复制的资源；
   - `.bank` 额外生成一份同名的 `.rebank` 差分包，并用
     `<名>.rebank.src` 记录源 `bank` 的 MD5（见 `STAMP_SUFFIX`），用于判断
     「源 bank 没变就跳过重建差分」；
   - 目录里的 `launcher_manifest.json` 记录「上一轮投放了哪些文件」，
     下一轮据此找出不再被任何 Mod 引用的陈旧文件并移入 `_orphan/`。

本模块的关键约束：**所有清理动作都必须按 `{Mod名}_` 前缀严格匹配**，否则会
误删别的 Mod 的包。:func:`_target_belongs_to` 就是这条规则的唯一实现。

历史说明：早期版本用「给同名 bank 追加数字序号」的方式避免覆盖，现在投放名
已统一带 `{Mod名}_` 前缀，同名冲突由前缀解决，序号方案已整体移除。
"""

import os
import json
import hashlib
import datetime
import shutil
from typing import List, Dict, Any
from functions.base.settings_manager import SettingsManager
from functions.base.common.path_utils import get_mod_root_dir
from functions.web_update.translation_source import get_translation_dir_name as _translation_dir_name
from subprocess import run, CREATE_NO_WINDOW
from functions.base.common.json_io import read_json


def _decode_output(data):
    """把子进程输出解码成字符串。

    Windows 控制台的编码并不统一：中文系统上批处理脚本输出通常是 GBK，
    而程序自己打印的可能是 UTF-8。这里依次尝试 UTF-8、GBK，全都失败时
    用 UTF-8 + `errors="replace"` 兜底，保证日志不会因为一个坏字节而中断。

    Args:
        data: `subprocess` 拿到的原始字节（可能为 None 或空字节串）。

    Returns:
        解码后的文本；输入为空时返回空字符串。
    """
    if not data:
        return ''
    for enc in ('utf-8', 'gbk'):
        try:
            return data.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode('utf-8', errors='replace')


# 投放目录里的清单文件名：记录上一轮投放了哪些包，用于清理陈旧文件
MANIFEST_NAME = "launcher_manifest.json"
# 陈旧包（已无 Mod 引用）的隔离目录，放在投放目录下，方便用户手动找回
ORPHAN_DIR_NAME = "_orphan"
# 差分包版本标记的后缀：`<xxx>.rebank.src`，内容为源 bank 的 MD5
STAMP_SUFFIX = ".src"


def _manifest_path(mod_root: str) -> str:
    """返回投放目录下清单文件的完整路径。

    Args:
        mod_root: 投放目录（`%APPDATA%/LimbusCompanyMods`）。

    Returns:
        清单文件路径，如 `.../LimbusCompanyMods/launcher_manifest.json`。
    """
    return os.path.join(mod_root, MANIFEST_NAME)


def _read_manifest(mod_root: str) -> Dict[str, Any]:
    """读取投放清单。

    清单只是「上一轮状态的缓存」，不是权威数据：文件缺失、内容损坏、不是
    字典时都返回空字典，让调用方按「第一次运行」处理，绝不能因此中断加载。

    Args:
        mod_root: 投放目录。

    Returns:
        清单内容字典；读取失败时返回 `{}`。
    """
    try:
        with open(_manifest_path(mod_root), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_manifest(mod_root: str, data: Dict[str, Any]) -> None:
    """写入投放清单（先写临时文件再原子替换）。

    写入时自动补上 `version` 与 `written` 两个字段，便于排查「清单是哪一轮
    写的」。用 `os.replace` 而不是直接覆盖，避免写到一半崩溃留下半截 JSON。

    Args:
        mod_root: 投放目录。
        data: 要写入的清单内容，通常包含 `package`（本轮的包名列表）与
            `manual`（用户手动放置、不应被自动清理的包名列表）。
    """
    try:
        payload = dict(data)
        payload["version"] = 1
        payload["written"] = datetime.datetime.now().isoformat(timespec="seconds")
        tmp = _manifest_path(mod_root) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp, _manifest_path(mod_root))
    except OSError as e:
        print(f"写入 mod 清单失败: {e}", flush=True)


def _read_stamp(path: str) -> str:
    """读取差分包版本标记（源 bank 的 MD5）。

    Args:
        path: 标记文件路径，形如 `<xxx>.rebank.src`。

    Returns:
        文件内容（已 strip）；文件不存在或读不出来时返回空字符串，
        调用方会把它当成「标记不匹配」，从而重建差分。
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def _write_stamp(path: str, digest: str) -> None:
    """写入差分包版本标记。

    Args:
        path: 标记文件路径（`<xxx>.rebank.src`）。
        digest: 源 bank 的 MD5，下次加载时比对它来判断 Mod 是否更新。
    """
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(digest)
    except OSError as e:
        print(f"写入版本标记失败 {path}: {e}", flush=True)


def _remove_quietly(path: str, label: str = "文件") -> None:
    """删除一个文件，失败只打日志、不抛异常。

    卸载路径上个别文件删不掉（被游戏或杀软占用）不应中断整个卸载流程，
    所以这里吞掉 `OSError`。

    Args:
        path: 要删除的文件路径。
        label: 日志里用来称呼它的中文名，如「旧差分」「版本标记」。
    """
    try:
        if os.path.isfile(path):
            os.remove(path)
            print(f"删除{label}: {path}", flush=True)
    except OSError as e:
        print(f"删除{label} {path} 失败: {e}", flush=True)


def _listdir_safe(path: str) -> List[str]:
    """安全地列目录：目录不存在或没有权限时返回空列表。

    Args:
        path: 目录路径。

    Returns:
        目录下的条目名列表；出错时返回 `[]`（不抛异常）。
    """
    try:
        return os.listdir(path)
    except OSError:
        return []


def _target_belongs_to(target_name: str, prefix: str) -> bool:
    """判断投放目录里的某个文件是否属于指定 Mod。

    投放文件名规则是 `{Mod名}_{文件名}`，不同 Mod 的同名资源靠前缀天然区分，
    不再需要给 bank 追加序号。判定时先剥掉 `.src` 版本标记后缀，再取扩展名
    之前的主干，要求它与 `prefix`（`{Mod名}_{文件名主干}`）**完全相等**。

    这里刻意不用 `startswith` 做宽松匹配：Mod 名本身可能带下划线，宽松匹配会
    把 `A_B` 的包误判成属于 `A`，进而误删。

    Args:
        target_name: 投放目录里的文件名（可能带 `.src` / `.rebank` 等后缀）。
        prefix: 期望的前缀，形如 `{Mod名}_{文件名主干}`。

    Returns:
        属于该 Mod 时返回 True。

    Examples:
        >>> _target_belongs_to("Shadow_1.rebank.src", "Shadow_1")
        True
        >>> _target_belongs_to("Shadow_2.bank", "Shadow_1")
        False
    """
    name = target_name
    # `.src` 是版本标记，判断归属时先剥掉，否则扩展名解析会出错
    if name.lower().endswith(STAMP_SUFFIX):
        name = name[:-len(STAMP_SUFFIX)]
    stem = os.path.splitext(name)[0]
    return stem == prefix


def _move_orphans(target_dir: str, stale_names: List[str]) -> None:
    """把不再被任何 Mod 引用的陈旧包移到 `_orphan` 目录。

    不直接删除是刻意的：用户可能只是暂时禁用了 Mod，直接删包等于毁掉资源；
    移到 `_orphan` 后既能保证游戏不再读到它，又允许用户手动拖回上一级恢复。

    以下文件会被跳过（它们不是 Mod 投放的包）：
    - `*.orig` / `*.disabled`：备份与手动禁用的文件；
    - `launcher_manifest.json`：清单本身；
    - `log.txt`：日志。

    Args:
        target_dir: 投放目录。
        stale_names: 需要移走的文件名列表（来自旧清单与本轮投放结果的差集）。
    """
    moved = []
    orphan_dir = None  # 懒创建：没有要移动的文件时不留空目录
    for name in stale_names:
        path = os.path.join(target_dir, name)
        if not os.path.isfile(path):
            continue
        if name.lower().endswith((".orig", ".disabled")) or name in (MANIFEST_NAME, "log.txt"):
            continue
        if orphan_dir is None:
            orphan_dir = os.path.join(target_dir, ORPHAN_DIR_NAME)
            os.makedirs(orphan_dir, exist_ok=True)
        try:
            shutil.move(path, os.path.join(orphan_dir, name))
            moved.append(name)
        except OSError as e:
            print(f"移动残留文件 {name} 失败: {e}", flush=True)
    if moved:
        print(f"已把 {len(moved)} 个不再使用的附属文件移到 {ORPHAN_DIR_NAME}\\ "
              f"(需要可拖回上一级): {', '.join(moved)}", flush=True)


def _run_mod_bat(mod_path, bat_name, mod_name, timeout=None):
    """在 Mod 目录里执行它的 `.bat` 脚本（Install / Uninstall）。

    Mod 作者常用批处理做「拷贝资源」之类的自定义安装步骤，启动器必须支持。
    实现上有几个刻意的处理：

    1. 读取脚本内容后**删掉所有 `pause`**，写到临时文件 `_no_pause_<原名>`
       再执行 —— 否则批处理会卡在「请按任意键继续」把启动器一起挂住；
    2. `CREATE_NO_WINDOW` 避免弹出黑色控制台窗口；
    3. 捕获 stdout/stderr 并按 GBK/UTF-8 解码后打日志，方便排查 Mod 脚本报错；
    4. 无论成功失败都删掉临时脚本。

    Args:
        mod_path: Mod 目录（脚本所在目录，同时作为工作目录）。
        bat_name: 脚本文件名，如 `Installer.bat` / `Uninstaller.bat`。
        mod_name: Mod 名，仅用于日志前缀。
        timeout: 超时秒数；超时会抛 `TimeoutExpired`，由调用方决定如何处理。
    """
    try:
        abs_path = os.path.abspath(mod_path)
        bat_file = os.path.join(abs_path, bat_name)
        if not os.path.isfile(bat_file):
            print(f"[{mod_name}] 未找到 {bat_file}, 跳过", flush=True)
            return
        print(f"[{mod_name}] 运行 {bat_name} (cwd={abs_path})", flush=True)
        tmp_bat = os.path.join(abs_path, '_no_pause_' + bat_name)
        try:
            with open(bat_file, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
            # 去掉 pause（含其后同行内容），否则脚本会等人按键而卡死
            import re as _re
            content = _re.sub(r'\bpause\b[^\r\n]*', '', content, flags=_re.IGNORECASE)
            with open(tmp_bat, 'w', encoding='utf-8', errors='replace') as f:
                f.write(content)
            result = run(
                [tmp_bat],
                shell=True, creationflags=CREATE_NO_WINDOW,
                cwd=abs_path,
                capture_output=True,
                timeout=timeout,
            )
        finally:
            # 临时脚本必须清理，即使执行时抛了超时异常
            try:
                os.remove(tmp_bat)
            except Exception:
                pass
        for line in _decode_output(result.stdout).splitlines():
            if line.strip():
                print(f"[{mod_name} {bat_name}] {line}", flush=True)
        for line in _decode_output(result.stderr).splitlines():
            if line.strip():
                print(f"[{mod_name} {bat_name} stderr] {line}", flush=True)
    except Exception as e:
        print(f"执行 {mod_name} {bat_name} 失败: {e}", flush=True)


class ModManager:
    """Mod 的加载器 / 卸载器。

    职责边界：
    - **加载**（:meth:`load_all_mods`）：把 `mods/<Mod名>/` 里登记的资源复制到
      投放目录 `%APPDATA%/LimbusCompanyMods`，按需生成 `.rebank` 差分包，复制
      语言文件，并维护清单、清理陈旧包；
    - **卸载**（:meth:`unload_mod` / :meth:`unload_all_mods`）：删除投放目录里
      属于该 Mod 的包及其 `.rebank` / `.src` 附属文件，必要时先跑
      `Uninstaller.bat`。

    注意：这里的「卸载」只清理**投放目录**里的副本，不动 Mod 源目录，也
    不还原游戏本体资源；要还原游戏本体被改写的资源请用
    `functions.base.mod_force_uninstall`（强卸载）。

    Attributes:
        mod_dir: Mod 源目录名，相对于启动器根目录（即 `mods`）。
    """

    # Mod 源目录（启动器根目录下的 mods/），相对路径依赖进程工作目录为启动器根
    mod_dir = 'mods'

    def __init__(self):
        # 目前无需实例状态：目录与设置都实时从环境/配置文件读取
        pass

    def get_mod_directory(self) -> str:
        """返回投放目录（单文件 Mod 目录）的绝对路径。

        即 `%APPDATA%/LimbusCompanyMods`，由
        :func:`functions.base.common.path_utils.get_mod_root_dir` 负责创建与
        返回。所有「复制出去的包」都放在这里，游戏侧的 mod loader 从这里读取。

        Returns:
            投放目录的绝对路径字符串。
        """
        return get_mod_root_dir()

    @staticmethod
    def get_mod_info(mod_name: str) -> Dict[str, Any]:
        """读取指定 Mod 的 `mod_info.json`。

        Args:
            mod_name: Mod 目录名（不是 `mod_info.json` 里显示的展示名）。

        Returns:
            解析后的字典，常见字段：`name`、`version`、`author`、
            `description`、`file_names`、`settings`、`icon`。

        Raises:
            FileNotFoundError: Mod 目录或 `mod_info.json` 不存在。
        """
        mod_info_path = os.path.join(
            'mods', 
            mod_name, 
            'mod_info.json'
        )
        
        if not os.path.exists(mod_info_path):
            raise FileNotFoundError(f"Mod信息文件不存在: {mod_info_path}")
        
        return read_json(mod_info_path)
    
    @staticmethod
    def get_mod_path() -> List[str]:
        """列出所有「结构完整」的 Mod 目录路径。

        判定标准：`mods/` 下的子目录，且其中存在 `mod_info.json`。没有
        `mod_info.json` 的目录（比如用户随手放的文件夹）会被忽略。

        Returns:
            形如 `['mods/A', 'mods/B']` 的相对路径列表。
        """
        mods_dir = 'mods'
        mod_paths = []
        
        for mod_name in _listdir_safe(mods_dir):
            mod_path = os.path.join(mods_dir, mod_name)
            
            if os.path.isdir(mod_path) and os.path.exists(os.path.join(mod_path, 'mod_info.json')):
                mod_paths.append(mod_path)

        return mod_paths
    
    def load_all_mods(self) -> List[str]:
        """加载所有启用中的 Mod（启动器启动流程的核心步骤）。

        完整流程：

        1. 读旧清单，算出本轮应存在的包名集合 `new_pkg_names`；
        2. 遍历每个 Mod 目录：
           - 若 `settings.enable` 为真且存在 `Installer.bat`，先执行安装脚本；
           - 若为启用状态，把 `file_names` 里的文件复制到投放目录，统一加
             `{Mod名}_` 前缀；`.bank` 额外生成 `.rebank` 差分包并用 `.src`
             记录源 MD5（源没变则跳过重建，见 `STAMP_SUFFIX`）；
           - 复制该 Mod 的语言文件（:meth:`load_language`）；
           - 若为禁用状态，调用 :meth:`unload_mod` 清掉它投放的包；
        3. 用「旧清单 - 本轮包名 - 仍存在的 Mod 前缀」求出陈旧包，移入
           `_orphan/`（见 :func:`_move_orphans`），最后写回新清单。

        单个 Mod 出错只打日志并继续处理下一个，保证一个坏 Mod 不会让整个
        启动流程失败。

        Returns:
            本轮成功加载的 Mod 名列表。
        """
        loaded_mods = []

        manifest_root = self.get_mod_directory()
        old_manifest = _read_manifest(manifest_root)
        new_pkg_names: List[str] = []

        all_mod_paths = self.get_mod_path()
        if not all_mod_paths:
            print("mods 目录下没有可处理的 mod, 跳过本轮残留清理")
            return loaded_mods
        # 仍然存在的 Mod 前缀：它们的旧包不应被当成「陈旧包」移走
        alive_prefixes = {os.path.basename(p) + '_' for p in all_mod_paths}

        for mod_path in all_mod_paths:
            
            mod_name = os.path.basename(mod_path)
            
            try:
                # 有安装脚本的 Mod 需要在投放前先跑一遍（可能自带解包/转换逻辑）
                has_installer = os.path.exists(os.path.join(mod_path, 'Installer.bat'))
                    
                mod_info = self.get_mod_info(mod_name)
                if mod_info.get('settings', {}).get('enable', False) and has_installer:
                    _run_mod_bat(mod_path, 'Installer.bat', mod_name, timeout=300)
                    print(f"成功加载Mod贴图资源: {mod_name}")
            
                # 重新读取：Installer.bat 有可能改写了 mod_info.json
                mod_info = self.get_mod_info(mod_name)
                
                file_names = mod_info.get('file_names', [])
                    
                if mod_info.get("settings", {}).get("enable", False):
                    target_dir = self.get_mod_directory()

                    for file_name in file_names:
                        source_file = os.path.join(mod_path, file_name)
                        if not os.path.isfile(source_file):
                            print(f"跳过缺失文件: {source_file}")
                            continue

                        # 投放名统一加前缀，避免不同 Mod 的同名资源互相覆盖
                        target_name = f"{mod_name}_{file_name}"
                        target_file = os.path.join(target_dir, target_name)
                        new_pkg_names.append(target_name)

                        if file_name.lower().endswith('.bank'):
                            # .bank 除了本体，还要维护同名 .rebank 差分与 .src 标记
                            stem = os.path.splitext(file_name)[0]
                            rebank_name = f"{mod_name}_{stem}.rebank"
                            rebank_path = os.path.join(target_dir, rebank_name)
                            stamp_path = rebank_path + STAMP_SUFFIX
                            new_pkg_names.append(rebank_name)
                            new_pkg_names.append(rebank_name + STAMP_SUFFIX)
                            src_md5 = self._file_md5(source_file)

                            # 源 bank 没变且差分已存在 -> 无需重建，直接跳过
                            if os.path.isfile(rebank_path) and _read_stamp(stamp_path) == src_md5:
                                print(f"跳过 {file_name}: 差分已是最新 (源 bank 未变化)")
                                continue
                            if os.path.isfile(rebank_path):
                                print(f"检测到 mod 更新: {file_name} 已变化, 重新生成差分")
                                _remove_quietly(rebank_path, "旧差分")
                            os.makedirs(os.path.dirname(target_file), exist_ok=True)
                            shutil.copy2(source_file, target_file)
                            _write_stamp(stamp_path, src_md5)
                            print(f"复制 Mod 文件: {source_file} -> {target_file}")
                            continue

                        os.makedirs(os.path.dirname(target_file), exist_ok=True)

                        shutil.copy2(source_file, target_file)
                        print(f"复制 Mod 文件: {source_file} -> {target_file}")

                    self.load_language(mod_name, self.mod_dir)
                    
                    loaded_mods.append(mod_name)
                    print(f"成功加载Mod: {mod_name}")
                else:
                    # 禁用状态：确保它之前投放的包不残留
                    print(f"跳过Mod {mod_name}: 没有启用")
                    self.unload_mod(mod_name)

            except Exception as e:
                print(f"处理Mod {mod_name} 失败: {e}")
        
        # 清理陈旧包：不在本轮投放列表、且所属 Mod 已不存在的旧包
        try:
            target_root = self.get_mod_directory()
            stale = [n for n in (old_manifest.get("package") or [])
                     if n not in set(new_pkg_names)
                     and not any(n.startswith(p) for p in alive_prefixes)]
            
            if stale:
                _move_orphans(target_root, stale)
            _write_manifest(target_root, {"package": new_pkg_names,
                                          "manual": old_manifest.get("manual") or []})
        except Exception as e:
            print(f"同步 mod 清单失败: {e}", flush=True)

        return loaded_mods
        
    @staticmethod
    def _file_md5(path: str, chunk: int = 1 << 20) -> str:
        """分块计算文件的 MD5。

        用 1MB 分块而不是一次性读入，避免把几百 MB 的 bank 整个塞进内存。
        用于判断「源 bank 是否变化」以及「目标位置是否已存在同样内容」。

        Args:
            path: 文件路径。
            chunk: 每次读取的字节数，默认 1MB。

        Returns:
            32 位小写十六进制 MD5 摘要。
        """
        h = hashlib.md5()
        with open(path, "rb") as f:
            while True:
                b = f.read(chunk)
                if not b:
                    break
                h.update(b)
        return h.hexdigest()

    @staticmethod
    def load_language(name: str, dir: str) -> None:
        """把 Mod 自带的语言文件复制进游戏的语言目录。

        Mod 可以在 `mods/<Mod名>/extra_files/` 放本地化文本，游戏只会读取
        `<游戏目录>/LimbusCompany_Data/lang/<当前语言>/`，因此这里整体拷贝。
        目标语言目录名由
        :func:`functions.web_update.translation_source.get_translation_dir_name`
        给出（跟随启动器当前语言设置）。

        任何失败（游戏路径未配置、目录不存在、复制出错）都只打日志，不影响
        Mod 主体资源的加载。

        Args:
            name: Mod 目录名；传空字符串时表示从 `dir/extra_files` 读取
                （`dir` 直接作为源目录）。
            dir: Mod 源目录的父目录，通常传 `ModManager.mod_dir`（即 `mods`）。
        """
        try:
            game_path: str = SettingsManager().get_setting('game_path') # type: ignore
            
            if not os.path.exists(game_path):
                print(f"错误: 游戏路径不存在: {game_path}")
                return
            
            if name != '':
                lang_dir = os.path.join(dir, name, 'extra_files')
            else:
                lang_dir = dir + '/extra_files'
            
            if not os.path.exists(lang_dir):
                return
            
            target_lang_dir = os.path.join(game_path, 'LimbusCompany_Data', 'lang',
                                           _translation_dir_name())
            
            os.makedirs(target_lang_dir, exist_ok=True)
            
            # dirs_exist_ok=True：多次加载时覆盖旧文本而不是报「目录已存在」
            shutil.copytree(lang_dir, target_lang_dir, dirs_exist_ok=True)
            print(f"语言文件复制成功: {lang_dir} -> {target_lang_dir}/")
            
        except Exception as e:
            print(f"复制语言文件失败: {e}")
    
    def unload_all_mods(self) -> List[str]:
        """卸载所有 Mod 投放到投放目录里的包。

        对 `mods/` 下每个目录调用 :meth:`unload_mod`；注意它只清理投放目录，
        不会删除 Mod 源目录。

        Returns:
            实际处理过的 Mod 名列表（`unload_mod` 返回非空时计入）。
        """
        unloaded_mods = []
        mods_dir = self.mod_dir
        
        for mod_name in _listdir_safe(mods_dir):
            result = self.unload_mod(mod_name)
            if result:
                unloaded_mods.append(result)
        
        return unloaded_mods

    def unload_mod(self, mod_name: str, run_bat: bool = True) -> str | None:
        """卸载单个 Mod：清掉它在投放目录里的所有包。

        步骤：

        1. 若 `mods/<Mod名>/` 存在且含 `mod_info.json`，读取它的
           `file_names` 作为「归属判定」的依据；
        2. `run_bat=True` 且存在 `Uninstaller.bat` 时先执行卸载脚本（失败只
           打日志，不阻断后续清理）；
        3. 对每个登记文件名，构造前缀 `{Mod名}_{文件名主干}`，遍历投放目录，
           用 :func:`_target_belongs_to` 找出属于它的文件并删除；
        4. 删除 `.bank` 时顺带删除对应的 `.rebank` 差分与 `.rebank.src`
           版本标记。

        注意：这里**不会**还原游戏本体被 Mod 改写的资源，也不会删除 Mod
        源目录；完全还原请用 `functions.base.mod_force_uninstall` 的强卸载。

        Args:
            mod_name: Mod 目录名。
            run_bat: 是否执行 Mod 自带的 `Uninstaller.bat`。批量清理时若不想
                触发 Mod 脚本，可传 False。

        Returns:
            Mod 名（表示已处理）；Mod 目录不存在或处理异常时返回 None。
        """
        mod_path = os.path.join(self.mod_dir, mod_name)

        # 没有 mod_info.json 的目录不视为 Mod，直接跳过
        if os.path.isdir(mod_path) and os.path.exists(os.path.join(mod_path, 'mod_info.json')):
            try:
                mod_info = self.get_mod_info(mod_name)
                file_names = mod_info.get('file_names', [])
                do_flag = False

                # 投放目录（单文件 Mod 目录）
                target_dir = self.get_mod_directory()

                # 先跑 Mod 自带卸载脚本：它可能删掉本模块不认识的附属文件
                if run_bat and os.path.exists(
                    os.path.join(mod_path, 'Uninstaller.bat')):
                    try:
                        _run_mod_bat(mod_path, 'Uninstaller.bat', mod_name, timeout=30)
                        print(f"{mod_name} Mod 资源缓存成功清理", flush=True)
                    except Exception as e:
                        print(f"执行 {mod_name} Uninstaller.bat 失败(超时或异常): {e}", flush=True)

                for file_name in file_names:
                    stem, _ = os.path.splitext(file_name)
                    # 归属前缀：{Mod名}_{去掉扩展名的文件名}
                    prefix = mod_name + '_' + stem
                    try:
                        targets = os.listdir(target_dir)
                    except OSError:
                        print(f"无法读取目标目录: {target_dir}")
                        continue
                    for target_name in targets:
                        # 检查目标文件是否属于当前Mod
                        if not _target_belongs_to(target_name, prefix):
                            # 不属于
                            continue
                        chosen_file = os.path.join(target_dir, target_name)

                        try:
                            os.remove(chosen_file)
                            print(f"删除附属文件: {chosen_file}", flush=True)
                            do_flag = True
                        except OSError as e:
                            print(f"删除附属文件 {chosen_file} 失败: {e}", flush=True)

                        # .bank 的配套差分与版本标记一并清掉，否则会残留孤儿文件
                        if os.path.splitext(target_name)[1].lower() == ".bank":
                            cache = os.path.join(
                                target_dir, os.path.splitext(target_name)[0] + ".rebank")
                            if os.path.isfile(cache):
                                try:
                                    os.remove(cache)
                                    print(f"删除缓存: {cache}", flush=True)
                                except OSError as e:
                                    print(f"删除缓存 {cache} 失败: {e}", flush=True)
                            _remove_quietly(cache + STAMP_SUFFIX, "版本标记")

                if do_flag:
                    print(f"成功卸载Mod: {mod_name}")
                return mod_name
            except Exception as e:
                print(f"卸载Mod {mod_name} 失败: {e}")
        return None

    def get_all_mods(self) -> List[Dict[str, Any]]:
        """读取所有 Mod 的元信息。

        用于资源管理页面的 Mod 列表：遍历 `mods/` 下结构完整的目录，逐个
        读取 `mod_info.json`，并把目录名写入返回字典的 `name` 字段（后端
        后续操作用目录名作为唯一标识）。

        个别 Mod 的 `mod_info.json` 损坏时只打日志并跳过，不影响列表整体。

        Returns:
            Mod 信息字典列表，每项至少包含 `name`（目录名），其余字段来自
            `mod_info.json`。
        """
        mods = []
        mods_dir = 'mods'
        
        for mod_name in _listdir_safe(mods_dir):
            mod_path = os.path.join(mods_dir, mod_name)
            
            if os.path.isdir(mod_path) and os.path.exists(os.path.join(mod_path, 'mod_info.json')):
                try:
                    mod_info = self.get_mod_info(mod_name)
                    mod_info['name'] = mod_name
                    mods.append(mod_info)
                except Exception as e:
                    print(f"获取Mod {mod_name} 信息失败: {e}")
        
        return mods
