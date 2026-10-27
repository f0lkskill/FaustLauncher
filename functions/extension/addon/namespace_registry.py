"""插件命名空间注册表。

启动器给**每一个**插件准备同一个共享容器，任何插件都可以往里面开自己的
命名空间、放自己的工具；其他插件按命名空间名取用。启动器本身不认识任何
具体的命名空间，也不为某个插件做特殊适配 —— 谁提供、提供什么，全由插件
自己决定：

    # 提供方（任意插件，命名空间名自己起）
    NS = ADDON_ARG['Namespaces']
    NS.provide('il2cpp', resolve=resolve, names=names)
    NS.provide('inject', find_pid=find_game_pid, inject=inject_dll)

    # 使用方（任意插件）
    NS = ADDON_ARG['Namespaces']
    NS.il2cpp.resolve()          # 属性访问
    NS['inject']['find_pid']()   # 字典访问，两种写法等价

设计约束：
    * 命名空间对外**只读** —— 使用方拿不到 ``expose``，只能读里面的工具。
    * 一个命名空间可以被多次 ``provide`` 追加内容（提供方分批注册），
      同名工具后写的覆盖先写的，并打一行警告。
    * 未注册的命名空间在访问时抛 :class:`NamespaceMissing`，让插件能用
      ``try/except`` 或 :meth:`NamespaceRegistry.has` 判断后优雅降级。
"""

from typing import Any, Dict, Iterator, List, Optional


class NamespaceMissing(AttributeError):
    """请求的命名空间还没有被任何插件提供。"""


class Namespace:
    """单个命名空间的只读视图。

    提供方通过 :meth:`expose` 往里放工具，使用方只能通过属性或下标读取；
    没有提供 ``setattr``/``__setitem__``，所以插件无法误改别人的工具。
    """

    __slots__ = ('_name', '_items')

    def __init__(self, name: str) -> None:
        self._name = name
        self._items: Dict[str, Any] = {}

    # ---------- 提供方接口 ----------

    @property
    def name(self) -> str:
        """命名空间名字（例如 ``'il2cpp'``）。"""
        return self._name

    def expose(self, name: Optional[str] = None, value: Any = None,
               **items: Any) -> 'Namespace':
        """注册一个或多个工具，返回自身以便链式调用。

        Args:
            name: 单个工具的名字；也可省略，改用关键字参数批量注册。
            value: ``name`` 对应的工具对象。
            **items: 批量注册的工具。

        Returns:
            当前命名空间，便于 ``NS.provide('x').expose(a=1).expose(b=2)``。
        """
        if name is not None:
            self._put(str(name), value)
        for key, item in items.items():
            self._put(str(key), item)
        return self

    def _put(self, key: str, value: Any) -> None:
        """写入一个工具；同名覆盖时提示一次，方便排查插件互相打架。"""
        if key in self._items and self._items[key] is not value:
            print(f"[插件命名空间] {self._name} 的工具 {key} 被覆盖")
        self._items[key] = value

    # ---------- 使用方接口 ----------

    def __getattr__(self, item: str) -> Any:
        if item.startswith('_'):
            raise AttributeError(item)
        try:
            return self._items[item]
        except KeyError:
            raise AttributeError(
                f"命名空间 {self._name} 里没有 {item}"
                f"（现有：{', '.join(sorted(self._items)) or '空'}）") from None

    def __getitem__(self, item: str) -> Any:
        try:
            return self._items[str(item)]
        except KeyError:
            raise KeyError(
                f"命名空间 {self._name} 里没有 {item}") from None

    def __contains__(self, item: object) -> bool:
        return str(item) in self._items

    def __iter__(self) -> Iterator[str]:
        return iter(self._items)

    def __len__(self) -> int:
        return len(self._items)

    def keys(self) -> List[str]:
        """所有工具名，供插件自检或界面展示。"""
        return list(self._items)

    def __repr__(self) -> str:
        return f"<Namespace {self._name}: {', '.join(sorted(self._items)) or '空'}>"


class NamespaceRegistry:
    """全局命名空间容器，挂在 ``ADDON_ARG['Namespaces']`` 上。"""

    __slots__ = ('_spaces',)

    def __init__(self) -> None:
        self._spaces: Dict[str, Namespace] = {}

    # ---------- 提供方接口 ----------

    def provide(self, space: str, **items: Any) -> Namespace:
        """取得（必要时创建）一个命名空间并批量注册工具。

        Args:
            space: 命名空间名字，例如 ``'il2cpp'``。
            **items: 要注册的工具。

        Returns:
            该命名空间对象，可继续 :meth:`Namespace.expose` 追加。
        """
        name = str(space).strip()
        if not name:
            raise ValueError('命名空间名不能为空')
        target = self._spaces.get(name)
        if target is None:
            target = Namespace(name)
            self._spaces[name] = target
        for key, value in items.items():
            target._put(str(key), value)
        return target

    def drop(self, space: str) -> bool:
        """移除一个命名空间（插件卸载时清理用）。"""
        return self._spaces.pop(str(space), None) is not None

    def clear(self) -> None:
        """清空全部命名空间（启动器重载插件时调用）。"""
        self._spaces.clear()

    # ---------- 使用方接口 ----------

    def space(self, name: str) -> Optional[Namespace]:
        """取命名空间；不存在返回 ``None``，不抛异常。"""
        return self._spaces.get(str(name))

    def has(self, name: str) -> bool:
        """判断命名空间是否存在。"""
        return str(name) in self._spaces

    def spaces(self) -> List[str]:
        """所有已注册的命名空间名。"""
        return sorted(self._spaces)

    def snapshot(self) -> Dict[str, List[str]]:
        """``{命名空间: [工具名...]}``，给生态表与调试用。"""
        return {name: sorted(space.keys()) for name, space in self._spaces.items()}

    def __getattr__(self, name: str) -> Namespace:
        if name.startswith('_'):
            raise AttributeError(name)
        target = self._spaces.get(name)
        if target is None:
            raise NamespaceMissing(
                f"命名空间 {name} 尚未注册"
                f"（已注册：{', '.join(self.spaces()) or '无'}）；"
                f"通常说明提供它的插件未安装或未加载")
        return target

    def __getitem__(self, name: str) -> Namespace:
        target = self._spaces.get(str(name))
        if target is None:
            raise KeyError(f"命名空间 {name} 尚未注册")
        return target

    def __contains__(self, name: object) -> bool:
        return str(name) in self._spaces

    def __iter__(self) -> Iterator[str]:
        return iter(self.spaces())

    def __len__(self) -> int:
        return len(self._spaces)

    def __repr__(self) -> str:
        return f"<NamespaceRegistry {', '.join(self.spaces()) or '空'}>"
