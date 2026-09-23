"""hook 目标定义 —— "要盯住哪些东西"的声明式清单。

这里只放**跨版本稳定的描述**（符号名 / 类名 / 值域），不放易变的数字：
具体偏移由 dump 流水线每次重新解出来，写进云端笔记 ``FaustLauncher.hook_index``。
游戏更新后，只要这些名字还在（Project Moon 基本不会改类名），偏移就能自动复原。

目标分两类：

``HOOK_TARGETS``（代码偏移）
    要给 DLL detour 的函数。索引里给的是 ``rva`` + ``prologue``（目标函数前 16 字节），
    两者配对使用：DLL 装钩前先比对 prologue，与本机 DLL 不一致就不装钩 —— 这是
    防"旧偏移打到新版本"的最后一道闸。

``CHAIN_TARGETS``（数据偏移）
    外部进程读游戏数值用的多级指针链。首级是模块内的一个槽位（
    ``GameAssembly.dll + base_offset``，Cheat Engine 里看到的那个地址）；
    ``offsets`` 是随后的逐级偏移（最后一级是值的字段偏移）。

    这类链的**根槽位**（``base_offset``）会随构建变化，但它指向的是 IL2CPP 的
    ``Il2CppClass*`` —— 所以只要知道类名，就能在模块的数据节里重新把它扫出来
    （见 ``locator.py``）。类名一旦被自动发现就会写进索引的 ``root_class``，
    以后每次更新都是"按名字重定位"，不再需要人工找偏移。
"""

from __future__ import annotations

from dataclasses import dataclass, field


# --------------------------------------------------------------------------- 代码钩子


@dataclass(frozen=True)
class HookTarget:
    """一个要 detour 的函数。"""

    key: str                     # 索引里的键（英文小写下划线）
    symbol: str                  # dump.cs 里的方法名：``类::方法`` 或 ``类$$方法``
    description: str
    compat_field: str = ""       # 写进 cheat_damage 兼容块的字段名（空则不入兼容块）
    required: bool = True        # 解不出来时是否算失败
    group: str = "damage"        # 分组：damage（伤害/阵营）/ battle（回合、技能、速度）


# 默认盯住的两个目标：与 test/damage_log.* 和 web.lcta.top/cheat_damage.json 完全对齐，
# 名字取自 Il2CppDumper 的 ``类$$方法`` 写法（BattleUnitModel 在空命名空间下）。
# 注意同名方法在多处重载（BattleUnitModel 是 4 参数版本、BuffAbility 是 6 参数版本），
# 索引按"名字精确匹配取第一处"，与官方 payload 的做法一致（已实测一致）。
HOOK_TARGETS: tuple[HookTarget, ...] = (
    HookTarget(
        key="take_attack_dmg_multiplier",
        symbol="BattleUnitModel$$GetTakeAttackDmgMultiplier",
        description="战斗单位受击伤害倍率（单点覆盖全部子类；伤害/减伤类插件的入口）",
        compat_field="rva_get_take_attack_dmg_multiplier",
    ),
    HookTarget(
        key="opponent_faction",
        symbol="BattleUnitModel$$GetOpponentFaction",
        description="战斗单位敌对阵营判定（判断敌我，配合上面的倍率做方向过滤）",
        compat_field="rva_get_opponent_faction",
    ),
    # ---- 战斗事件类钩子（成就监测用：回合边界 / 技能使用 / 速度初始化）
    # 实测 RVA（build 2026-09-17）：RefreshSpeed=0x11C89D0、
    # DoneWithAction=0x11AD140、BattleActionModelManager::OnRoundStart_Before=0xB63FA0
    HookTarget(
        key="unit_refresh_speed",
        symbol="BattleUnitModel::RefreshSpeed",
        description="单位速度初始化（回合开始/结束时重掷速度；外部观测速度用）",
        group="battle",
    ),
    HookTarget(
        key="action_done_with_action",
        symbol="BattleActionModel::DoneWithAction",
        description="行动执行完成（每个行动一次；技能使用观测点）",
        group="battle",
    ),
    HookTarget(
        key="manager_on_round_start_before",
        symbol="BattleActionModelManager::OnRoundStart_Before",
        description="回合开始前（每回合唯一一次，作为回合边界）",
        group="battle",
    ),
)


# --------------------------------------------------------------------------- 数据链


@dataclass
class ChainTarget:
    """一条"模块槽 → 多级指针 → 值"的读取链。

    ``base_offset`` / ``offsets`` 是**上次已知**的数字，只作为回退默认值；
    每次更新都会尝试用 ``root_class`` / ``field_refs`` 重新解析一遍。
    """

    key: str
    description: str
    base_offset: int
    offsets: tuple[int, ...]
    module: str = "GameAssembly.dll"
    value_type: str = "int32"
    root_class: str = ""                       # 根槽位指向的 Il2CppClass 名（可自动发现）
    static_fields_offset: int = 0xB8           # Il2CppClass::static_fields 的成员偏移
    field_refs: tuple[tuple[str, str], ...] = ()   # ((类, 字段), ...) 用于按名字刷新 offsets
    value_range: tuple[int, int] | None = None  # 合理值域（用于校验/发现）
    step_classes: tuple[str, ...] = ()         # 每级目标对象的类名（发现后填充，便于排障）

    def as_dict(self, **extra) -> dict:
        data = {
            "description": self.description,
            "module": self.module,
            "base_offset": self.base_offset,
            "offsets": list(self.offsets),
            "value_type": self.value_type,
            "root_class": self.root_class,
            "static_fields_offset": self.static_fields_offset,
            "field_refs": [list(item) for item in self.field_refs],
            "value_range": list(self.value_range) if self.value_range else None,
            "step_classes": list(self.step_classes),
        }
        data.update(extra)
        return data


# 脑啡肽容量：链来自用户桌面 ok.py 的 CE 结果（首级 0x07BB4F90 + 0xB8/0x80/0x18/0x28）。
# root_class 留空 —— 第一次跑会由结构性扫描自动认出类名并回填。
ENKEPHALIN_CHAIN = ChainTarget(
    key="enkephalin",
    description="脑啡肽容量（不是狂气；成就「满分脑啡肽」用它）",
    base_offset=0x07BB4F90,
    offsets=(0xB8, 0x80, 0x18, 0x28),
    value_type="int32",
    value_range=(0, 1000),
)

CHAIN_TARGETS: tuple[ChainTarget, ...] = (ENKEPHALIN_CHAIN,)


# --------------------------------------------------------------------------- 战斗事件观测点


@dataclass(frozen=True)
class ObserveTarget:
    """成就战斗观测点（注入 battle_watch.dll 的钩子表条目）。

    与 ``HookTarget`` 的区别：这是**给观测 DLL 用的事件源**，除了 RVA/prologue 还要带
    ``kind``（detour 的签名与事件内容）与“是否解掉尾调用桩”。

    实测教训（2026-09-23）：dump.cs 里给的 RVA 有不少是 IL2CPP 尾调用桩
    （``33 D2 E9 rel32`` = ``xor edx,edx; jmp 真实实现``），例如
    ``BattleUnitModel::RefreshSpeed`` 实际是 ``jmp SetRandomSpeed``、
    ``BattleActionModelManager::OnRoundStart_Before`` 实际是 ``jmp Init``。
    钩在桩上、而调用方直接调真实实现 → 整场战斗 0 事件。所以默认 ``resolve_stub=True``，
    由驱动静态解引用到真实实现再下发。
    """

    key: str                 # 索引里的键
    symbol: str              # dump.cs 里的方法名（``类::方法`` 或 ``类$$方法``）
    kind: str                # 见 battle_watch.py 的 KIND_*（detour 签名与事件内容）
    fallback_rva: int        # 拿不到索引时的回退 RVA
    description: str = ""
    resolve_stub: bool = True


OBSERVE_TARGETS: tuple[ObserveTarget, ...] = (
    ObserveTarget(
        key="unit_refresh_speed", symbol="BattleUnitModel::RefreshSpeed", kind="unit",
        fallback_rva=0x11C89D0,
        description="速度初始化（公开入口；实测是 jmp SetRandomSpeed 的尾调用桩）",
    ),
    ObserveTarget(
        key="unit_set_random_speed", symbol="BattleUnitModel::SetRandomSpeed", kind="unit",
        fallback_rva=0x11C8490, description="速度掷骰（真实实现，每回合每单位）",
    ),
    ObserveTarget(
        key="unit_set_speed", symbol="BattleUnitModel::SetSpeed", kind="unit_int_bool",
        fallback_rva=0x11C7970, description="速度被设置/覆盖（带 value 参数）",
    ),
    ObserveTarget(
        key="unit_get_origin_speed", symbol="BattleUnitModel::GetIntegerOfOriginSpeed",
        kind="unit_get_int", fallback_rva=0x11C7B50,
        description="读有效速度（含覆盖；UI/排序热路径，去重后上报）",
    ),
    ObserveTarget(
        key="unit_round_start", symbol="BattleUnitModel::OnRoundStart_Before", kind="unit",
        fallback_rva=0x11E7380, description="单位回合开始（回合边界+速度）",
    ),
    ObserveTarget(
        key="manager_on_round_start_before", symbol="BattleActionModelManager::OnRoundStart_Before",
        kind="plain", fallback_rva=0xB63FA0,
        description="回合开始前（实测是 jmp Init 的尾调用桩）",
    ),
    ObserveTarget(
        key="manager_init", symbol="BattleActionModelManager::Init", kind="plain",
        fallback_rva=0xB63DC0, description="行动管理器初始化/回合边界（真实实现）",
    ),
    ObserveTarget(
        key="action_on_end_turn", symbol="BattleActionModel::OnEndTurn", kind="action_int",
        fallback_rva=0x11ACBA0, description="行动在回合结束时（技能观测）",
    ),
    ObserveTarget(
        key="action_done_with_action", symbol="BattleActionModel::DoneWithAction", kind="action_int",
        fallback_rva=0x11AD140, description="行动完成（实测普通战斗不触发，留作对照）",
    ),
    ObserveTarget(
        key="take_attack_dmg_multiplier", symbol="BattleUnitModel::GetTakeAttackDmgMultiplier",
        kind="damage_action", fallback_rva=0x11E1D10,
        description="受击伤害倍率（已证实会被调用：拿 attacker 身份 + action 技能）",
        resolve_stub=False,
    ),
)


def hook_symbol_entries() -> list[tuple[str, str, str, str]]:
    """给 updater 用：``(key, symbol, description, compat_field)``（含观测点）。"""
    entries = [(t.key, t.symbol, t.description, t.compat_field) for t in HOOK_TARGETS]
    entries += [(t.key, t.symbol, t.description, "") for t in OBSERVE_TARGETS]
    return entries


# --------------------------------------------------------------------------- 结构体字段

# 事件钩子里要读的字段（key → (类, 字段, 上次已知偏移)）。
# 这些名字会被 dump 流水线解析成偏移，写进索引的 ``fields`` 段；
# 注入 DLL 直接读索引里的偏移（不写死），拿不到索引时才用这里的回退值。
#
# 偏移来源：dump.cs（build 2026-09-17）实测。
BATTLE_FIELDS: dict[str, tuple[str, str, int]] = {
    # ---- BattleUnitModel ----
    "unit_instance_id": ("BattleUnitModel", "_instanceID", 0x60),
    "unit_origin_id": ("BattleUnitModel", "_originID", 0x64),
    "unit_origin_speed": ("BattleUnitModel", "_originSpeed", 0xCC),
    "unit_overwrited_speed": ("BattleUnitModel", "_overwritedSpeed", 0xD0),
    "unit_int_speed_turn": ("BattleUnitModel", "_thisTurnIntSpeedOnCmdPhase", 0x184),
    # ---- CharacterState（BattleUnitModel._state 指向它；HP / 理智都在这里）----
    # ``_mp`` 就是界面上的理智(SP)：同类的 ``_maxMp = 45`` / ``_minMp = -45``
    # 常量正好就是 SP 的上下限（负数理智 = 陷入恐慌、魔法少女成就用）。
    # 三个值都是 ACTk ``ObscuredInt``（value = hiddenValue ^ currentCryptoKey）。
    "unit_state": ("BattleUnitModel", "_state", 0x148),
    "state_hp": ("CharacterState", "_hp", 0x148),
    "state_max_hp": ("CharacterState", "_maxHp", 0x11C),
    "state_mp": ("CharacterState", "_mp", 0x158),
    # ---- BattleActionModel ----
    "action_skill": ("BattleActionModel", "_skill", 0x20),
    "action_commander_id": ("BattleActionModel", "_commanderInstanceID", 0xB4),
    "action_actor_id": ("BattleActionModel", "_orderedActionActorInstanceId", 0xBC),
    # ---- SkillModel / SkillDataModel ----
    "skill_data": ("SkillModel", "_skillData", 0x10),
    "skill_id": ("SkillDataModel", "id", 0x10),          # ObscuredInt：<身份5位><槽位2位>
    "skill_tier": ("SkillDataModel", "skillTier", 0x40),  # ObscuredInt：1/2/3 = 技能一/二/三
}


# --------------------------------------------------------------------------- 符号保留范围

# 只有命中这些模式的类，其方法/字段才会进索引（否则索引会有几十 MB）。
# 这些是"钩子/读值最可能用到"的类；需要更多时在这里加即可，或临时用 CLI 的
# ``--focus`` 覆盖。
FOCUS_PATTERNS: tuple[str, ...] = (
    "BattleUnitModel",
    "BattleActionModel",
    "AttackDamage",
    "DamageInfo",
    "CoinModel",
    "BuffAbility",
    "BattleUnit",
    "BattleManager",
    "Enkephalin",
    "Achievement",
    "SaveManager",
    "PlayerData",
    "UserData",
    "UnitData",
    "PassiveAbility",
)

# 索引里最多保留多少符号（防止 focus 写太宽导致本地缓存过大；
# 发布到云端时还会再裁剪一次，见 index.MAX_PUBLISH_METHODS）
MAX_METHODS = 40000
MAX_FIELDS = 20000


def all_targets() -> tuple[tuple[HookTarget, ...], tuple[ChainTarget, ...]]:
    return HOOK_TARGETS, CHAIN_TARGETS


def required_symbols() -> list[str]:
    """所有必须在 dump.cs 里找到的符号名（用于 dump 时的白名单保留）。"""
    names = [t.symbol for t in HOOK_TARGETS]
    names += [t.symbol for t in OBSERVE_TARGETS]
    for chain in CHAIN_TARGETS:
        for cls, fld in chain.field_refs:
            names.append(f"{cls}::{fld}")
        if chain.root_class:
            names.append(chain.root_class)
    for cls, fld, _fallback in BATTLE_FIELDS.values():
        names.append(f"{cls}::{fld}")
    return names


def battle_field_keys() -> tuple[str, ...]:
    """事件类字段的键名（顺序稳定，便于日志/调试）。"""
    return tuple(BATTLE_FIELDS.keys())
