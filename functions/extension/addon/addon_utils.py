"""插件管理器：扫描/载入/卸载插件，并维护它们注册的回调与命名空间。

插件就是一个目录，目录里必须有 ``addon_info.json`` 和 ``scr.py``；管理器把
``scr.py`` 当作脚本 ``exec``，通过 ``ADDON_ARG`` 把自身、目录名、命名空间
容器等交给插件。所有插件共享同一个命名空间代理，启动器本身不针对任何具体
插件写死逻辑。

这里的“卸载”分两种：:meth:`AddonManager.unload_addon` 只执行回调并从内存
摘掉插件，:meth:`AddonManager.remove_addon` 才会删磁盘目录。删除/重装前调用
方还要先结束插件拉起的子进程（见 ``addon_processes.py``），否则 Windows 下
目录会因为被占用而删不掉。

运行入口采用显式注册：插件调用 ``register_run_func`` 后，资源页卡片才会出现
▶ 按钮；管理器重载时会清空注册，插件每次载入都要重新注册。
"""

import os
import json
import sys
import threading
from types import ModuleType
from typing import Dict, List, Optional, Any
from functions.web_update.translation_source import CustomTranslateSource
from functions.base.common.json_io import read_json, write_json
from functions.extension.addon.namespace_registry import NamespaceRegistry

#: Windows 不允许出现在目录名里的字符。插件的 ``name`` 会被直接用作目录名，
#: 所以校验时用同一份规则，避免安装到一半才发现 ``mkdir`` 失败。
_INVALID_DIR_CHARS = frozenset('<>:"/\\|?*')
#: Windows 保留设备名（允许带扩展名，所以比较时只看第一个点之前）。
_RESERVED_DIR_NAMES = frozenset(
    ['CON', 'PRN', 'AUX', 'NUL']
    + [f'COM{i}' for i in range(1, 10)]
    + [f'LPT{i}' for i in range(1, 10)]
)


def is_valid_addon_dir_name(name: str) -> bool:
    """判断插件名能否原样用作 ``addons/`` 下的目录名。

    除了字符白名单，还要挡掉首尾空白、结尾的点以及 ``CON``/``COM1`` 这类
    Windows 保留名 —— 这些都是“看起来正常、真正建目录时才报错”的坑。

    Args:
        name: 欲作为目录名的插件名。

    Returns:
        bool: 能否原样在 ``addons/`` 下建出同名目录。
    """
    name = str(name or '')
    if not name or name != name.strip() or name.endswith('.'):
        return False
    if any(ch in _INVALID_DIR_CHARS or ord(ch) < 32 for ch in name):
        return False
    return name.split('.', 1)[0].upper() not in _RESERVED_DIR_NAMES


def validate_addon_dir(addon_path: str) -> tuple[str, str]:
    """校验一个目录是不是可安装的插件，返回 ``(插件名, 错误说明)``。

    判定标准与运行时载入保持一致：必须有可解析的 ``addon_info.json``，
    ``name`` 是非空字符串且能安全用作目录名，``scr.py`` 必须存在（载入器
    就是 ``exec`` 这个文件，缺了它插件永远不会起来）。合格时返回
    ``(name, '')``；不合格返回 ``('', 原因)``，调用方据此丢弃暂存目录，
    不把半成品放进 ``addons/``，也不触发重载。

    Args:
        addon_path: 待检查的插件目录（通常是压缩包解压后的暂存目录）。

    Returns:
        tuple[str, str]: ``(清单里的插件名, 错误说明)``；合格时错误说明为空串。
    """
    addon_path = os.path.abspath(str(addon_path or ''))
    info_path = os.path.join(addon_path, 'addon_info.json')
    if not os.path.isfile(info_path):
        return '', '缺少 addon_info.json'
    try:
        info = read_json(info_path)
    except Exception as e:  # noqa: BLE001 - 坏 JSON 也属于“格式不合格”
        return '', f'addon_info.json 解析失败: {e}'
    if not isinstance(info, dict):
        return '', 'addon_info.json 不是 JSON 对象'
    name = str(info.get('name') or '').strip()
    if not name:
        return '', 'addon_info.json 缺少 name'
    if not is_valid_addon_dir_name(name):
        return '', f'插件名不能用作目录名: {name}'
    if not os.path.isfile(os.path.join(addon_path, 'scr.py')):
        return '', '缺少 scr.py'
    return name, ''


class _ScratchAddonManager:
    """收集插件回调用的假管理器。

    删除插件时要执行它的 ``on_unload``/删除回调，但插件的 ``scr.py`` 只在真实
    管理器里跑过。这里把脚本再 exec 一遍、让所有注册调用落到这个假对象上，
    就能拿到回调列表而不污染真管理器的状态。
    """

    def __init__(self) -> None:
        self.menu_items: List[Any] = []
        self.custom_tray_items: List[Any] = []
        self.gamestart_funcs: List[Any] = []
        self.del_funcs: List[Dict[str, Any]] = []
        self.enabled_funcs: List[Dict[str, Any]] = []
        self.disabled_funcs: List[Dict[str, Any]] = []
        self.extend_translate_source: List[Any] = []
        self.run_funcs: Dict[str, Dict[str, Any]] = {}

    def register_tray_item(self, item) -> None:
        """只把菜单项记在收集列表里，不触发任何真实托盘刷新。"""
        self.custom_tray_items.append(item)
        self.menu_items.append(item)

    def register_run_func(self, name, func, title='') -> None:
        """收集阶段也接受注册调用（不生效），避免插件重装时脚本报错。"""
        if callable(func):
            self.run_funcs[str(name or '')] = {'func': func, 'title': str(title or '')}

    def _refresh_tray_menu(self) -> None:
        """收集阶段不需要刷新托盘，留空实现以兼容插件脚本的调用。"""
        pass

#: 最近创建的那个管理器。命名空间、已载入模块都挂在实例上，而插件是 exec 进
#: 各自模块的，谁也拿不到「启动器正在用的是哪个实例」。成就这类非插件功能要借
#: WarpHook 的命名空间时，只能靠这个引用找到它。
_current_manager = None


def current_manager():
    """当前进程里的插件管理器（最近创建的那个），没有就返回 None。"""
    return _current_manager


class AddonManager:

    def __init__(self, menu_items=None, app=None) -> None:
        """新建管理器并立即扫描 ``addons/``。

        构造时把自己登记为 :func:`current_manager`，这样插件脚本内部（拿不到
        管理器实例）也能通过全局函数找到它。

        Args:
            menu_items: 外部已有的托盘菜单项列表；None 时自建。
            app: 主应用对象，仅用于刷新托盘菜单，可为 None。
        """
        global _current_manager
        _current_manager = self
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
        # 插件自己的「运行入口」：插件载入时调用 register_run_func 注册，
        # 资源页卡片只在注册过时显示 ▶ 按钮（没注册的插件完全不出现）。
        # 值形如 {'func': callable, 'title': '仓库面板'}。
        self.run_funcs: Dict[str, Dict[str, Any]] = {}
        # 插件命名空间代理层：所有插件通过 ADDON_ARG['Namespaces'] 拿同一份
        # 容器。谁想开命名空间、往里放什么工具，全由插件自己决定，
        # 启动器不针对任何插件做特殊适配。见 namespace_registry.py。
        self.namespaces = NamespaceRegistry()
        # 载入时被依赖关系挡下的插件 -> 原因，供界面提示
        self.dep_skipped: Dict[str, str] = {}
        # 必需插件的下载器（由 app 层注入）。签名：callable(addon_name) -> bool。
        # 交给外部注入是为了让 extension 层不必知道云端下载怎么做。
        self.required_installer: Optional[Any] = None
        self.scan_addons()

    def register_tray_item(self, item) -> None:
        """注册一个托盘菜单项并立刻刷新原生菜单。"""
        self.custom_tray_items.append(item)
        self.menu_items.append(item)
        self._refresh_tray_menu()

    # ---- 插件独立运行入口 ----
    # 插件在 scr.py 里调用：
    #   ADDON_ARG['AddonManager'].register_run_func(ADDON_ARG['AddonName'], 函数, '按钮悬停提示')
    # 注册后资源页的插件卡片右侧会多出一个 ▶ 图标按钮；没注册的插件不会显示。
    def register_run_func(self, name, func, title='') -> bool:
        """注册本插件的独立运行入口（资源页卡片上的 ▶ 按钮）。

        Args:
            name: 插件目录名，通常直接传 ``ADDON_ARG['AddonName']``。
            func: 点击按钮时执行的无参可调用对象。
            title: 可选的按钮悬停提示；留空时前端显示「运行」。

        Returns:
            注册是否成功（名字为空或 func 不可调用时返回 False）。
        """
        addon_name = str(name or '').strip()
        if not addon_name or not callable(func):
            print(f"插件运行入口注册失败: name={addon_name!r} func={func!r}")
            return False
        self.run_funcs[addon_name] = {'func': func, 'title': str(title or '').strip()}
        print(f"插件 {addon_name} 注册了运行入口")
        return True

    def has_run_func(self, addon_name: str) -> bool:
        """插件是否注册过运行入口（决定资源页是否显示 ▶ 按钮）。"""
        return str(addon_name or '').strip() in self.run_funcs

    def run_addon_entry(self, addon_name: str) -> Dict[str, Any]:
        """执行插件注册的运行入口。

        入口可能是打开一个 Tk 面板这类会阻塞的调用，所以放到后台线程执行，
        前端点击后立即返回，不卡住 pywebview 的 JS 桥。
        """
        name = str(addon_name or '').strip()
        entry = self.run_funcs.get(name)
        if not entry:
            return {'ok': False, 'error': '该插件未注册运行入口'}
        func = entry.get('func')
        if not callable(func):
            return {'ok': False, 'error': '运行入口不可用'}

        def _call() -> None:
            try:
                func()
            except Exception as exc:  # noqa: BLE001 - 插件自己的异常不能拖垮启动器
                print(f"执行插件 {name} 的运行入口失败: {type(exc).__name__}: {exc}")

        threading.Thread(target=_call, name=f"faust-addon-run-{name}", daemon=True).start()
        return {'ok': True}

    def _refresh_tray_menu(self) -> None:
        """让主应用重建托盘菜单；没有 app 或刷新失败时静默跳过。"""
        try:
            if self.app is not None and hasattr(self.app, 'tray') and self.app.tray is not None:
                self.app.tray.update_menu()
        except Exception:
            pass

    def clear_custom_tray_items(self) -> None:
        """清空插件注册的菜单项并刷新托盘（重载插件前调用）。"""
        self.custom_tray_items.clear()
        self.menu_items.clear()
        self._refresh_tray_menu()

    def get_custom_tray_items(self) -> List[Any]:
        """合并两个来源的菜单项并按对象 id 去重，坏条目由 _is_tray_item 过滤。"""
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
        """把扫描结果按“启用/禁用/永久/因依赖跳过”打印到终端，供排障用。"""
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
        """重新列出 ``addons/`` 下的一级目录；目录不存在时创建它。

        只按目录名登记，不在这里校验插件格式：缺清单或缺 scr.py 的目录会在
        后续载入时自然失败，不应拖垮整个扫描。
        """
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
        """读指定插件的 addon_info.json。

        Args:
            addon_name: 插件目录名，不是清单里的显示名。

        Returns:
            解析出的字典；目录不存在、缺文件或 JSON 损坏时返回 None。
        """
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
        """按目录名在已扫描的插件里找路径，找不到返回 None。"""
        for path in self.addon_paths:
            if os.path.basename(path) == addon_name:
                return path
        return None
    
    def get_all_addons(self) -> List[Dict[str, Any]]:
        """返回 ``[{'name', 'path', 'info'}, ...]``；清单读不到时用占位描述。"""
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
            """DFS 访问一个节点；返回它是否可载入，失败原因写进 skipped。"""
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
        """按依赖顺序载入单个插件：检查启用状态/依赖，再 exec 它的 scr.py。

        Args:
            addon_name: 插件目录名。
            ADDON_ARG: 可选的扩展参数字典；管理器会往里注入 AddonManager、
                AddonName、ExtendTranslateSource、Namespaces 四个键。

        Returns:
            bool: 是否成功执行完脚本并登记模块。
        """
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
        """执行该插件注册的启用回调；单个回调出错只打印，不影响其他插件。"""
        for enabled_func in self.enabled_funcs:
            if enabled_func.get('name') == addon_name and enabled_func.get('func'):
                try:
                    enabled_func['func']()
                    print(f"插件 {addon_name} 的启用回调已执行")
                except Exception as e:
                    print(f"执行插件 {addon_name} 的启用回调失败: {e}")
                    
    def when_addon_disabled(self, addon_name: str) -> None:
        """执行该插件注册的禁用回调；单个回调出错只打印，不影响其他插件。"""
        for disabled_func in self.disabled_funcs:
            if disabled_func.get('name') == addon_name and disabled_func.get('func'):
                try:
                    disabled_func['func']()
                    print(f"插件 {addon_name} 的禁用回调已执行")
                except Exception as e:
                    print(f"执行插件 {addon_name} 的禁用回调失败: {e}")

    def unload_addon(self, addon_name: str) -> bool:
        """卸载单个插件：执行它的 ``on_unload`` 并从管理器里摘掉。

        与 :meth:`remove_addon` 的区别：这里**只停插件、不碰磁盘**。重装插件前
        要先让插件的线程、共享内存、外部子进程收尾，之后才能安全删除目录。
        """
        name = str(addon_name or '').strip()
        mod = self.loaded_modules.pop(name, None)
        if mod is not None:
            try:
                on_unload = getattr(mod, 'on_unload', None)
                if callable(on_unload):
                    on_unload()
            except Exception as e:  # noqa: BLE001 - 插件收尾失败也要继续删
                print(f"卸载插件 {name} 时出错: {type(e).__name__}: {e}")

        # 摘掉这个插件遗留的回调，避免重装后同一函数被注册两次。
        owners = getattr(self, 'gamestart_owners', {}) or {}
        self.gamestart_funcs[:] = [
            f for f in self.gamestart_funcs if owners.get(id(f)) != name]
        self.gamestart_owners = {k: v for k, v in owners.items() if v != name}
        for bucket in (self.del_funcs, self.enabled_funcs, self.disabled_funcs):
            bucket[:] = [x for x in bucket if x.get('name') != name]
        self.run_funcs.pop(name, None)
        return mod is not None

    def unload_all_addons(self) -> None:
        """执行所有插件的 on_unload，清空回调/命名空间/运行入口/托盘菜单。

        不删磁盘文件；重载流程会紧接着重新扫描并载入。
        """
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
        if hasattr(self, 'gamestart_owners'):
            self.gamestart_owners.clear()
        self.del_funcs.clear()
        self.enabled_funcs.clear()
        self.disabled_funcs.clear()
        self.namespaces.clear()
        self.dep_skipped.clear()
        self.run_funcs.clear()
        self.clear_custom_tray_items()

    def reload_all_addons(self, ADDON_ARG: Optional[Dict[str, Any]] = None) -> bool:
        """卸载全部插件后重新扫描并按依赖顺序载入。

        Args:
            ADDON_ARG: 透传给 :meth:`run_all_addon` 的扩展参数。

        Returns:
            bool: 重载流程是否没有抛出异常（单个插件载入失败仍算成功）。
        """
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
        
    def add_addon(self, addon_path: str, addon_name: Optional[str] = None) -> bool:
        """把一个现成的插件目录复制进 ``addons/``。

        默认沿用源目录名，保持旧调用方的行为；本地导入时由调用方传入
        :func:`validate_addon_dir` 解析出的清单名，让落盘目录和插件自称的
        名字一致，而不是让暂存目录名（以前是 ``faust_inst_*``）泄漏进来。

        Args:
            addon_path: 源插件目录。
            addon_name: 显式的落盘目录名；留空时取源目录名。

        Returns:
            bool: 是否复制成功；目标已存在或复制失败时返回 False（半成品
            目录会被清掉，避免下次安装被误判为“已存在”）。
        """
        if not os.path.exists(addon_path):
            print(f"插件路径不存在: {addon_path}")
            return False

        addon_name = str(addon_name or '').strip() or os.path.basename(addon_path)
        dest_path = os.path.join(self.addons_dir, addon_name)

        if os.path.exists(dest_path):
            print(f"插件 {addon_name} 已存在")
            return False

        import shutil
        try:
            shutil.copytree(addon_path, dest_path)
            self.scan_addons()
            print(f"插件 {addon_name} 添加成功")
            return True
        except Exception as e:
            # 复制到一半失败会留下半个目录，下次安装会被误判成“已存在”。
            shutil.rmtree(dest_path, ignore_errors=True)
            print(f"添加插件失败: {e}")
            return False
    
    def _run_del_funcs(self, addon_name: str, funcs: List[Dict[str, Any]]) -> bool:
        """执行列表里属于该插件的删除回调，单个失败也继续并记为已尝试。

        Returns:
            bool: 是否至少找到并执行过一个回调。
        """
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
        """用假管理器再跑一遍 scr.py，收集该插件注册的清理回调。

        插件没载入过时也能拿到删除回调，是 :meth:`remove_addon` 的兜底来源。
        脚本执行出错只打印，返回收集到的部分结果。

        Args:
            addon_name: 插件目录名。

        Returns:
            _ScratchAddonManager: 只含回调记录的假管理器。
        """
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
        """先执行删除回调（必要时从脚本重新收集），再删除插件目录。

        这里只负责插件自己的清理逻辑；占用目录的子进程要由调用方在调用本
        方法之前结束，否则 Windows 下目录会删不掉。

        Returns:
            bool: 目录是否成功删除。
        """
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
        
    def ensure_required(self) -> Dict[str, Dict[str, Any]]:
        """补齐必需插件；下载器还没注入时只是记录缺失原因。

        下载完成后会重扫插件目录并重载，让新装上的插件立刻生效。
        """
        try:
            from functions.extension.addon.required_addons import ensure_all
        except Exception as exc:
            print(f"载入必需插件声明失败: {exc}")
            return {}
        
        result = ensure_all(installer=self.required_installer, root=self.addons_dir)

        if any((state or {}).get('status') == 'installed' for state in result.values()):
            self.scan_addons()

            try:
                self.reload_all_addons()
            except Exception as exc:
                print(f"重载插件失败: {exc}")

        return result

    def run_all_addon(self, ADDON_ARG: Optional[Dict[str, Any]] = None) -> None:
        """启动流程入口：补必需插件 → 算依赖顺序 → 逐个载入 → 同步汉化源。

        单个插件抛异常只打印并继续，坏插件不会拖垮启动器。

        Args:
            ADDON_ARG: 透传给每个 :meth:`run_addon` 的扩展参数。
        """
        # 先把「必需插件」补齐（例如 WarpHook）。缺失时不阻塞启动：
        # 下载失败只是让依赖它的功能降级，其它插件照常载入。
        self.ensure_required()

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

        if self.namespaces and '--debug' in sys.argv:
            print(f"[debug] 插件命名空间: {self.namespaces.snapshot()}")

        self._sync_extend_translate_source()

    def _sync_extend_translate_source(self) -> None:
        """把插件注册的自定义汉化源推给翻译模块，失败只打印。"""
        try:
            from functions.web_update.translation_source import set_extend_translate_source
            set_extend_translate_source(self.extend_translate_source)
            names = [str(getattr(x, "name", "") or "?") for x in self.extend_translate_source]
            print(f"已同步插件自定义汉化源: {names or '无'}")
        except Exception as e:
            print(f"同步插件自定义汉化源失败: {e}")

    def run_game_start_event(self) -> None:
        """依次触发插件注册的游戏启动回调，单个失败不影响后续。"""
        for f in list(self.gamestart_funcs):
            try:
                f()
            except Exception as e:
                print(f"执行游戏启动回调失败: {e}")
