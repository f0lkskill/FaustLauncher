# -*- coding: utf-8 -*-
"""成就钩子的「读法」到 WarpHook 读取链的翻译。

老链路（`hook_dll/battle_watch.c`）为每种读法手写了一个 thunk：四十个钩子槽
乘以十六种读法，就是六百多个函数，再由 `pick_detour()` 用二重 switch 分派。
那些 thunk 做的事情其实高度重复——调原函数、从某个参数出发按固定路径读几个
整数、拼成一行事件发出去。

WarpHook 的读取链把「按路径读整数」这件事变成了数据：一条链 = 从哪个参数出发、
跳几跳（每跳可解引用）、落点按什么类型解释。于是十六种读法退化成十六行配置。

但这个翻译不是无所不能的，写在这里说清楚边界：

* **能表达**：按固定偏移跳几级再读一个 int / float / bool / 混淆 int。
  例：`self → [+state] → [+hp]` 读血量；`action → [+skill] → [+data] → [+id]` 读技能 id。
* **不能表达**：函数**返回值**（在寄存器里，钩子读不到内存）、**容器遍历**
  （buff 列表要按 List 布局走 items/size）、**字符串比较**（buff 名要读 il2cpp
  string 再算 FNV-1a）。这三类仍然需要 C 侧特化，对应 `NATIVE_*` 里列出的项。

字段偏移不写死在本文件里：老链路是运行时从 `WarpConfig.off_*` 读的，说明
它们本来就可配（不同游戏版本会变）。这里把偏移当参数传进来，由调用方
（成就插件）决定从校准结果还是默认表取值。
"""

KIND_PLAIN = 'plain'
KIND_UNIT = 'unit'
KIND_UNIT_INT_BOOL = 'unit_int_bool'
KIND_UNIT_GET_INT = 'unit_get_int'
KIND_ACTION_INT = 'action_int'
KIND_DAMAGE_ACTION = 'damage_action'
KIND_SKV = 'skv'
KIND_STAGE_STAT = 'stage_stat'
KIND_RAILWAY_TOTAL = 'railway_total'
KIND_CACHE_SELF = 'cache_self'
KIND_NODE_STATE = 'node_state'
KIND_CACHE_ARG1 = 'cache_arg1'
KIND_RAILWAY_NODE = 'railway_node'
KIND_RAILWAY_HIST = 'railway_hist'
KIND_STAGE_NODE_ID = 'stage_node_id'
KIND_RAILWAY_UI_TEXT = 'railway_ui_text'

# 十六种读法，顺序与 battle_watch.c / battle_watch.py 的 BWK_* 编号一致
KIND_ORDER = (
    KIND_PLAIN, KIND_UNIT, KIND_UNIT_INT_BOOL, KIND_UNIT_GET_INT,
    KIND_ACTION_INT, KIND_DAMAGE_ACTION, KIND_SKV, KIND_STAGE_STAT,
    KIND_RAILWAY_TOTAL, KIND_CACHE_SELF, KIND_NODE_STATE, KIND_CACHE_ARG1,
    KIND_RAILWAY_NODE, KIND_RAILWAY_HIST, KIND_STAGE_NODE_ID,
    KIND_RAILWAY_UI_TEXT,
)

# 参数形状：argc 是「不含 this」的参数个数，与 C 侧 thunk 签名严格对应。
# 名字只用于生成配置时自查，不影响行为。
KIND_SIGNATURES = {
    KIND_PLAIN: (1, ('method',)),
    KIND_UNIT: (1, ('method',)),
    KIND_UNIT_INT_BOOL: (3, ('value', 'cm', 'method')),
    KIND_UNIT_GET_INT: (1, ('method',)),
    KIND_ACTION_INT: (2, ('timing', 'method')),
    KIND_DAMAGE_ACTION: (5, ('action', 'coin', 'attacker', 'crit', 'method')),
    KIND_SKV: (2, ('a1', 'method')),
    KIND_STAGE_STAT: (3, ('a1', 'a2', 'method')),
    KIND_RAILWAY_TOTAL: (1, ('method',)),
    KIND_CACHE_SELF: (1, ('method',)),
    KIND_NODE_STATE: (2, ('a1', 'method')),
    KIND_CACHE_ARG1: (2, ('a1', 'method')),
    KIND_RAILWAY_NODE: (2, ('a1', 'method')),
    KIND_RAILWAY_HIST: (2, ('a1', 'method')),
    KIND_STAGE_NODE_ID: (2, ('a1', 'method')),
    KIND_RAILWAY_UI_TEXT: (2, ('a1', 'method')),
}

# 必须由 C 侧特化的能力，读取链表达不了
NATIVE_BUFF_LIST = 'buff_list'      # 遍历 BuffDetail → List<BuffModel> → static id
NATIVE_BUFF_HASH = 'buff_hash'      # 读 il2cpp string 再算 FNV-1a 判断是不是关注的 buff
NATIVE_RETURN_VALUE = 'return_value'  # 原函数返回值（浮点伤害、int 结果）在寄存器里
NATIVE_CONTAINER_WALK = 'container_walk'  # List/Array 遍历（关卡列表、铁路节点）
NATIVE_UI_TEXT = 'ui_text'          # 读 UI 文本组件
NATIVE_POINTER_CACHE = 'pointer_cache'  # 只缓存对象指针给采样线程，不读值

NATIVE_KINDS = (
    NATIVE_BUFF_LIST, NATIVE_BUFF_HASH, NATIVE_RETURN_VALUE,
    NATIVE_CONTAINER_WALK, NATIVE_UI_TEXT, NATIVE_POINTER_CACHE,
)

# 每种读法需要 C 侧额外做什么（空元组 = 纯配置就够）
KIND_NATIVE = {
    KIND_PLAIN: (),
    KIND_UNIT: (NATIVE_BUFF_LIST, NATIVE_BUFF_HASH),
    KIND_UNIT_INT_BOOL: (NATIVE_BUFF_LIST, NATIVE_BUFF_HASH),
    KIND_UNIT_GET_INT: (NATIVE_RETURN_VALUE, NATIVE_BUFF_LIST),
    KIND_ACTION_INT: (),
    KIND_DAMAGE_ACTION: (NATIVE_RETURN_VALUE, NATIVE_BUFF_LIST, NATIVE_BUFF_HASH),
    KIND_SKV: (),
    KIND_STAGE_STAT: (),
    KIND_RAILWAY_TOTAL: (NATIVE_CONTAINER_WALK,),
    KIND_CACHE_SELF: (NATIVE_POINTER_CACHE,),
    KIND_NODE_STATE: (),
    KIND_CACHE_ARG1: (NATIVE_POINTER_CACHE,),
    KIND_RAILWAY_NODE: (NATIVE_CONTAINER_WALK,),
    KIND_RAILWAY_HIST: (NATIVE_CONTAINER_WALK,),
    KIND_STAGE_NODE_ID: (NATIVE_CONTAINER_WALK,),
    KIND_RAILWAY_UI_TEXT: (NATIVE_UI_TEXT,),
}

# 事件槽位约定：与老链路的 VAL/SPD/ACT 行里最重要的四个数字对齐
OUT_PRIMARY = 0     # 主值（伤害、hp、技能 id 等）
OUT_SECONDARY = 1   # 次值（max hp、tier、oid 等）
OUT_UNIT_ID = 2     # 单位 instance id
OUT_ORIGIN_ID = 3   # 单位 origin id（角色静态 id）


def _read(arg, chain, out, kind='int'):
    """构造一条读取链。chain 是 [(偏移, 是否解引用), ...]。"""
    return {
        'arg': arg,
        'off': [int(step[0]) for step in chain],
        'deref': [bool(step[1]) for step in chain],
        'out': out,
        'kind': kind,
    }


def unit_vitals(offsets):
    """self → [+state] → [+hp / +max_hp / +mp]，三个都是 ObscuredInt。

    老链路 `read_unit_vitals()` 走的就是这条，`_mp` 是理智(SP)，负数代表恐慌。
    """
    state = offsets['unit_state']
    return [
        _read(0, [(state, True), (offsets['state_hp'], False)], OUT_PRIMARY, 'obscured'),
        _read(0, [(state, True), (offsets['state_max_hp'], False)], OUT_SECONDARY, 'obscured'),
    ]


def unit_identity(offsets):
    """self → [+instance_id] / [+origin_id]，都是普通 int。"""
    return [
        _read(0, [(offsets['unit_instance_id'], False)], OUT_UNIT_ID),
        _read(0, [(offsets['unit_origin_id'], False)], OUT_ORIGIN_ID),
    ]


def unit_speed(offsets):
    """self → [+origin_speed]，速度按 float 位模式取回来由 py 还原。"""
    return [
        _read(0, [(offsets['unit_origin_speed'], False)], OUT_PRIMARY, 'float'),
    ]


def action_skill(offsets, arg=1):
    """action → [+skill] → [+data] → [+skill_id] / [+tier]。"""
    skill = offsets['action_skill']
    data = offsets['skill_data']
    return [
        _read(arg, [(skill, True), (data, True), (offsets['skill_id'], False)],
              OUT_PRIMARY),
        _read(arg, [(skill, True), (data, True), (offsets['skill_tier'], False)],
              OUT_SECONDARY),
    ]


def attacker_origin_id(offsets, arg=3):
    """attacker → [+origin_id]，伤害钩子用它判断是哪一方打出来的。"""
    return [
        _read(arg, [(offsets['unit_origin_id'], False)], OUT_ORIGIN_ID),
    ]


# 单位一帧的八格布局：老链路一次命中要发 SPD 和 VAL 两行，一行五六个数，
# 四格装不下。八格刚好一次装完，桥那边就不用把一条钩子拆成两条再配对。
SLOT_IID = 0
SLOT_OID = 1
SLOT_HP = 2
SLOT_MAX_HP = 3
SLOT_MP = 4
SLOT_ORIGIN_SPEED = 5
SLOT_OVERWRITED_SPEED = 6
SLOT_INT_SPEED_TURN = 7


def unit_frame(offsets):
    """self 身上的八个字段，一次读完：编号、模板、血量三件套、速度三件套。

    速度那三个是**定点数**（存的是 ×1000 的值），原样带回 Python 再除，
    免得在这里做整数除法把 -1 哨兵变成 0。
    """
    state = offsets['unit_state']
    return [
        _read(0, [(offsets['unit_instance_id'], False)], SLOT_IID),
        _read(0, [(offsets['unit_origin_id'], False)], SLOT_OID),
        _read(0, [(state, True), (offsets['state_hp'], False)], SLOT_HP, 'obscured'),
        _read(0, [(state, True), (offsets['state_max_hp'], False)], SLOT_MAX_HP, 'obscured'),
        _read(0, [(state, True), (offsets['state_mp'], False)], SLOT_MP, 'obscured'),
        _read(0, [(offsets['unit_origin_speed'], False)], SLOT_ORIGIN_SPEED),
        _read(0, [(offsets['unit_overwrited_speed'], False)], SLOT_OVERWRITED_SPEED),
        _read(0, [(offsets['unit_int_speed_turn'], False)], SLOT_INT_SPEED_TURN),
    ]


# 每种读法「默认」读哪些槽。调用方可以在此基础上增删。
_KIND_READS = {
    KIND_PLAIN: lambda off: [],
    KIND_UNIT: lambda off: unit_frame(off),
    KIND_UNIT_INT_BOOL: lambda off: unit_frame(off),
    KIND_UNIT_GET_INT: lambda off: unit_frame(off),
    KIND_ACTION_INT: lambda off: action_skill(off),
    KIND_DAMAGE_ACTION: lambda off: (
        attacker_origin_id(off) + unit_vitals(off)
    ),
    KIND_SKV: lambda off: [],
    KIND_STAGE_STAT: lambda off: [],
    KIND_RAILWAY_TOTAL: lambda off: [],
    KIND_CACHE_SELF: lambda off: [],
    KIND_NODE_STATE: lambda off: [],
    KIND_CACHE_ARG1: lambda off: [],
    KIND_RAILWAY_NODE: lambda off: [],
    KIND_RAILWAY_HIST: lambda off: [],
    KIND_STAGE_NODE_ID: lambda off: [],
    KIND_RAILWAY_UI_TEXT: lambda off: [],
}

# 偏移表的键：与老链路 WarpConfig 的字段名一一对应（去掉 off_ 前缀）
OFFSET_KEYS = (
    'unit_instance_id', 'unit_origin_id', 'unit_origin_speed',
    'unit_state', 'state_hp', 'state_max_hp', 'state_mp',
    'unit_buff_detail', 'buff_detail_list', 'buff_model_data', 'buff_static_id',
    'action_skill', 'skill_data', 'skill_id', 'skill_tier',
)


def hook_spec(kind, klass, method, offsets=None, **extra):
    """把一种读法翻译成 `Host.hook()` 能直接吃的参数。

    返回 dict，键是 `klass/method/argc/reads/native/kind`，额外关键字原样并入。
    `offsets` 为空时 `reads` 为空（只报事件不读值），并保留 `native` 说明。
    """
    if kind not in KIND_SIGNATURES:
        raise ValueError('未知读法：%r' % (kind,))
    argc, _names = KIND_SIGNATURES[kind]
    reads = []
    if offsets:
        builder = _KIND_READS[kind]
        try:
            reads = builder(offsets)
        except KeyError as exc:
            raise KeyError('读法 %s 缺少偏移字段 %s' % (kind, exc)) from None
    spec = {
        'klass': klass,
        'method': method,
        'argc': argc,
        'reads': reads,
        'native': list(KIND_NATIVE[kind]),
        'kind': kind,
    }
    spec.update(extra)
    return spec


def missing_offsets(offsets):
    """返回偏移表里缺哪些键，方便启动时一次性报出来而不是逐个 KeyError。"""
    have = set(offsets or {})
    return [k for k in OFFSET_KEYS if k not in have]


def summary():
    """给日志/自检用的一句话概括。"""
    pure = [k for k in KIND_ORDER if not KIND_NATIVE[k]]
    native = [k for k in KIND_ORDER if KIND_NATIVE[k]]
    return (
        '%d 种读法：%d 种可纯配置表达（%s），%d 种仍需 C 侧特化（%s）'
        % (len(KIND_ORDER), len(pure), '、'.join(pure),
           len(native), '、'.join(native))
    )
