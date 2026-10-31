# -*- coding: utf-8 -*-
"""warp.game 的门面：把「包装好的一次调用」摆到插件面前。

新手不该认识这些东西：类名、方法名、argc、对象槽、字段偏移、共享内存。
他应该只写::

    game.popup('你好')
    for u in game.units():
        print(u.id, u.hp, [b.key for b in u.buffs()])

    game.on_round_start(lambda battle: print(battle.count, battle.units))

底层能力（钩子、读链、对象槽、共享内存）全在这里被吃掉了，插件碰不到。
**但底层不会被删**：``warp.game`` 上的这些函数都是 ``Live`` 的转发，
想做更细的事仍然可以直接拿 ``warp.plugin.Host`` 自己写。

一个 ``Live`` 实例按插件名懒创建，负责：

- 起一个 ``Service``（等游戏、注入、心跳、状态播报）
- 维护一条「回合开始」钩子和场景缓存
- 把命中的瞬间翻译成回调参数（``Battle`` / ``Unit`` / ``Buff``）
"""

import threading
import time

from . import fields, objects
from .base import log
from .host import Host, _owner_of_caller
from .service import Service

# 场景编号 -> 名字（与 objects.SCENES 同源，这里只做转发，方便插件少记一个名字）
SCENES = objects.SCENES

_LIVES = {}


def _now():
    return time.time()


class Battle:
    """一次「战斗快照」：某一刻场上所有单位的只读视图。

    由 :meth:`Live.battle` / :meth:`Live.on_round_start` 交给你。
    里面的 ``Unit`` 是活的——读它们的属性会**现读游戏内存**，不是缓存值。
    """

    __slots__ = ("_live", "scene", "scene_name", "units")

    def __init__(self, live, scene_value, units):
        self._live = live
        self.scene = int(scene_value)
        self.scene_name = SCENES.get(self.scene, f'未知({self.scene})')
        self.units = list(units)

    @property
    def count(self):
        """场上单位数。"""
        return len(self.units)

    @property
    def alive(self):
        """还活着的单位。"""
        return [u for u in self.units if u.alive]

    def by_identity(self, identity):
        """按人格 / 角色 ID 找单位（``10115`` 这种）。"""
        identity = int(identity)
        for u in self.units:
            if u.identity == identity:
                return u
        return None

    ally = by_identity

    def by_id(self, instance_id):
        """按战斗内编号找单位（界面上那个 ``1``、``2``）。"""
        instance_id = int(instance_id)
        for u in self.units:
            if u.id == instance_id:
                return u
        return None

    def __len__(self):
        return len(self.units)

    def __iter__(self):
        return iter(self.units)

    def __repr__(self):
        return f"<Battle {self.scene_name} count={self.count}>"


class Live:
    """一个插件的「游戏生活」：连接、快照、回调。

    一般情况下用模块级函数（``game.units()`` 之类）就够了，不需要自己 new。
    """

    def __init__(self, owner=None, host=None, auto=True):
        self.owner = owner or _owner_of_caller() or 'plugin'
        self._host = host
        self._service = None
        self._stop = threading.Event()
        self._thread = None
        self._lock = threading.RLock()
        self._auto = bool(auto)

        self._round_cbs = []
        self._scene_cbs = []
        self._last_round = None
        self._last_scene = None
        self._scene = None
        self._scene_at = 0.0
        self._hooks_on = False

    # ---------- 连接 ----------

    def host(self):
        """和游戏通信的通道（惰性创建）。"""
        if self._host is None:
            self._host = Host(addon_name=self.owner, hooks=[], texts=[])
        return self._host

    def start(self, menu=()):
        """开始等游戏 / 注入 / 跟踪场景。调一次就行，重复调无副作用。"""
        if self._service is not None:
            return self
        self._service = Service(
            addon_name=self.owner,
            name=self.owner,
            sync=self._push,
            auto=(lambda: self._auto) if self._auto else None,
            menu=tuple(menu),
        )
        self._service.start()
        self._thread = threading.Thread(
            target=self._pump, daemon=True, name=f'{self.owner}-live')
        self._thread.start()
        return self

    def close(self):
        """收尾：停线程、栈掉 Service。插件卸载时自动调。"""
        self._stop.set()
        if self._service is not None:
            try:
                self._service.stop()
            except Exception:  # noqa: BLE001
                pass
            self._service = None

    def status(self):
        """宿主状态（``hooked`` / ``status_text`` / ``log_tail`` 这些）。"""
        if self._service is None:
            return self.host().status()
        return self._service.status()

    def describe(self):
        """一行中文状态，直接打日志用。"""
        st = self.status()
        if self._service is not None:
            return self._service.describe(st)
        return self.host().status_line(st)

    # ---------- 数据 ----------

    def scene(self, timeout=1.0):
        """当前场景。

        返回 ``{'value': 1, 'name': '战斗', 'time_scale': 1.0, 'entries': 1}``。
        拿不到时 ``value`` 是 ``None``。
        """
        host = self.host()
        out = {'value': None, 'name': '未知', 'time_scale': None, 'entries': None}
        try:
            raw = objects.scene_full(host, objects.SLOT_SCENE, timeout=timeout)
        except Exception:  # noqa: BLE001
            raw = None
        if isinstance(raw, dict) and raw:
            value = raw.get('scene')
            out['value'] = value
            out['name'] = SCENES.get(value, f'未知({value})') if value is not None else '未知'
            out['time_scale'] = raw.get('time_scale')
            out['entries'] = raw.get('scene_entries')
        return out

    def battle(self, timeout=1.0):
        """当前战斗的全场快照；不在战斗里（或拿不到管理器）返回 ``None``。"""
        host = self.host()
        try:
            acc = objects.access(host)
        except Exception:  # noqa: BLE001
            return None
        try:
            live_count = objects.count(host, objects.SLOT_MANAGER)
        except Exception:  # noqa: BLE001
            live_count = 0
        if live_count <= 0:
            # 单例还没拿到：试一次静态调用，成功就继续
            try:
                acc.manager(timeout=timeout)
                live_count = objects.count(host, objects.SLOT_MANAGER)
            except Exception:  # noqa: BLE001
                return None
        if live_count <= 0:
            return None
        try:
            units = objects.units(host, objects.SLOT_MANAGER, acc=acc)
        except Exception:  # noqa: BLE001
            return None
        if not units:
            return None
        value = self.scene(timeout=timeout).get('value')
        return Battle(self, value if value is not None else -1, units)

    def units(self, limit=None):
        """全场单位列表（不在战斗里返回空列表）。"""
        battle = self.battle()
        if battle is None:
            return []
        units = battle.units
        return units[:limit] if limit else units

    def count(self):
        """场上单位数。"""
        return len(self.units())

    def unit(self, id=None, identity=None, index=None):
        """按编号 / 人格 ID / 序号找一个单位，找不到返回 ``None``。

        ::

            game.unit(id=1)            # 界面上编号 1 的那个
            game.unit(identity=10115)  # 浮士德-魁首
            game.unit(index=0)         # 字典里第 0 个
        """
        if index is not None:
            units = self.units()
            index = int(index)
            return units[index] if 0 <= index < len(units) else None
        battle = self.battle()
        if battle is None:
            return None
        if id is not None:
            return battle.by_id(id)
        if identity is not None:
            return battle.by_identity(identity)
        return None

    def player(self):
        """我方第一个单位（通常就是主角位）。"""
        for u in self.units():
            if u.get_pro('_position', 0) == 1:
                return u
        units = self.units()
        return units[0] if units else None

    # ---------- 动作 ----------

    def popup(self, text, timeout=2.0, wait=True, wait_timeout=120.0):
        """让游戏弹一句原版弹窗。

        ``wait=True``（默认）会先等宿主挂上再弹，所以直接写
        ``game.popup('你好')`` 就行，不用自己判断游戏起来没有。
        游戏根本没开时最多等 ``wait_timeout`` 秒，然后返回失败原因。
        """
        if wait:
            deadline = time.time() + float(wait_timeout)
            while time.time() < deadline:
                st = self.status()
                if st.get('hooked'):
                    time.sleep(0.5)      # 等游戏主循环稳一下，别卡在加载画面
                    break
                if not st.get('ready'):
                    try:
                        self.start()     # 没连接就先把「等游戏 + 注入」跑起来
                    except Exception:    # noqa: BLE001
                        pass
                time.sleep(0.2)
        return self.host().popup(text, timeout=timeout)

    def log(self, message):
        """带插件名的日志。"""
        log(message, prefix=f'[{self.owner}]')

    # ---------- 回调 ----------

    def on_round_start(self, handler):
        """每回合开始时调 ``handler(battle)``。

        用的是 ``BattleObjectManager.OnRoundStart_Model`` —— 一回合一次，
        频率低，随便你在这里做什么。回调跑在独立线程上，``time.sleep`` 安全。
        """
        self._round_cbs.append(handler)
        self._ensure_hooks()
        return handler

    def on_scene_changed(self, handler):
        """场景切换时调 ``handler(scene)``，参数同 :meth:`scene`。"""
        self._scene_cbs.append(handler)
        self.start()
        return handler

    def on_battle_start(self, handler):
        """进入战斗场景时调 ``handler(battle)``（等价于过滤后的场景回调）。"""
        def _cb(scene):
            if scene.get('value') == 1:
                battle = self.battle()
                if battle is not None:
                    handler(battle)
        self.on_scene_changed(_cb)
        return handler

    def on_battle_end(self, handler):
        """离开战斗场景时调 ``handler(scene)``。"""
        def _cb(scene):
            if scene.get('value') != 1:
                handler(scene)
        self.on_scene_changed(_cb)
        return handler

    # ---------- 内部 ----------

    def _live_hooks(self):
        """门面自己要用的钩子：只有一条「回合开始」。"""
        return [{
            'klass': 'BattleObjectManager',
            'method': 'OnRoundStart_Model',
            'argc': 1,
            'actions': 0,
            'cache': (0, objects.SLOT_MANAGER),
        }]

    def _push(self):
        host = self.host()
        hooks = self._live_hooks() if self._hooks_on else []
        host.configure(hooks=hooks, texts=[])
        return host.push(True) not in ('共享内存不可用',)

    def _ensure_hooks(self):
        if self._hooks_on:
            return
        self._hooks_on = True
        self.start()
        try:
            self._push()
        except Exception as exc:  # noqa: BLE001
            log(f'回合钩子写入失败：{exc}', prefix=f'[{self.owner}]')

    def _pump(self):
        """后台循环：心跳 + 回合命中 + 场景变化。"""
        host = self.host()
        last_round = None
        last_scene = None
        while not self._stop.is_set():
            try:
                host.beat()
                if self._round_cbs:
                    hits = host.hits(method='OnRoundStart_Model')
                    if last_round is None:
                        last_round = hits
                    elif hits > last_round:
                        last_round = hits
                        battle = self.battle()
                        if battle is not None:
                            for cb in list(self._round_cbs):
                                self._safe(cb, battle)
                    elif hits < last_round:
                        last_round = hits
                if self._scene_cbs:
                    scene = self.scene()
                    if last_scene is None:
                        last_scene = scene.get('value')
                    elif scene.get('value') != last_scene:
                        last_scene = scene.get('value')
                        for cb in list(self._scene_cbs):
                            self._safe(cb, scene)
            except Exception:  # noqa: BLE001
                pass
            if self._stop.wait(0.25):
                break

    def _safe(self, handler, argument):
        try:
            handler(argument)
        except Exception as exc:  # noqa: BLE001
            log(f'回调出错：{exc}', prefix=f'[{self.owner}]')


def live(owner=None, host=None):
    """按插件名取（或建）一个 ``Live``。"""
    key = owner or _owner_of_caller() or 'plugin'
    inst = _LIVES.get(key)
    if inst is None:
        inst = Live(key, host=host)
        _LIVES[key] = inst
    return inst


def close_all():
    """停掉所有门面实例（插件卸载时由 WarpHook 调）。"""
    for inst in list(_LIVES.values()):
        try:
            inst.close()
        except Exception:  # noqa: BLE001
            pass
    _LIVES.clear()


# ========== 模块级转发：插件写 warp.game.units() 就够 ==========

def start(menu=()):
    """开始等游戏 / 注入。第一次真正需要连接时自动调，也可以自己先调。"""
    return live().start(menu=menu)


def status():
    """宿主状态字典。"""
    return live().status()


def describe():
    """一行中文状态。"""
    return live().describe()


def popup(text, timeout=2.0, wait=True, wait_timeout=120.0):
    """让游戏弹一句原版弹窗（会自动等游戏起来、自动注入）。"""
    return live().popup(text, timeout=timeout, wait=wait, wait_timeout=wait_timeout)


def scene(timeout=1.0):
    """当前场景：``{'value','name','time_scale','entries'}``。"""
    return live().scene(timeout=timeout)


def battle(timeout=1.0):
    """当前战斗快照（``Battle``），不在战斗里返回 ``None``。"""
    return live().battle(timeout=timeout)


def units(limit=None):
    """全场单位列表（``Unit`` 列表）。"""
    return live().units(limit=limit)


def count():
    """场上单位数。"""
    return live().count()


def unit(id=None, identity=None, index=None):
    """找一个单位：按编号 / 人格 ID / 序号。"""
    return live().unit(id=id, identity=identity, index=index)


def player():
    """我方第一个单位。"""
    return live().player()


def on_round_start(handler):
    """每回合开始调 ``handler(battle)``。"""
    return live().on_round_start(handler)


def on_scene_changed(handler):
    """场景切换调 ``handler(scene)``。"""
    return live().on_scene_changed(handler)


def on_battle_start(handler):
    """进入战斗调 ``handler(battle)``。"""
    return live().on_battle_start(handler)


def on_battle_end(handler):
    """离开战斗调 ``handler(scene)``。"""
    return live().on_battle_end(handler)


def close():
    """收尾（插件卸载时自动调，一般不用管）。"""
    return live().close()
