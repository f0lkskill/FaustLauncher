import os
import json
import shutil
from typing import List, Dict, Any

class ModUtils:
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
    
    def get_mod_info(self, mod_name: str) -> Dict[str, Any]:
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
    
    def load_all_mods(self) -> List[str]:
        """
        装载所有mod
        读取每个mod_info.json里的settings键值来决定是否加载
        """
        loaded_mods = []
        mods_dir = 'mods'
        
        # 遍历所有mod目录
        for mod_name in os.listdir(mods_dir):
            mod_path = os.path.join(mods_dir, mod_name)
            
            # 检查是否是目录且存在mod_info.json
            if os.path.isdir(mod_path) and os.path.exists(os.path.join(mod_path, 'mod_info.json')):
                try:
                    # 获取mod信息
                    mod_info = self.get_mod_info(mod_name)
                    
                    # 检查settings键值
                    if mod_info["settings"].get("enable", False):
                        file_names = mod_info.get('file_names', [])
                        
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
                            print(f"复制文件: {source_file} -> {target_file}")
                        
                        loaded_mods.append(mod_name)
                        print(f"成功加载Mod: {mod_name}")
                    else:
                        print(f"跳过Mod {mod_name}: 没有启用")
                except Exception as e:
                    print(f"加载Mod {mod_name} 失败: {e}")
        
        return loaded_mods
    
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