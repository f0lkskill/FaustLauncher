import os
import json
import sys
from types import ModuleType
from typing import Dict, List, Optional, Any
from functions.web_update.translation_source import CustomTranslateSource
from functions.base.common.json_io import read_json, write_json

class _ScratchAddonManager:

    def __init__(self) -> None:
        self.menu_items: List[Any] = []
        self.custom_tray_items: List[Any] = []
        self.gamestart_funcs: List[Any] = []
        self.del_funcs: List[Dict[str, Any]] = []
        self.enabled_funcs: List[Dict[str, Any]] = []
        self.disabled_funcs: List[Dict[str, Any]] = []
        self.extend_translate_source: List[Any] = []

    def register_tray_item(self, item) -> None:
        self.custom_tray_items.append(item)
        self.menu_items.append(item)

    def _refresh_tray_menu(self) -> None:
        pass

class AddonManager:

    def __init__(self, menu_items=None, app=None) -> None:
        self.menu_items = menu_items if menu_items is not None else []
        self.app = app
        self.gamestart_funcs: List[Any] = []
        self.del_funcs: List[Dict[str, Any]] = []
        self.enabled_funcs: List[Dict[str, Any]] = []
        self.disabled_funcs: List[Dict[str, Any]] = []
        self.addon_paths: List[str] = []
        self.addon_names: List[str] = []
        self.loaded_modules: Dict[str, ModuleType] = {}
        self.custom_tray_items: List[Any] = []
        self.addons_dir = 'addons'
        self.extend_translate_source:list[CustomTranslateSource] = []
        self.scan_addons()

    def register_tray_item(self, item) -> None:
        self.custom_tray_items.append(item)
        self.menu_items.append(item)
        self._refresh_tray_menu()

    def _refresh_tray_menu(self) -> None:
        try:
            if self.app is not None and hasattr(self.app, 'tray') and self.app.tray is not None:
                self.app.tray.update_menu()
        except Exception:
            pass

    def clear_custom_tray_items(self) -> None:
        self.custom_tray_items.clear()
        self.menu_items.clear()
        self._refresh_tray_menu()

    def get_custom_tray_items(self) -> List[Any]:
        seen: set = set()
        merged: List[Any] = []
        for item in [*self.custom_tray_items, *self.menu_items]:
            if id(item) not in seen:
                seen.add(id(item))
                merged.append(item)
        return merged

    def build_tray_menu_items(self) -> List[Any]:
        items: List[Any] = []

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
                import pystray
                items.append(pystray.MenuItem(label, _make_runner(name)))
            except Exception:
                items.append((label, _make_runner(name)))

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
        self.addon_paths = []
        self.addon_names = []
        if not os.path.exists(self.addons_dir):
            os.makedirs(self.addons_dir)
            return

        for item in os.listdir(self.addons_dir):
            item_path = os.path.join(self.addons_dir, item)
            if os.path.isdir(item_path):
                self.addon_paths.append(item_path)
                self.addon_names.append(os.path.basename(item_path))
    
    def get_addon_info(self, addon_name: str) -> Optional[Dict[str, Any]]:
        addon_path = self.get_addon_path(addon_name)
        if not addon_path:
            return None
        
        info_path = os.path.join(addon_path, 'addon_info.json')
        if not os.path.exists(info_path):
            print(f"插件 {addon_name} 缺少 addon_info.json 文件")
            return None
        
        try:
            return read_json(info_path)
        except Exception as e:
            print(f"读取插件信息失败: {e}")
            return None
    
    def get_addon_path(self, addon_name: str) -> Optional[str]:
        for path in self.addon_paths:
            if os.path.basename(path) == addon_name:
                return path
        return None
    
    def get_all_addons(self) -> List[Dict[str, Any]]:
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

        scr_path = os.path.join(addon_path, 'scr.py')
        if not os.path.exists(scr_path):
            return False

        print(f"载入插件 {addon_name}...")

        try:
            ADDON_ARG['AddonManager'] = self
            ADDON_ARG['AddonName'] = addon_name
            ADDON_ARG['ExtendTranslateSource'] = self.extend_translate_source

            _gs_before = len(self.gamestart_funcs)

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

            mod = ModuleType(f"__addon_{addon_name}__")
            mod.__dict__.update({k: v for k, v in module_globals.items() if not k.startswith('__')})
            mod.__file__ = scr_path
            self.loaded_modules[addon_name] = mod

            if not hasattr(self, 'gamestart_owners'):
                self.gamestart_owners = {}
            for f in self.gamestart_funcs[_gs_before:]:
                self.gamestart_owners[id(f)] = addon_name

            # Legacy addons append directly to menu_items; refresh after loading too.
            self._refresh_tray_menu()
            print(f"插件 {addon_name} 初始化完成!")
            return True
        except Exception as e:
            print(f"插件 {addon_name} 载入失败: {e}")
            return False
        
    def when_addon_enabled(self, addon_name: str) -> None:
        for enabled_func in self.enabled_funcs:
            if enabled_func.get('name') == addon_name and enabled_func.get('func'):
                try:
                    enabled_func['func']()
                    print(f"插件 {addon_name} 的启用回调已执行")
                except Exception as e:
                    print(f"执行插件 {addon_name} 的启用回调失败: {e}")
                    
    def when_addon_disabled(self, addon_name: str) -> None:
        for disabled_func in self.disabled_funcs:
            if disabled_func.get('name') == addon_name and disabled_func.get('func'):
                try:
                    disabled_func['func']()
                    print(f"插件 {addon_name} 的禁用回调已执行")
                except Exception as e:
                    print(f"执行插件 {addon_name} 的禁用回调失败: {e}")

    def unload_all_addons(self) -> None:
        for name, mod in list(self.loaded_modules.items()):
            try:
                on_unload = getattr(mod, 'on_unload', None)
                if callable(on_unload):
                    on_unload()
            except Exception as e:
                print(f"插件 {name} 清理时出错: {e}")

            for key in [f"__addon_{name}__"]:
                if key in sys.modules:
                    del sys.modules[key]

        self.loaded_modules.clear()
        self.gamestart_funcs.clear()
        self.del_funcs.clear()
        self.enabled_funcs.clear()
        self.disabled_funcs.clear()
        self.clear_custom_tray_items()

    def reload_all_addons(self, ADDON_ARG: Optional[Dict[str, Any]] = None) -> bool:
        print("开始重载插件...")
        try:
            self.extend_translate_source.clear()

            self.unload_all_addons()
            self.scan_addons()
            self.run_all_addon(ADDON_ARG)
            print("插件重载完成")
            return True
        except Exception as e:
            print(f"插件重载失败: {e}")
            return False
        
    def add_addon(self, addon_path: str) -> bool:
        if not os.path.exists(addon_path):
            print(f"插件路径不存在: {addon_path}")
            return False
        
        addon_name = os.path.basename(addon_path)
        dest_path = os.path.join(self.addons_dir, addon_name)
        
        if os.path.exists(dest_path):
            print(f"插件 {addon_name} 已存在")
            return False
        
        try:
            import shutil
            shutil.copytree(addon_path, dest_path)
            self.scan_addons()
            print(f"插件 {addon_name} 添加成功")
            return True
        except Exception as e:
            print(f"添加插件失败: {e}")
            return False
    
    def _run_del_funcs(self, addon_name: str, funcs: List[Dict[str, Any]]) -> bool:
        ran = False
        for del_func in funcs:
            if del_func.get('name') == addon_name and del_func.get('func'):
                try:
                    del_func['func']()
                    print(f"插件 {addon_name} 的删除回调已执行")
                    ran = True
                except Exception as e:
                    print(f"执行插件 {addon_name} 的删除回调失败: {e}")
                    ran = True
        return ran

    def collect_addon_callbacks(self, addon_name: str) -> _ScratchAddonManager:
        scratch = _ScratchAddonManager()
        addon_path = self.get_addon_path(addon_name)
        if not addon_path:
            return scratch
        scr_path = os.path.join(addon_path, 'scr.py')
        if not os.path.exists(scr_path):
            return scratch
        try:
            addon_arg: Dict[str, Any] = {
                'AddonManager': scratch,
                'AddonName': addon_name,
                'ExtendTranslateSource': scratch.extend_translate_source,
            }
            builtins_dict = vars(__builtins__) if isinstance(__builtins__, ModuleType) else dict(__builtins__)
            module_globals: Dict[str, Any] = {
                **builtins_dict,
                'ADDON_ARG': addon_arg,
                '__file__': scr_path,
                '__name__': f"__addon_collect_{addon_name}__",
            }
            with open(scr_path, 'r', encoding='utf-8') as f:
                addon_scr = f.read()
            exec(compile(addon_scr, scr_path, 'exec'), module_globals)
        except Exception as e:
            print(f"收集插件 {addon_name} 的清理回调失败: {e}")
        return scratch

    def remove_addon(self, addon_name: str) -> bool:
        ran = self._run_del_funcs(addon_name, self.del_funcs)

        if not ran:
            scratch = self.collect_addon_callbacks(addon_name)
            if scratch.del_funcs:
                self._run_del_funcs(addon_name, scratch.del_funcs)
            else:
                print(f"插件 {addon_name} 未注册删除回调, 仅删除插件目录 (游戏目录残留需手动清理)")

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
        if not self.addon_names:
            self.scan_addons()
        for name in self.addon_names:
            try:
                self.run_addon(name, ADDON_ARG if ADDON_ARG is not None else {})
            except Exception as e:
                print(f"运行插件 {name} 时发生未捕获错误: {e}")
        self._sync_extend_translate_source()

    def _sync_extend_translate_source(self) -> None:
        try:
            from functions.web_update.translation_source import set_extend_translate_source
            set_extend_translate_source(self.extend_translate_source)
            names = [str(getattr(x, "name", "") or "?") for x in self.extend_translate_source]
            print(f"已同步插件自定义汉化源: {names or '无'}")
        except Exception as e:
            print(f"同步插件自定义汉化源失败: {e}")

    def run_game_start_event(self) -> None:
        for f in list(self.gamestart_funcs):
            try:
                f()
            except Exception as e:
                print(f"执行游戏启动回调失败: {e}")
