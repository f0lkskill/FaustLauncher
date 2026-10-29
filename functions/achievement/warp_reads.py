# -*- coding: utf-8 -*-
"""成就钩子的「读法」到 WarpHook 读取链的翻译。

老链路（`hook_dll/battle_watch.c`）为每种读法手写了一个 thunk：四十个钩子槽
乘以十六种读法，就是六百多个函数，再由 `pick_detour()` 用二重 switch 分派。
那些 thunk 做的事情其实高度重复——调原函数、从某个参数出发按固定路径读几个
整数、拼成一行事件发出去。

WarpHook 的读取链把「按路径读整数」这件事变成了数据：一条链 = 从哪个参数出发、
跳几跳（每跳可解引用）、落点按什么类型解释。于是十六种读法退化成十六行配置。

但这个翻译不是无所不能的，写在这里说清楚边界（v0.8 起边界往外推了一大截）：

* **能表达**：按固定偏移跳几级再读一个 int / float / bool / 混淆 int。
  例：`self → [+state] → [+hp]` 读血量；`action → [+skill] → [+data] → [+id]` 读技能 id。
* **v0.8 起也能表达**：
  - **函数返回值**——钩子声明 ``ret_kind``（int32/float），thunk 按类型调
    原函数把 RAX/XMM0 的返回值直出进事件格（``GetTotalClearTurn`` 的总回合、
    ``GetTakeAttackDmgMultiplier`` 的伤害倍率）；带返回值或声明 ``when=post``
    时事件在原函数**之后**发，构造函数里「调用之后才填好」的字段也读得到。
  - **值类型容器遍历**——``list_val``/``array_val`` 步按 4B 元素取值，
    ``sum``/``count`` 两种落点直接对 ``List<int>`` 求和/计数
    （``RailwayDungeonHistoryDataByCollection::.ctor`` 的 clear_turns）。
  - **字符串取数**——``text`` 落点读 il2cpp string 的 UTF-16 内容取开头数字
    （``RailwayDungeonMapUpperUILine1002::UpdateUI`` 之后 UI 文本 "86" → 86）。
* **仍然不能表达**：buff 链遍历 + buff 名 FNV-1a 比较（``NATIVE_BUFF_LIST`` /
  ``NATIVE_BUFF_HASH``）——damage 钩子的 BUF 行因此仍不发，buff 类成就走
  采样器路径；多行明细（``stage_statistic`` 的逐关卡 STG 行）同理暂缓。

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
#
# 注意：这个数是**老 thunk 从寄存器里取几格**，不等于方法真实声明的参数个数
# （il2cpp 的部分方法还带隐藏的 MethodInfo*）。真要装钩子，得用 dump.cs 里的
# 真实签名，由 `warp_source.ARGC_OVERRIDE` 兜底。
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
    # railway_hist 的 .ctor 真实声明 9 个参数（老 thunk 形参 a1..a9，a1=int 线路
    # 号、a4=List<int> clear_turns）；stage_node_id 的 SetData 是 5 个 int。
    KIND_RAILWAY_NODE: (2, ('a1', 'method')),
    KIND_RAILWAY_HIST: (10, ('cid', 'a2', 'a3', 'turns', 'a5', 'a6', 'a7', 'a8',
                             'a9', 'method')),
    KIND_STAGE_NODE_ID: (6, ('part', 'chapter', 'node', 'stage', 'state', 'method')),
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

# 每种读法需要 C 侧额外做什么（空元组 = 纯配置就够）。
# v0.8 起返回值/值类型容器/字符串取数都有了通用原语，原先标着
# NATIVE_RETURN_VALUE / NATIVE_CONTAINER_WALK / NATIVE_UI_TEXT 的五种读法
# 全部转成纯配置；真正的 C 特化只剩 buff 链那两个（BUF 行本轮不发）。
KIND_NATIVE = {
    KIND_PLAIN: (),
    KIND_UNIT: (NATIVE_BUFF_LIST, NATIVE_BUFF_HASH),
    KIND_UNIT_INT_BOOL: (NATIVE_BUFF_LIST, NATIVE_BUFF_HASH),
    KIND_UNIT_GET_INT: (NATIVE_BUFF_LIST,),
    KIND_ACTION_INT: (),
    KIND_DAMAGE_ACTION: (NATIVE_BUFF_LIST, NATIVE_BUFF_HASH),
    KIND_SKV: (),
    KIND_STAGE_STAT: (),
    KIND_RAILWAY_TOTAL: (),
    KIND_CACHE_SELF: (NATIVE_POINTER_CACHE,),
    KIND_NODE_STATE: (),
    KIND_CACHE_ARG1: (NATIVE_POINTER_CACHE,),
    KIND_RAILWAY_NODE: (),
    KIND_RAILWAY_HIST: (),
    KIND_STAGE_NODE_ID: (),
    KIND_RAILWAY_UI_TEXT: (),
}

# 事件槽位约定：与老链路的 VAL/SPD/ACT 行里最重要的四个数字对齐
OUT_PRIMARY = 0     # 主值（伤害、hp、技能 id 等）
OUT_SECONDARY = 1   # 次值（max hp、tier、oid 等）
OUT_UNIT_ID = 2     # 单位 instance id
OUT_ORIGIN_ID = 3   # 单位 origin id（角色静态 id）
OUT_ACTOR = 4       # 行动：出手者 instance id
OUT_COMMANDER = 5   # 行动：指令者 instance id


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


def action_frame(offsets, arg=1):
    """action 对象身上的四项：出手者、指令者、技能 id、技能层级。

    `BattleActionModel::OnEndTurn(action, timing, info)` 的 action 是**第一个参数**
    而不是 self（self 是 BattleActionModel 自己），所以 arg 默认 1。
    """
    skill = offsets['action_skill']
    data = offsets['skill_data']
    return [
        _read(arg, [(offsets['action_actor_id'], False)], OUT_ACTOR),
        _read(arg, [(offsets['action_commander_id'], False)], OUT_COMMANDER),
        _read(arg, [(skill, True), (data, True), (offsets['skill_id'], False)], OUT_PRIMARY),
        _read(arg, [(skill, True), (data, True), (offsets['skill_tier'], False)],
              OUT_SECONDARY),
    ]


def attacker_origin_id(offsets, arg=3):
    """attacker → [+origin_id]，伤害钩子用它判断是哪一方打出来的。"""
    return [
        _read(arg, [(offsets['unit_origin_id'], False)], OUT_ORIGIN_ID),
    ]


# damage 事件的十二格布局：一条 GetTakeAttackDmgMultiplier 命中要同时
# 还原 ACT（action 系）和 VAL（unit 系）两行，老链路一次发两行、这里
# 一格装一个数。缺 mp / iid / oid 的话 VAL 行就得编数据 —— 全读齐。
SLOT_DMG_HP = 0
SLOT_DMG_MAX_HP = 1
SLOT_DMG_MP = 2
SLOT_DMG_ATTACKER_OID = 3
SLOT_DMG_ACTOR = 4
SLOT_DMG_COMMANDER = 5
SLOT_DMG_SKID = 6
SLOT_DMG_TIER = 7
SLOT_DMG_IID = 8
SLOT_DMG_OID = 9


def damage_frame(offsets):
    """伤害钩子的一帧：attacker 的 origin id + 受击者三围 + action 四件套。

    参数布局（老链路 DEF_DAMAGE_THUNK 同款）：self=受击单位、a1=action、
    a2=coin、a3=attacker、a4=crit。返回值是 float 倍率（本钩子取了但不直出，
    与老链路一致 —— 伤害数值成就走 VAL 行的 hp 变化）。
    """
    skill = offsets['action_skill']
    data = offsets['skill_data']
    state = offsets['unit_state']
    return [
        _read(0, [(state, True), (offsets['state_hp'], False)], SLOT_DMG_HP, 'obscured'),
        _read(0, [(state, True), (offsets['state_max_hp'], False)], SLOT_DMG_MAX_HP, 'obscured'),
        _read(0, [(state, True), (offsets['state_mp'], False)], SLOT_DMG_MP, 'obscured'),
        _read(3, [(offsets['unit_origin_id'], False)], SLOT_DMG_ATTACKER_OID),
        _read(1, [(offsets['action_actor_id'], False)], SLOT_DMG_ACTOR),
        _read(1, [(offsets['action_commander_id'], False)], SLOT_DMG_COMMANDER),
        _read(1, [(skill, True), (data, True), (offsets['skill_id'], False)], SLOT_DMG_SKID),
        _read(1, [(skill, True), (data, True), (offsets['skill_tier'], False)], SLOT_DMG_TIER),
        _read(0, [(offsets['unit_instance_id'], False)], SLOT_DMG_IID),
        _read(0, [(offsets['unit_origin_id'], False)], SLOT_DMG_OID),
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
    KIND_ACTION_INT: lambda off: action_frame(off),
    KIND_DAMAGE_ACTION: lambda off: damage_frame(off),
    KIND_SKV: lambda off: [
        # 表现层 BattleSkillViewBase 的 _attackerInstanceID：技能动画在演哪个单位。
        _read(0, [(off['skv_attacker_iid'], False)], OUT_PRIMARY),
    ],
    KIND_STAGE_STAT: lambda off: [],
    # GetTotalClearTurn(int) 的返回值直出格 0，self._collectionId 进格 1。
    KIND_RAILWAY_TOTAL: lambda off: [
        _read(0, [(off['railway_collection_id'], False)], 1),
    ],
    KIND_CACHE_SELF: lambda off: [],
    KIND_NODE_STATE: lambda off: [
        # 三个参数都是值类型 int（main/sub/node），读链 0 跳 = 直接取参数值。
        _read(1, [], OUT_PRIMARY),
        _read(2, [], OUT_SECONDARY),
        _read(3, [], OUT_UNIT_ID),
    ],
    KIND_CACHE_ARG1: lambda off: [],
    # RailwayDungeonFormerSaveData::.ctor 的两个字段是构造完才填好的，
    # 配 when=post 在原函数之后读。
    KIND_RAILWAY_NODE: lambda off: [
        _read(0, [(off['railway_node_id'], False)], 0),
        _read(0, [(off['railway_node_turn'], False)], 1),
    ],
    # 九参构造：a1=线路号（值类型零跳直出）、a4=List<int> clear_turns 求和/计数。
    KIND_RAILWAY_HIST: lambda off: [
        _read(1, [], 0),
        _read(4, [], 1, 'sum'),
        _read(4, [], 2, 'count'),
    ],
    # SetData(part, chapter, node, stage, state)：五个 int 参数原样进事件。
    KIND_STAGE_NODE_ID: lambda off: [
        _read(1, [], 0),
        _read(2, [], 1),
        _read(3, [], 2),
        _read(4, [], 3),
        _read(5, [], 4),
    ],
    # UpdateUI 之后 self[ui_text]→TMP 组件 →[tmp_text]→il2cpp string，取开头数字。
    KIND_RAILWAY_UI_TEXT: lambda off: [
        _read(0, [(off['railway_ui_text'], True), (off['tmp_text'], True)], 0, 'text'),
    ],
}

# 需要返回值/POST 语义的读法：hook_spec 把这些并进 spec，
# warp_source 塞进 Host.hook(when=..., ret_kind=..., ret_slot=...)。
KIND_EVENT_WHEN_POST = (
    KIND_RAILWAY_TOTAL,      # 返回值语义上就是「调完才有」
    KIND_RAILWAY_NODE, KIND_RAILWAY_HIST, KIND_RAILWAY_UI_TEXT,
)
KIND_RETURN = {
    # 读法: (ret_kind 名字, 直出的事件格)
    KIND_RAILWAY_TOTAL: ('int32', 0),
    KIND_DAMAGE_ACTION: ('float', None),   # 取返回值但先不直出（老链路也不发伤害值）
}

# 偏移表的键：与老链路 WarpConfig 的字段名一一对应（去掉 off_ 前缀）
OFFSET_KEYS = (
    'unit_instance_id', 'unit_origin_id', 'unit_origin_speed',
    'unit_state', 'state_hp', 'state_max_hp', 'state_mp',
    'unit_buff_detail', 'buff_detail_list', 'buff_model_data', 'buff_static_id',
    'action_skill', 'skill_data', 'skill_id', 'skill_tier',
    'skv_attacker_iid',
    'railway_collection_id', 'railway_node_id', 'railway_node_turn',
    'railway_ui_text', 'tmp_text',
)


# 只缓存对象、不发事件的那两种读法各自占一个对象槽。
# 0：``cache_self`` 抓到的对象；1：``cache_arg1`` 抓到的对象。
CACHE_SLOTS = {
    KIND_CACHE_SELF: 0,
    KIND_CACHE_ARG1: 1,
}


def hook_spec(kind, klass, method, offsets=None, **extra):
    """把一种读法翻译成 `Host.hook()` 能直接吃的参数。

    返回 dict，键是 `klass/method/argc/reads/native/kind`，额外关键字原样并入。
    `offsets` 为空时 `reads` 为空（只报事件不读值），并保留 `native` 说明。
    """
    if kind not in KIND_SIGNATURES:
        raise ValueError('未知读法：%r' % (kind,))
    # KIND_SIGNATURES 的第一项是「含 self 的格子数」，而 class_get_method_from_name
    # 要的是真实参数个数（不含 this）。差 1 不是笔误：钩子能找到全靠这个数对。
    argc = max(0, KIND_SIGNATURES[kind][0] - 1)
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
    # 构造函数/UI 刷新这类「调用之后才有值」的钩子：事件改到 POST 发。
    if kind in KIND_EVENT_WHEN_POST:
        spec['when'] = 1
    ret = KIND_RETURN.get(kind)
    if ret is not None:
        spec['ret_kind'] = ret[0]
        if ret[1] is not None:
            spec['ret_slot'] = ret[1]
        # 带返回值 = 事件本来就该在原函数之后发（Host.hook() 关键字路径有
        # 同款兜底；这里在配置源头写死，dict 直传路径不靠下游补）。
        spec.setdefault('when', 1)
    # 只缓存对象、不发事件的读法：把指针留在对象槽里，等采样侧回读。
    # 槽号在 CACHE_SLOTS 里定死，同一类读法共用一格 —— 它们抓的是同一个
    # 存档管理器对象，谁后命中谁的值就是最新的一份。
    slot = CACHE_SLOTS.get(kind)
    if slot is not None:
        spec['cache'] = (0 if kind == KIND_CACHE_SELF else 1, slot)
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
