import os
import json
import hashlib
import re
import shutil
from typing import List, Dict, Any
from functions.base.settings_manager import SettingsManager
from functions.base.common.path_utils import get_mod_root_dir
from functions.web_update.translation_source import get_translation_dir_name as _translation_dir_name
from subprocess import run, CREATE_NO_WINDOW


def _strip_suffix_number(name: str) -> str:
    """去掉名字末尾的数字（同名 mod 的 1,2,3... 序列后缀）"""
    m = re.match(r"^(.*?)(\d+)$", name)
    return m.group(1) if m else name


def _suffix_number(name: str) -> int:
    """名字末尾的数字；没有数字的按 0"""
    m = re.match(r"^(.*?)(\d+)$", name)
    return int(m.group(2)) if m else 0


def _decode_output(data):
    """bat 输出解码: cmd 默认用系统 ANSI/OEM 编码 (中文系统 GBK), 先试 UTF-8, 失败回落 GBK"""
    if not data:
        return ''
    for enc in ('utf-8', 'gbk'):
        try:
            return data.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode('utf-8', errors='replace')


def _run_mod_bat(mod_path, bat_name, mod_name, timeout=None):
    """运行 mod 的 bat 脚本 (cwd=mod 目录绝对路径), 捕获并打印其 echo 输出。
    运行前移除 bat 内的 pause 命令 (pause 会阻塞等待按键导致超时)。"""
    try:
        abs_path = os.path.abspath(mod_path)
        bat_file = os.path.join(abs_path, bat_name)
        if not os.path.isfile(bat_file):
            print(f"[{mod_name}] 未找到 {bat_file}, 跳过", flush=True)
            return
        print(f"[{mod_name}] 运行 {bat_name} (cwd={abs_path})", flush=True)
        # 生成去掉 pause 的临时 bat (pause 阻塞等待按键, 无交互环境必超时)
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
        """初始化Mod工具类"""
        pass

    def get_mod_directory(self):
        """获取Mod目录路径"""
        return get_mod_root_dir()
    
    @staticmethod
    def get_mod_info(mod_name: str) -> Dict[str, Any]:
        """获取Mod信息"""
        mod_info_path = os.path.join(
            'mods', 
            mod_name, 
            'mod_info.json'
        )
        
        if not os.path.exists(mod_info_path):
            raise FileNotFoundError(f"Mod信息文件不存在: {mod_info_path}")
        
        with open(mod_info_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    @staticmethod
    def get_mod_path() -> List[str]:
        mods_dir = 'mods'
        mod_paths = []
        
        # 遍历所有mod目录
        for mod_name in os.listdir(mods_dir):
            mod_path = os.path.join(mods_dir, mod_name)
            
            # 检查是否是目录且存在mod_info.json
            if os.path.isdir(mod_path) and os.path.exists(os.path.join(mod_path, 'mod_info.json')):
                mod_paths.append(mod_path)

        return mod_paths
    
    def load_all_mods(self) -> List[str]:
        """
        装载所有mod
        读取每个mod_info.json里的settings键值来决定是否加载
        """
        loaded_mods = []
        used = {}  # 本次装载已占用的目标文件名 -> 源文件 md5 (同名 .bank 编号用)

        # 遍历所有mod目录
        for mod_path in self.get_mod_path():
            
            mod_name = os.path.basename(mod_path)
            
            try:
                has_installer = False
                has_uninstaller = False
                try:
                    # 删除 安装/卸载 脚本的 pause 命令, 可读可写模式
                    # 用 r+ 模式打开文件（可读可写）
                    for file_name in ['Installer.bat', 'Uninstaller.bat']:
                        if not os.path.exists(os.path.join(mod_path, file_name)):
                            # 这个Mod没有安装/卸载脚本，跳过删除pause命令
                            continue
                        
                        # 检查文件名，设置标志
                        if file_name == 'Installer.bat':
                            has_installer = True
                        elif file_name == 'Uninstaller.bat':
                            has_uninstaller = True
                            
                        with open(os.path.join(mod_path, file_name), 'r+', encoding='utf-8') as f:
                            content = f.read()  # 读取全部内容
                            content = content.replace('pause', '')
                            f.seek(0)          # 回到文件开头
                            f.write(content)   # 写入新内容
                            f.truncate()       # 截断多余内容（如果新内容比旧内容短）
                            
                except Exception as e:
                    print(f"删除脚本pause命令时出错: {e}")
                    
                # 获取mod信息
                mod_info = self.get_mod_info(mod_name)
                if mod_info.get('settings', {}).get('enable', False) and has_installer:
                    # 启用mod，载入文件
                    # 执行安装脚本 (cwd=mod_path: bat 内相对路径基于 mod 目录), 输出 echo 内容
                    _run_mod_bat(mod_path, 'Installer.bat', mod_name)
                    # print(f"成功加载Mod贴图资源: {mod_name}")
                elif mod_info.get('settings', {}).get('enable', False) and has_uninstaller:
                    # 禁用mod
                    _run_mod_bat(mod_path, 'Uninstaller.bat', mod_name)
                    # print(f"成功卸载Mod贴图资源: {mod_name}")
            
                # 获取mod信息
                mod_info = self.get_mod_info(mod_name)
                
                # 获取file_names，确保变量在任何分支中都已定义
                file_names = mod_info.get('file_names', [])
                    
                # 检查settings键值
                if mod_info["settings"].get("enable", False):
                    # 获取目标目录
                    target_dir = self.get_mod_directory()

                    # 复制文件
                    for file_name in file_names:
                        source_file = os.path.join(mod_path, file_name)
                        if not os.path.isfile(source_file):
                            print(f"跳过缺失文件: {source_file}")
                            continue

                        if file_name.lower().endswith('.bank'):
                            stem, ext = os.path.splitext(file_name)
                            # 需求: mod 目录已有对应 rebank 差分则不处理
                            if os.path.exists(os.path.join(target_dir, stem + '.rebank')):
                                print(f"跳过 {file_name}: 已有对应 rebank 差分，无需复制")
                                continue
                            # 需求: 同名声音 mod 文件 → 名字末尾添加 1,2,3...
                            target_file, file_name = self._unique_bank_name(
                                target_dir, source_file, file_name, used)
                        else:
                            target_file = os.path.join(target_dir, file_name)

                        # 确保目标目录存在
                        os.makedirs(os.path.dirname(target_file), exist_ok=True)

                        # 复制文件
                        shutil.copy2(source_file, target_file)
                        print(f"复制 Mod 文件: {source_file} -> {target_file}")

                    # 装载语言文件
                    self.load_language(mod_name, self.mod_dir)
                    
                    loaded_mods.append(mod_name)
                    print(f"成功加载Mod: {mod_name}")
                else:
                    print(f"跳过Mod {mod_name}: 没有启用")
                    # 清理已复制文件/转换缓存/语言文件 (含 Uninstaller.bat)
                    self.unload_mod(mod_name)

            except Exception as e:
                print(f"处理Mod {mod_name} 失败: {e}")
        
        return loaded_mods
        
    @staticmethod
    def _file_md5(path: str, chunk: int = 1 << 20) -> str:
        """计算文件 md5（用于区分同名文件是否同一内容）"""
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
        """目标目录中针对同一原版 bank 的 rebank 最大序号（无则 -1）。

        家族 = 去掉末尾数字的 stem（X.assets1.rebank / X.assets.rebank -> X.assets）。
        只统计启用状态的 .rebank（不含 .disabled）。
        """
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
        """同名声音 mod 文件 → 名字末尾添加 1,2,3... 序列后缀。

        规则（针对同一原版 bank 的多个 mod）：
        - 目标目录已有同家族 rebank（如 X.assets1.rebank）时，新复制 bank 延续其
          最大序号 +1（如 -> X.assets2.bank），保证应用顺序正确、不被旧 rebank 遮蔽；
        - 自身序号已大于已有 rebank 最大序号则保留原名；
        - 无 rebank 家族时：内容相同的同名文件原地覆盖（保持原名，避免每次启动都
          累加编号），不同内容的同名文件在名字末尾加数字。
        返回 (目标路径, 最终文件名)。
        """
        stem, ext = os.path.splitext(file_name)
        src_md5 = cls._file_md5(source_file)

        base = _strip_suffix_number(stem)
        own_idx = _suffix_number(stem)
        max_rebank_idx = cls._rebank_max_index(target_dir, base)

        if max_rebank_idx >= 0 and own_idx <= max_rebank_idx:
            # 与既有 rebank 针对同一原版: 延续索引, 新 bank 排到既有差分之后
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
                            break  # 目标已存在且内容相同
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
                    break  # 同一份文件再次复制，原地覆盖
            else:
                target = os.path.join(target_dir, candidate)
                if os.path.exists(target):
                    try:
                        if cls._file_md5(target) == src_md5:
                            break  # 目标已存在且内容相同，原地覆盖
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
        """
        装载语言文件到游戏目录下的 lang 文件夹下
        """
        try:
            game_path: str = SettingsManager().get_setting('game_path') # type: ignore
            
            # 检查游戏路径是否存在
            if not os.path.exists(game_path):
                print(f"错误: 游戏路径不存在: {game_path}")
                return
            
            # 确定源目录
            if name != '':
                lang_dir = os.path.join(dir, name, 'extra_files')
            else:
                lang_dir = dir + '/extra_files'
            
            # 检查源目录是否存在
            if not os.path.exists(lang_dir):
                # print(f"{name} 没有额外的语言文件, 跳过复制语言文件。")
                return
            
            target_lang_dir = os.path.join(game_path, 'LimbusCompany_Data', 'lang', 'LLC_zh-CN')
            
            # 创建目标目录（如果不存在）
            os.makedirs(target_lang_dir, exist_ok=True)
            
            # 复制整个目录结构，使用 dirs_exist_ok=True 允许目标目录存在
            shutil.copytree(lang_dir, target_lang_dir, dirs_exist_ok=True)
            print(f"语言文件复制成功: {lang_dir} -> {target_lang_dir}/")
            
        except Exception as e:
            print(f"复制语言文件失败: {e}")
    
    def unload_all_mods(self) -> List[str]:
        """
        卸载所有mod
        删除所有mod的文件
        """
        unloaded_mods = []
        mods_dir = self.mod_dir
        
        # 遍历所有mod目录
        for mod_name in os.listdir(mods_dir):
            result = self.unload_mod(mod_name)
            if result:
                unloaded_mods.append(result)
        
        return unloaded_mods

    def unload_mod(self, mod_name:str, run_bat: bool = True):
        """
        卸载指定mod
        Args:
            mod_name (str): mod名称
            run_bat (bool): 是否执行 Uninstaller.bat (默认运行, 输出 echo 日志;
                            若 bat 派生进程占用 mods 目录导致删除失败, 可设为 False 跳过)
        """
        mod_path = os.path.join(self.mod_dir, mod_name)

        # 检查是否是目录且存在mod_info.json
        if os.path.isdir(mod_path) and os.path.exists(os.path.join(mod_path, 'mod_info.json')):
            try:
                # 获取mod信息
                mod_info = self.get_mod_info(mod_name)
                file_names = mod_info.get('file_names', [])
                
                # 获取目标目录
                target_dir = self.get_mod_directory()

                # 1) 先执行卸载脚本 (清理 Installer.bat 复制到游戏目录的缓存), 带超时防阻塞, 输出 echo 内容
                if run_bat and os.path.exists(
                    os.path.join(mod_path, 'Uninstaller.bat')):
                    try:
                        _run_mod_bat(mod_path, 'Uninstaller.bat', mod_name, timeout=30)
                        print(f"{mod_name} Mod 资源缓存成功清理", flush=True)
                    except Exception as e:
                        print(f"执行 {mod_name} Uninstaller.bat 失败(超时或异常): {e}", flush=True)

                # 2) 删除复制到目标目录的文件:
                #    加载器会把 .bank 转成 .rebank, 同名声音 mod 可能带 X1/X2 编号副本,
                #    因此按"文件名(去后缀) stem 家族"匹配, 包含即可, 不校验后缀/md5,
                #    删除目标目录下所有匹配文件 (含 .bank/.rebank/.dll 等)
                for file_name in file_names:
                    stem, _ = os.path.splitext(file_name)
                    base = _strip_suffix_number(stem)
                    try:
                        targets = os.listdir(target_dir)
                    except OSError:
                        continue
                    for target_name in targets:
                        t_stem, _ = os.path.splitext(target_name)
                        t_base = _strip_suffix_number(t_stem)
                        if base not in t_base and t_base not in base:
                            continue
                        chosen_file = os.path.join(target_dir, target_name)
                        try:
                            os.remove(chosen_file)
                            print(f"删除文件: {chosen_file}", flush=True)
                        except OSError as e:
                            print(f"删除文件 {chosen_file} 失败: {e}", flush=True)
                        # bank 转换遗留的差分缓存一并清理 (转换命名 = bank 同名)
                        if os.path.splitext(target_name)[1].lower() == ".bank":
                            cache = os.path.join(target_dir, t_stem + ".rebank")
                            if os.path.isfile(cache):
                                try:
                                    os.remove(cache)
                                    print(f"删除缓存: {cache}", flush=True)
                                except OSError as e:
                                    print(f"删除缓存 {cache} 失败: {e}", flush=True)

                # 3) 清理 extra_files 合并进游戏汉化目录的语言文件 (内容一致才删)
                lang_dir = os.path.join(mod_path, 'extra_files')
                if os.path.isdir(lang_dir):
                    try:
                        game_path: str = SettingsManager().get_setting('game_path') # type: ignore
                        target_lang_dir = os.path.join(game_path, 'LimbusCompany_Data', 'lang',
                                                       _translation_dir_name())
                        for root, _, files in os.walk(lang_dir):
                            for fn in files:
                                src = os.path.join(root, fn)
                                dst = os.path.join(target_lang_dir, os.path.relpath(src, lang_dir))
                                try:
                                    if os.path.isfile(dst) and self._file_md5(dst) == self._file_md5(src):
                                        os.remove(dst)
                                        print(f"删除语言文件: {dst}")
                                except OSError:
                                    pass
                    except Exception as e:
                        print(f"清理语言文件失败: {e}")

                print(f"成功卸载Mod: {mod_name}")
                return mod_name
            except Exception as e:
                print(f"卸载Mod {mod_name} 失败: {e}")
    
    def get_all_mods(self) -> List[Dict[str, Any]]:
        """获取所有可用的mod信息"""
        mods = []
        mods_dir = 'mods'
        
        # 遍历所有mod目录
        for mod_name in os.listdir(mods_dir):
            mod_path = os.path.join(mods_dir, mod_name)
            
            # 检查是否是目录且存在mod_info.json
            if os.path.isdir(mod_path) and os.path.exists(os.path.join(mod_path, 'mod_info.json')):
                try:
                    mod_info = self.get_mod_info(mod_name)
                    mod_info['name'] = mod_name
                    mods.append(mod_info)
                except Exception as e:
                    print(f"获取Mod {mod_name} 信息失败: {e}")
        
        return mods