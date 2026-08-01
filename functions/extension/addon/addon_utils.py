import os
import json
import sys
from types import ModuleType
from typing import Dict, List, Optional, Any

class AddonManager:
    """
    插件管理器
    负责记录插件路径, 获取指定插件的路径, 以及其下的 addon_info.json 信息, 解析运行 scr.py 等
    """

    def __init__(self, menu_items=None, app=None) -> None:
        """
        初始化插件管理器

        Args:
            menu_items: 供插件往托盘"插件"子菜单添加自定义项的列表引用（向后兼容）
            app: FaustLauncherApp 实例，用于触发托盘菜单重建等
        """
        self.menu_items = menu_items if menu_items is not None else []
        self.app = app  # FaustLauncherApp 实例，用于触发托盘菜单重建等
        self.gamestart_funcs: List[Any] = []
        self.del_funcs: List[Dict[str, Any]] = []  # 记录插件注册的删除回调函数
        self.enabled_funcs: List[Dict[str, Any]] = []  # 记录插件注册的启用回调函数
        self.disabled_funcs: List[Dict[str, Any]] = []  # 记录插件注册的禁用回调函数
        self.addon_paths: List[str] = []
        self.addon_names: List[str] = []
        self.loaded_modules: Dict[str, ModuleType] = {}  # 已加载的插件模块引用
        self.custom_tray_items: List[Any] = []  # 插件主动注册的自定义托盘菜单项
        self.addons_dir = 'addons'
        self.scan_addons()

    def register_tray_item(self, item) -> None:
        """
        插件调用此方法在托盘"插件"折叠栏中添加自定义菜单项。
        推荐使用此方法，而不是直接操作 menu_items。

        Args:
            item: pystray.MenuItem 或可以被 pystray.Menu 接受的对象
        """
        self.custom_tray_items.append(item)
        # 同时向后兼容：追加到旧插件使用的 menu_items
        self.menu_items.append(item)
        # 尝试刷新托盘菜单（如果 app 可用）
        self._refresh_tray_menu()

    def _refresh_tray_menu(self) -> None:
        """内部方法：刷新托盘菜单（如果已创建）"""
        try:
            if self.app is not None and hasattr(self.app, 'tray') and self.app.tray is not None:
                self.app.tray.update_menu()
        except Exception:
            pass

    def clear_custom_tray_items(self) -> None:
        """清空插件注册的自定义托盘项（重载插件时调用）"""
        self.custom_tray_items.clear()
        # 清空向后兼容的 menu_items
        self.menu_items.clear()

    def get_custom_tray_items(self) -> List[Any]:
        """返回所有插件注册的自定义托盘菜单项"""
        # 同时合并 custom_tray_items 与 menu_items，避免插件使用旧 API 注册的项丢失
        seen: set = set()
        merged: List[Any] = []
        for item in [*self.custom_tray_items, *self.menu_items]:
            if id(item) not in seen:
                seen.add(id(item))
                merged.append(item)
        return merged

    def build_tray_menu_items(self) -> List[Any]:
        """
        供托盘菜单构建器调用，返回完整的"插件"子菜单内容列表：
        [自动扫描项...] → [分隔线 → 自定义项...] → [分隔线 → 重载/管理]
        返回 pystray.MenuItem 列表。
        """
        items: List[Any] = []

        # 1) 自动扫描的插件 — 点击运行
        for addon in self.get_all_addons():
            name = addon['name']
            try:
                enabled = bool(addon.get('info', {}).get('settings', {}).get('enable', True))
            except Exception:
                enabled = True

            def _make_runner(n: str):
                def _run(icon=None, item=None):
                    try:
                        self.run_addon(n)
                    except Exception as e:
                        print(f"手动运行插件 {n} 失败: {e}")
                return _run

            label = f"🔧 {name}" if enabled else f"⚙️ {name} (已禁用)"
            try:
                import pystray  # 延迟导入，避免非 GUI 环境也依赖 pystray
                items.append(pystray.MenuItem(label, _make_runner(name)))
            except Exception:
                # 如果没有 pystray，返回一个存结构（用于测试/调试）
                items.append((label, _make_runner(name)))

        # 2) 插件主动注册的自定义项
        custom_items = self.get_custom_tray_items()
        if custom_items:
            if items:
                try:
                    import pystray
                    items.append(pystray.MenuItem(
                        '─── 自定义项 ───', None, enabled=False))
                except Exception:
                    items.append(('─── 自定义项 ───', None))
            items.extend(custom_items)

        # 3) 管理项：重载插件
        try:
            import pystray
            if items:
                items.append(pystray.MenuItem('─────────────', None, enabled=False))
            items.append(pystray.MenuItem(
                '🔄 重载插件',
                lambda icon=None, item=None: self.reload_all_addons()))
            items.append(pystray.MenuItem(
                '📋 插件列表',
                lambda icon=None, item=None: self._print_addon_status()))
        except Exception:
            # 无 pystray 环境的 fallback
            if items:
                items.append(('─────────────', None))
            items.append(('🔄 重载插件', lambda: self.reload_all_addons()))

        if not items or all(isinstance(x, tuple) and x[1] is None for x in items):
            try:
                import pystray
                items = [pystray.MenuItem('（暂无可用插件）', None, enabled=False)]
            except Exception:
                items = [('（暂无可用插件）', None)]

        return items

    def _print_addon_status(self) -> None:
        """在终端输出当前插件加载状态（调试用）"""
        print(f"共扫描到 {len(self.addon_names)} 个插件：")
        for name in self.addon_names:
            info = self.get_addon_info(name)
            try:
                enabled = bool(info.get('settings', {}).get('enable', True)) if info else True
            except Exception:
                enabled = True
            status = "✅ 已启用" if enabled else "⛔ 已禁用"
            print(f"  {status}  {name}")
        print(f"插件自定义菜单项: {len(self.get_custom_tray_items())} 个")

    def scan_addons(self) -> None:
        """
        扫描addons文件夹，记录所有插件路径
        """
        self.addon_paths = []
        self.addon_names = []
        if not os.path.exists(self.addons_dir):
            os.makedirs(self.addons_dir)
            return

        # 遍历addons文件夹下的所有子文件夹作为插件
        for item in os.listdir(self.addons_dir):
            item_path = os.path.join(self.addons_dir, item)
            if os.path.isdir(item_path):
                self.addon_paths.append(item_path)
                self.addon_names.append(os.path.basename(item_path))
    
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
    
    def run_addon(self, addon_name: str, ADDON_ARG: Optional[Dict[str, Any]] = None) -> bool:
        """
        运行指定插件的 scr.py

        Args:
            addon_name: 插件名称
            ADDON_ARG: 传递给插件的参数字典

        Returns:
            是否运行成功
        """
        if ADDON_ARG is None:
            ADDON_ARG = {}

        info = self.get_addon_info(addon_name)
        if info is None:
            print(f"插件 {addon_name} 信息读取失败，跳过载入")
            return False

        try:
            if not bool(info.get("settings", {}).get("enable", True)):
                print(f"插件 {addon_name} 被禁用，跳过载入")
                return False
        except Exception:
            pass

        addon_path = self.get_addon_path(addon_name)
        if not addon_path:
            print(f"插件 {addon_name} 不存在")
            return False

        # 尝试运行 scr.py
        scr_path = os.path.join(addon_path, 'scr.py')
        if not os.path.exists(scr_path):
            # 没有 scr.py 的插件视为仅信息型，直接跳过
            return False

        print(f"载入插件 {addon_name}...")

        try:
            ADDON_ARG['AddonManager'] = self
            ADDON_ARG['AddonName'] = addon_name

            # 构造一个独立的命名空间，防止与全局变量冲突
            builtins_dict = vars(__builtins__) if isinstance(__builtins__, ModuleType) else dict(__builtins__)
            module_globals: Dict[str, Any] = {
                **builtins_dict,
                'ADDON_ARG': ADDON_ARG,
                '__file__': scr_path,
                '__name__': f"__addon_{addon_name}__",
            }

            with open(scr_path, 'r', encoding='utf-8') as f:
                addon_scr = f.read()

            exec(compile(addon_scr, scr_path, 'exec'), module_globals)

            # 记录加载模块，供可能的清理使用
            mod = ModuleType(f"__addon_{addon_name}__")
            mod.__dict__.update({k: v for k, v in module_globals.items() if not k.startswith('__')})
            mod.__file__ = scr_path
            self.loaded_modules[addon_name] = mod

            print(f"插件 {addon_name} 初始化完成!")
            return True
        except Exception as e:
            print(f"插件 {addon_name} 载入失败: {e}")
            return False
        
    def when_addon_enabled(self, addon_name: str) -> None:
        """
        当插件被启用时调用的回调函数。
        插件可以在其 scr.py 中注册此回调，以便在启用时执行特定操作。
        """
        for enabled_func in self.enabled_funcs:
            if enabled_func.get('name') == addon_name and enabled_func.get('func'):
                try:
                    enabled_func['func']()
                    print(f"插件 {addon_name} 的启用回调已执行")
                except Exception as e:
                    print(f"执行插件 {addon_name} 的启用回调失败: {e}")
                    
    def when_addon_disabled(self, addon_name: str) -> None:
        """
        当插件被禁用时调用的回调函数。
        插件可以在其 scr.py 中注册此回调，以便在禁用时执行特定操作。
        """
        for disabled_func in self.disabled_funcs:
            if disabled_func.get('name') == addon_name and disabled_func.get('func'):
                try:
                    disabled_func['func']()
                    print(f"插件 {addon_name} 的禁用回调已执行")
                except Exception as e:
                    print(f"执行插件 {addon_name} 的禁用回调失败: {e}")

    def unload_all_addons(self) -> None:
        """
        尝试卸载所有已加载的插件：清理记录的模块引用。
        注意：实际资源（线程、Tk窗口等）仍需插件自身提供的清理函数释放。
        我们会尝试调用插件模块中约定的 on_unload 函数。
        """
        for name, mod in list(self.loaded_modules.items()):
            try:
                on_unload = getattr(mod, 'on_unload', None)
                if callable(on_unload):
                    on_unload()
            except Exception as e:
                print(f"插件 {name} 清理时出错: {e}")

            # 从 sys.modules 中移除同名项（如果存在）
            for key in [f"__addon_{name}__"]:
                if key in sys.modules:
                    del sys.modules[key]

        self.loaded_modules.clear()
        self.gamestart_funcs.clear()
        self.del_funcs.clear()
        self.enabled_funcs.clear()
        self.disabled_funcs.clear()
        # 同时清空插件注册的自定义托盘项，避免重载后出现重复项
        self.clear_custom_tray_items()

    def reload_all_addons(self, ADDON_ARG: Optional[Dict[str, Any]] = None) -> bool:
        """
        重新加载所有插件：
        1. 尝试卸载旧插件（调用 on_unload 清理）
        2. 重新扫描 addons 目录
        3. 逐个加载新插件
        """
        print("🔄 开始重载插件...")
        try:
            self.unload_all_addons()
            self.scan_addons()
            self.run_all_addon(ADDON_ARG)
            print("✅ 插件重载完成")
            return True
        except Exception as e:
            print(f"❌ 插件重载失败: {e}")
            return False
        
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
        # print(self.del_funcs)
        for del_func in self.del_funcs:
            # print(f"检查插件 {addon_name} 的删除回调注册: {del_func}")
            if del_func.get('name') == addon_name and del_func.get('func'):
                try:
                    del_func['func']()
                    print(f"插件 {addon_name} 的删除回调已执行")
                except Exception as e:
                    print(f"执行插件 {addon_name} 的删除回调失败: {e}")
        
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
        
    def run_all_addon(self, ADDON_ARG: Optional[Dict[str, Any]] = None) -> None:
        """运行当前扫描到的所有插件"""
        if not self.addon_names:
            # 懒扫描一次
            self.scan_addons()
        for name in self.addon_names:
            try:
                self.run_addon(name, ADDON_ARG if ADDON_ARG is not None else {})
            except Exception as e:
                print(f"运行插件 {name} 时发生未捕获错误: {e}")

    def run_game_start_event(self) -> None:
        """触发所有注册的游戏启动回调"""
        for f in list(self.gamestart_funcs):
            try:
                f()
            except Exception as e:
                print(f"执行游戏启动回调失败: {e}")