import os
import json
import hashlib
import datetime
import re
import shutil
from typing import List, Dict, Any
from functions.base.settings_manager import SettingsManager
from functions.base.common.path_utils import get_mod_root_dir
from functions.web_update.translation_source import get_translation_dir_name as _translation_dir_name
from subprocess import run, CREATE_NO_WINDOW
from functions.base.common.json_io import read_json

def _strip_suffix_number(name: str) -> str:
    m = re.match(r"^(.*?)(\d+)$", name)
    return m.group(1) if m else name

def _suffix_number(name: str) -> int:
    m = re.match(r"^(.*?)(\d+)$", name)
    return int(m.group(2)) if m else 0

def _decode_output(data):
    if not data:
        return ''
    for enc in ('utf-8', 'gbk'):
        try:
            return data.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode('utf-8', errors='replace')

MANIFEST_NAME = "launcher_manifest.json"
ORPHAN_DIR_NAME = "_orphan"
STAMP_SUFFIX = ".src"

def _manifest_path(mod_root: str) -> str:
    return os.path.join(mod_root, MANIFEST_NAME)

def _read_manifest(mod_root: str) -> Dict[str, Any]:
    try:
        with open(_manifest_path(mod_root), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}

def _write_manifest(mod_root: str, data: Dict[str, Any]) -> None:
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
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""

def _write_stamp(path: str, digest: str) -> None:
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(digest)
    except OSError as e:
        print(f"写入版本标记失败 {path}: {e}", flush=True)

def _remove_quietly(path: str, label: str = "文件") -> None:
    try:
        if os.path.isfile(path):
            os.remove(path)
            print(f"删除{label}: {path}", flush=True)
    except OSError as e:
        print(f"删除{label} {path} 失败: {e}", flush=True)

def _listdir_safe(path: str) -> List[str]:
    try:
        return os.listdir(path)
    except OSError:
        return []

def _target_belongs_to(target_name: str, prefix: str) -> bool:
    name = target_name
    if name.lower().endswith(STAMP_SUFFIX):
        name = name[:-len(STAMP_SUFFIX)]
    stem = os.path.splitext(name)[0]
    if stem == prefix:
        return True
    if stem.startswith(prefix):
        return stem[len(prefix):].isdigit()
    return False

def _move_orphans(target_dir: str, stale_names: List[str]) -> None:
    moved = []
    orphan_dir = None
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
    mod_dir = 'mods'
     
    def __init__(self):
        pass

    def get_mod_directory(self):
        return get_mod_root_dir()
    
    @staticmethod
    def get_mod_info(mod_name: str) -> Dict[str, Any]:
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
        mods_dir = 'mods'
        mod_paths = []
        
        for mod_name in _listdir_safe(mods_dir):
            mod_path = os.path.join(mods_dir, mod_name)
            
            if os.path.isdir(mod_path) and os.path.exists(os.path.join(mod_path, 'mod_info.json')):
                mod_paths.append(mod_path)

        return mod_paths
    
    def load_all_mods(self) -> List[str]:
        loaded_mods = []
        used = {}

        manifest_root = self.get_mod_directory()
        old_manifest = _read_manifest(manifest_root)
        new_pkg_names: List[str] = []

        all_mod_paths = self.get_mod_path()
        if not all_mod_paths:
            print("mods 目录下没有可处理的 mod, 跳过本轮残留清理")
            return loaded_mods
        alive_prefixes = {os.path.basename(p) + '_' for p in all_mod_paths}

        for mod_path in all_mod_paths:
            
            mod_name = os.path.basename(mod_path)
            
            try:
                has_installer = os.path.exists(os.path.join(mod_path, 'Installer.bat'))
                    
                mod_info = self.get_mod_info(mod_name)
                if mod_info.get('settings', {}).get('enable', False) and has_installer:
                    _run_mod_bat(mod_path, 'Installer.bat', mod_name, timeout=300)
                    print(f"成功加载Mod贴图资源: {mod_name}")
            
                mod_info = self.get_mod_info(mod_name)
                
                file_names = mod_info.get('file_names', [])
                    
                if mod_info.get("settings", {}).get("enable", False):
                    target_dir = self.get_mod_directory()

                    for file_name in file_names:
                        source_file = os.path.join(mod_path, file_name)
                        if not os.path.isfile(source_file):
                            print(f"跳过缺失文件: {source_file}")
                            continue
                        target_name = f"{mod_name}_{file_name}"
                        target_file = os.path.join(target_dir, target_name)
                        new_pkg_names.append(target_name)

                        if file_name.lower().endswith('.bank'):
                            stem = os.path.splitext(file_name)[0]
                            rebank_name = f"{mod_name}_{stem}.rebank"
                            rebank_path = os.path.join(target_dir, rebank_name)
                            stamp_path = rebank_path + STAMP_SUFFIX
                            new_pkg_names.append(rebank_name)
                            new_pkg_names.append(rebank_name + STAMP_SUFFIX)
                            src_md5 = self._file_md5(source_file)
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
                    print(f"跳过Mod {mod_name}: 没有启用")
                    self.unload_mod(mod_name)

            except Exception as e:
                print(f"处理Mod {mod_name} 失败: {e}")
        
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
        h = hashlib.md5()
        with open(path, "rb") as f:
            while True:
                b = f.read(chunk)
                if not b:
                    break
                h.update(b)
        return h.hexdigest()

    @staticmethod
    def _rebank_max_index(target_dir: str, base: str) -> int:
        max_idx = -1
        try:
            for f in os.listdir(target_dir):
                if not f.lower().endswith(".rebank"):
                    continue
                stem = f[:-len(".rebank")]
                if _strip_suffix_number(stem) == base:
                    max_idx = max(max_idx, _suffix_number(stem))
        except OSError:
            pass
        return max_idx

    @classmethod
    def _unique_bank_name(cls, target_dir: str, source_file: str, file_name: str,
                          used: Dict[str, str]):
        stem, ext = os.path.splitext(file_name)
        src_md5 = cls._file_md5(source_file)

        base = _strip_suffix_number(stem)
        own_idx = _suffix_number(stem)
        max_rebank_idx = cls._rebank_max_index(target_dir, base)

        if max_rebank_idx >= 0 and own_idx <= max_rebank_idx:
            num = 0
            while True:
                candidate = "%s%d%s" % (base, max_rebank_idx + 1 + num, ext)
                if candidate in used and used[candidate] != src_md5:
                    num += 1
                    continue
                target = os.path.join(target_dir, candidate)
                if os.path.exists(target):
                    try:
                        if cls._file_md5(target) == src_md5:
                            break
                    except OSError:
                        pass
                    num += 1
                    continue
                break
            used[candidate] = src_md5
            return os.path.join(target_dir, candidate), candidate

        candidate = file_name
        num = 0
        while True:
            if candidate in used:
                if used[candidate] == src_md5:
                    break
            else:
                target = os.path.join(target_dir, candidate)
                if os.path.exists(target):
                    try:
                        if cls._file_md5(target) == src_md5:
                            break
                    except OSError:
                        pass
                else:
                    break
            num += 1
            candidate = "%s%d%s" % (stem, num, ext)
        used[candidate] = src_md5
        return os.path.join(target_dir, candidate), candidate
        
    @staticmethod
    def load_language(name: str, dir: str) -> None:
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
            
            shutil.copytree(lang_dir, target_lang_dir, dirs_exist_ok=True)
            print(f"语言文件复制成功: {lang_dir} -> {target_lang_dir}/")
            
        except Exception as e:
            print(f"复制语言文件失败: {e}")
    
    def unload_all_mods(self) -> List[str]:
        unloaded_mods = []
        mods_dir = self.mod_dir
        
        for mod_name in _listdir_safe(mods_dir):
            result = self.unload_mod(mod_name)
            if result:
                unloaded_mods.append(result)
        
        return unloaded_mods

    def unload_mod(self, mod_name:str, run_bat: bool = True):
        mod_path = os.path.join(self.mod_dir, mod_name)

        if os.path.isdir(mod_path) and os.path.exists(os.path.join(mod_path, 'mod_info.json')):
            try:
                mod_info = self.get_mod_info(mod_name)
                file_names = mod_info.get('file_names', [])
                do_flag = False
                
                target_dir = self.get_mod_directory()

                if run_bat and os.path.exists(
                    os.path.join(mod_path, 'Uninstaller.bat')):
                    try:
                        _run_mod_bat(mod_path, 'Uninstaller.bat', mod_name, timeout=30)
                        print(f"{mod_name} Mod 资源缓存成功清理", flush=True)
                    except Exception as e:
                        print(f"执行 {mod_name} Uninstaller.bat 失败(超时或异常): {e}", flush=True)

                for file_name in file_names:
                    stem, _ = os.path.splitext(file_name)
                    prefix = mod_name + '_' + stem
                    try:
                        targets = os.listdir(target_dir)
                    except OSError:
                        print(f"无法读取目标目录: {target_dir}")
                        continue
                    for target_name in targets:
                        if not _target_belongs_to(target_name, prefix):
                            continue
                        chosen_file = os.path.join(target_dir, target_name)
                        try:
                            os.remove(chosen_file)
                            print(f"删除附属文件: {chosen_file}", flush=True)
                            do_flag = True
                        except OSError as e:
                            print(f"删除附属文件 {chosen_file} 失败: {e}", flush=True)
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
    
    def get_all_mods(self) -> List[Dict[str, Any]]:
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
