"""warp.game：把「抽卡」这件事包成看得懂的调用。

引擎只知道「哪个方法被钩住了、第几个参数是什么」；这里把它翻译成
``GachaBill``（哪一类抽卡）与 ``Gacha.on_buy``（抽卡时想干什么）。
"""

import threading

from .base import log
from .host import HF_BLOCK, Host, _owner_of_caller, _tick32, host_alive

# ========== 语义层：把「类名 + argc + 参数槽」包成看得懂的调用 ==========

GACHA_TYPE_NAMES = {0: '普通', 1: '付费单抽', 2: '不能用狂气', 3: '免费'}


class GachaBill:
    """一次抽卡请求的快照。

    宿主拦下请求的那一刻把参数读出来，Python 这边拿到的就是这个对象。
    """

    def __init__(self, kind=0, gacha_id=0, payment_id=0):
        self.type_id = int(kind)
        self.type_name = GACHA_TYPE_NAMES.get(self.type_id, f'unknown({self.type_id})')
        self.gacha_id = int(gacha_id)
        self.payment_id = int(payment_id)

    @property
    def is_paid(self):
        return self.type_id == 1

    @property
    def is_free(self):
        return self.type_id == 3

    def __repr__(self):
        return f"<GachaBill {self.type_name} #{self.type_id}>"


class GachaWatcher:
    """``on_buy`` 起的那个事件循环 —— 插件不用管它，宿主统一收尾。"""

    def __init__(self, host, stop, thread, owner):
        self.host = host
        self.stop_event = stop
        self.thread = thread
        self.owner = owner

    def stop(self):
        self.stop_event.set()

    @property
    def running(self):
        return self.thread.is_alive()


class Gacha:
    """把「抽卡」这件事包成三件顺手的东西。

    - ``hooks(allow_paid=True)``：要登记的钩子表（一条看参数、一条拦）
    - ``bill(host)``：读回「刚被拦下的这单是什么类型」
    - ``blocked(host)``：本插件拦下来过几次（事件计数）
    - ``on_buy(handler)``：宿主替你起线程，每拦下一单就调一次 handler

    插件这边只要写一个函数，弹窗自己调::

        def handle_gacha(bill):
            warp.game.gacha.on_buy(handle_gacha)

        def handle_gacha(bill):
            if bill.is_paid:
                return
            host.popup("去刷镜牢换碎片")

    不用 ``on_buy`` 也行，自己写循环：``host.beat()`` + ``blocked()`` 看数字变化 +
    ``bill()`` 读类型，然后 ``host.popup()``。
    """

    def __init__(self):
        # owner -> GachaWatcher：同一个插件重复 on_buy 就自动换掉旧的，
        # 插件卸载时由 WarpHook.on_unload() 统一 stop_all()，插件自己不用记。
        self._watchers = {}

    def stop(self, owner=None):
        """停掉某个插件（默认当前调用者）的抽卡循环。一般不用手动调。"""
        owner = owner or _owner_of_caller() or 'gacha'
        watcher = self._watchers.pop(owner, None)
        if watcher is not None:
            watcher.stop()
        return watcher is not None

    def stop_all(self):
        """停掉全部抽卡循环（插件卸载时由 WarpHook 自己调）。"""
        for watcher in list(self._watchers.values()):
            try:
                watcher.stop()
            except Exception:  # noqa: BLE001
                pass
        self._watchers.clear()

    def hooks(self, allow_paid=True):
        """两条钩子：一条把 GachaType 读进 vars[0]，一条把下单拦下来。"""
        return [
            {
                'klass': 'MainUI.GachaUIPresenter',
                'method': 'OpenGachaAlarmUI',
                'argc': 1,
                'probe_class': 'GachaPayment',
                'probe_method': 'get_GachaType',
                'probe_index': 0,
                'probe_slot': 0,
                'actions': 0,
                'flags': 0,
            },
            {
                'klass': 'MainUI.GachaUIPresenter',
                'method': 'OnGachaSelected',
                'argc': 2,
                'actions': 0,
                'flags': HF_BLOCK,
                'guard_var': 0 if allow_paid else -1,
                'guard_value': 1,
            },
        ]

    def bill(self, host):
        """刚被拦下的那一单（类型从宿主读回来）。"""
        block = host.block()
        kind = 0
        if block is not None:
            kind = int(block.cfg.vars[0])
        return GachaBill(kind)

    def blocked(self, host):
        """本插件一共拦下过几次 —— 数字变大就说明刚发生了一单。"""
        return host.hits(method='OnGachaSelected', blocked=True)

    def on_buy(self, handler, allow_paid=True, interval=0.25, host=None):
        """接住玩家的抽卡请求，宿主替你把钩子和线程跑起来。

        插件只交一个函数进来，弹窗由你自己在函数里调::

            def handle_gacha(bill):
                if bill.is_paid:
                    return                      # 放行
                my_host.popup("去刷镜牢换碎片")   # 拦下并弹出来

            warp.game.gacha.on_buy(handle_gacha)

        宿主只负责「钩子登记 + 循环线程 + 心跳」，**不替你弹窗** ——
        弹不弹、弹什么、弹几次都由插件用 ``host.popup()`` 自己决定。
        ``handler`` 的返回值不做任何处理。

        返回 ``GachaWatcher``，卸载时 ``.stop()`` 一下即可。
        """
        owner = _owner_of_caller() or 'gacha'
        if host is None:
            host = Host(addon_name=owner, hooks=[], texts=[])
        host.configure(hooks=self.hooks(allow_paid=allow_paid))
        try:
            host.push(True)
        except Exception as exc:  # noqa: BLE001
            log(f"抽卡钩子没能写进共享内存：{exc}")

        stop = threading.Event()
        step = max(0.05, float(interval))

        def _pump():
            last = self.blocked(host)
            while not stop.is_set():
                try:
                    host.beat()
                    n = self.blocked(host)
                    if n > last:
                        last = n
                        handler(self.bill(host))
                    elif n < last:
                        last = n          # 重新推配置会把计数清零
                except Exception:  # noqa: BLE001
                    pass
                stop.wait(step)

        thread = threading.Thread(target=_pump, daemon=True, name=f'{owner}-gacha')
        thread.start()
        watcher = GachaWatcher(host, stop, thread, owner)
        old = self._watchers.pop(owner, None)
        if old is not None:
            old.stop()                    # 同一插件重复登记：旧的自己退场
        self._watchers[owner] = watcher
        return watcher


gacha = Gacha()


gacha = Gacha()
