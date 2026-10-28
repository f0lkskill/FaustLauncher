"""WarpHook 的类型桩：只给 IDE 与静态检查看，运行时一行都不会执行。

依赖库把自己全部能力挂在命名空间 ``warp`` 里（``warp.game`` / ``warp.plugin``
/ ``warp.il2cpp`` / ``warp.inject`` / ``warp.shm`` / ``warp.log``），那些成员是
插件运行时才挂上去的，静态分析器看不到 —— 于是 ``_W.game.gacha.on_buy(...)``
在 IDE 里既没有补全也没有参数提示，还得吃一句「Any 的成员不存在」。

这里用 :class:`typing.Protocol` 把「某个命名空间里应该有什么」写清楚，插件
只要在 ``TYPE_CHECKING`` 分支里 import 一下就能拿到真实的补全与类型检查：

    from typing import TYPE_CHECKING, cast

    if TYPE_CHECKING:
        from addons.WarpHook.warp_stub import WarpNamespace

    _NS = ADDON_ARG.get('Namespaces')
    _W = cast("WarpNamespace", _NS.space('warp') if _NS is not None else None)

要点：

* ``TYPE_CHECKING`` 在运行时恒为 ``False``，所以这份文件**永远不会被真正
  import** —— 依赖库没装、插件照样能载入。
* 这里只写类型，不写实现，也不 import 任何依赖库自己的模块，所以不会把
  WarpHook 的运行时对象拖进插件的导入链。
* 插件侧用 ``cast`` 而不是 ``assert``：``cast`` 只影响静态分析，运行时如果
  依赖库真的没装，``_W`` 就是 ``None``，错误会出现在真正调用那一行，位置更准。
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Protocol, Sequence, Tuple, Type


class GachaBill(Protocol):
    """一次抽卡请求的账单 —— ``warp.game.gacha.bill(host)`` 的返回值。"""

    type_id: int
    """``GachaPayment::get_GachaType()`` 的原值：0 普通 / 1 付费单抽 / 2 不能用狂气 / 3 免费。"""

    type_name: str
    """``type_id`` 的中文名，例如 ``'付费单抽'``。"""

    is_paid: bool
    """是不是付费单抽（``type_id == 1``）。"""

    is_free: bool
    """是不是免费抽（``type_id == 3``）。"""

    gacha_id: int
    payment_id: int


class GachaWatcher(Protocol):
    """``warp.game.gacha.on_buy()`` 返回的观察者，代表一条正在跑的抽卡循环。"""

    @property
    def running(self) -> bool:
        """线程还活着吗。"""
        ...

    def stop(self) -> None:
        """停掉这条循环（幂等）。"""
        ...


class Gacha(Protocol):
    """``warp.game.gacha``：抽卡事件的开箱即用封装。"""

    def hooks(self, allow_paid: bool = True) -> List[Dict[str, Any]]:
        """要登记的钩子表；``allow_paid=True`` 时付费单抽直接放行。"""
        ...

    def bill(self, host: "Host") -> GachaBill:
        """按宿主里探针写下的 ``vars[0]`` 造一张账单。"""
        ...

    def blocked(self, host: "Host") -> int:
        """这个插件的拦截钩子已经真正拦下多少单。"""
        ...

    def on_buy(
        self,
        handler: Callable[[GachaBill], Any],
        allow_paid: bool = True,
        interval: float = 0.25,
        host: Optional["Host"] = None,
    ) -> GachaWatcher:
        """登记钩子、起线程、把「有人下单」回调给 ``handler``。

        宿主只负责钩子 / 线程 / 心跳；弹不弹、弹什么由 ``handler`` 自己用
        ``host.popup()`` 决定。同一个插件重复调用会自动替换旧循环。
        """

        ...

    def stop(self, owner: Optional[str] = None) -> None:
        """停掉指定插件的抽卡循环（``owner=None`` 时按当前调用方判断）。"""
        ...

    def stop_all(self) -> None:
        """停掉所有插件的抽卡循环。"""
        ...


class Host(Protocol):
    """``warp.plugin.Host``：一块共享内存 + 一组钩子，代表「本插件在游戏里的宿主」。"""

    def __init__(
        self,
        addon_name: Optional[str] = None,
        hooks: Optional[Sequence[Dict[str, Any]]] = None,
        texts: Optional[Sequence[str]] = None,
        map_name: Optional[str] = None,
        skip_env: Optional[str] = None,
    ) -> None:
        """``addon_name`` 用来区分插件；``map_name``/``skip_env`` 一般不用传
        （映射名由宿主统一管理，传了也会被忽略）。"""
        ...

    def configure(
        self,
        hooks: Optional[Sequence[Dict[str, Any]]] = None,
        texts: Optional[Sequence[str]] = None,
        **kwargs: Any,
    ) -> None:
        """改配置（只在内存里改，``push()`` 之后才生效）。"""

    def push(self, enabled: bool = True) -> str:
        """把当前配置写进共享内存，返回一句人能看懂的结果，例如 ``'已生效'``。"""
        ...

    def hook(
        self,
        klass: str,
        method: str,
        argc: int = 0,
        block: bool = False,
        actions: Optional[int] = None,
        probe: Optional[Tuple[str, str, int, int]] = None,
        guard: Optional[Tuple[int, int]] = None,
        **extra: Any,
    ) -> Dict[str, Any]:
        """登记一条钩子（``probe``/``guard`` 用来读参数、按参数放行）。"""
        ...

    def clear_hooks(self) -> None:
        """清空本插件登记的钩子。"""
        ...

    def hooks(self) -> List[Dict[str, Any]]:
        """本插件当前登记的钩子副本。"""
        ...

    def hits(self, method: Optional[str] = None, blocked: bool = False,
             owner: Optional[str] = None) -> int:
        """本插件钩子被调用的次数；``blocked=True`` 只数「真的拦下来」的次数。"""
        ...

    def beat(self) -> bool:
        """写一次心跳。"""
        ...

    def poll(self) -> Dict[str, Any]:
        """读一次完整状态。"""
        ...

    def status(self, owner: Optional[str] = None) -> Dict[str, Any]:
        """状态字典（``ready``/``hooked``/``status_text``/``last_error`` 等）。"""
        ...

    def popup(self, text: str, timeout: float = 2.0) -> str:
        """让游戏弹一个原版系统弹窗，正文是 ``text``。返回 ``'已执行'`` 之类的结果。"""
        ...

    def kill_game(self, timeout: float = 2.0) -> str:
        """让游戏进程立即退出。"""
        ...

    def set_enabled(self, enabled: bool = True) -> bool:
        """开 / 关这组钩子（关掉后钩子还在，只是不动作）。"""
        ...

    def block(self) -> Any:
        """共享内存视图（``cfg`` / ``vars`` / ``hooks`` / ``texts``）。"""
        ...

    def read_mapped(self) -> int:
        """宿主已经绑定好的 il2cpp 导出名数量（排错用）。"""
        ...

    def inject_now(self, wait: bool = False, stop_event: Any = None) -> bool:
        """立刻注入当前游戏（``wait=True`` 就在后台等它起来）。"""
        ...

    def close(self) -> None:
        """关掉映射视图，不碰线程。"""
        ...


class Service(Protocol):
    """``warp.plugin.Service``：插件的运行骨架（等游戏 / 注入 / 心跳 / 播报 / 托盘 / 卸载）。"""

    def __init__(
        self,
        *,
        addon_name: Optional[str] = None,
        name: Optional[str] = None,
        sync: Optional[Callable[[], Any]] = None,
        auto: Optional[Callable[[], bool]] = None,
        menu: Sequence[Tuple[str, Callable[[], Any]]] = (),
        interval: float = 0.25,
        host: Any = None,
        shared: bool = True,
    ) -> None:
        """``addon_name`` 用来区分不同插件；``sync`` 负责把设置推给游戏；
        ``auto()`` 决定游戏启动时要不要自动注入；``menu`` 是要挂到托盘上的项；
        ``host`` 可以是共享宿主 ``Host``，也可以是自带 DLL 的 ``Runtime``；
        ``shared=False`` 时按 ``runtime`` 自己的 ``hooked`` 判断是否已注入。"""

    def host(self) -> Host:
        """本插件的宿主（惰性创建）。"""
        ...

    def sync(self) -> Any:
        """调插件的 ``sync`` 回调，把最新设置推给游戏。"""
        ...

    def start(self) -> None:
        """起后台线程：等游戏 → 注入 → 心跳 → 状态播报。"""
        ...

    def stop(self) -> None:
        """停掉后台线程、抽卡循环、映射视图。"""
        ...

    def inject_now(self, wait: bool = False) -> bool:
        """立刻注入当前游戏。"""
        ...

    def on_hit(
        self,
        callback: Callable[[Host], Any],
        *,
        method: Optional[str] = None,
        once: bool = False,
        delay: float = 0.0,
        thread: bool = True,
    ) -> "Service":
        """钩子命中时调 ``callback(host)``。

        宿主只记命中次数，做什么由回调自己写（``host.popup(...)`` /
        ``host.kill_game()``）；``delay`` 是命中后再等多久（秒），
        ``thread=True`` 时回调跑在独立线程里，``time.sleep`` 不影响心跳。
        """
        ...

    def set_enabled(self, enabled: bool = True) -> bool:
        """开 / 关本插件在游戏里的钩子。"""
        ...

    def status(self) -> Dict[str, Any]:
        """读一次状态。"""
        ...

    @classmethod
    def stop_all(cls) -> None:
        """停掉所有已注册的 Service。"""
        ...


class Plugin(Protocol):
    """``warp.plugin``：宿主与运行骨架。"""

    Host: Type[Host]
    Service: Type[Service]
    Runtime: Any
    """``warp.plugin.Runtime``：老式「一个插件一个 Runtime」封装（新插件用 Service）。"""
    host_alive: Callable[[Any], bool]

    # 钩子动作位（``extern``/``guard`` 参数）与宿主容量常量
    ACT_POPUP: int
    ACT_PANEL: int
    ACT_KILL: int
    HF_BLOCK: int
    HF_ONCE: int

    HOST_MAX_HOOKS: int
    HOST_MAX_TEXTS: int
    HOST_DLL_NAME: str
    HOST_STATUS_TEXT: Dict[int, str]
    HOST_MAP_BYTES: int
    HOST_HEADER_SIZE: int
    HOST_HOOK_SIZE: int
    HOST_TEXT_SIZE: int
    HOST_HOOK_OFFSET: int
    HOST_TEXTS_OFFSET: int
    HOST_EXPORTS_OFFSET: int
    HOST_VAR_COUNT: int

    # 命令通道
    HOST_CMD_TEXT_LEN: int
    CMD_NONE: int
    CMD_POPUP: int
    CMD_KILL: int


class IL2Cpp(Protocol):
    """``warp.il2cpp``：il2cpp 导出名解析。"""

    def resolve(self, refresh: bool = False) -> Dict[str, str]:
        """``{'domain_get': '混淆后的导出名', ...}``。"""
        ...

    def names_table(self) -> List[str]:
        """内置的基准导出名清单。"""
        ...


class Inject(Protocol):
    """``warp.inject``：找进程、等模块、注入 DLL。"""

    def find_pid(self, process: str = ...) -> Optional[int]: ...

    def has_gameassembly(self, pid: int, module: str = ...) -> bool: ...

    def wait_for_game(self, timeout: float = ..., stop_event: Any = ...) -> Optional[int]: ...

    def wait_for_gameassembly(self, pid: int, timeout: float = ..., stop_event: Any = ...) -> bool: ...

    def inject(self, pid: int, dll_path: str) -> bool: ...


class Shm(Protocol):
    """``warp.shm``：共享内存。"""

    def open(self, name: str, size: int, struct_cls: Any, **kwargs: Any) -> Any: ...


class Log(Protocol):
    """``warp.log``：写日志。"""

    def write(self, message: str, prefix: str = ...) -> None: ...


class WarpNamespace(Protocol):
    """``warp`` 这个顶级命名空间的全部成员。

    插件里这样拿到它::

        _W = cast("WarpNamespace", _NS.space('warp') if _NS is not None else None)
        _W.game.gacha.on_buy(handle_gacha, allow_paid=True)
    """

    name: str
    game: Game
    """``warp.game``：游戏概念层（目前有 ``gacha``）。"""

    plugin: Plugin
    il2cpp: IL2Cpp
    inject: Inject
    shm: Shm
    log: Log


class Game(Protocol):
    """``warp.game``：游戏概念层。"""

    gacha: Gacha
