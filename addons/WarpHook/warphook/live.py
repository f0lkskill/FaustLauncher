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

from . import audio, fields, objects
from .base import log
from .host import Host, _owner_of_caller, command_quiet
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
        self._extra_hooks = []
        self._last_round = None
        self._round_pending = False
        self._round_retry_at = 0.0
        self._round_backoff = 0.25
        self._last_scene = None
        self._scene = None
        self._scene_at = 0.0
        self._scene_retry_at = 0.0
        self._scene_backoff = 0.5
        self._hooks_on = False
        self._pushed_ok = False

    # ---------- 连接 ----------

    def host(self):
        """和游戏通信的通道（惰性创建）。"""
        if self._host is None:
            self._host = Host(addon_name=self.owner, hooks=[], texts=[])
        return self._host

    def start(self, menu=()):
        """开始等游戏 / 注入 / 跟踪场景。调一次就行，重复调无副作用。"""
        self._stop.clear()   # close() 过的实例可复活（防御：_LIVES 除名是主修）
        if self._service is not None:
            return self
        self._service = Service(
            addon_name=self.owner,
            name=self.owner,
            host=self.host(),
            sync=self._push,
            auto=(lambda: self._auto) if self._auto else None,
            menu=tuple(menu),
        )
        self._service.start()
        self.host().bind_owner(self.owner)
        self._thread = threading.Thread(
            target=self._pump, daemon=True, name=f'{self.owner}-live')
        self._thread.start()
        return self

    def close(self):
        """收尾：停线程、栈掉 Service。插件卸载时自动调。

        必须 join：卸载流程紧接着就会解除共享内存映射（``registry.on_unload``
        最后那段），线程若还活着，下一轮 ``host.beat()`` 就会读到已释放的内存 ——
        那是进程级 AV，没有 traceback，整个启动器直接消失。
        """
        self._stop.set()
        # Host 是所有插件共享的，单个 Live 卸载不能 close() 全局宿主。
        # 映射只在 registry.on_unload 确认线程退出后统一释放。
        thread = self._thread
        if (thread is not None and thread.is_alive()
                and thread is not threading.current_thread()):
            thread.join(timeout=5.0)
        if thread is not None and thread.is_alive():
            log('停止监听超时：保留线程引用及共享映射，避免在途访问失效',
                prefix=f'[{self.owner}]')
            return False
        self._thread = None
        if self._service is not None:
            try:
                if self._service.stop() is False:
                    return False
            except Exception:  # noqa: BLE001
                import traceback
                log(f'[{self.owner}] 停止 Service 异常，保留引用和共享映射\n{traceback.format_exc()}')
                return False
            self._service = None
        # 从单例缓存里除名：插件重载后 ``live()`` 必须给全新实例。
        # 不除名的后果（0.9.27 真机教训）：重载拿到旧实例，``_stop`` 还是
        # set 状态，``_pump`` 起来第一轮就退出 —— 不补装钩子、不读命中、
        # 所有回调全哑，而注入/同步调用（battle/scene）照常工作，
        # 日志只留下「等待游戏加载」一条，看起来像装死。
        if _LIVES.get(self.owner) is self:
            _LIVES.pop(self.owner, None)
        return True

    def status(self):
        """宿主状态（``hooked`` / ``status_text`` / ``log_tail`` 这些）。"""
        if self._service is None:
            return self.host().status(owner=self.owner)
        return self._service.status()

    def describe(self):
        """一行中文状态，直接打日志用。"""
        st = self.status()
        if self._service is not None:
            return self._service.describe(st)
        return self.host().status_line(st)

    def inject(self, wait=False):
        """手动注入游戏（右键菜单「注入」用；游戏已在跑则直接连接）。"""
        if self._service is None:
            self.start()
        return self._service.inject_now(wait=wait)

    # ---------- 数据 ----------

    def scene(self, timeout=1.0):
        """当前场景。

        返回 ``{'value': 1, 'name': '战斗', 'time_scale': 1.0, 'entries': 1}``。
        拿不到时 ``value`` 是 ``None``。
        """
        host = self.host()
        out = {'value': None, 'name': '未知', 'time_scale': None, 'entries': None}
        # 多个调用者共用一次采样；未知/失败不拿旧场景冒充新状态。
        with self._lock:
            now = time.monotonic()
            if now < self._scene_retry_at:
                return dict(self._scene) if self._scene is not None else out
            self._scene = None
            try:
                ready = (self._service.object_read_ready(objects.SLOT_SCENE)
                         if self._service is not None else
                         Service._object_read_ready(host, objects.SLOT_SCENE))
                if not ready:
                    return out
                # scene_full 会扫描全部字段；这里只读公开接口需要的三个，
                # 任一失败立即停止，避免同一轮剩余字段不断撞 busy/timeout。
                for key, field in (('value', 'sceneState'),
                                   ('time_scale', '_currentTimeScale'),
                                   ('entries', '_mainSceneEntryCount')):
                    spec = fields.read_chain('GlobalGameManager', field)
                    result = host.read(objects.SLOT_SCENE, spec['off'],
                                       kind=spec['kind'], timeout=timeout, detail=True)
                    if not result.get('ok'):
                        return {'value': None, 'name': '未知',
                                'time_scale': None, 'entries': None}
                    out[key] = result['value']
                value = out['value']
                out['name'] = SCENES.get(value, f'未知({value})')
                self._scene = dict(out)
                self._scene_at = now
                self._scene_backoff = 0.5
                self._scene_retry_at = now + 0.5
                return out
            finally:
                if self._scene is None:
                    self._scene_retry_at = time.monotonic() + self._scene_backoff
                    self._scene_backoff = min(10.0, self._scene_backoff * 2.0)

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

    def wait_ready(self, wait_timeout=120.0):
        """等宿主挂上（``hooked``）。返回是否就绪；游戏没开最多等 ``wait_timeout`` 秒。"""
        st = self.status()
        if st.get('hooked'):
            return True
        deadline = time.time() + float(wait_timeout)
        while time.time() < deadline:
            if not st.get('ready'):
                try:
                    self.start()     # 没连接就先把「等游戏 + 注入」跑起来
                except Exception:    # noqa: BLE001
                    pass
            time.sleep(0.2)
            st = self.status()
            if st.get('hooked'):
                time.sleep(0.5)      # 等游戏主循环稳一下，别卡在加载画面
                return True
        return False

    def popup(self, text, timeout=2.0, wait=True, wait_timeout=120.0):
        """让游戏弹一句原版弹窗。

        ``wait=True``（默认）会先等宿主挂上再弹，所以直接写
        ``game.popup('你好')`` 就行，不用自己判断游戏起来没有。
        游戏根本没开时最多等 ``wait_timeout`` 秒，然后返回失败原因。
        """
        if wait:
            self.wait_ready(wait_timeout)
        return self.host().popup(text, timeout=timeout)

    # ---------- 声音 ----------

    def bgm(self, name, bank=None, stop_current=True, wait=True,
            wait_timeout=120.0, timeout=2.0):
        """放一首战斗 BGM：``game.bgm('Battle_Cp9_Boss_10')``。

        名字收短名（``Battle_Cp9_Boss_10``）或完整路径
        （``event:/BGM/Battle/Battle_Cp9_Boss_10``）。
        别的关卡的曲**不在当前已加载的音库里**，要传 ``bank``
        （``game.bgm('Battle_Cp9_Boss_10', bank='BGM_Default_S7_3')``），
        否则 ``StartAddBGM`` 会静默失败。
        返回 ``{'ok', 'name', 'path', 'reason'}``。
        """
        if wait:
            self.wait_ready(wait_timeout)
        return audio.play(self.host(), name, bank=bank,
                          stop_current=stop_current, timeout=timeout)

    def bgm_stop(self, restore=True, timeout=2.0):
        """停掉插件放的附加曲，``restore=True`` 时接回游戏原曲。"""
        return audio.stop(self.host(), restore=restore, timeout=timeout)

    def bgm_playing(self, timeout=2.0):
        """游戏认为战斗曲在响吗。"""
        return audio.is_playing(self.host(), timeout=timeout)

    def bgm_index(self, timeout=2.0):
        """当前战斗曲的编号（``-1`` = 没在放）。"""
        return audio.current_index(self.host(), timeout=timeout)

    def bgm_lock_install(self):
        """装换曲锁钩子（并进门面钩子表，与回合钩子一次 push 共存）。

        锁的原理见 :func:`warphook.audio.guard_hook_defs`：拦住游戏回合
        结束的「盖回默认曲」，让插件放的曲子不中断、不重播。钩子表按
        owner 分段、configure 全量重写 —— 锁钩子必须和回合钩子**合并
        push**，独立 push 会把回合钩子清掉（回调从此失联）。
        """
        defs = audio.guard_hook_defs()
        have = {(h.get('klass'), h.get('method')) for h in self._extra_hooks}
        added = 0
        for item in defs:
            key = (item['klass'], item['method'])
            if key not in have:
                self._extra_hooks.append(item)
                added += 1
        self._hooks_on = True
        ok = self._push()
        audio.lock(self.host(), True)          # 初始放行
        status = audio.guard_status(self.host(), owner=self.owner)
        # 辅段由所有插件共享；push 成功不代表四个锁入口都分到了槽。
        return {'ok': bool(ok) and not status['missing'], 'added': added,
                'missing': status['missing'], 'configured': status['configured'],
                'installed_verified': False}

    def bgm_lock_status(self):
        """只读锁入口、guard 与实际命中/拦截计数。"""
        return audio.guard_status(self.host(), owner=self.owner)

    def bgm_lock(self, allow):
        """开/关换曲锁。``True`` 放行游戏换曲；``False`` 锁死，游戏盖不回去。

        **放曲前必须先解锁**（``bgm_lock(True)``），否则放曲的两个直调
        会撞上自己的锁。
        """
        return audio.lock(self.host(), allow)

    def bgm_hook(self, name, method='StartAddBGM', push=True):
        """让游戏自己放我们的曲子：改写它起附加曲时传的曲名。

        ``game.bgm('X')`` 是插件自己发调用；这个方法反过来 —— 游戏每次起附
        加曲都会经过 ``StartAddBGM``，我们把它的曲名参数换成 ``X``，于是整条
        播放流程都由游戏自己走，插件一次 invoke 都不用发。
        **要在它被调用之前装。**
        """
        short = audio.short_name(name)
        if not short:
            return {'ok': False, 'name': '', 'reason': '名字是空的'}
        host = self.host()
        made = host.make_str(short, slot=audio.SLOT_BATTLE_BGM)
        if isinstance(made, str) and made != '已执行':
            return {'ok': False, 'name': short, 'reason': made}
        entry = {
            'klass': 'BattleSoundGenerator',
            'method': method,
            'argc': 3 if method == 'StartAddBGM' else 1,
            'rewrite': (1, audio.SLOT_BATTLE_BGM),
        }
        self._extra_hooks = [h for h in self._extra_hooks
                             if not (h.get('klass') == entry['klass']
                                     and h.get('method') == entry['method'])]
        self._extra_hooks.append(entry)
        if push:
            self._hooks_on = True
            self._push()
        return {'ok': True, 'name': short, 'reason': ''}

    def bgm_unhook(self, push=True):
        """撤掉 :meth:`bgm_hook` 装的改写钩子。"""
        kept = [h for h in self._extra_hooks
                if not h.get('rewrite')]
        removed = len(self._extra_hooks) - len(kept)
        self._extra_hooks = kept
        if push:
            self._push()
        self.host().release(audio.SLOT_BATTLE_BGM)
        return {'ok': True, 'removed': removed}

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
        """门面钩子表：回合钩子 + 换曲锁钩子，**永远一体**。

        回合钩子带 ``event``（→ actions|EVENT）：事件动作才会把 self
        （BattleObjectManager 实例）落进 SLOT_MANAGER，``battle()`` 就有现成
        指针可用。裸 ``actions=0`` 只数命中不落槽，``battle()`` 只好去调
        ``get_Instance`` —— 那是泛型共享方法，直调必 AV（0.9.25 定案）。

        锁钩子（audio.guard_hook_defs）不再等 bgm_lock_install 惰性追加：
        钩子表按 owner 分段、configure 全量重写，任何一次「只含回合钩子」
        的 push 都会把锁清掉（0.9.27 真机实证 28..31 变空）—— 干脆每次
        push 都是完整集，辅段 5 格 = 回合 1 + 锁 4（仍与其他辅助插件共享）。
        """
        hooks = [{
            'klass': 'BattleObjectManager',
            'method': 'OnRoundStart_Model',
            'argc': 1,
            'actions': 0,
            'event': 30,
            'cache': (0, objects.SLOT_MANAGER),
        }]
        hooks.extend(self._extra_hooks)
        known = {(h.get('klass'), h.get('method')) for h in hooks}
        for item in audio.guard_hook_defs():
            if (item['klass'], item['method']) not in known:
                hooks.append(item)
        return hooks

    def _push(self):
        host = self.host()
        hooks = self._live_hooks() if self._hooks_on else []
        def push_owned():
            host.configure(hooks=hooks, texts=[])
            return host.push(True)
        message = host._act(self.owner, push_owned)
        ok = message not in ('共享内存不可用',)
        self._pushed_ok = bool(ok)
        return self._pushed_ok

    def _ensure_hooks(self):
        if self._hooks_on:
            return
        self._hooks_on = True
        self.start()
        # 注册发生在插件 scr.py 的同步 exec 中。Host.push/block 会解析导出表，
        # 绝不能在这里连接游戏或扫描 GameAssembly；Service 后台就绪时统一推送。
        self._pushed_ok = False

    def _poll_round(self):
        """只由真实命中建立待投递；多次命中合并成最新的一份战斗快照。

        计数可能因重连/重配归零，不能一直拿旧高水位比较。首次非零也代表
        已命中，而非应丢弃的 baseline。快照失败不消费事件，只有失败退避；
        正常命中立即尝试，不额外 sleep，也不按周期伪造业务回调。
        """
        if not self._round_cbs or self._stop.is_set():
            return False
        hits = self.host().hits(method='OnRoundStart_Model', owner=self.owner)
        previous = self._last_round
        self._last_round = hits
        if hits > (previous if previous is not None else 0) or (
                previous is not None and hits < previous and hits > 0):
            self._round_pending = True
            log(f'回合命中 owner={self.owner} hits={previous}->{hits} '
                f'callbacks={len(self._round_cbs)}', prefix=f'[{self.owner}]')
        if (not self._round_pending or self._stop.is_set()
                or time.monotonic() < self._round_retry_at):
            return False
        battle = None
        try:
            battle = self.battle()
        finally:
            if battle is None:
                self._round_retry_at = time.monotonic() + self._round_backoff
                self._round_backoff = min(4.0, self._round_backoff * 2.0)
        if battle is None:
            log('回合已命中但战斗快照不可用（保留待重试，未调用业务回调）',
                prefix=f'[{self.owner}]')
            return False
        if self._stop.is_set():
            return False
        for cb in list(self._round_cbs):
            if self._stop.is_set():
                return False
            self._safe(cb, battle)
        self._round_pending = False
        self._round_retry_at = 0.0
        self._round_backoff = 0.25
        return True

    def _pump(self):
        """后台循环：心跳 + 回合命中 + 场景变化。"""
        host = self.host()
        last_scene = None
        next_error = 0.0
        while not self._stop.is_set():
            # beat/status/hits 都可能经 Host.block 初始化共享内存并解析导出。
            # 在 Service 确认 GameAssembly、同步并注入前不要抢跑（更不能阻塞重载）。
            if (self._service is None
                    or self._service._phase != 'monitoring'):
                if self._stop.wait(0.25):
                    break
                continue
            try:
                host.beat()
                # 后台连接完成后补装，直到成功
                if self._hooks_on and not self._pushed_ok:
                    if self._push():
                        log('回合钩子配置已写入（是否安装成功请看宿主状态）',
                            prefix=f'[{self.owner}]')
                self._poll_round()
                if self._scene_cbs and not command_quiet():
                    # 场景是高频轮询：读命令一来一回要一两秒，照着 0.25s
                    # 的节奏硬发会把命令通道占满，弹窗这类必须成功的命令
                    # 就永远等不到空档。通道忙或有弹窗在等，这一拍就跳过。
                    if host.channel_busy():
                        pass
                    else:
                        scene = self.scene()
                        if scene.get('value') is None:
                            pass  # 加载/通道忙不是离开战斗，不派发虚假的场景变化。
                        elif last_scene is None:
                            last_scene = scene.get('value')
                        elif scene.get('value') != last_scene:
                            last_scene = scene.get('value')
                            for cb in list(self._scene_cbs):
                                self._safe(cb, scene)
            except Exception:  # noqa: BLE001
                import traceback
                now = time.monotonic()
                if now >= next_error:
                    next_error = now + 10.0
                    log(f'实时监听异常（继续重试）owner={self.owner}\n'
                        f'{traceback.format_exc()}', prefix=f'[{self.owner}]')
            if self._stop.wait(0.25):
                break

    def _safe(self, handler, argument):
        try:
            handler(argument)
        except Exception:  # noqa: BLE001
            import traceback
            log(f'回调出错 handler={getattr(handler, "__qualname__", repr(handler))}\n'
                f'{traceback.format_exc()}', prefix=f'[{self.owner}]')


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
    ok = True
    for inst in list(_LIVES.values()):
        try:
            if inst.close() is False:
                ok = False
        except Exception:  # noqa: BLE001
            import traceback
            log(f'关闭实时监听失败\n{traceback.format_exc()}')
            ok = False
    return ok


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


def bgm(name, bank=None, stop_current=True, wait=True, wait_timeout=120.0,
        timeout=2.0):
    """放一首战斗 BGM：``game.bgm('Battle_Cp9_Boss_10', bank='BGM_Default_S7_3')``。"""
    return live().bgm(name, bank=bank, stop_current=stop_current, wait=wait,
                      wait_timeout=wait_timeout, timeout=timeout)


def bgm_stop(restore=True, timeout=2.0):
    """停掉插件放的附加曲，默认接回游戏原曲。"""
    return live().bgm_stop(restore=restore, timeout=timeout)


def bgm_playing(timeout=2.0):
    """游戏认为战斗曲在响吗。"""
    return live().bgm_playing(timeout=timeout)


def bgm_index(timeout=2.0):
    """当前战斗曲编号（``-1`` = 没在放）。"""
    return live().bgm_index(timeout=timeout)


def bgm_hook(name, push=True):
    """让游戏自己放我们的曲子：``game.bgm_hook('Battle_Cp9_Boss_10')``。"""
    return live().bgm_hook(name, push=push)


def bgm_unhook(push=True):
    """撤掉 ``game.bgm_hook`` 装的改写钩子。"""
    return live().bgm_unhook(push=push)


def bgm_lock_install():
    """装换曲锁钩子（每插件一次；宿主自动 late 重试）。"""
    return live().bgm_lock_install()


def bgm_lock_status():
    """只读当前插件锁配置及命中/拦截计数。"""
    return live().bgm_lock_status()


def bgm_lock(allow):
    """开/关换曲锁：``True`` 放行游戏换曲；``False`` 锁死。"""
    return live().bgm_lock(allow)


def inject(wait=False):
    """手动注入游戏（托盘/插件菜单「注入游戏」用）。"""
    return live().inject(wait=wait)


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
