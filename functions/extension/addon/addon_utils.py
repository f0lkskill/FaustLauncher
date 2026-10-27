import os
import json
import sys
from types import ModuleType
from typing import Dict, List, Optional, Any
from functions.web_update.translation_source import CustomTranslateSource
from functions.base.common.json_io import read_json, write_json
from functions.extension.addon.namespace_registry import NamespaceRegistry

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
        # 插件命名空间代理层：所有插件通过 ADDON_ARG['Namespaces'] 拿同一份
        # 容器。谁想开命名空间、往里放什么工具，全由插件自己决定，
        # 启动器不针对任何插件做特殊适配。见 namespace_registry.py。
        self.namespaces = NamespaceRegistry()
        # 载入时被依赖关系挡下的插件 -> 原因，供界面提示
        self.dep_skipped: Dict[str, str] = {}
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
            if not self._is_tray_item(item):
                continue
            if id(item) not in seen:
                seen.add(id(item))
                merged.append(item)
        return merged

    @staticmethod
    def _is_tray_item(item: Any) -> bool:
        """过滤掉混进来的非菜单项。

        插件可能把字符串/None 之类的东西塞进 ``menu_items``（例如把插件名
        当参数传给 ``pystray.Menu(...)``）。pystray 在构建原生菜单时会遍历
        items 并对每一项取 ``.visible``，一旦遇到 str 就直接抛
        ``AttributeError: 'str' object has no attribute 'visible'``，
        整个托盘菜单（连带主菜单）都建不出来。这里提前把非菜单项过滤掉，
        坏插件只影响自己，不拖垮托盘。
        """
        if item is None or isinstance(item, (str, bytes)):
            return False
        # pystray.MenuItem / Menu 都有 visible 属性；其它对象一律不放行。
        # 取值本身也可能抛错（Menu 里混了 str 时 .visible 会炸），一并兜住。
        try:
            return bool(item.visible)
        except Exception:
            return False

    def build_tray_menu_items(self) -> List[Any]:
        """Only show menus explicitly registered by addons, including the legacy API."""
        return self.get_custom_tray_items()

    def _print_addon_status(self) -> None:
        print(f"共扫描到 {len(self.addon_names)} 个插件：")
        for name in self.addon_names:
            info = self.get_addon_info(name)
            try:
                enabled = bool(info.get('settings', {}).get('enable', True)) if info else True
            except Exception:
                enabled = True
            if self.is_addon_permanent(name):
                status = "🔒 永久启用"
            else:
                status = "✅ 已启用" if enabled else "⛔ 已禁用"
            needs = self.get_addon_requires(name)
            suffix = f"  ← 依赖 {', '.join(needs)}" if needs else ""
            print(f"  {status}  {name}{suffix}")
        if self.dep_skipped:
            print(f"因依赖问题跳过 {len(self.dep_skipped)} 个：")
            for name, reason in self.dep_skipped.items():
                print(f"  ⚠️  {name}: {reason}")
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
    
    def get_addon_requires(self, addon_name: str) -> List[str]:
        """读插件声明的依赖插件名列表。

        ``addon_info.json`` 里的 ``requires`` 是可选键——没有依赖的插件根本不
        写这个键，所以这里返回空列表即可，不需要兼容「空数组」这种半状态。
        也接受单个字符串写法（``"requires": "WarpHook"``），方便手写清单。

        Args:
            addon_name: 插件目录名。

        Returns:
            依赖的插件目录名列表，顺序与清单里一致。
        """
        info = self.get_addon_info(addon_name) or {}
        raw = info.get('requires')
        if not raw:
            return []
        if isinstance(raw, str):
            raw = [raw]
        if not isinstance(raw, (list, tuple, set)):
            return []
        result: List[str] = []
        for item in raw:
            name = str(item).strip()
            if name and name not in result:
                result.append(name)
        return result

    def is_addon_permanent(self, addon_name: str) -> bool:
        """插件是否标记为「永久启用」（依赖库类插件，界面不允许关闭）。"""
        info = self.get_addon_info(addon_name) or {}
        return bool(info.get('permanent'))

    def get_addon_provides(self, addon_name: str) -> List[str]:
        """插件声明自己提供的命名空间名，纯自描述元数据，启动器不校验。"""
        info = self.get_addon_info(addon_name) or {}
        raw = info.get('provides')
        if not raw:
            return []
        if isinstance(raw, str):
            raw = [raw]
        if not isinstance(raw, (list, tuple, set)):
            return []
        return [str(item).strip() for item in raw if str(item).strip()]

    def resolve_load_order(self) -> tuple:
        """按 ``requires`` 做拓扑排序，算出插件载入顺序与被跳过项。

        被依赖的插件先载入（提供方必须先于使用方注册命名空间）。
        三种异常情况都会被挡下并记录原因：

            * 缺依赖：``requires`` 里写的插件目录不存在 → ``缺少依赖: X``
            * 循环依赖：A 依赖 B、B 又依赖 A → ``循环依赖``
            * 依赖不可用：依赖本身因上述原因被跳过 → ``依赖不可用: X``

        Returns:
            ``(载入顺序, 跳过原因表)``，后者形如 ``{'某插件': '缺少依赖: 某插件'}``。
        """
        names = list(self.addon_names)
        exists = set(names)
        requires = {name: self.get_addon_requires(name) for name in names}

        order: List[str] = []
        state: Dict[str, int] = {}       # 1=访问中 2=已完成
        skipped: Dict[str, str] = {}

        def visit(name: str, stack: List[str]) -> bool:
            if state.get(name) == 2:
                return name not in skipped
            if state.get(name) == 1:
                # 回边即环：把环上所有节点都标掉
                try:
                    start = stack.index(name)
                except ValueError:
                    start = 0
                for item in stack[start:]:
                    skipped.setdefault(item, '循环依赖')
                return False

            state[name] = 1
            stack.append(name)
            try:
                for dep in requires.get(name, []):
                    if dep not in exists:
                        skipped[name] = f'缺少依赖: {dep}'
                        state[name] = 2
                        return False
                    if not visit(dep, stack):
                        skipped.setdefault(name, f'依赖不可用: {dep}')
                        state[name] = 2
                        return False
            finally:
                if stack and stack[-1] == name:
                    stack.pop()

            state[name] = 2
            order.append(name)
            return True

        for name in names:
            try:
                visit(name, [])
            except Exception as exc:  # 依赖声明写坏了也不该拖垮整个启动
                skipped[name] = f'依赖解析失败: {exc}'
                state[name] = 2

        return [name for name in order if name not in skipped], skipped

    def run_addon(self, addon_name: str, ADDON_ARG: Optional[Dict[str, Any]] = None) -> bool:
        if ADDON_ARG is None:
            ADDON_ARG = {}

        info = self.get_addon_info(addon_name)
        if info is None:
            print(f"插件 {addon_name} 信息读取失败，跳过载入")
            return False

        # 依赖库类插件（permanent）永远载入，不受 settings.enable 控制：
        # 它自己不产生行为，被关掉只会让依赖它的插件静默失效。
        permanent = self.is_addon_permanent(addon_name)
        try:
            if not permanent and not bool(info.get("settings", {}).get("enable", True)):
                print(f"插件 {addon_name} 被禁用，跳过载入")
                return False
        except Exception:
            pass

        missing = [dep for dep in self.get_addon_requires(addon_name)
                   if dep not in self.addon_names]
        if missing:
            reason = '缺少依赖: ' + ', '.join(missing)
            self.dep_skipped[addon_name] = reason
            print(f"插件 {addon_name} 跳过载入（{reason}）")
            return False

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
            # 插件命名空间代理层：所有插件共享同一个容器，任何插件都可以
            # 往里注册自己的命名空间，其他插件按名字读取。
            # 见 namespace_registry.py。
            ADDON_ARG['Namespaces'] = self.namespaces

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
        self.namespaces.clear()
        self.dep_skipped.clear()
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
                'Namespaces': self.namespaces,
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
        self.dep_skipped = {}
        order, skipped = self.resolve_load_order()
        self.dep_skipped = dict(skipped)
        for name, reason in skipped.items():
            print(f"插件 {name} 跳过载入（{reason}）")
        args = ADDON_ARG if ADDON_ARG is not None else {}
        for name in order:
            try:
                self.run_addon(name, args)
            except Exception as e:
                print(f"运行插件 {name} 时发生未捕获错误: {e}")
        if self.namespaces:
            print(f"插件命名空间: {self.namespaces.snapshot()}")
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
