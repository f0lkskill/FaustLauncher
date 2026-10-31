"""warp.plugin.Runtime / Service：插件运行骨架。

插件只交两样东西 —— ``sync``（怎么把设置写进共享内存）与 ``menu``（托盘菜单），
等游戏、注入、心跳、状态播报、卸载收尾都在这里。插件不需要记任何句柄。
"""

import ctypes
import os
import sys
import threading
import time

from . import env
from .base import (
    _valid_snapshot,
    shm_open,
    ensure_exports,
    find_game_pid,
    has_gameassembly,
    inject_dll,
    log,
    wait_for_game,
    wait_for_gameassembly,
    GAME_PROCESS,
    GAME_DLL_NAME,
    WAIT_GAME_TIMEOUT,
    WAIT_DLL_TIMEOUT,
)
from .game import gacha
from .host import _INJECT_LOCK, Host, _owner_of_caller, _tick32, host_alive

# ========== warp.plugin：插件运行骨架 ==========

# 约定好的通用字段名。任何插件的配置结构体只要有这五个 int32 字段，就能直接用
# :class:`Runtime` —— 它们是「开关 / 已挂钩 / 状态码 / 错误码 / 是否初始化」。
COMMON_FIELDS = ('enabled', 'hooked', 'status', 'last_error')


def _caller_dir():
    """推断「调用 Runtime 的那个插件」所在目录。

    插件是被启动器 ``exec`` 的，``__file__`` 虽然注入了但指向插件自己的文件；
    这里再退一层用调用栈的 ``co_filename``，避免拿成 WarpHook 自己的目录。
    """
    try:
        frame = sys._getframe(1)
    except Exception:  # noqa: BLE001
        frame = None
    # 顺着调用栈往上找最近一个「插件目录」：判定标准是同一个目录里有
    # addon_info.json。Warphook 自己的包目录没有这个文件，于是会被跳过 ——
    # 这样拆包以后不管中间多套几层，拿到的仍是真正调用方的目录。
    while frame is not None:
        path = frame.f_code.co_filename
        if path:
            folder = os.path.dirname(os.path.abspath(path))
            if os.path.isfile(os.path.join(folder, 'addon_info.json')):
                return folder
        frame = frame.f_back
    return os.path.dirname(os.path.abspath(__file__))


class Runtime:
    """插件运行骨架：把每个插件都要写一遍的流程集中到一处。

    插件只需要提供三样东西：

    * 共享内存结构体（含 :data:`COMMON_FIELDS` 五个约定字段）与映射名
    * ``apply(block, enabled)`` —— 往结构体里写自己的业务字段，返回 ``(ok, message)``
    * ``read(block)`` —— 从结构体读出自己的业务状态，返回 dict

    剩下的共享内存映射、il2cpp 导出名填充、找进程、等 GameAssembly、注入、
    状态轮询、托盘菜单、gamestart 自动注入、卸载清理，全部由这里处理。

    Args:
        addon_name: 插件名（菜单标题、日志前缀）。
        map_name: 共享内存名。
        struct_cls: 配置结构体类型。
        magic: 结构体 ``magic`` 字段的期望值（用于判断是否需要初始化）。
        dll_name: 插件目录下的 DLL 文件名。
        exports: il2cpp 导出名序列（顺序与 C 侧一致）；空表示不需要。
        config_size: 结构体字节数；默认 ``sizeof(struct_cls)``。
        magic_field: 用作初始化标记的字段名。
        log_prefix: 日志前缀，默认 ``[插件名]``。
        settings_reader: ``() -> dict``，读业务设置；默认读 addon_info 的 settings。
        apply: ``(block, enabled) -> (ok, message)``，写业务字段。
        read: ``(block) -> dict``，读业务状态。
        format_line: ``(status_dict) -> str``，状态行文本。
        menu_labels: 三个菜单项文案（注入 / 解除 / 应用）。
        auto_key: settings 里控制自动注入的键名。
        register_menu: 是否注册托盘菜单。
        register_start: 是否注册 gamestart 回调与「已在运行则补注入」。
    """

    def __init__(self, *, addon_name, map_name, struct_cls, magic, dll_name,
                 exports=(), config_size=None, name_max=64, exports_offset=None,
                 magic_field='magic', log_prefix=None, plugin_dir=None,
                 settings_reader=None, apply=None, read=None, format_line=None,
                 menu_labels=('注入', '解除', '应用设置'), auto_key='自动注入',
                 skip_env=None, on_tick=None, key_fields=None,
                 register_menu=True, register_start=True):
        self.addon_name = addon_name
        self.map_name = map_name
        self.struct_cls = struct_cls
        self.magic = magic
        self.magic_field = magic_field
        self.dll_name = dll_name
        self.exports = tuple(exports)
        self.name_max = name_max
        self.config_size = config_size or ctypes.sizeof(struct_cls)
        # 导出名表通常紧接在结构体之后；插件若在两者之间还塞了别的东西
        # （比如 BattleSnark 的台词区），就自己指定偏移。
        self.exports_offset = (self.config_size if exports_offset is None
                               else int(exports_offset))
        self.map_size = self.exports_offset + len(self.exports) * name_max
        self.log_prefix = log_prefix or f"[{addon_name}]"
        self.plugin_dir = plugin_dir or _caller_dir()
        self.auto_key = auto_key
        self.skip_env = skip_env
        self._reader = settings_reader
        self._apply = apply
        self._read = read
        self._format = format_line
        self._menu_labels = menu_labels
        self._on_tick = on_tick
        # 状态轮询的「关键变化」判据：只有这些字段变了才写日志。
        # 默认只看挂上没有、有没有报错 —— 计数器之类每回合都在动的字段
        # 放进去会把日志刷爆。
        self.key_fields = tuple(key_fields or ('hooked', 'last_error'))

        self._block = None
        self._manager = env.ADDON_ARG.get('AddonManager')      # type: ignore[name-defined]

    # ---------- 日志 ----------

    def log(self, message):
        """按插件前缀打一行日志。"""
        log(message, self.log_prefix)

    # ---------- 设置 ----------

    def settings(self):
        """读这个插件在 addon_info.json 里的 settings。"""
        if self._reader is not None:
            try:
                return self._reader() or {}
            except Exception as exc:  # noqa: BLE001
                self.log(f"读取设置失败：{exc}")
                return {}
        if self._manager is None:
            return {}
        try:
            info = self._manager.get_addon_info(self.addon_name) or {}
        except Exception:  # noqa: BLE001
            return {}
        return info.get('settings') or {}

    # ---------- 共享内存 ----------

    def block(self):
        """建立/打开共享内存，返回 :class:`SharedMap`；失败返回 ``None``。

        首次映射时顺手把 il2cpp 导出名表补进去 —— 共享内存可能是上一个进程留下
        的，DLL 读不到表就取不到 il2cpp 接口。
        """
        if self._block is not None:
            return self._block
        try:
            self._block = shm_open(
                self.map_name, self.map_size, self.struct_cls,
                magic_field=self.magic_field, magic_value=self.magic,
                init=self._init_cfg)
        except Exception as exc:  # noqa: BLE001
            self.log(f"共享内存不可用：{exc}")
            return None
        if self._block is not None and self.exports:
            if self.read_mapped(self._block) < len(self.exports):
                ensure_exports(self._block, self.exports,
                               self.exports_offset, self.name_max)
        if self._block is not None and self._apply is not None:
            # 首次建立映射时把业务字段（文案/延迟之类）也写进去，这样插件刚被
            # 打开、还没点过「应用设置」时，状态里看到的就已经是配置值而不是 0。
            try:
                self._apply(self._block, False)
            except Exception:  # noqa: BLE001
                pass
        return self._block

    def cfg(self):
        """只要配置结构体。"""
        blk = self.block()
        return blk.cfg if blk is not None else None

    def _init_cfg(self, cfg):
        """共享内存首次建立（或 magic 对不上）时把通用字段清零。"""
        for field in COMMON_FIELDS:
            if hasattr(cfg, field):
                try:
                    setattr(cfg, field, 0)
                except Exception:  # noqa: BLE001
                    pass

    def read_mapped(self, blk=None):
        """读回导出名表里非空的项数。"""
        blk = blk if blk is not None else self.block()
        if blk is None or not self.exports:
            return 0
        try:
            return int(blk.read_table(self.exports_offset, len(self.exports),
                                      self.name_max))
        except Exception:  # noqa: BLE001
            return 0

    # ---------- 开关 ----------

    def push(self, enabled=True):
        """把业务字段和开关写进共享内存，返回 ``(ok, message)``。"""
        blk = self.block()
        if blk is None:
            return False, "共享内存不可用"
        if self.exports:
            ensure_exports(blk, self.exports, self.exports_offset, self.name_max)
        try:
            blk.cfg.enabled = 1 if enabled else 0
        except Exception as exc:  # noqa: BLE001
            return False, f"写开关失败：{exc}"
        if self._apply is not None:
            try:
                return self._apply(blk, enabled)
            except Exception as exc:  # noqa: BLE001
                return False, f"写配置失败：{exc}"
        return True, "已开启" if enabled else "已关闭"

    def set_enabled(self, enabled=True):
        """武装/解除，返回是否成功（失败会打日志）。"""
        ok, message = self.push(enabled)
        if ok:
            # 解除时不要复用 apply 的文案（那说的是「已武装」，容易误导）
            self.log(f"已开启：{message}" if enabled else "已解除")
        else:
            self.log(f"设置失败：{message}")
        return ok

    def arm(self):
        """开启（武装）。"""
        return self.set_enabled(True)

    def disarm(self):
        """解除（DLL 保留，随时可再开）。"""
        return self.set_enabled(False)

    # ---------- 状态 ----------

    def status(self):
        """读回 DLL 侧状态（通用字段 + 插件自己的业务字段）。"""
        blk = self.block()
        if blk is None:
            return {}
        cfg = blk.cfg
        st = {}
        for field in COMMON_FIELDS:
            if hasattr(cfg, field):
                st[field] = int(getattr(cfg, field))
        st['enabled'] = bool(st.get('enabled'))
        st['hooked'] = bool(st.get('hooked'))
        st['export_mapped'] = self.read_mapped(blk)
        if self._read is not None:
            try:
                st.update(self._read(blk) or {})
            except Exception as exc:  # noqa: BLE001
                self.log(f"读取状态失败：{exc}")
        return st


    # ---------- 注入 ----------

    def dll_path(self):
        """插件目录下的 DLL 绝对路径。"""
        return os.path.join(self.plugin_dir, self.dll_name)

    # ---------- 单步原语（和 Host 对齐，Service 两种通道都能开） ----------

    def beat(self):
        """写一次心跳，表示「本插件还在管着这块内存」。"""
        blk = self.block()
        if blk is None:
            return False
        try:
            blk.cfg.heartbeat = int(_tick32())
        except Exception:  # noqa: BLE001
            return False
        return True

    def poll(self):
        """读一次状态（等同 ``status()``，名字与 Host 对齐）。"""
        return self.status()

    def close(self):
        """丢掉映射视图；不碰 DLL、不碰线程。"""
        self._block = None

    def inject_now(self, wait=False, stop_event=None):
        """完整流程：写配置 → 找游戏 → 等 GameAssembly → 注入 → 交给状态轮询。"""
        ok, message = self.push(True)
        if not ok:
            self.log(f"注入中止：{message}")
            return False

        pid = find_game_pid() if not wait else wait_for_game(stop_event=stop_event)
        if pid is None:
            self.log("注入中止：没有找到运行中的游戏")
            return False

        if not wait_for_gameassembly(pid, stop_event=stop_event):
            self.log("注入中止：等待 GameAssembly.dll 超时")
            return False

        with _INJECT_LOCK:
            # 抢到锁之后再确认一次：可能刚被别的插件注入过
            if host_alive(self.block()):
                self.log("宿主已在运行，跳过重复注入")
                return True
            ok, message = inject_dll(pid, self.dll_path())
        if not ok:
            self.log(f"注入失败：{message}")
            return ok
        self.log(f"已注入（PID {pid}）")
        return ok

    # ---------- 状态轮询 ----------

def _service_registry():
    """插件服务注册表。

    故意挂在 ``env.ADDON_MANAGER`` 上而不是类变量上：插件被重载时本模块会重新 exec，
    类变量跟着重建，但**旧实例的线程还在跑**——于是就出现两条 worker 同时播报
    「游戏已连接，等待挂钩」。挂在启动器对象上就跨得过重载。
    """
    if env.ADDON_MANAGER is None:
        return Service._services
    reg = getattr(env.ADDON_MANAGER, '_warp_services', None)
    if reg is None:
        reg = {}
        try:
            setattr(env.ADDON_MANAGER, '_warp_services', reg)
        except Exception:  # noqa: BLE001
            return Service._services
    return reg


class Service:
    """一个插件的整套后台流程：等游戏 → 注入 → 心跳 → 状态播报 → 托盘菜单。

    插件只要交两样东西，剩下的全归这里管：

    - ``sync``：怎么把当前设置写进共享内存（插件自己知道设置长什么样）
    - ``menu``：托盘里那几项叫什么、点了调谁（不传就不注册）

    ::

        service = warp.plugin.Service(
            addon_name=env.ADDON_NAME,
            name='NoGacha',
            sync=_push,
            auto=lambda: _settings()[1],
            menu=(('注入拦截', lambda: service.inject_now(wait=True)),
                  ('解除拦截', lambda: service.set_enabled(False)),
                  ('应用设置', lambda: service.sync())),
        )
        service.start()

    线程、心跳、注入时机、卸载收尾都在本类里；插件不需要记任何句柄。
    """

    _services = {}

    def __init__(self, *, addon_name=None, name=None, sync=None, auto=None,
                 menu=(), interval=0.25, host=None, shared=True):
        self.addon_name = addon_name or _owner_of_caller() or 'plugin'
        self.name = name or self.addon_name
        self._sync_cb = sync
        self._auto_cb = auto
        self._menu = tuple(menu)
        self.interval = max(0.05, float(interval))
        self._host = host
        # shared=True 表示目标 DLL 是共享宿主（warp_host.dll，一块映射多插件共用）；
        # False 表示插件自带 DLL（自己的映射、自己的 header），判断「是否已挂上」
        # 的方式不一样。
        self.shared = bool(shared)
        self._stop = threading.Event()
        self._thread = None
        self._last_key = None
        self._closed = False
        self._hit_seen = {}
        self._hit_done = set()
        self._event_callbacks = []
        reg = _service_registry()
        old = reg.get(self.addon_name)
        if old is not None and old is not self:
            try:
                old.stop()
            except Exception:  # noqa: BLE001
                pass
        reg[self.addon_name] = self
        if env.ADDON_MANAGER is not None:
            if self._menu:
                try:
                    self.register_menu()
                except Exception:  # noqa: BLE001
                    pass
            try:
                env.ADDON_MANAGER.gamestart_funcs.append(self._on_game_start)
            except Exception:  # noqa: BLE001
                pass

    # ---------- 基础 ----------

    def log(self, message):
        log(message, prefix=f'[{self.name}]')

    def host(self):
        """本插件与 DLL 之间的通道（惰性创建，第一次真要用时才建）。"""
        if self._host is None:
            self._host = Host(addon_name=self.addon_name, hooks=[], texts=[])
        return self._host

    def _already_running(self, host):
        """目标 DLL 是不是已经挂上了。

        共享宿主看 header 里的心跳（映射是一块多人共用的，只有 DLL 真的在写心跳
        才说明它在跑）；自带 DLL 的插件看它自己的 ``hooked`` 字段。
        """
        if self.shared:
            try:
                return bool(host_alive(host.block()))
            except Exception:  # noqa: BLE001
                return False
        try:
            st = host.poll() or {}
        except Exception:  # noqa: BLE001
            return False
        return bool(st.get('hooked'))

    def sync(self):
        """把最新设置推给游戏里的宿主。插件自己的 ``_push`` 干这件事。"""
        if self._sync_cb is None:
            return True
        try:
            return self._sync_cb()
        except Exception as exc:  # noqa: BLE001
            self.log(f'推送设置失败：{exc}')
            return False

    # ---------- 状态文案 ----------

    def describe(self, st):
        if st.get('last_error'):
            return f"出错：{st.get('last_error_text')}"
        if st.get('hooked'):
            return (f"工作中，命中 {st.get('evt_count', 0)} 次"
                    f" / 已生效 {st.get('fired', 0)} 次")
        if not st.get('ready'):
            return "等待游戏加载"
        return "游戏已连接，等待挂钩"

    def _state_key(self, st):
        return (st.get('hooked'), st.get('last_error'), st.get('status'))

    # ---------- 后台流程 ----------

    def _worker(self, stop):
        host = self.host()
        dll = host.dll_path()
        if not os.path.isfile(dll):
            self.log(f'找不到宿主 DLL：{dll}')
            return

        self.log('等待游戏启动…')
        pid = wait_for_game(stop_event=stop)
        if pid is None:
            return
        if not wait_for_gameassembly(pid, stop_event=stop):
            self.log('等待 GameAssembly.dll 超时')
            return

        self.sync()
        if self._already_running(host):
            self.log('宿主已在运行，跳过重复注入')
        else:
            ok, message = inject_dll(pid, dll)
            if not ok:
                self.log(f'注入失败：{message}')
                return
            self.log(f'已注入（PID {pid}）')
            self.sync()

        while not stop.is_set():
            try:
                host.beat()
                self._dispatch_hits(host, stop)
                self._dispatch_events(host)
                st = host.poll()
                if st:
                    key = self._state_key(st)
                    if key != self._last_key:
                        self._last_key = key
                        self.log(self.describe(st))
            except Exception:  # noqa: BLE001
                pass
            if stop.wait(self.interval):
                break

    # ---------- 钩子命中派发 ----------

    def on_event(self, callback):
        """事件回调 —— 钩子每命中一次，引擎就往队列塞一条，这里被逐条喂到。

        ``callback(host, event)``，``event`` 是 ``{'id','hook','tick','a','b','c','d'}'``。
        跟 :meth:`on_hit` 的区别：``on_hit`` 只知道「命中了多少下」（计数器差），
        这里拿到的是**每一次命中的现场**（参数、时机），可以丢进队列慢慢算。

        钩子要用 ``event=事件号`` 声明才会入队；队列是环形的，满了丢最旧的，
        所以回调不必抢在别人前面 —— 但也别太慢，攒太多会盖掉旧事件。
        """
        self._event_callbacks.append(callback)
        return self

    def _dispatch_events(self, host):
        callbacks = getattr(self, '_event_callbacks', None)
        if not callbacks:
            return
        events = host.events()
        if not events:
            return
        for callback in list(callbacks):
            for event in events:
                try:
                    callback(host, event)
                except Exception:  # noqa: BLE001
                    pass

    def on_hit(self, callback, *, method=None, once=False, delay=0.0,
               thread=True):
        '''钩子命中时调 ``callback(host)``。

        宿主只负责「把命中次数记下来」，什么时候做什么由插件在回调里自己写：
        ::

            def _boom(host):
                host.popup('倒计时开始')
                time.sleep(3)
                host.kill_game()

            service.on_hit(_boom, method='FixedUpdate', once=True, delay=5.0)

        ``delay`` 是命中后再等多久才调（秒）；``thread=True`` 时回调跑在独立线程，
        不会拖慢心跳与状态播报（``time.sleep`` 放在回调里是安全的）。
        '''
        key = (method or '', bool(once))
        self._hit_callbacks = getattr(self, '_hit_callbacks', {})
        self._hit_callbacks[key] = (callback, float(delay), bool(thread))
        if method is not None:
            self._hit_seen.setdefault((method, 'count'), 0)
        return self

    def _dispatch_hits(self, host, stop):
        callbacks = getattr(self, '_hit_callbacks', None)
        if not callbacks:
            return
        for (method, once), (callback, delay, use_thread) in list(callbacks.items()):
            if method is None:
                continue
            try:
                count = host.hits(method=method)
            except Exception:  # noqa: BLE001
                continue
            if method not in self._hit_seen:
                # 第一次看到这个钩子：把当时的计数当底数（注入前就跑起来的
                # FixedUpdate 已经命中过几百次），只对之后的增量回调。
                self._hit_seen[method] = count
                continue
            last = self._hit_seen[method]
            if count <= last:
                if count < last:
                    self._hit_seen[method] = count
                continue
            self._hit_seen[method] = count
            if once:
                if method in self._hit_done:
                    continue
                self._hit_done.add(method)
            self._run_hit(callback, host, delay, use_thread, stop)

    def _run_hit(self, callback, host, delay, use_thread, stop):
        def _go():
            try:
                if delay > 0 and stop.wait(delay):
                    return
                callback(host)
            except Exception as exc:  # noqa: BLE001
                self.log(f'命中回调出错：{exc}')

        if use_thread:
            threading.Thread(target=_go, daemon=True,
                             name=f'{self.name}-hit').start()
        else:
            _go()

    def start(self):
        """起（或复用）后台流程。重复调用不会起第二条。"""
        if self._closed:
            return self
        if self._thread is not None and self._thread.is_alive():
            return self
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._worker, args=(self._stop,),
            daemon=True, name=f'{self.name}-auto')
        self._thread.start()
        return self

    def stop(self):
        """停后台流程，顺便收掉本插件的抽卡循环与映射视图。

        线程必须 join 掉再关映射：``_worker`` 每轮都会读共享内存，而卸载流程紧接着
        就会解除映射，读到已释放的地址是进程级 AV（没有 traceback）。
        """
        try:
            self._stop.set()
        except Exception:  # noqa: BLE001
            pass
        if self._host is not None:
            try:
                # 先关视图，线程里的 read/beat 会立刻返回默认值而不是等超时
                self._host.close()
            except Exception:  # noqa: BLE001
                pass
        thread = getattr(self, "_thread", None)
        if (thread is not None and thread.is_alive()
                and thread is not threading.current_thread()):
            thread.join(timeout=5.0)
        self._thread = None
        try:
            gacha.stop(self.addon_name)
        except Exception:  # noqa: BLE001
            pass
        self._closed = True
        _service_registry().pop(self.addon_name, None)
        return True

    def _on_game_start(self):
        """启动器通知「游戏起来了」：按设置的自动注入开关决定跟不跟。"""
        if self._closed:
            return
        if os.environ.get(f'{self.name.upper()}_SKIP_ATTACH') == '1':
            return
        try:
            if self._auto_cb is not None and not self._auto_cb():
                self.log('自动注入已关闭，跳过')
                return
        except Exception:  # noqa: BLE001
            pass
        self.start()

    # ---------- 对外动作 ----------

    def inject_now(self, wait=False):
        """立刻注入当前游戏；``wait=True`` 就在后台等它起来。"""
        if wait:
            self.start()
            return True
        host = self.host()
        pid = wait_for_game(timeout=1.0)
        if pid is None:
            return False
        if not wait_for_gameassembly(pid, timeout=10.0):
            return False
        self.sync()
        if self._already_running(host):
            self.log('宿主已在运行，跳过重复注入')
            self.start()
            return True
        ok, message = inject_dll(pid, host.dll_path())
        if ok:
            self.log(f'已注入（PID {pid}）')
            self.sync()
            self.start()
        else:
            self.log(f'注入失败：{message}')
        return ok

    def set_enabled(self, enabled=True):
        """开/关，并把最新设置推给游戏。"""
        self.sync()
        ok = self.host().set_enabled(bool(enabled))
        if ok:
            self.log('已开启' if enabled else '已关闭')
        return ok

    def status(self):
        """当前状态（只读一次，不起线程）。"""
        st = self.host().poll()
        st['status_text'] = self.describe(st)
        return st

    # ---------- 托盘 ----------

    def register_menu(self):
        """把 ``menu`` 里那几项注册成本插件自己的托盘菜单。"""
        if not self._menu:
            return False
        try:
            from pystray import Menu, MenuItem
        except Exception:  # noqa: BLE001
            return False
        if env.ADDON_MANAGER is None:
            return False
        items = tuple(MenuItem(label, (lambda cb=cb: cb()))
                      for label, cb in self._menu)
        env.ADDON_MANAGER.register_tray_item(MenuItem(self.name, action=Menu(*items)))
        return True

    @classmethod
    def stop_all(cls):
        for service in list(cls._services.values()):
            try:
                service.stop()
            except Exception:  # noqa: BLE001
                pass
        cls._services.clear()
