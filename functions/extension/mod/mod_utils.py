import os
import json
import shutil
from typing import List, Dict, Any
from functions.base.settings_manager import SettingsManager
from subprocess import call, CREATE_NO_WINDOW

class ModManager:
    mod_dir = 'mods'
     
    def __init__(self):
        """初始化Mod工具类"""
        pass

    def get_mod_directory(self):
        """获取Mod目录路径"""
        roaming_path = os.getenv('APPDATA')
        mod_path = os.path.join(roaming_path, 'LimbusCompanyMods') # type: ignore
        
        # 如果目录不存在则创建
        if not os.path.exists(mod_path):
            os.makedirs(mod_path)
            print(f"创建Mod目录: {mod_path}")
        
        return mod_path
    
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
                    # 执行安装脚本
                    call([os.path.join(mod_path, 'Installer.bat')], shell=True, creationflags=CREATE_NO_WINDOW)
                    # print(f"成功加载Mod贴图资源: {mod_name}")
                elif mod_info.get('settings', {}).get('enable', False) and has_uninstaller:
                    # 禁用mod
                    call([os.path.join(mod_path, 'Uninstaller.bat')], shell=True, creationflags=CREATE_NO_WINDOW)
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
                    # 删除所有文件
                    target_dir = self.get_mod_directory()
                    for file_name in file_names:
                        target_file = os.path.join(target_dir, file_name)
                        if os.path.exists(target_file):
                            os.remove(target_file)
                            print(f"卸载 Mod 文件: {target_file}")

            except Exception as e:
                print(f"处理Mod {mod_name} 失败: {e}")
        
        return loaded_mods
        
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
        mods_dir = 'mods'
        
        # 遍历所有mod目录
        for mod_name in os.listdir(mods_dir):
            mod_path = os.path.join(mods_dir, mod_name)
            
            # 检查是否是目录且存在mod_info.json
            if os.path.isdir(mod_path) and os.path.exists(os.path.join(mod_path, 'mod_info.json')):
                try:
                    # 获取mod信息
                    mod_info = self.get_mod_info(mod_name)
                    file_names = mod_info.get('file_names', [])
                    
                    # 获取目标目录
                    target_dir = self.get_mod_directory()
                    
                    # 删除文件
                    for file_name in file_names:
                        target_file = os.path.join(target_dir, file_name)
                        
                        if os.path.exists(target_file):
                            os.remove(target_file)
                            print(f"删除文件: {target_file}")
                    
                    unloaded_mods.append(mod_name)
                    print(f"成功卸载Mod: {mod_name}")
                except Exception as e:
                    print(f"卸载Mod {mod_name} 失败: {e}")
        
        return unloaded_mods
    
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