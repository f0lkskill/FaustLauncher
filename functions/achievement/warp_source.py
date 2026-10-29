# -*- coding: utf-8 -*-
"""用 WarpHook 取代老链路 battle_watch.dll（P5 已下线），给成就系统供事件。

## 为什么要有这一层

老链路 `battle_watch.dll` 里四十个钩子槽 × 十六种读法 = 六百多个手写 thunk，
每种读法还各自 `_snprintf` 出一种文本行（`VAL tag=... hp=...`），再由
`BattleWatch.handle_line()` 解析回 Python 对象。规则引擎（2756 行）只认这些行。

WarpHook 把「挂钩子 + 按路径读内存」变成了配置，于是这一层要做的只剩翻译：
**把 WarpHook 的十二格事件，还原成老 DLL 会发的那种文本行**。规则引擎一行
都不用改。

## 分工

* `battle_watch.py` 仍然是成就规则的唯一实现（什么时候算过、写哪条成就）；
* `warp_reads.py` 负责「一种读法对应哪几条读取链」；
* 本文件负责「挂哪些钩子、事件怎么变成行」。三者的边界不重叠。

## 接入进度

v0.7 接了 unit 系与回合边界；v0.8 起返回值、值类型容器、字符串取数三个
原语进了宿主，老链路**全部事件钩子都已接入**（buff 链的 BUF 行除外 ——
buff 类成就走采样器路径，与 v0.7 行为一致）。
"""
from __future__ import annotations

import os
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
    'manager_on_round_start_before',
    'action_on_end_turn',
    'action_done_with_action',
    'skv_start',
    'skv_complete',
    'skv_end',
    'node_cleared',
    'node_clear_state',
    # ---- v0.8：老链路剩下的五种信号源，读取链 + 返回值 + 容器聚合到位后
    # 全部能以纯配置表达，一次接完（老链路至此没有未迁移的事件钩子）。
    'railway_total',
    'railway_node',
    'railway_hist',
    'stage_node_id',
    'railway_ui_text',
    'take_attack_dmg_multiplier',
    # 下面这些老链路里只缓存对象指针、不当场发事件（cache_self / cache_arg1）。
    # 挂上来是为了让对象槽里有值 —— 采样侧要用时能按偏移读存档结构，
    # 而不是留个「钩子根本没装」的空洞。
    'stage_clear_info',
    'stage_clear_query',
    'stage_clear_last',
    'node_cleared_short',
    'stage_progress',
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

#: damage 钩子一条事件同时还原 ACT + VAL 两行（十二格刚好装下）。
DAMAGE_KINDS = (WR.KIND_DAMAGE_ACTION,)

#: railway 系：每种一行格式，见 railway_lines()。
RAILWAY_KINDS = (
    WR.KIND_RAILWAY_TOTAL, WR.KIND_RAILWAY_NODE, WR.KIND_RAILWAY_HIST,
    WR.KIND_STAGE_NODE_ID, WR.KIND_RAILWAY_UI_TEXT,
)

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
    event_no = 0
    for name in names:
        entry = BW.FALLBACK_HOOKS.get(name)
        if entry is None:
            raise KeyError('老链路里没有这个钩子：%s' % name)
        target, _rva, kind = entry
        klass, _, method = target.partition('::')
        if not method:
            raise ValueError('钩子名不是 类::方法 的形状：%s' % target)
        spec = WR.hook_spec(kind, klass, method, offsets=offsets)
        cache = spec.get('cache')
        hook = {
            'name': name,
            'klass': spec['klass'],
            'method': spec['method'],
            'argc': ARGC_OVERRIDE.get(name, spec['argc']),
            'reads': spec['reads'],
            'kind': kind,
            # 只缓存对象的钩子不发事件（老链路里它们也不发）；事件号只发给
            # 真正要投递的钩子，免得号段里一堆空号。
            'event': None if cache else EVENT_ID_BASE + event_no,
            # unit 钩子在 RefreshSpeed/SetSpeed 这类方法上会被频繁调用，
            # 值没变就没必要让规则引擎重算一遍（血量不动时一轮能省几百条）
            'dedupe': bool(spec['reads']) and not cache,
        }
        # 「调用之后才有值」与「要读返回值」的钩子：when/ret_* 三件套
        # 透传给宿主（dict 配置路径与 hook() 关键字路径同一个默认表）。
        if spec.get('when'):
            hook['when'] = int(spec['when'])
        if spec.get('ret_kind'):
            hook['ret_kind'] = spec['ret_kind']
            hook['ret_slot'] = int(spec.get('ret_slot', -1))
        if cache:
            hook['cache'] = cache
        else:
            event_no += 1
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


def damage_lines(tag, ev):
    """damage 钩子还原成老 DLL 同一次命中发的两行：先 ACT 后 VAL。

    十二格布局见 `warp_reads.damage_frame`：a..c=受击者 hp/mhp/mp、
    d=出手方 origin id、e/f=action 的 actor/cmd、g/h=技能 id/tier、
    i/j=受击者 iid/oid。`slot`/`tf` 老链路从 coin/crit 挤出来，读取链
    取不到，保持 -1（规则引擎按缺字段处理）。
    """
    return [
        'ACT tag=%s actor=%d cmd=%d skid=%d slot=-1 tier=%d tf=-1 aoid=%d'
        % (tag, int(ev.get('e', -1)), int(ev.get('f', -1)),
           int(ev.get('g', -1)), int(ev.get('h', -1)), int(ev.get('d', -1))),
        'VAL tag=%s iid=%d oid=%d hp=%d mhp=%d mp=%d'
        % (tag, int(ev.get('i', 0)), int(ev.get('j', 0)),
           int(ev.get('a', 0)), int(ev.get('b', 0)), int(ev.get('c', 0))),
    ]


def railway_lines(kind, tag, ev):
    """railway 系五种读法 → 老 DLL 的四种文本行。

    * ``RWT line=.. total=..``：GetTotalClearTurn 的返回值直出格 0（a），
      self._collectionId 读链进格 1（b）；
    * ``RWT node=.. turn=..``：FormerSaveData::.ctor 之后读两个新字段；
    * ``RWT line=.. total=.. nodes=..``：HistoryDataByCollection::.ctor 的
      a1=线路号、a4=List<int> 求和/计数（老行尾的 vals=.. 明细这里不发，
      解析侧只认 line/total/nodes）；
    * ``SNI part=.. chapter=.. node=.. stage=.. state=..``：SetData 五个
      int 参数原样出；
    * ``RUT text=..``：UI 文本取开头数字（"86" → 86）。
    """
    if kind == WR.KIND_RAILWAY_TOTAL:
        return ['RWT line=%d total=%d' % (int(ev.get('b', -1)), int(ev.get('a', -1)))]
    if kind == WR.KIND_RAILWAY_NODE:
        return ['RWT node=%d turn=%d' % (int(ev.get('a', -1)), int(ev.get('b', -1)))]
    if kind == WR.KIND_RAILWAY_HIST:
        return ['RWT line=%d total=%d nodes=%d'
                % (int(ev.get('a', -1)), int(ev.get('b', -1)), int(ev.get('c', 0)))]
    if kind == WR.KIND_STAGE_NODE_ID:
        return ['SNI part=%d chapter=%d node=%d stage=%d state=%d'
                % (int(ev.get('a', 0)), int(ev.get('b', 0)), int(ev.get('c', 0)),
                   int(ev.get('d', 0)), int(ev.get('e', 0)))]
    if kind == WR.KIND_RAILWAY_UI_TEXT:
        return ['RUT text=%d' % int(ev.get('a', -1))]
    return []


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
    if kind in DAMAGE_KINDS:
        return damage_lines(tag, ev)
    if kind in RAILWAY_KINDS:
        return railway_lines(kind, tag, ev)
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
        """取 WarpHook 的 Host 工厂（插件没装也能直连 warphook 包）。

        两条路径：
        * 启动器主进程：用实际在用的 ``AddonManager`` 实例 —— ``namespaces``
          是实例属性，随手 new 一个拿到的是空注册表；
        * 成就监测子进程：插件系统不在这个进程里跑，直接把 addons/WarpHook
          加进 ``sys.path`` import warphook。共享内存本身是跨进程的，
          warp_host.dll 由谁注入都一样，钩子表本来就只有成就这一个作者。
        """
        from functions.extension.addon.addon_utils import current_manager
        manager = current_manager()
        namespaces = getattr(manager, 'namespaces', None) if manager else None
        if namespaces is not None:
            try:
                return namespaces['warp'].plugin.Host
            except KeyError:
                pass
        return self._host_direct()

    @staticmethod
    def _host_direct():
        """绕过插件系统直连 warphook（子进程路径）。失败返回 None。"""
        import sys as _sys
        try:
            import warphook  # 已可导入（sys.path 里已有）就直接用
        except ImportError:
            try:
                from functions.base.common.path_utils import get_app_root
                root = get_app_root()
            except Exception:  # noqa: BLE001
                root = os.path.dirname(os.path.dirname(os.path.dirname(
                    os.path.abspath(__file__)
                )))
            addon_dir = os.path.join(str(root), 'addons', 'WarpHook')
            if not os.path.isdir(addon_dir):
                return None
            if addon_dir not in _sys.path:
                _sys.path.insert(0, addon_dir)
            try:
                import warphook
            except ImportError:
                return None
        return getattr(warphook, 'Host', None)

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
