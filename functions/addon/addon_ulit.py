import os
import json
import threading
from typing import Dict, List, Optional, Any

class AddonManager:
    """
    插件管理器
    负责记录插件路径, 获取指定插件的路径, 以及其下的 addon_info.json 信息, 解析运行 scr.py 等
    """

    def __init__(self, menu_items) -> None:
        """
        初始化插件管理器
        """
        self.menu_items = menu_items
        self.gamestart_funcs = []
        self.addon_paths: List[str] = []
        self.addon_names: List[str] = []
        self.addons_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'addons')
        self.scan_addons()
    
    def scan_addons(self) -> None:
        """
        扫描addons文件夹，记录所有插件路径
        """
        self.addon_paths = []
        if not os.path.exists(self.addons_dir):
            os.makedirs(self.addons_dir)
            return
        
        # 遍历addons文件夹下的所有子文件夹作为插件
        for item in os.listdir(self.addons_dir):
            item_path = os.path.join(self.addons_dir, item)
            if os.path.isdir(item_path):
                self.addon_paths.append(item_path)
                self.addon_names.append(str(item_path).split('\\')[-1])
    
    def get_addon_info(self, addon_name: str) -> Optional[Dict[str, Any]]:
        """
        获取指定插件的addon_info.json信息
        
        Args:
            addon_name: 插件名称
            
        Returns:
            插件信息字典，如果没有找到则返回None
        """
        addon_path = self.get_addon_path(addon_name)
        if not addon_path:
            return None
        
        info_path = os.path.join(addon_path, 'addon_info.json')
        if not os.path.exists(info_path):
            print(f"插件 {addon_name} 缺少 addon_info.json 文件")
            return None
        
        try:
            with open(info_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"读取插件信息失败: {e}")
            return None
    
    def get_addon_path(self, addon_name: str) -> Optional[str]:
        """
        根据插件名称获取插件路径
        
        Args:
            addon_name: 插件名称
            
        Returns:
            插件路径，如果没有找到则返回None
        """
        for path in self.addon_paths:
            if os.path.basename(path) == addon_name:
                return path
        return None
    
    def get_all_addons(self) -> List[Dict[str, Any]]:
        """
        获取所有插件的信息列表
        
        Returns:
            插件信息列表
        """
        addons = []
        for path in self.addon_paths:
            addon_name = os.path.basename(path)
            info = self.get_addon_info(addon_name)
            if info:
                addons.append({
                    'name': addon_name,
                    'path': path,
                    'info': info
                })
            else:
                addons.append({
                    'name': addon_name,
                    'path': path,
                    'info': {'name': addon_name, 'description': '无描述'}
                })
        return addons
    
    def run_addon(self, addon_name: str, ADDON_ARG:dict = {}):
        """
        运行指定插件的scr.py
        
        Args:
            addon_name: 插件名称
            *args: 传递给插件的位置参数
            **kwargs: 传递给插件的关键字参数
            
        Returns:
            是否运行成功
        """

        # print(self.get_addon_info(addon_name))
        if self.get_addon_info(addon_name)["settings"]["enable"] is False: # type: ignore
            print(f"插件 {addon_name} 被禁用，跳过运行")
            return False

        addon_path = self.get_addon_path(addon_name)
        if not addon_path:
            print(f"插件 {addon_name} 不存在")
            return False
        
        # 尝试运行scr.py
        scr_path = os.path.join(addon_path, 'scr.py')
        if not os.path.exists(scr_path):
            print(f"插件 {addon_name} 缺少 scr.py 文件")
            return False
        
        def thread_run():
            try:
                ADDON_ARG['AddonManager'] = self
                ADDON_ARG['AddonName'] = addon_name

                addon_file = open(addon_path + '\\scr.py', encoding='utf-8')
                addon_scr = addon_file.read()
                
                # print(addon_scr)

                exec(addon_scr)

                print(f"插件 {addon_name} 初始化完成!")

            except Exception as e:
                print(f"插件 {addon_name} 载入失败: {e}")

            finally:
                addon_file.close() # type: ignore
        
        print(f"载入插件 {addon_name}...")

        thread_run()

        # threading.Thread(target=thread_run).start()
        return True
        
    def add_addon(self, addon_path: str) -> bool:
        """
        添加插件
        
        Args:
            addon_path: 插件路径
            
        Returns:
            是否添加成功
        """
        if not os.path.exists(addon_path):
            print(f"插件路径不存在: {addon_path}")
            return False
        
        addon_name = os.path.basename(addon_path)
        dest_path = os.path.join(self.addons_dir, addon_name)
        
        if os.path.exists(dest_path):
            print(f"插件 {addon_name} 已存在")
            return False
        
        try:
            # 复制插件到addons文件夹
            import shutil
            shutil.copytree(addon_path, dest_path)
            self.scan_addons()
            print(f"插件 {addon_name} 添加成功")
            return True
        except Exception as e:
            print(f"添加插件失败: {e}")
            return False
    
    def remove_addon(self, addon_name: str) -> bool:
        """
        删除插件
        
        Args:
            addon_name: 插件名称
            
        Returns:
            是否删除成功
        """
        addon_path = self.get_addon_path(addon_name)
        if not addon_path:
            print(f"插件 {addon_name} 不存在")
            return False
        
        try:
            import shutil
            shutil.rmtree(addon_path)
            self.scan_addons()
            print(f"插件 {addon_name} 删除成功")
            return True
        except Exception as e:
            print(f"删除插件失败: {e}")
            return False
        
    def run_all_addon(self, ADDON_ARG:dict = {}):
        for name in self.addon_names:
            self.run_addon(name, ADDON_ARG)

    def run_game_start_event(self):
        for f in self.gamestart_funcs:
            f()