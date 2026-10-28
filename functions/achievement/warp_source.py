# -*- coding: utf-8 -*-
"""用 WarpHook 取代 `hook_dll/battle_watch.dll`，给成就系统供事件。

## 为什么要有这一层

老链路 `battle_watch.dll` 里四十个钩子槽 × 十六种读法 = 六百多个手写 thunk，
每种读法还各自 `_snprintf` 出一种文本行（`VAL tag=... hp=...`），再由
`BattleWatch.handle_line()` 解析回 Python 对象。规则引擎（2756 行）只认这些行。

WarpHook 把「挂钩子 + 按路径读内存」变成了配置，于是这一层要做的只剩翻译：
**把 WarpHook 的八格事件，还原成老 DLL 会发的那种文本行**。规则引擎一行都不用改。

## 分工

* `battle_watch.py` 仍然是成就规则的唯一实现（什么时候算过、写哪条成就）；
* `warp_reads.py` 负责「一种读法对应哪几条读取链」；
* 本文件负责「挂哪些钩子、事件怎么变成行」。三者的边界不重叠。

## 为什么不一次接完

十六种读法里有九种要读**函数返回值**、**容器内容**或**字符串**，读取链表达不了
（见 `warp_reads.py` 的边界说明）。第一批先接 unit 系与回合边界 —— 血量、理智、
速度、回合数是战斗成就的绝大多数，先把这条链跑通再谈剩下的。
"""
from __future__ import annotations

import threading
import time

from functions.achievement import battle_watch as BW
from functions.achievement import warp_reads as WR

#: 第一批挂的钩子：名字取自 `battle_watch.FALLBACK_HOOKS`。
#: unit 系发 SPD + VAL，plain 系发 RND。
FIRST_BATCH = (
    'unit_refresh_speed',
    'unit_set_random_speed',
    'unit_set_speed',
    'unit_get_origin_speed',
    'unit_round_start',
    'manager_init',
    'action_on_end_turn',
    'action_done_with_action',
    'skv_start',
    'skv_complete',
    'skv_end',
    'node_cleared',
    'node_clear_state',
)

#: 钩子的真实参数个数（**不含 this**）。
#: `KIND_SIGNATURES` 里那个数是「老 thunk 从寄存器里取几个格子」，和
#: `class_get_method_from_name` 要的参数个数不是一回事 —— 对不上就
#: `method not found`，一个钩子都装不上。这里按 dump.cs 的实际签名写死。
ARGC_OVERRIDE = {
    'action_on_end_turn': 3,        # OnEndTurn(action, timing, info)
    'action_done_with_action': 2,   # DoneWithAction(action, timing)
    'skv_start': 0,                 # Skill_Start()
    'skv_complete': 0,              # Skill_Complete()
    'skv_end': 0,                   # Skill_End()
    'node_cleared': 3,              # IsNodeCleared(mainchapter, subchapter, node)
    'node_clear_state': 3,          # GetClearNodeState(mainchapter, subchapter, node)
}

#: 行动类钩子读 action 对象，发 ACT 行。
ACTION_KINDS = (WR.KIND_ACTION_INT,)

#: 这些读法用八格 + 两行就能还原成老链路的语义。
UNIT_KINDS = (WR.KIND_UNIT, WR.KIND_UNIT_INT_BOOL, WR.KIND_UNIT_GET_INT)
#: SKV 读法发的是 `RND tag=... iid=...`（技能动画在演哪个单位），
#: 与 plain 同一行格式，所以并进一组。
PLAIN_KINDS = (WR.KIND_PLAIN, WR.KIND_SKV)

#: 节点通关查询：三个值类型参数直接当结果，发 `NCL main=.. sub=.. node=..`。
NODE_KINDS = (WR.KIND_NODE_STATE,)

#: 事件号从 1 开始（0 会被 DLL 当成「没填」而退回钩子下标）。
EVENT_ID_BASE = 1


def default_offsets():
    """老链路的默认偏移表 —— 键名比 `BWConfig` 少了 `off_` 前缀。"""
    return dict(BW.FALLBACK_FIELDS)


def build_hooks(names=None, offsets=None):
    """把选中的老钩子翻译成 `Host.hook()` / 钩子 dict 能吃的形状。

    Args:
        names: 钩子名序列，默认 :data:`FIRST_BATCH`。
        offsets: 字段偏移表，默认 :func:`default_offsets`。

    Returns:
        钩子 dict 列表，每项含 `klass/method/argc/event/reads/dedupe` 与
        `name`（老钩子名，翻译行时用它当 `tag`）。
    """
    names = tuple(names or FIRST_BATCH)
    offsets = offsets if offsets is not None else default_offsets()
    hooks = []
    for index, name in enumerate(names):
        entry = BW.FALLBACK_HOOKS.get(name)
        if entry is None:
            raise KeyError('老链路里没有这个钩子：%s' % name)
        target, _rva, kind = entry
        klass, _, method = target.partition('::')
        if not method:
            raise ValueError('钩子名不是 类::方法 的形状：%s' % target)
        spec = WR.hook_spec(kind, klass, method, offsets=offsets)
        hook = {
            'name': name,
            'klass': spec['klass'],
            'method': spec['method'],
            'argc': ARGC_OVERRIDE.get(name, spec['argc']),
            'reads': spec['reads'],
            'event': EVENT_ID_BASE + index,
            'kind': kind,
            # unit 钩子在 RefreshSpeed/SetSpeed 这类方法上会被频繁调用，
            # 值没变就没必要让规则引擎重算一遍（血量不动时一轮能省几百条）
            'dedupe': bool(spec['reads']),
        }
        hooks.append(hook)
    return hooks


def action_lines(tag, ev):
    """一个 action 事件还原成 ACT 行。

    老 DLL 里这一行有七个字段，我们能从 action → skill → data 摸到其中四个：
    出手者、指令者、技能 id、层级。`slot` / `tf` / `aoid` 要先读 coin 与 attacker，
    读取链够不着，先给 -1 —— 规则引擎对缺字段本来就是按 -1 处理的。
    """
    return [
        'ACT tag=%s actor=%d cmd=%d skid=%d slot=-1 tier=%d tf=-1 aoid=%d'
        % (tag, int(ev.get('e', -1)), int(ev.get('f', -1)),
           int(ev.get('a', -1)), int(ev.get('b', -1)), int(ev.get('e', -1))),
    ]


def _speed_int(raw):
    """速度定点数 → 整数速度。与 `battle_watch.speed_int` 同一套规矩。"""
    raw = int(raw)
    if raw < 0:
        return -1
    return raw // BW.SPEED_SCALE


def unit_lines(tag, ev):
    """一个 unit 事件还原成 SPD + VAL 两行（顺序与老 DLL 一致：先速度后血量）。"""
    iid = int(ev.get('a', 0))
    oid = int(ev.get('b', 0))
    hp = int(ev.get('c', 0))
    max_hp = int(ev.get('d', 0))
    mp = int(ev.get('e', 0))
    os_raw = int(ev.get('f', 0))
    ow_raw = int(ev.get('g', 0))
    its = int(ev.get('h', 0))
    return [
        'SPD tag=%s iid=%d oid=%d os=%d osi=%d ow=%d owi=%d its=%d'
        % (tag, iid, oid, os_raw, _speed_int(os_raw), ow_raw, _speed_int(ow_raw), its),
        'VAL tag=%s iid=%d oid=%d hp=%d mhp=%d mp=%d'
        % (tag, iid, oid, hp, max_hp, mp),
    ]


def node_lines(tag, ev):
    """关卡节点状态查询还原成 NCL 行。

    老链路是 `int (self, int main, int sub, int node, mi)`，三个参数原样打印，
    `cleared=1` 表示「被问过一次」而不是「通关了」—— 是否通关要看游戏给的返回值，
    那个值在寄存器里，钩子读不到。所以只报「问过哪些节点」。
    """
    return [
        'NCL main=%d sub=%d node=%d cleared=1'
        % (int(ev.get('a', 0)), int(ev.get('b', 0)), int(ev.get('c', 0)))
    ]


def plain_lines(tag, ev):
    """plain 钩子（管理器的回合开始/初始化）发一行回合边界。"""
    iid = int(ev.get('a', 0))
    if iid > 0:
        return ['RND tag=%s iid=%d' % (tag, iid)]
    return ['RND tag=%s' % tag]


def event_lines(kind, tag, ev):
    """按读法把事件翻成文本行。认不出的读法返回空列表（第一批不接）。"""
    if kind in UNIT_KINDS:
        return unit_lines(tag, ev)
    if kind in ACTION_KINDS:
        return action_lines(tag, ev)
    if kind in PLAIN_KINDS:
        return plain_lines(tag, ev)
    if kind in NODE_KINDS:
        return node_lines(tag, ev)
    return []


class WarpSource:
    """把 WarpHook 的事件流翻译成 `BattleWatch.handle_line()` 认的行。

    用法::

        source = WarpSource(watch)
        if source.attach():          # 挂上钩子、注入、开始轮询
            source.join()

    对象内部只有一个线程：读事件、翻行、喂给规则引擎。规则引擎自己的锁负责
    串行化，所以这里不必再包一层。
    """

    def __init__(self, watch, names=None, offsets=None, poll_interval=0.1,
                 log=None):
        self.watch = watch
        self.names = tuple(names or FIRST_BATCH)
        self.offsets = offsets if offsets is not None else default_offsets()
        self.poll_interval = max(0.02, float(poll_interval))
        self._log = log or (lambda _m: None)
        self._host = None
        self._hooks = []
        self._by_event = {}
        self._thread = None
        self._stop = threading.Event()
        self.lines_in = 0
        self.events_out = 0

    # ---- 装配 ----------------------------------------------------------
    def host(self):
        """取 WarpHook 的 Host 工厂（插件没装就是 None）。

        必须用启动器实际在用的那个 ``AddonManager`` 实例 —— ``namespaces`` 是
        实例属性，随手 new 一个拿到的是空注册表。
        """
        from functions.extension.addon.addon_utils import current_manager
        manager = current_manager()
        namespaces = getattr(manager, 'namespaces', None) if manager else None
        if namespaces is None:
            return None
        try:
            space = namespaces['warp']
        except KeyError:
            return None
        return space.plugin.Host

    def attach(self):
        """挂钩子并把宿主 DLL 注进去。成功返回 True。"""
        factory = self.host()
        if factory is None:
            self._log('[成就] 没找到 WarpHook，成就钩子无处可挂')
            return False
        try:
            self._hooks = build_hooks(self.names, self.offsets)
        except (KeyError, ValueError) as exc:
            self._log('[成就] 钩子配置有问题：%s' % exc)
            return False
        self._by_event = {int(h['event']): h for h in self._hooks}
        payload = [dict(h) for h in self._hooks]
        for hook in payload:
            hook.pop('name', None)
            hook.pop('kind', None)
            hook['actions'] = 0x08          # HOST_ACT_EVENT：只要事件，不弹窗
        try:
            self._host = factory(addon_name='成就钩子', hooks=payload, texts=[])
        except Exception as exc:              # noqa: BLE001 —— 插件侧任何异常都别炸启动器
            self._log('[成就] 建 Host 失败：%s' % exc)
            return False
        try:
            self._host.push(True)
            if not self._host.status().get('hooked'):
                # 不等 —— 游戏大概率还没开，赢了才回。宿主自己会盯着进程列表，
                # 一看到游戏起来就注入，配置早写好了（先配置后注入是支持的）。
                self._host.inject_now(wait=False)
        except Exception as exc:              # noqa: BLE001
            self._log('[成就] 注入失败：%s' % exc)
            return False
        self._log('[成就] 已挂 %d 个钩子（WarpHook 引擎）' % len(self._hooks))
        return True

    # ---- 轮询 ----------------------------------------------------------
    def pump(self):
        """读一批事件，翻译成行喂给规则引擎。返回这轮喂了几行。"""
        if self._host is None:
            return 0
        try:
            events = self._host.events()
        except Exception as exc:              # noqa: BLE001
            self._log('[成就] 读事件失败：%s' % exc)
            return 0
        fed = 0
        for ev in events:
            hook = self._by_event.get(int(ev.get('id', -1)))
            if hook is None:
                continue
            self.events_out += 1
            for line in event_lines(hook['kind'], hook['name'], ev):
                try:
                    self.watch.handle_line(line)
                except Exception as exc:      # noqa: BLE001
                    self._log('[成就] 规则引擎吃不下这一行：%s（%s）' % (line, exc))
                    continue
                fed += 1
                self.lines_in += 1
        return fed

    def run(self, duration=None):
        """轮询直到 :meth:`stop`（或 `duration` 秒到）。"""
        deadline = None if duration is None else time.time() + float(duration)
        while not self._stop.is_set():
            self.pump()
            if deadline is not None and time.time() >= deadline:
                break
            self._stop.wait(self.poll_interval)

    def start(self):
        if self._thread and self._thread.is_alive():
            return True
        self._stop.clear()
        self._thread = threading.Thread(target=self.run, name='warp-source', daemon=True)
        self._thread.start()
        return True

    def stop(self):
        self._stop.set()

    def join(self, timeout=None):
        if self._thread:
            self._thread.join(timeout)

    @property
    def running(self):
        return bool(self._thread and self._thread.is_alive())

    def stats(self):
        return {
            'hooks': len(self._hooks),
            'events': self.events_out,
            'lines': self.lines_in,
            'lost': int(getattr(self._host, 'events_lost', 0)) if self._host else 0,
            'running': self.running,
        }
