
from __future__ import annotations

from dataclasses import dataclass, field

@dataclass(frozen=True)
class HookTarget:

    key: str
    symbol: str
    description: str
    compat_field: str = ""
    required: bool = True
    group: str = "damage"

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

@dataclass
class ChainTarget:

    key: str
    description: str
    base_offset: int
    offsets: tuple[int, ...]
    module: str = "GameAssembly.dll"
    value_type: str = "int32"
    root_class: str = ""
    static_fields_offset: int = 0xB8
    field_refs: tuple[tuple[str, str], ...] = ()
    value_range: tuple[int, int] | None = None
    step_classes: tuple[str, ...] = ()

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

ENKEPHALIN_CHAIN = ChainTarget(
    key="enkephalin",
    description="脑啡肽容量（不是狂气；成就「满分脑啡肽」用它）",
    base_offset=0x07BB4F90,
    offsets=(0xB8, 0x80, 0x18, 0x28),
    value_type="int32",
    value_range=(0, 1000),
)

CHAIN_TARGETS: tuple[ChainTarget, ...] = (ENKEPHALIN_CHAIN,)

@dataclass(frozen=True)
class ObserveTarget:

    key: str
    symbol: str
    kind: str
    fallback_rva: int
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
        key="skv_start", symbol="BattleSkillViewBase::Skill_Start", kind="skv",
        fallback_rva=0x9B4D80, description="技能动画开始（表现层，事件带 iid）"),
    ObserveTarget(
        key="skv_complete", symbol="BattleSkillViewBase::Skill_Complete", kind="skv",
        fallback_rva=0x9BD810, description="技能动画完成（表现层，事件带 iid）"),
    ObserveTarget(
        key="skv_end", symbol="BattleSkillViewBase::Skill_End", kind="skv",
        fallback_rva=0x9475C0, description="技能动画结束（表现层，实测是 jmp 桩→Skill_EndMethod）"),
    ObserveTarget(
        key="take_attack_dmg_multiplier", symbol="BattleUnitModel::GetTakeAttackDmgMultiplier",
        kind="damage_action", fallback_rva=0x11E1D10,
        description="受击伤害倍率（已证实会被调用：拿 attacker 身份 + action 技能）",
        resolve_stub=False,
    ),
    ObserveTarget(
        key="stage_statistic", symbol="StageStatisticPopupData::.ctor", kind="stage_stat",
        fallback_rva=0x13C8DE0,
        description="关卡结算统计（通关回合数 + 关卡 uid；铁路成就靠它）",
        resolve_stub=False,
    ),
    ObserveTarget(
        key="railway_total",
        symbol="RailwayDungeonHistoryDataByCollection::GetTotalClearTurn",
        kind="railway_total", fallback_rva=0x1A83AF0,
        description="折射铁路整条线总回合（进线路前显示的最好回合数）",
        resolve_stub=False,
    ),
    ObserveTarget(
        key="stage_clear_info", symbol="UserStageClearInfoData::UpdateData",
        kind="cache_self", fallback_rva=0x18E62D0,
        description="存档已通关关卡记录（挂 UpdateData 抓对象，供采样线程轮询）",
        resolve_stub=False,
    ),
    ObserveTarget(
        key="stage_clear_query", symbol="UserStageClearInfoData::GetData",
        kind="cache_self", fallback_rva=0x18E6300,
        description="UI 查询已通关记录（抓对象指针，与 stage_clear_info 多头挂点）",
        resolve_stub=False,
    ),
    ObserveTarget(
        key="stage_clear_last", symbol="UserStageClearInfoData::GetLastClearData",
        kind="cache_self", fallback_rva=0x18E63E0,
        description="UI 查询最后一次通关记录（抓对象指针）",
        resolve_stub=False,
    ),
    ObserveTarget(
        key="node_cleared", symbol="UserStageNodeStateData::IsNodeCleared",
        kind="node_state", fallback_rva=0x18B0A30,
        description="关卡是否已通关（章节/节点是入参，不依赖存档结构）",
        resolve_stub=False,
    ),
    ObserveTarget(
        key="node_clear_state", symbol="UserStageNodeStateData::GetClearNodeState",
        kind="node_state", fallback_rva=0x18B0630,
        description="关卡通关状态（含难度/次数）",
        resolve_stub=False,
    ),
    ObserveTarget(
        key="stage_progress", symbol="UserStageNodeStateData::UpdateData",
        kind="cache_arg1", fallback_rva=0x18AFFE0,
        description="存档全量进度树（登录时下发，采样线程遍历即可全量判定）",
        resolve_stub=False,
    ),
    ObserveTarget(
        key="railway_node", symbol="RailwayDungeonFormerSaveData::.ctor",
        kind="railway_node", fallback_rva=0x18B38D0,
        description="折射铁路每节点通关回合（填 nodeId/clearTurn）",
        resolve_stub=False,
    ),
    ObserveTarget(
        key="railway_hist", symbol="RailwayDungeonHistoryDataByCollection::.ctor",
        kind="railway_hist", fallback_rva=0x1A83860,
        description="折射铁路历史记录（各节点回合列表 → 整条线总回合）",
        resolve_stub=False,
    ),
    ObserveTarget(
        key="stage_node_id", symbol="StageNodeIdInfo::SetData", kind="stage_node_id",
        fallback_rva=0x12636F0,
        description="关卡身份（章 + 第几关 + 关卡id + 通关状态）→ 界面上的 10-4",
        resolve_stub=False,
    ),
    ObserveTarget(
        key="railway_ui_text",
        symbol="RailwayDungeonMapUpperUILine1002::UpdateUI", kind="railway_ui_text",
        fallback_rva=0x1A4E500,
        description="铁路地图显示的总回合文本（读 UI 显示值，不猜聚合）",
        resolve_stub=False,
    ),
)

def hook_symbol_entries() -> list[tuple[str, str, str, str]]:
    entries = [(t.key, t.symbol, t.description, t.compat_field) for t in HOOK_TARGETS]
    entries += [(t.key, t.symbol, t.description, "") for t in OBSERVE_TARGETS]
    return entries

BATTLE_FIELDS: dict[str, tuple[str, str, int]] = {
    "unit_instance_id": ("BattleUnitModel", "_instanceID", 0x60),
    "unit_origin_id": ("BattleUnitModel", "_originID", 0x64),
    "unit_origin_speed": ("BattleUnitModel", "_originSpeed", 0xCC),
    "unit_overwrited_speed": ("BattleUnitModel", "_overwritedSpeed", 0xD0),
    "unit_int_speed_turn": ("BattleUnitModel", "_thisTurnIntSpeedOnCmdPhase", 0x184),
    "unit_state": ("BattleUnitModel", "_state", 0x148),    "state_hp": ("CharacterState", "_hp", 0x148),
    "state_max_hp": ("CharacterState", "_maxHp", 0x11C),
    "state_mp": ("CharacterState", "_mp", 0x158),
    "unit_buff_detail": ("BattleUnitModel", "_buffDetail", 0xE0),
    "buff_detail_list": ("BuffDetail", "_grantedBuffList", 0x10),
    "buff_model_data": ("BuffModel", "_buffData", 0x68),
    "buff_static_id": ("BuffStaticData", "id", 0x18),
    "action_skill": ("BattleActionModel", "_skill", 0x20),
    "action_commander_id": ("BattleActionModel", "_commanderInstanceID", 0xB4),
    "action_actor_id": ("BattleActionModel", "_orderedActionActorInstanceId", 0xBC),
    "skill_data": ("SkillModel", "_skillData", 0x10),
    "skill_id": ("SkillDataModel", "id", 0x10),
    "skill_tier": ("SkillDataModel", "skillTier", 0x40),
    "stage_slot_list": ("StageStatisticPopupData", "_slotDataList", 0x10),
    "slot_uid": ("StageStatisticPopupSlotData", "_uid", 0x10),
    "slot_clear_turn": ("StageStatisticPopupSlotData", "_clearTurn", 0x18),
    "slot_dead_count": ("StageStatisticPopupSlotData", "_deadUnitCount", 0x1C),
    "slot_ex_cleared": ("StageStatisticPopupSlotData", "_exCleared", 0x20),
    "railway_collection_id": ("RailwayDungeonHistoryDataByCollection", "_collectionId", 0x10),
    "stage_clear_list": ("UserStageClearInfoData", "_stageClearInfoList", 0x18),
    "clear_info_list": ("StageClearInfoList", "_list", 0x10),
    "clear_info_id": ("StageClearInfo", "_id", 0x10),
    "railway_ui_text": ("RailwayDungeonMapUpperUILine1002", "tmp_totalTurn", 0x28),
    "tmp_text": ("TMP_Text", "m_text", 0xE0),
}

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
    "StageStatisticPopup",
    "RailwayDungeonHistoryData",
    "StageClearInfo",
    "StageNodeIdInfo",
    "RailwayDungeonMapUpperUI",
    "TMP_Text",
    "SaveManager",
    "PlayerData",
    "UserData",
    "UnitData",
    "PassiveAbility",
)

MAX_METHODS = 40000
MAX_FIELDS = 20000

def all_targets() -> tuple[tuple[HookTarget, ...], tuple[ChainTarget, ...]]:
    return HOOK_TARGETS, CHAIN_TARGETS

def required_symbols() -> list[str]:
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
    return tuple(BATTLE_FIELDS.keys())
