"""战斗事件观测驱动 v2 —— 注入 ``hook_dll/battle_watch.dll`` 并解析事件（成就用）。

与 v1 的区别（v1 的教训：钩到了 IL2CPP 尾调用桩，整场战斗 0 事件）：

1. **尾调用桩解引用**：dump.cs 的 RVA 可能是 ``33 D2 E9 rel32``（``xor edx,edx;
   jmp 真实实现``）。驱动静态读本机 ``GameAssembly.dll``，遇到桩就顺着跳过去，
   钩真实实现，并在日志里写明"0x… (RefreshSpeed) 是尾调用桩 → 改钩 0x… (SetRandomSpeed)"；
2. **通用钩子表**：要钩什么、什么签名（kind）、prologue、字段偏移，全部写进共享内存，
   DLL 不写死任何数字；同一地址会被自动合并（去重）；
3. **命中计数**：DLL 累加每个钩子的调用次数（``hook_hits[]``），驱动轮询后报出
   "哪个钩子被调了多少次" —— 装钩成功但 0 次调用一眼可见；
4. **可见性**：独立事件日志 ``logs/battle_watch.log``（不刷屏、不被截断）、
   状态文件 ``cache/achievement/battle_watch_status.json``、每 20 秒一条心跳日志、
   全事件记录（不再只记两个成就相关的），并支持 ``--status`` / ``--probe`` 离线自查。

事件行（DLL → 环形缓冲）::

    RND tag=<钩子名>                                                        回合边界
    SPD tag=<钩子名> iid=.. oid=.. os=.. osi=.. ow=.. owi=.. its=.. [eff=..]  速度
    VAL tag=<钩子名> iid=.. oid=.. hp=.. mhp=.. mp=..                        血量 / 理智
    ACT tag=<钩子名> actor=.. cmd=.. skid=.. slot=.. tier=.. aoid=..         行动/技能

``os``/``ow`` 是「速度 ×1000」的**定点原始值**，``osi``/``owi`` 是换算后的**整数速度**
（见下面 ``SPEED_SCALE``）。驱动侧两条路都认：DLL 给了 ``osi``/``owi`` 就直接用，
没给（v2 DLL / 老日志）就自己按 ``SPEED_SCALE`` 换算。

``hp``/``mhp``/``mp`` 来自 ``unit[0x148] → CharacterState``（0x148 / 0x11C / 0x158，
都是 ACTk ``ObscuredInt``）；``mp`` 就是界面上的**理智(SP)**：同类常量 ``_minMp = -45`` /
``_maxMp = 45`` 正是它的上下限，负数理智 = 陷入恐慌。

日志分工（重要）::

    logs/battle_watch.log      全量事件流（RND/SPD/VAL/ACT 每行都写）—— 用来看细节
    logs/achievement_hook.log  只留成就相关：生命周期 / 错误 / 观测点首次命中 /
                               心跳 / 规则命中（★）；**不刷事件**

事件行默认不进成就日志（``verbose=True``，或设置项 ``achievement_log_verbose`` 才进）。
两个日志都在每次实例启动时清空重写（只保留本次运行）。

本模块**不认识任何具体成就**：身份 ID / 技能 ID / 阈值这些业务常量全部写在成就模块里
（``functions/achievement/data/*.py``），通过 ``BattleRule`` 登记进来。驱动只提供
「事件字段解释」与下面这张规则表——加新成就不需要改本文件。

判定规则（``BattleRule``）—— 一次登记，驱动按类型统一求值（**没有针对具体成就的分支**）::

使用示例（id 均为占位值——真实身份/技能常量只存在于成就模块里）::

    BattleRule(key="ach_demo_skill",  kind="skill",  identity_ids=(10001,), skill_ids=(1000101,))
    BattleRule(key="ach_demo_speed",  kind="speed",  identity_ids=(10002,), threshold=9)
    BattleRule(key="ach_demo_mental", kind="mental", identity_ids=(10003,), threshold=0)
    BattleRule(key="ach_demo_hp",     kind="hp",     identity_ids=(10004,), ratio=1.0)

| kind | 看的事件 | 命中条件 | 何时置位 |
|---|---|---|---|
| ``skill`` | ``ACT`` | ``skill_ids`` 命中，或（``identity_ids``+``tiers``）拼出的技能 ID 命中，或（``gated_skill_ids`` 且 actor 身份在 ``identity_ids`` 里） | 回合边界结算 |
| ``speed`` | ``SPD`` | 身份命中且 ``fields``（默认全部速度字段）里任一 == ``threshold`` | 立刻（回合边界兜底） |
| ``mental`` | ``VAL`` | 身份命中且 ``mp < threshold`` | 立刻（回合边界兜底） |
| ``hp`` | ``VAL`` | 身份命中且 ``hp < mhp * ratio`` | 立刻（回合边界兜底） |

“立刻”类都走同一个求值器（``BattleWatch._eval_immediate_locked``）：加新类型 = 在
``BattleRule`` 里加一个 ``match_*`` + 一个 ``RULE_KIND_*``，调用处不用 if/else。
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import json
import os
import re
import sys
import threading
import time
from dataclasses import dataclass, field

# --------------------------------------------------------------------------- 协议常量

BW_MAGIC = 0x34574246            # "FBW4"（v3 加血量/理智，v5 加 buff 偏移与关注表）
MAP_NAME = "Local\\FaustLauncher_BattleWatch"
LOG_RING_CAP = 512
LOG_LINE_MAX = 255
MAX_HOOKS = 12
HOOK_NAME_LEN = 40
TARGET_PROCESS = "LimbusCompany.exe"

# 关注 buff 表大小（与 C 端 BW_BUFF_WATCH_MAX 一致）
BUFF_WATCH_MAX = 32


def fnv1a64(text) -> int:
    """FNV-1a 64 哈希（与 C 端 fnv1a64 逐位一致）—— 用于把 buff 名写进关注表。

    buff 的 id 是字符串（如 ``HanafudaTwo`` / ``FutureEyeOnRodion``），
    跨进程传名字太占空间，所以两边用同一个哈希对身份。
    """
    data = text.encode("utf-8", "replace") if isinstance(text, str) else bytes(text)
    h = 0xCBF29CE484222325
    for byte in data:
        h ^= byte
        h = (h * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return h

# 钩子 kind（必须与 battle_watch.c 的 BWK_* 一致）
KIND_PLAIN = 0        # void (self, mi)                                   → RND
KIND_UNIT = 1         # void (self, mi)                                   → SPD
KIND_UNIT_INT_BOOL = 2  # void (self, int value, bool checkMinMax, mi)     → SPD
KIND_UNIT_GET_INT = 3   # int (self, mi)                                  → SPD（去重）
KIND_ACTION_INT = 4     # void (self, int timing, mi)                     → ACT
KIND_DAMAGE_ACTION = 5  # float(self, action, coin, attacker, bool, mi)    → ACT
KIND_NUMBERS = {"plain": KIND_PLAIN, "unit": KIND_UNIT,
                "unit_int_bool": KIND_UNIT_INT_BOOL, "unit_get_int": KIND_UNIT_GET_INT,
                "action_int": KIND_ACTION_INT, "damage_action": KIND_DAMAGE_ACTION}

# --------------------------------------------------------------------------- 字段语义

# 驱动只负责解释「事件里的字节」，不认识任何具体成就：
# 具体身份/技能/阈值全部是成就侧登记的 ``BattleRule`` 数据（见本文件末尾的规则表章节）。

# 速度字段的单位（**关键**，2026-09-17 build 实测）：
# ``_originSpeed``(0xCC) / ``_overwritedSpeed``(0xD0) 存的是「速度 ×1000」的定点数，
# 小数部分是隐藏的同速排序值（同速单位靠它决定先后）。直接当成速度看会得到 14518 这种怪值。
# 证据（反汇编本机 GameAssembly.dll）：
#   GetIntegerOfPureOriginalSpeed = 带符号 /1000（魔数 0x10624DD3 的 idiv 序列）
#   GetIntegerOfOverwritedSpeed   = 同上（<=0 原样返回）
#   ChangeIntegerPartOfSpeed      = 只改整数部分、保留小数（差值 ×1000 加回 _originSpeed）
#   SetRandomSpeed                = Random.Range(lower*1000, upper*1000+1000) 后写 0xCC
#   GetSpeedLowerLimit/UpperLimit = 返回*整数*速度（内部 Math.Round + 下限 1）
#   常量 _CORRECTION_FOR_SPEED = 1000、_MIN_SPEED = 1000
# 结论：**界面/逻辑上的速度 = trunc(字段 / 1000)**（setter 保证 >= 0，负值只可能是未初始化）。
SPEED_SCALE = 1000

# 血量/理智读不出来时 DLL 会发这个哨兵（HP 不可能为负、理智只有 ±45）——
# 避免把“读失败”当成“理智负数”误触发成就。
VITAL_UNREAD = -1000

# SPD 事件的字段清单（驱动知道事件里有什么，成就只用 ``fields`` 选自己要看的那几个），
# 值都是**整数速度**：os/ow/eff 已归一化，its 本来就是整数。
# os=_originSpeed（本回合掷出的速度）、ow=_overwritedSpeed（被技能覆盖后的速度）、
# its=_thisTurnIntSpeedOnCmdPhase（命令阶段快照，回合开始那一刻还是上一回合的值）、
# eff=有效速度（游戏 GetIntegerOfOriginSpeed 语义：ow>=0 用 ow，否则用 os）。
SPEED_FIELD_ORDER = ("os", "ow", "its", "eff")


def speed_int(raw: int) -> int:
    """把「速度 ×1000」定点值还原成整数速度（向零取整，与游戏 ``GetIntegerOf*Speed`` 一致）。

    负值（-1）是「本回合还没掷速度」的哨兵，原样返回 -1（游戏侧会算成 0，但 0 会误导排查）。
    """
    if raw is None:
        return -1
    if raw < 0:
        return -1
    return raw // SPEED_SCALE


def speed_text(value: int, raw: int) -> str:
    """速度的日志写法：未掷（原始值为负哨兵）时写“未掷”，否则“整数(原始)”方便对照。"""
    if raw is None or raw < 0:
        return "未掷"
    return f"{value}(raw {raw})"


# --------------------------------------------------------------------------- 判定规则

# 成就侧只登记「数据」，具体判定全在驱动里（见模块头部说明）。
# 加新类型 = 在 ``BattleRule`` 里加一个 ``match_*`` + 一个 ``RULE_KIND_*``，调用处不需要 if：
#   skill  → ACT 里出现目标技能（回合边界结算）
#   speed  → SPD 里目标身份的速度命中某值（立刻）
#   mental → VAL 里目标身份的理智(SP) 低于阈值（立刻）
#   hp     → VAL 里目标身份的血量低于最大血量的比例（立刻）
RULE_KIND_SKILL = "skill"
RULE_KIND_SPEED = "speed"
RULE_KIND_MENTAL = "mental"
RULE_KIND_HP = "hp"
RULE_KIND_BUFF = "buff"        # 目标身份身上有指定 buff（BUF 事件，立刻）
RULE_KIND_PRESENCE = "presence"  # 目标身份在场上（由单位表推出，立刻）
RULE_KINDS = (RULE_KIND_SKILL, RULE_KIND_SPEED, RULE_KIND_MENTAL, RULE_KIND_HP,
              RULE_KIND_BUFF, RULE_KIND_PRESENCE)
# “观测到就立刻置位”的类型（skill 类走「技能动画结束」结算，单独一条路）
RULE_KINDS_IMMEDIATE = (RULE_KIND_SPEED, RULE_KIND_MENTAL, RULE_KIND_HP,
                        RULE_KIND_BUFF, RULE_KIND_PRESENCE)


@dataclass(frozen=True)
class BattleRule:
    """一条可数据化的战斗判定规则（成就基类构造时登记，驱动每帧拿它比对事件）。

    匹配技能（``kind="skill"``）有三种写法，任一命中即可：

    1. ``skill_ids``：完整技能 ID（自带身份，最硬，如 ``1000101``）；
    2. ``identity_ids`` + ``tiers``：按「技能 ID = 身份×100 + 槽位」拼，
       例如 ``identity_ids=(10001,), tiers=(3,)`` 就是「10001 的三技能」；
    3. ``gated_skill_ids``：ID 里不带身份的技能（例如被转化后的技能），
       此时额外要求 actor 身份在 ``identity_ids`` 里，避免敌人用同名技能误触发。
    """

    key: str                                  # 规则名（= 成就 id，成就侧按它取结果）
    label: str = ""                           # 日志里显示的可读名（由成就侧提供）
    kind: str = RULE_KIND_SKILL
    identity_ids: tuple[int, ...] = ()        # 目标身份（5 位身份 ID）
    skill_ids: tuple[int, ...] = ()           # kind=skill：完整技能 ID
    tiers: tuple[int, ...] = ()               # kind=skill：技能槽位（1/2/3/4）
    gated_skill_ids: tuple[int, ...] = ()     # kind=skill：需 actor 身份匹配的技能 ID
    threshold: int = 0                        # mental：mp < threshold；speed：速度 == threshold
    ratio: float = 1.0                        # hp：hp < mhp * ratio
    fields: tuple[str, ...] = ()              # speed：看哪几个速度字段（空 = SPEED_FIELD_ORDER）
    buffs: tuple[str, ...] = ()               # buff：要看的 buff 名（Bufs.json 的 id，如 "HanafudaTwo"）
    any_skill: bool = False                   # skill："用了任意技能"（只看身份，不看具体技能）
    max_round: int = 0                        # 只在第 max_round 回合及以前生效（0 = 不限）
    min_round: int = 0                        # 从第 min_round 回合开始生效（0 = 不限）

    # 回合窗口（0 = 不限制）。"首个回合"就用 max_round=1。
    def round_ok(self, round_seq: int) -> bool:
        if self.max_round and round_seq > self.max_round:
            return False
        if self.min_round and round_seq < self.min_round:
            return False
        return True

    # 匹配
    def match_skill(self, skid: int, actor_oid: int, round_seq: int = 0) -> bool:
        """技能命中：``skill_ids`` / 身份+槽位 / 受控 ID / ``any_skill`` 任一。"""
        if not self.round_ok(round_seq):
            return False
        if self.any_skill:
            if actor_oid in self.identity_ids:
                return True
            return bool(skid is not None and skid >= 0 and (skid // 100) in self.identity_ids)
        if skid is not None and skid >= 0:
            if skid in self.skill_ids:
                return True
            if self.tiers and (skid // 100) in self.identity_ids and (skid % 100) in self.tiers:
                return True
            if skid in self.gated_skill_ids and actor_oid in self.identity_ids:
                return True
        return False

    def match_buff(self, oid: int, names: set, round_seq: int = 0) -> tuple:
        """buff 命中：返回 ``(是否命中, 命中的 buff 名)``。

        ``names`` 是该单位当前身上（且在关注表里的）buff 名集合；
        ``max_round`` 可实现"首个回合开始时是否带某 buff"这类需求。
        """
        if self.kind != RULE_KIND_BUFF or oid not in self.identity_ids:
            return False, ()
        if not self.round_ok(round_seq):
            return False, ()
        hit = tuple(n for n in self.buffs if n in names)
        return bool(hit), hit

    def match_presence(self, oid: int, round_seq: int = 0) -> bool:
        """场上存在该身份（``kind="presence"``）。"""
        return (self.kind == RULE_KIND_PRESENCE and oid in self.identity_ids
                and self.round_ok(round_seq))

    def match_vitals(self, oid: int, hp: int, mhp: int, mp: int) -> bool:
        """血量/理智类的命中判定（``oid`` 不在目标身份里一律不命中）。

        读失败（``VITAL_UNREAD``）一律不命中，宁可漏也不能误判。
        """
        if oid not in self.identity_ids:
            return False
        if self.kind == RULE_KIND_MENTAL:
            return mp != VITAL_UNREAD and mp < self.threshold
        if self.kind == RULE_KIND_HP:
            if VITAL_UNREAD in (hp, mhp) or mhp <= 0:
                return False
            return hp < mhp * self.ratio
        return False

    def match_speed(self, oid: int, speeds: dict) -> tuple[bool, tuple[str, ...]]:
        """速度命中判定：返回 ``(是否命中, 命中的字段名)``。

        ``speeds`` 是驱动归一化后的 SPD 字段（``os``/``ow``/``its``/``eff``）。
        ``fields`` 为空时看全部字段；未掷速度（-1 哨兵）不会等于任何非负阈值。
        """
        if self.kind != RULE_KIND_SPEED or oid not in self.identity_ids:
            return False, ()
        names = self.fields or SPEED_FIELD_ORDER
        hit = tuple(name for name in names if speeds.get(name) == self.threshold)
        return bool(hit), hit

    def threshold_text(self) -> str:
        """阈值的人类可读写法（写进成就详情/日志）。"""
        if self.kind == RULE_KIND_MENTAL:
            return f"理智 < {self.threshold}"
        if self.kind == RULE_KIND_HP:
            return f"血量 < 最大血量的 {self.ratio:.0%}"
        if self.kind == RULE_KIND_SPEED:
            return f"速度 == {self.threshold}"
        if self.kind == RULE_KIND_BUFF:
            return f"身上有 buff {'/'.join(self.buffs)}"
        if self.kind == RULE_KIND_PRESENCE:
            return "在场上"
        if self.any_skill:
            return "使用了任意技能"
        return "技能命中"


_rules: dict[str, BattleRule] = {}
_rules_lock = threading.Lock()


def register_rule(rule) -> BattleRule:
    """登记一条判定规则（重复 key 以最后一次为准）。支持传 dict。

    登记后会把「buff 类规则用到的 buff 名」同步到关注表（驱动侧读它决定要不要
    去看 buff 链）—— 所以成就构造完就不需要额外操作。
    """
    if isinstance(rule, dict):
        rule = BattleRule(**rule)
    with _rules_lock:
        _rules[rule.key] = rule
    try:
        _sync_buff_watch()
    except Exception:
        pass
    return rule


def registered_rules() -> dict[str, BattleRule]:
    with _rules_lock:
        return dict(_rules)


def clear_rules() -> None:
    with _rules_lock:
        _rules.clear()


def watched_identities() -> set[int]:
    """所有规则里出现过的目标身份（状态文件只保留这些单位的血量/理智/buff）。"""
    with _rules_lock:
        rules = list(_rules.values())
    ids: set[int] = set()
    for rule in rules:
        ids.update(rule.identity_ids)
    return ids


def watched_buff_names() -> tuple[str, ...]:
    """所有 buff 类规则用到的 buff 名（稳定排序）。

    关注表的第 i 位就是这个 tuple 的第 i 项 → DLL 发的位掩码能直接映射回名字。
    """
    with _rules_lock:
        rules = list(_rules.values())
    names: list[str] = []
    for rule in rules:
        if rule.kind == RULE_KIND_BUFF:
            for name in rule.buffs:
                if name and name not in names:
                    names.append(name)
    names.sort()
    return tuple(names[:BUFF_WATCH_MAX])


def _sync_buff_watch() -> tuple[str, ...]:
    """把关注 buff 名（FNV-1a 64）写进共享内存关注表；没配就写 0。"""
    names = watched_buff_names()
    with _watch_lock:
        watch = _watch
    if watch is not None:
        watch.sync_buff_watch(names)
    return names


def rule_hit(key: str) -> str | None:
    """规则是否命中过；命中返回详情文本（未命中/没观测到返回 None）。"""
    with _watch_lock:
        watch = _watch
    if watch is None:
        return None
    return watch.rule_detail(key)


def rule_order(key: str) -> int:
    """规则命中的先后序号（越小越早；未命中返回 0）。"""
    with _watch_lock:
        watch = _watch
    if watch is None:
        return 0
    return watch.rule_order(key)


def rule_live(key: str) -> bool:
    """按当前观测重新判一次规则（不置位；给复合成就的“状态条件”用）。"""
    with _watch_lock:
        watch = _watch
    if watch is None:
        return False
    return watch.rule_live(key)

# 回合边界信号：这些钩子的命中计数增加 = 新回合（或每单位回合开始的第一次）
BOUNDARY_PREFERRED = ("manager_init", "manager_on_round_start_before")
BOUNDARY_FALLBACK = ("unit_round_start",)

# 表现层动画 tick（DLL 用 plain kind 发 ``RND tag=skv_*``）：它们**不是**回合边界，
# 只用来推进"动画相位"。见 BattleSkillViewBase（Skill_Start / Skill_Complete / Skill_End）。
ANIM_TICK_TAGS = ("skv_start", "skv_complete", "skv_end")

# 要"等动画"的规则类型：命中后先进待放行队列，由动画 tick 逐个放行。
# 技能类本来就走待结算（pending_flags）；hp/理智/buff 之前是立刻置位，而这游戏的值变化
# 全在回合开头的结算瞬间 → 立刻置位 = "回合开始立刻结算"，所以一起改成等动画。
RULE_KINDS_ANIM_WAIT = ("hp", "mental", "buff")

# 「技能动画结束」的收尾事件：**只用 done_with_action**。
# 实测同一手技能里 ``action_on_end_turn`` 先到、``action_done_with_action`` 后到
# （中间还夹着 take_attack_dmg_multiplier 的伤害事件）—— 拿 on_end_turn 结算
# 等于“动画还没播完就结算”，所以只在 done 上结算。
ACTION_END_TAGS = ("action_done_with_action",)
# 静默期兜底：个别技能不调收尾函数时，事件停这么久就当作动画放完。
# 2.5s ≈ 一手技能动画的时长（太短会在动画中途结算，太长会让成就慢半拍）。
SKILL_SETTLE_QUIET_SEC = 2.5

HEARTBEAT_SEC = 20.0
STATUS_WRITE_SEC = 2.0
HOOK_MERGE_WARN = "已合并到同一地址"

ERROR_TEXT = {
    0: "正常",
    1: "共享内存不可用",
    2: "GameAssembly.dll 60 秒内未加载",
    3: "版本自检失败（prologue 不匹配，索引与本机 DLL 不是同一版本）",
    4: "MinHook 初始化失败",
    5: "MinHook 创建钩子失败",
    6: "MinHook 启用钩子失败",
}

# --------------------------------------------------------------------------- 回退值

# 拿不到 hook_index 时的兜底（RVA 来自 build 2026-09-17 实测）
FALLBACK_HOOKS: dict[str, tuple[str, int, str]] = {
    # key: (symbol, rva, kind)
    "unit_refresh_speed": ("BattleUnitModel::RefreshSpeed", 0x11C89D0, "unit"),
    "unit_set_random_speed": ("BattleUnitModel::SetRandomSpeed", 0x11C8490, "unit"),
    "unit_set_speed": ("BattleUnitModel::SetSpeed", 0x11C7970, "unit_int_bool"),
    "unit_get_origin_speed": ("BattleUnitModel::GetIntegerOfOriginSpeed", 0x11C7B50,
                              "unit_get_int"),
    "unit_round_start": ("BattleUnitModel::OnRoundStart_Before", 0x11E7380, "unit"),
    "manager_on_round_start_before": ("BattleActionModelManager::OnRoundStart_Before",
                                      0xB63FA0, "plain"),
    "manager_init": ("BattleActionModelManager::Init", 0xB63DC0, "plain"),
    "action_on_end_turn": ("BattleActionModel::OnEndTurn", 0x11ACBA0, "action_int"),
    "action_done_with_action": ("BattleActionModel::DoneWithAction", 0x11AD140, "action_int"),
    "take_attack_dmg_multiplier": ("BattleUnitModel::GetTakeAttackDmgMultiplier", 0x11E1D10,
                                  "damage_action"),
    # ---- 表现层（动画相位）-----------------------------------------------
    # ⚠ 这游戏的战斗是"**先算完整回合、再播动画**"：结算阶段（伤害/收尾回调）全挤在回合
    # 刚开始的一瞬间，拿它们当"动画结束"必然变成"回合一开始就解锁"。只有表现层的
    # BattleSkillViewBase 回调能反映动画进度（RVA 来自 dump.cs，build 34E76109）。
    # 它们走 plain kind（DLL 发 RND tag=<钩子名>），驱动按 tag 前缀 ``skv_`` 区分相位。
    "skv_start": ("BattleSkillViewBase::Skill_Start", 0x9B4D80, "plain"),
    "skv_complete": ("BattleSkillViewBase::Skill_Complete", 0x9BD810, "plain"),
    "skv_end": ("BattleSkillViewBase::Skill_End", 0x9475C0, "plain"),
}
FALLBACK_FIELDS: dict[str, int] = {
    "unit_instance_id": 0x60,
    "unit_origin_id": 0x64,
    "unit_origin_speed": 0xCC,
    "unit_overwrited_speed": 0xD0,
    "unit_int_speed_turn": 0x184,
    # CharacterState 链（HP / 理智，都是 ObscuredInt）
    "unit_state": 0x148,          # BattleUnitModel::_state → CharacterState*
    "state_hp": 0x148,            # CharacterState::_hp
    "state_max_hp": 0x11C,        # CharacterState::_maxHp
    "state_mp": 0x158,            # CharacterState::_mp（理智/SP，±45）
    # buff 链（buff 的 id 是字符串，如 HanafudaTwo / FutureEyeOnRodion，与 Lang/Bufs.json 一致）
    "unit_buff_detail": 0xE0,     # BattleUnitModel::_buffDetail → BuffDetail*
    "buff_detail_list": 0x10,     # BuffDetail::_grantedBuffList : List<BuffModel>
    "buff_model_data": 0x68,      # BuffModel::_buffData → BuffStaticData*
    "buff_static_id": 0x18,       # BuffStaticData::id : string
    "action_skill": 0x20,
    "action_commander_id": 0xB4,
    "action_actor_id": 0xBC,
    "skill_data": 0x10,
    "skill_id": 0x10,
    "skill_tier": 0x40,
}
# 该候选不做桩解引用（本身就是真实实现/已验证可用）
NO_STUB_RESOLVE = {"take_attack_dmg_multiplier"}

# --------------------------------------------------------------------------- 共享内存结构


class BWConfig(ctypes.Structure):
    """与 ``hook_dll/battle_watch.c`` 的 ``BW_CONFIG``（v2）一一对应。

    DLL 启动后会回写 ``ring_offset`` / ``struct_size``，本模块会核对。
    """

    _fields_ = [
        ("magic", ctypes.c_int32),
        ("observing", ctypes.c_int32),
        ("log", ctypes.c_int32),
        ("retry_requested", ctypes.c_int32),
        ("hook_count", ctypes.c_int32),
        ("hook_rva", ctypes.c_int32 * MAX_HOOKS),
        ("hook_kind", ctypes.c_int32 * MAX_HOOKS),
        ("hook_hits", ctypes.c_int32 * MAX_HOOKS),
        ("hook_prologue", (ctypes.c_ubyte * 16) * MAX_HOOKS),
        ("hook_name", (ctypes.c_char * HOOK_NAME_LEN) * MAX_HOOKS),
        ("off_unit_instance_id", ctypes.c_int32),
        ("off_unit_origin_id", ctypes.c_int32),
        ("off_unit_origin_speed", ctypes.c_int32),
        ("off_unit_overwrited_speed", ctypes.c_int32),
        ("off_unit_int_speed_turn", ctypes.c_int32),
        ("off_unit_state", ctypes.c_int32),
        ("off_state_hp", ctypes.c_int32),
        ("off_state_max_hp", ctypes.c_int32),
        ("off_state_mp", ctypes.c_int32),
        ("off_unit_buff_detail", ctypes.c_int32),
        ("off_buff_detail_list", ctypes.c_int32),
        ("off_buff_model_data", ctypes.c_int32),
        ("off_buff_static_id", ctypes.c_int32),
        ("off_action_skill", ctypes.c_int32),
        ("off_action_commander_id", ctypes.c_int32),
        ("off_action_actor_id", ctypes.c_int32),
        ("off_skill_data", ctypes.c_int32),
        ("off_skill_id", ctypes.c_int32),
        ("off_skill_tier", ctypes.c_int32),
        ("gameassembly_found", ctypes.c_int32),
        ("verified", ctypes.c_int32),
        ("installed", ctypes.c_int32),
        ("last_error", ctypes.c_int32),
        ("event_count", ctypes.c_int32),
        ("round_seq", ctypes.c_int32),
        ("ring_offset", ctypes.c_int32),
        ("struct_size", ctypes.c_int32),
        ("last_log", ctypes.c_char * 128),
        ("log_head", ctypes.c_int32),
        ("log_ring", (ctypes.c_char * (LOG_LINE_MAX + 1)) * LOG_RING_CAP),
        # 关注 buff 表（在结构体末尾：ring 偏移不变，只让总大小变）
        ("buff_watch_count", ctypes.c_int32),
        ("buff_watch_hashes", ctypes.c_uint64 * BUFF_WATCH_MAX),
    ]


CONFIG_SIZE = ctypes.sizeof(BWConfig)
RING_OFFSET = BWConfig.log_ring.offset

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_LPVOID = ctypes.c_void_p
_HANDLE = ctypes.c_void_p
_LPCWSTR = ctypes.c_wchar_p

_kernel32.CreateFileMappingW.restype = _HANDLE
_kernel32.CreateFileMappingW.argtypes = [_HANDLE, _LPVOID, wt.DWORD, wt.DWORD, wt.DWORD, _LPCWSTR]
_kernel32.OpenFileMappingW.restype = _HANDLE
_kernel32.OpenFileMappingW.argtypes = [wt.DWORD, wt.BOOL, _LPCWSTR]
_kernel32.MapViewOfFile.restype = _LPVOID
_kernel32.MapViewOfFile.argtypes = [_HANDLE, wt.DWORD, wt.DWORD, wt.DWORD, ctypes.c_size_t]
_kernel32.UnmapViewOfFile.argtypes = [_LPVOID]
_kernel32.CloseHandle.argtypes = [_HANDLE]
_kernel32.OpenProcess.restype = _HANDLE
_kernel32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
_kernel32.VirtualAllocEx.restype = _LPVOID
_kernel32.VirtualAllocEx.argtypes = [_HANDLE, _LPVOID, ctypes.c_size_t, wt.DWORD, wt.DWORD]
_kernel32.VirtualFreeEx.argtypes = [_HANDLE, _LPVOID, ctypes.c_size_t, wt.DWORD]
_kernel32.WriteProcessMemory.argtypes = [_HANDLE, _LPVOID, _LPVOID, ctypes.c_size_t,
                                         ctypes.POINTER(ctypes.c_size_t)]
_kernel32.CreateRemoteThread.restype = _HANDLE
_kernel32.CreateRemoteThread.argtypes = [_HANDLE, _LPVOID, ctypes.c_size_t, _LPVOID,
                                         _LPVOID, wt.DWORD, _LPVOID]
_kernel32.WaitForSingleObject.argtypes = [_HANDLE, wt.DWORD]
_kernel32.GetExitCodeThread.argtypes = [_HANDLE, ctypes.POINTER(wt.DWORD)]
_kernel32.GetModuleHandleW.restype = _HANDLE
_kernel32.GetModuleHandleW.argtypes = [_LPCWSTR]
_kernel32.GetProcAddress.restype = _LPVOID
_kernel32.GetProcAddress.argtypes = [_HANDLE, ctypes.c_char_p]

PROCESS_ACCESS = 0x0002 | 0x0400 | 0x0008 | 0x0020 | 0x0010
TH32CS_SNAPPROCESS = 0x00000002


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wt.DWORD),
        ("cntUsage", wt.DWORD),
        ("th32ProcessID", wt.DWORD),
        ("th32DefaultHeapID", ctypes.POINTER(wt.ULONG)),
        ("th32ModuleID", wt.DWORD),
        ("cntThreads", wt.DWORD),
        ("th32ParentProcessID", wt.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wt.DWORD),
        ("szExeFile", ctypes.c_wchar * 260),
    ]


_kernel32.CreateToolhelp32Snapshot.argtypes = [wt.DWORD, wt.DWORD]
_kernel32.CreateToolhelp32Snapshot.restype = _HANDLE
_kernel32.Process32FirstW.argtypes = [_HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
_kernel32.Process32NextW.argtypes = [_HANDLE, ctypes.POINTER(PROCESSENTRY32W)]


# ============================================================================
# 注入流程的基础设施：身份校验 / 挂起窗口 / 远端模块与 PE 身份回读
# ============================================================================
# 注入要同时保证三件事，任何一件不成立都会表现成“钩子没装上 / 事件全 0”：
#   1) **注对进程**：这个 PID 的映像路径必须是配置里的 ``game_path\LimbusCompany.exe``
#      （同名残留进程、别的副本、Steam 拉起的短命引导进程都要排除）；
#   2) **注对时机**：在“进程线程挂起 / 游戏还没跑起来”的窗口里注入。进程本来就处于挂起态
#      就直接借用；否则临时挂起它的全部线程，注入完只恢复我们自己加的那次挂起
#      —— 这样注入是原子的，不可能因为“游戏已经跑起来”而漏掉早期观测点；
#   3) **注对文件**：注入后回读远端模块表，确认加载的是这份 DLL 的完整路径
#      （``LoadLibraryW`` 遇到同名已加载模块只会返回旧句柄，不会重新加载）。
# 另外把“偏移量还能不能用”在**注入前**就查清楚（``_run_preflight`` →
# ``functions/hook/preflight.py``）：先用偏移量对**本机 GameAssembly.dll** 逐条比 prologue
# （不联网）；对不上才与云端对照（采用云端新版）；云端也对不上就本地重建并按需上传。
# 注入之后再比一次**进程内**的 GameAssembly.dll（``_verify_gameassembly``）作为收尾。
TH32CS_SNAPTHREAD = 0x00000004
TH32CS_SNAPMODULE = 0x00000008
TH32CS_SNAPMODULE32 = 0x00000010
THREAD_SUSPEND_RESUME = 0x0002
PROCESS_QUERY_LIMITED = 0x1000
SYNCHRONIZE = 0x00100000
SUSPEND_FAILED = 0xFFFFFFFF
GAME_STABLE_SECONDS = 1.0        # 与 resources/mod_loader/_internal/main.py 的判定约定一致
MODULE_VERIFY_SECONDS = 5.0      # 注入后回读远端模块的上限
GA_VERIFY_RETRY = 3              # 进程内 GameAssembly.dll 没枚举到时的重试次数
PE_HEADER_BYTES = 0x400


class THREADENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wt.DWORD),
        ("cntUsage", wt.DWORD),
        ("th32ThreadID", wt.DWORD),
        ("th32OwnerProcessID", wt.DWORD),
        ("tpBasePri", ctypes.c_long),
        ("tpDeltaPri", ctypes.c_long),
        ("dwFlags", wt.DWORD),
    ]


class MODULEENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wt.DWORD),
        ("th32ModuleID", wt.DWORD),
        ("th32ProcessID", wt.DWORD),
        ("GlblcntUsage", wt.DWORD),
        ("ProccntUsage", wt.DWORD),
        ("modBaseAddr", ctypes.c_void_p),
        ("modBaseSize", wt.DWORD),
        ("hModule", _HANDLE),
        ("szModule", ctypes.c_wchar * 256),
        ("szExePath", ctypes.c_wchar * 260),
    ]


_kernel32.Thread32First.argtypes = [_HANDLE, ctypes.POINTER(THREADENTRY32)]
_kernel32.Thread32Next.argtypes = [_HANDLE, ctypes.POINTER(THREADENTRY32)]
_kernel32.Module32FirstW.argtypes = [_HANDLE, ctypes.POINTER(MODULEENTRY32W)]
_kernel32.Module32NextW.argtypes = [_HANDLE, ctypes.POINTER(MODULEENTRY32W)]
_kernel32.OpenThread.restype = _HANDLE
_kernel32.OpenThread.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
_kernel32.SuspendThread.argtypes = [_HANDLE]
_kernel32.SuspendThread.restype = wt.DWORD
_kernel32.ResumeThread.argtypes = [_HANDLE]
_kernel32.ResumeThread.restype = wt.DWORD
_kernel32.QueryFullProcessImageNameW.argtypes = [_HANDLE, wt.DWORD, ctypes.c_wchar_p,
                                                 ctypes.POINTER(wt.DWORD)]
_kernel32.ReadProcessMemory.argtypes = [_HANDLE, _LPVOID, _LPVOID, ctypes.c_size_t,
                                        ctypes.POINTER(ctypes.c_size_t)]
_kernel32.GetProcessTimes.argtypes = [_HANDLE, ctypes.POINTER(wt.FILETIME),
                                      ctypes.POINTER(wt.FILETIME),
                                      ctypes.POINTER(wt.FILETIME),
                                      ctypes.POINTER(wt.FILETIME)]


# 最近一次 dll_path() 的选择说明（多份候选同时存在时用来说清楚“注的是哪一份”）
_DLL_CHOICE_NOTE = ""


def _process_image_path(pid: int) -> str:
    """进程映像的完整路径（不是命令行，也不受工作目录影响）。"""
    proc = _kernel32.OpenProcess(PROCESS_QUERY_LIMITED, False, pid)
    if not proc:
        return ""
    try:
        size = wt.DWORD(1024)
        buf = ctypes.create_unicode_buffer(1024)
        if _kernel32.QueryFullProcessImageNameW(proc, 0, buf, ctypes.byref(size)):
            return buf.value
    except Exception:  # noqa: BLE001
        pass
    finally:
        _kernel32.CloseHandle(proc)
    return ""


def _process_start_time(pid: int) -> int:
    """进程创建时间（FILETIME 合成长整数；拿不到返回 0）。同名多进程时用它挑最新的。"""
    proc = _kernel32.OpenProcess(PROCESS_QUERY_LIMITED, False, pid)
    if not proc:
        return 0
    try:
        created = wt.FILETIME()
        empty = wt.FILETIME()
        if _kernel32.GetProcessTimes(proc, ctypes.byref(created), ctypes.byref(empty),
                                     ctypes.byref(empty), ctypes.byref(empty)):
            return (int(created.dwHighDateTime) << 32) | int(created.dwLowDateTime)
    except Exception:  # noqa: BLE001
        pass
    finally:
        _kernel32.CloseHandle(proc)
    return 0


def _expected_game_exe() -> str:
    """配置里那台游戏的可执行文件完整路径（拿不到返回空串 → 跳过身份校验）。"""
    try:
        from functions.hook.paths import game_paths
        paths = game_paths()
        root = str(getattr(paths, "root", "") or "")
        if root:
            return os.path.join(root, TARGET_PROCESS)
    except Exception:  # noqa: BLE001
        pass
    return ""


def _expected_gameassembly() -> str:
    """配置里那台游戏的 GameAssembly.dll 路径（拿不到返回空串）。"""
    try:
        from functions.hook.paths import game_paths
        return str(getattr(game_paths(), "gameassembly", "") or "")
    except Exception:  # noqa: BLE001
        return ""


def _same_file(a: str, b: str) -> bool:
    if not a or not b:
        return False
    try:
        return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))
    except Exception:  # noqa: BLE001
        return False


def find_process_candidates(process_name: str = TARGET_PROCESS) -> list[tuple[int, str]]:
    """所有同名进程的 ``(pid, 映像完整路径)`` 列表（不保证顺序）。"""
    wanted = process_name.lower()
    if not wanted.endswith(".exe"):
        wanted += ".exe"
    snapshot = _kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    out: list[tuple[int, str]] = []
    if not snapshot or snapshot == -1:
        return out
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        ok = _kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while ok:
            if str(entry.szExeFile).lower() == wanted:
                pid = int(entry.th32ProcessID)
                out.append((pid, _process_image_path(pid)))
            ok = _kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        _kernel32.CloseHandle(snapshot)
    return out


def select_game_process(process_name: str = TARGET_PROCESS) -> tuple[int | None, str, str]:
    """挑出真正要注入的游戏进程。返回 ``(pid, 映像路径, 说明)``。

    优先级：映像路径 == 配置的游戏 exe；同名多进程时取创建时间最新的那个。
    """
    expected = _expected_game_exe()
    candidates = find_process_candidates(process_name)
    if not candidates:
        return None, "", ""
    if expected:
        for pid, image in candidates:
            if image and _same_file(image, expected):
                return pid, image, ""
    if len(candidates) > 1:
        candidates.sort(key=lambda item: _process_start_time(item[0]), reverse=True)
        pid, image = candidates[0]
        return pid, image, (f"发现 {len(candidates)} 个同名进程，取创建时间最新的 PID {pid}"
                            f"（映像 {image or '未知'}）")
    pid, image = candidates[0]
    if expected and image and not _same_file(image, expected):
        return pid, image, f"映像 {image} 与配置 {expected} 不一致（唯一同名进程，仍尝试注入）"
    return pid, image, ""


# 是否已确认“本进程是唯一的成就监测实例”（由 hook.py 拿到单实例互斥体后置位）。
# 只有它为真时，_open_map 才允许**接管**上次遗留的共享内存 —— 否则两实例会双钩。
_SOLE_INSTANCE = False


def set_sole_instance(value: bool = True) -> None:
    """由 hook.py 在拿到单实例互斥体后调用。"""
    global _SOLE_INSTANCE
    _SOLE_INSTANCE = bool(value)


def sole_instance() -> bool:
    return _SOLE_INSTANCE


def find_process_id(process_name: str = TARGET_PROCESS) -> int | None:
    """兼容旧入口：返回第一个同名进程 PID（``--probe``/``--status`` 用）。"""
    candidates = find_process_candidates(process_name)
    return candidates[0][0] if candidates else None


def pid_alive_for(pid: int, seconds: float) -> bool:
    """进程在 ``seconds`` 秒内是否一直存活（句柄判定，不受 PID 复用影响）。"""
    handle = _kernel32.OpenProcess(SYNCHRONIZE, False, pid)
    if not handle:
        return False
    try:
        return _kernel32.WaitForSingleObject(handle, int(seconds * 1000)) == 0x00000102
    finally:
        _kernel32.CloseHandle(handle)


def remote_modules(pid: int) -> list[tuple[str, str, int]]:
    """目标进程已加载模块的 ``(模块名, 完整路径, 基址)``（失败返回空列表）。"""
    snapshot = _kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32,
                                                  pid)
    out: list[tuple[str, str, int]] = []
    if not snapshot or snapshot == -1:
        return out
    try:
        entry = MODULEENTRY32W()
        entry.dwSize = ctypes.sizeof(MODULEENTRY32W)
        ok = _kernel32.Module32FirstW(snapshot, ctypes.byref(entry))
        while ok:
            out.append((str(entry.szModule), str(entry.szExePath),
                        int(entry.modBaseAddr or 0)))
            ok = _kernel32.Module32NextW(snapshot, ctypes.byref(entry))
    finally:
        _kernel32.CloseHandle(snapshot)
    return out


def read_remote(pid: int, address: int, size: int) -> bytes:
    """读目标进程内存（只读，读不到返回空串）。"""
    proc = _kernel32.OpenProcess(PROCESS_QUERY_LIMITED | 0x0010, False, pid)
    if not proc:
        return b""
    try:
        buf = ctypes.create_string_buffer(size)
        got = ctypes.c_size_t()
        if _kernel32.ReadProcessMemory(proc, ctypes.c_void_p(address), buf, size,
                                       ctypes.byref(got)):
            return buf.raw[:int(got.value)]
    except Exception:  # noqa: BLE001
        pass
    finally:
        _kernel32.CloseHandle(proc)
    return b""


def _parse_pe_header(head: bytes) -> dict:
    """从 PE 头部字节里取身份字段（时间戳 / 映像大小 / 入口 RVA）。

    ⚠ 不要拿整段头部哈希当判据：加载器会往头部写几个字节（实测 python.exe 偏移
    0x13A 处存的是模块基址），磁盘文件与内存映像的头部并不逐字节相等；
    ``header_sha256`` 只当诊断信息保留。
    """
    import hashlib
    import struct as _struct
    info = {"timestamp": 0, "size_of_image": 0, "entry_rva": 0, "header_sha256": ""}
    if len(head) < 0x40 or head[:2] != b"MZ":
        return info
    e_lfanew = _struct.unpack_from("<I", head, 0x3C)[0]
    if e_lfanew + 0x40 > len(head) or head[e_lfanew:e_lfanew + 4] != b"PE\0\0":
        return info
    opt = e_lfanew + 24
    info["timestamp"] = _struct.unpack_from("<I", head, e_lfanew + 8)[0]
    info["entry_rva"] = _struct.unpack_from("<I", head, opt + 16)[0]
    info["size_of_image"] = _struct.unpack_from("<I", head, opt + 56)[0]
    info["header_sha256"] = hashlib.sha256(head).hexdigest().upper()
    return info


def pe_identity_same(a: dict, b: dict) -> bool:
    """两份 PE 身份是不是同一份构建：时间戳 + 映像大小 + 入口 RVA。"""
    if not a or not b:
        return False
    for key in ("timestamp", "size_of_image", "entry_rva"):
        if int(a.get(key) or 0) != int(b.get(key) or 0):
            return False
    return True


def local_pe_identity(path: str) -> dict:
    """磁盘上某个 PE 文件的身份字段（前 0x400 字节就够）。"""
    try:
        with open(path, "rb") as fh:
            return _parse_pe_header(fh.read(PE_HEADER_BYTES))
    except OSError:
        return {"timestamp": 0, "size_of_image": 0, "entry_rva": 0, "header_sha256": ""}


def remote_pe_identity(pid: int, module_name: str = "gameassembly.dll") -> dict:
    """进程内某个模块的 PE 身份（含基址/路径）；没加载时返回空 dict。"""
    wanted = module_name.lower()
    for name, path, base in remote_modules(pid):
        if name.lower() != wanted or not base:
            continue
        info = _parse_pe_header(read_remote(pid, base, PE_HEADER_BYTES))
        if not info["timestamp"] and not info["size_of_image"]:
            return {}
        info.update({"base": base, "path": path, "module": name})
        return info
    return {}


def dll_info(path: str) -> dict:
    """要注入的那份 DLL 的文件身份（大小 / 修改时间 / 哈希），用于日志自证“注的是哪份”。"""
    import hashlib
    out = {"path": path, "size": 0, "mtime": "", "sha256": ""}
    try:
        st = os.stat(path)
        with open(path, "rb") as fh:
            out["sha256"] = hashlib.sha256(fh.read()).hexdigest().upper()
        out["size"] = int(st.st_size)
        out["mtime"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(st.st_mtime))
    except OSError:
        pass
    return out


class SuspendWindow:
    """注入窗口：在“进程线程挂起”的状态下做注入，退出时精确恢复。

    - 逐线程把 ``SuspendThread`` 的返回值当“既有挂起计数”：返回 0 = 这次挂起是我们加的
      （退出时恢复一次）；返回 >0 = 线程本来就挂起，立刻回滚，**不替游戏恢复它自己的挂起**。
    - 全部线程在进入前就已挂起 → 说明进程当前处于挂起态，直接借用这个窗口（这正是
      “检测到进程挂起再注入”想要的效果；Steam 拉起的进程通常不会挂起，所以更多时候
      是我们自己建立窗口）。
    """

    def __init__(self, pid: int, log=None) -> None:
        self.pid = pid
        self.log = log or (lambda _m: None)
        self.thread_ids: list[int] = []
        self.owned: list[int] = []      # 我们加了挂起的线程 id
        self.already = 0                # 进入前就已挂起的线程数
        self.was_suspended = False      # 进入前整个进程是否已挂起

    def _enumerate_threads(self) -> list[int]:
        snapshot = _kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0)
        if not snapshot or snapshot == -1:
            return []
        out: list[int] = []
        try:
            entry = THREADENTRY32()
            entry.dwSize = ctypes.sizeof(THREADENTRY32)
            ok = _kernel32.Thread32First(snapshot, ctypes.byref(entry))
            while ok:
                if int(entry.th32OwnerProcessID) == self.pid:
                    out.append(int(entry.th32ThreadID))
                ok = _kernel32.Thread32Next(snapshot, ctypes.byref(entry))
        finally:
            _kernel32.CloseHandle(snapshot)
        return out

    def __enter__(self) -> "SuspendWindow":
        self.thread_ids = self._enumerate_threads()
        for tid in self.thread_ids:
            handle = _kernel32.OpenThread(THREAD_SUSPEND_RESUME, False, tid)
            if not handle:
                continue
            try:
                prev = int(_kernel32.SuspendThread(handle))
                if prev == SUSPEND_FAILED:
                    continue
                if prev == 0:
                    self.owned.append(tid)
                else:
                    self.already += 1
                    _kernel32.ResumeThread(handle)      # 回滚，保持它原本的挂起状态
            finally:
                _kernel32.CloseHandle(handle)
        total = len(self.thread_ids)
        self.was_suspended = bool(total) and not self.owned and self.already >= total
        if self.was_suspended:
            self.log(f"[战斗观测] 检测到游戏进程已处于挂起态（{total}/{total} 个线程挂起）"
                     "→ 直接在这个挂起窗口内注入")
        elif self.owned:
            self.log(f"[战斗观测] 已建立注入窗口：挂起 {len(self.owned)} 个线程"
                     f"（共 {total} 个，其中 {self.already} 个本来就挂起）")
        else:
            self.log(f"[战斗观测] 未能挂起任何线程（共 {total} 个），按普通方式注入")
        return self

    def __exit__(self, *_exc) -> bool:
        for tid in self.owned:
            handle = _kernel32.OpenThread(THREAD_SUSPEND_RESUME, False, tid)
            if not handle:
                continue
            try:
                _kernel32.ResumeThread(handle)
            finally:
                _kernel32.CloseHandle(handle)
        if self.owned:
            self.log(f"[战斗观测] 注入窗口关闭：恢复 {len(self.owned)} 个线程")
        self.owned = []
        return False


def _project_root() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.abspath(os.path.join(here, "..", ".."))


def _pick_newest_dll(candidates: list[str]) -> tuple[str, str]:
    """从候选路径里取 mtime 最新的一份。返回 ``(路径, 说明)``（说明为空 = 只有一份）。"""
    found: list[tuple[str, float]] = []
    seen: set[str] = set()
    for path in candidates:
        if not path or not os.path.isfile(path):
            continue
        key = os.path.normcase(os.path.abspath(path))
        if key in seen:
            continue
        seen.add(key)
        try:
            found.append((path, os.path.getmtime(path)))
        except OSError:
            continue
    if not found:
        return "", ""
    found.sort(key=lambda item: item[1], reverse=True)
    if len(found) == 1:
        return found[0][0], ""
    others = ", ".join(f"{p}（{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(t))}）"
                       for p, t in found[1:])
    note = (f"发现 {len(found)} 份 battle_watch.dll，选用最新的一份 {found[0][0]}；"
            f"忽略: {others}")
    return found[0][0], note


def dll_path() -> str:
    """要注入的 battle_watch.dll（发布包里就是编译好的那份，**不会**在注入前现编译）。

    候选里可能同时存在多份（``_MEIPASS`` 打包副本 / 开发目录刚编译的 / ``_internal`` 部署的），
    此时取 **mtime 最新** 的一份 —— 否则开发目录里重新 build 之后，打包版会一直注入包里那份旧
    DLL，表现就是“改了代码/新功能没生效，因为注进去的还是旧 DLL”。选择结果记在
    ``_DLL_CHOICE_NOTE`` 里，由驱动与 ``--probe`` 输出出来。
    """
    global _DLL_CHOICE_NOTE
    here = os.path.dirname(os.path.abspath(__file__))
    root = _project_root()
    candidates = [
        os.path.join(here, "hook_dll", "battle_watch.dll"),
        os.path.join(root, "hook_dll", "battle_watch.dll"),
        os.path.join(root, "_internal", "hook_dll", "battle_watch.dll"),
        os.path.join(root, "resources", "achievement_hook", "battle_watch.dll"),
        os.path.join(here, "battle_watch.dll"),
    ]
    meipass = getattr(sys, "_MEIPASS", "")
    if meipass:
        candidates.insert(0, os.path.join(meipass, "hook_dll", "battle_watch.dll"))
    chosen, _DLL_CHOICE_NOTE = _pick_newest_dll(candidates)
    return chosen


def event_log_path() -> str:
    return os.path.join(_project_root(), "logs", "battle_watch.log")


def status_path() -> str:
    return os.path.join(_project_root(), "cache", "achievement", "battle_watch_status.json")


# --------------------------------------------------------------------------- 事件 / 状态

_KV_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)=(-?\d+)")


@dataclass
class BattleEvent:
    kind: str
    values: dict = field(default_factory=dict)
    tag: str = ""
    raw: str = ""
    ts: float = 0.0

    def get(self, key: str, default: int = 0) -> int:
        try:
            return int(self.values.get(key, default))
        except (TypeError, ValueError):
            return default

    def opt(self, key: str):
        """取不到就返回 ``None``（区别于 ``get`` 的 0 兜底）——用于「DLL 可选附加字段」。"""
        if key not in self.values:
            return None
        try:
            return int(self.values[key])
        except (TypeError, ValueError):
            return None


@dataclass
class BattleState:
    round_seq: int = 0
    units: dict = field(default_factory=dict)        # instanceID → originID
    speeds: dict = field(default_factory=dict)       # instanceID → {oid,os,ow,its,eff,os_raw,ow_raw}
    vitals: dict = field(default_factory=dict)       # instanceID → {oid,hp,mhp,mp,tag,round}
    buffs: dict = field(default_factory=dict)        # instanceID → {oid,mask,names,tag,round}
    skills: list = field(default_factory=list)       # 本回合 ACTION 事件（未结算）
    flags: dict = field(default_factory=dict)        # 规则 key → 命中详情（含本回合已结算的）
    flag_seq: dict = field(default_factory=dict)     # 规则 key → 命中序号（复合成就判“先后顺序”用）
    pending_flags: dict = field(default_factory=dict)  # 技能类规则本回合待结算：key → 详情
    pending_immediate: dict = field(default_factory=dict)  # hp/理智/buff 待动画放行：key → 详情
    pending_seqs: dict = field(default_factory=dict)   # key → 入队序号（跨类型按先后放行）
    pending_seq: int = 0                               # 入队计数器
    anim_ticks_total: int = 0                          # 收到的动画 tick 数（skv_*）
    anim_last_tag: str = ""                            # 最近一次 tick 的钩子名
    acts_total: int = 0
    spd_total: int = 0
    vitals_total: int = 0
    buff_total: int = 0
    rnd_total: int = 0
    settled_by: str = ""
    flag_counter: int = 0

    def snapshot(self) -> dict:
        """状态文件内容：全部由规则表驱动，不含任何成就专属字段。"""
        watched = watched_identities()
        speeds = {iid: info for iid, info in self.speeds.items()
                  if not watched or info.get("oid") in watched}
        vitals = {iid: info for iid, info in self.vitals.items()
                  if not watched or info.get("oid") in watched}
        buffs = {iid: info for iid, info in self.buffs.items()
                 if not watched or info.get("oid") in watched}
        return {
            "round_seq": self.round_seq,
            "units": len(self.units),
            "acts_total": self.acts_total,
            "spd_total": self.spd_total,
            "vitals_total": self.vitals_total,
            "rnd_total": self.rnd_total,
            "pending_skills": len(self.skills),
            "settled_by": self.settled_by,
            "rules": {key: {"kind": rule.kind, "label": rule.label,
                            "targets": list(rule.identity_ids),
                            "threshold": rule.threshold_text()}
                      for key, rule in sorted(registered_rules().items())},
            "rule_hits": dict(self.flags),
            "rule_order": dict(self.flag_seq),
            "rule_pending": sorted(self.pending_flags),
            "rule_pending_immediate": sorted(self.pending_immediate),
            "anim_ticks": self.anim_ticks_total,
            "anim_last_tag": self.anim_last_tag,
            "watched_speeds": speeds,
            "watched_vitals": vitals,
            "watched_buffs": buffs,
            "watched_buff_names": list(watched_buff_names()),
            "buff_total": self.buff_total,
        }


# --------------------------------------------------------------------------- 静态解析


def _read_at_rva(pe, rva: int, size: int) -> bytes:
    try:
        return pe.read_at_rva(rva, size)
    except Exception:
        return b""


def resolve_stub(pe, rva: int, names: dict, max_hops: int = 4,
                 on_log=None) -> tuple[int, list]:
    """跟随 IL2CPP 尾调用桩（``33 D2 E9 rel32`` / ``E9 rel32``），返回真实 RVA。

    返回 ``(最终 RVA, 跳转链 [(rva, name, 说明), ...])``。
    """
    import struct
    log = on_log or (lambda _m: None)
    hops = []
    current = rva
    for _ in range(max_hops):
        raw = _read_at_rva(pe, current, 16)
        if len(raw) < 8:
            break
        target = None
        if raw[0] == 0x33 and raw[1] == 0xD2 and raw[2] == 0xE9:
            target = current + 7 + struct.unpack_from("<i", raw, 3)[0]
            kind = "尾调用桩 (xor edx,edx; jmp)"
        elif raw[0] == 0xE9:
            target = current + 5 + struct.unpack_from("<i", raw, 1)[0]
            kind = "jmp 桩"
        if target is None or target == current:
            break
        hops.append((current, names.get(current, "?"), kind, target, names.get(target, "?")))
        log(f"[战斗观测] 0x{current:X} ({names.get(current, '?')}) 是{kind}"
            f" → 改钩 0x{target:X} ({names.get(target, '?')})")
        current = target
    return current, hops


def build_hook_table(on_log=None, pe_path: str = "") -> dict:
    """构造要下发给 DLL 的钩子表（RVA/prologue/kind/名字）。

    - RVA 优先取 hook_index（云端/本地缓存），缺失用内置回退值；
    - 遇到尾调用桩就解引用到真实实现；
    - 同一地址自动合并（保留第一个，日志记录被合并的键）。
    """
    log = on_log or (lambda _m: None)
    entries: dict[str, dict] = {}
    source = "fallback"

    # 1) 默认：内置回退
    for key, (symbol, rva, kind) in FALLBACK_HOOKS.items():
        entries[key] = {"key": key, "symbol": symbol, "rva": rva, "kind": kind,
                        "prologue": "", "source": "fallback"}

    # 2) 索引覆盖（RVA + prologue）
    index = None
    try:
        from functions.hook.index import get_index
        index, idx_source = get_index()
        if index is not None:
            source = idx_source or "index"
            for key in list(entries):
                hook = index.hook(key)
                if hook.get("rva"):
                    entries[key]["rva"] = int(hook["rva"])
                    entries[key]["source"] = source
                text = str(hook.get("prologue") or "").replace(" ", "")
                if text:
                    try:
                        entries[key]["prologue"] = bytes.fromhex(text)
                    except ValueError:
                        pass
    except Exception as exc:  # noqa: BLE001
        log(f"[战斗观测] hook_index 不可用，使用内置回退偏移: {exc}")

    # 3) 符号名 → RVA 反查表（把解引用结果翻译成可读名字）
    names: dict[int, str] = {}
    if index is not None:
        for key, item in (index.symbols.get("methods") or {}).items():
            rva = int(item.get("rva") or 0) if isinstance(item, dict) else int(item or 0)
            if rva:
                names.setdefault(rva, key)

    # 4) 尾调用桩解引用 + prologue 重算（用本机 DLL 文件的字节）
    pe = None
    if pe_path and os.path.isfile(pe_path):
        try:
            from functions.hook.pe import PeFile
            pe = PeFile(pe_path)
        except Exception as exc:  # noqa: BLE001
            log(f"[战斗观测] 读取 GameAssembly.dll 节表失败（跳过桩解引用）: {exc}")
    resolved: dict[str, dict] = {}
    used_rva: dict[int, str] = {}
    for key, item in entries.items():
        rva = int(item["rva"])
        if pe is not None and key not in NO_STUB_RESOLVE:
            final, hops = resolve_stub(pe, rva, names, on_log=log)
            item["stub_hops"] = [list(h) for h in hops]
            rva = final
        item["final_rva"] = rva
        if pe is not None and (not item["prologue"] or item.get("stub_hops")):
            data = pe.prologue(rva, 16)
            if data and len(data) == 16:
                item["prologue"] = data
        key_owner = used_rva.get(rva)
        if key_owner is not None:
            log(f"\n[战斗观测] {key} 与 {key_owner} 指向同一地址 0x{rva:X}，"
                f"已合并（{HOOK_MERGE_WARN}）")
            resolved[key_owner].setdefault("merged_keys", []).append(key)
            continue
        used_rva[rva] = key
        resolved[key] = item
    if len(resolved) > MAX_HOOKS:
        log(f"[战斗观测] 候选 {len(resolved)} 个超过 DLL 上限 {MAX_HOOKS}，只取前 {MAX_HOOKS} 个")
        resolved = {k: v for k, v in list(resolved.items())[:MAX_HOOKS]}
    return {"entries": resolved, "source": source, "names": names,
            "index_available": index is not None}


def describe_hook_table(table: dict) -> str:
    lines = []
    for i, (key, item) in enumerate(table["entries"].items()):
        pro = (item.get("prologue") or b"")[:8]
        lines.append(f"    [{i:2}] {key:32} 0x{int(item['final_rva']):X} "
                     f"kind={item['kind']:14} prologue={pro.hex(' ')}"
                     + (f"  已合并: {item['merged_keys']}" if item.get("merged_keys") else ""))
    return "\n".join(lines)


# --------------------------------------------------------------------------- 驱动


class BattleWatch:
    """注入 DLL + 抽事件 + 维护 ``BattleState``（后台线程）。"""

    def __init__(self, log_callback=None, poll_interval: float = 0.25,
                 process_name: str = TARGET_PROCESS, verbose: bool = False) -> None:
        self.log_callback = log_callback or (lambda _m: None)
        self.poll_interval = max(0.1, float(poll_interval))
        self.process_name = process_name
        self.verbose = verbose
        self.state = BattleState()
        self.table: dict = {}

        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._map_handle = None
        self._map_view = None
        self._injected_pid: int | None = None
        self._remote_module: int | None = None
        self._drained_head = 0
        self._status_logged: set[str] = set()
        self._last_hits: dict[str, int] = {}
        self._boundary_keys: set[str] = set()
        self._last_event_ts = 0.0
        self._last_heartbeat = 0.0
        self._last_status_write = 0.0
        self._last_boundary_ts = 0.0
        self._event_file = None
        self._phase = "未启动"
        # 注入现场（状态文件里能直接看到“注的是哪个进程/哪份 DLL”）
        self._injected_image = ""
        self._injected_dll = ""
        # 游戏 DLL（GameAssembly.dll）新鲜度校验结果
        self._ga_verified = False
        self._ga_retry = 0
        self._ga_note: dict = {}
        self._index_game_note: dict = {}
        self._preflight: dict = {}

    # ---------------------------------------------------------------- 对外
    def start(self) -> bool:
        if self._thread and self._thread.is_alive():
            return True
        self._stop.clear()
        self._thread = threading.Thread(target=self._run_guarded, name="battle-watch",
                                        daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)
        self._eject()
        self._close_map()
        self._close_event_file()

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive() and not self._stop.is_set())

    def settle_turn(self, reason: str = "", fallback_immediate: bool = True,
                    only_skills: bool = False) -> list:
        """结算：技能类规则置位（+ 立刻类规则拿最后观测值兜底复核）。

        调用时机：

        - **技能动画结束**（``action_done_with_action`` / ``action_on_end_turn`` 事件），
          以及一段静默期之后 —— ``settle_turn(reason, only_skills=True)``；
        - **回合边界** —— 全量结算（含立刻类兜底复核）。

        返回本回合已结算的技能事件列表。注意：``_write_status`` 必须在**锁外**调用
        （它内部会 ``snapshot()`` 再拿同一把非重入锁）。
        """
        settled: list[str] = []
        with self._lock:
            pending = list(self.state.skills)
            self.state.skills.clear()
            if pending:
                self.state.settled_by = reason
            # 挂起的判定（技能 + 等动画的 hp/理智/buff）按先后顺序全部放行
            flushed = self._flush_all_pending_locked()
            if flushed:
                self.state.settled_by = reason
                settled.extend(flushed)
            if fallback_immediate:
                suffix = f"{reason or '回合边界'}兜底"
                # 立刻类规则（速度/理智/血量/buff）：统一拿最后一次观测复核
                for info in list(self.state.vitals.values()):
                    settled += self._eval_immediate_locked(
                        lambda rule, i=info: rule.match_vitals(
                            i.get("oid", -1), i.get("hp", VITAL_UNREAD),
                            i.get("mhp", VITAL_UNREAD), i.get("mp", VITAL_UNREAD)),
                        lambda rule, i=info: self._vitals_detail(rule, i, suffix))
                for speeds in list(self.state.speeds.values()):
                    oid = speeds.get("oid", -1)
                    settled += self._eval_immediate_locked(
                        lambda rule, o=oid, s=speeds: rule.match_speed(o, s)[0],
                        lambda rule, o=oid, s=speeds: self._speed_detail(rule, o, s, suffix))
                for info in list(self.state.buffs.values()):
                    names = set(info.get("names") or ())
                    settled += self._eval_immediate_locked(
                        lambda rule, i=info, n=names: rule.match_buff(
                            i.get("oid", -1), n, self.state.round_seq)[0],
                        lambda rule, i=info, n=names: self._buff_detail(rule, i, suffix, n))
                settled += self._eval_presence_locked()
                # 兜底复核可能刚刚挂起新的判定（例：规则是后登记的）→ 一并放行
                more = self._flush_all_pending_locked()
                if more:
                    settled.extend(more)
        if only_skills and not settled and not pending:
            return pending
        for detail in settled:
            self._log(f"[战斗观测] ★ {detail}")
        self._write_status(force=True)
        return pending

    def settle_skills_if_quiet(self, reason: str = "技能动画结束（静默）") -> bool:
        """静默期兜底：有待结算技能且距上次事件超过阈值 → 结算技能类规则。

        动画结束时游戏不一定会调我们钩到的收尾函数（且不同技能收尾时机不一），
        所以主循环每隔一小段就来看一眼：事件停了就当作“这一手的动画放完了”。
        """
        with self._lock:
            if not self.state.pending_flags and not self.state.pending_immediate:
                return False
            quiet = time.time() - self._last_event_ts
        if quiet < SKILL_SETTLE_QUIET_SEC:
            return False
        return bool(self.settle_turn(reason, fallback_immediate=False,
                                     only_skills=True))

    def rule_detail(self, key: str) -> str | None:
        """规则是否命中；命中返回详情文本（未命中返回 None）。"""
        with self._lock:
            detail = self.state.flags.get(key)
        return detail or None

    def rule_order(self, key: str) -> int:
        """规则命中的先后序号（越小越早；未命中返回 0）—— 复合成就判顺序用。"""
        with self._lock:
            return int(self.state.flag_seq.get(key, 0))

    def rule_live(self, key: str) -> bool:
        """按**当前观测**重新判一次规则（不置位）—— 给复合成就的“状态条件”用。

        例如“满足前面两步后，现在场上是否存在拇指子辈希斯克里夫”：这是一条**状态**
        而不是事件顺序（他从第一回合就在场，不能因为记录得早而算顺序不对），
        所以要在检查的那一刻拿单位表/观测快照来判。
        """
        rule = registered_rules().get(key)
        if rule is None:
            return False
        with self._lock:
            round_seq = self.state.round_seq
            if rule.kind == RULE_KIND_PRESENCE:
                return any(rule.match_presence(oid, round_seq)
                           for oid in set(self.state.units.values()))
            if rule.kind in (RULE_KIND_MENTAL, RULE_KIND_HP):
                for info in self.state.vitals.values():
                    if rule.match_vitals(info.get("oid", -1), info.get("hp", VITAL_UNREAD),
                                         info.get("mhp", VITAL_UNREAD),
                                         info.get("mp", VITAL_UNREAD)):
                        return True
                return False
            if rule.kind == RULE_KIND_SPEED:
                for info in self.state.speeds.values():
                    if rule.match_speed(info.get("oid", -1), info)[0]:
                        return True
                return False
            if rule.kind == RULE_KIND_BUFF:
                for info in self.state.buffs.values():
                    if rule.match_buff(info.get("oid", -1),
                                       set(info.get("names") or ()), round_seq)[0]:
                        return True
                return False
        return False

    def snapshot(self) -> dict:
        with self._lock:
            snap = self.state.snapshot()
        snap["phase"] = self._phase
        snap["injected_pid"] = self._injected_pid
        snap["hook_hits"] = dict(self._last_hits)
        if self._injected_image or self._injected_dll:
            snap["injection"] = {
                "image": self._injected_image,
                "dll": self._injected_dll,
                "dll_info": dll_info(self._injected_dll) if self._injected_dll else {},
            }
        if self._index_game_note:
            snap["index_game"] = dict(self._index_game_note)
        if self._preflight:
            snap["preflight"] = dict(self._preflight)
        if self._ga_note:
            snap["gameassembly_check"] = dict(self._ga_note)
        return snap

    # ---------------------------------------------------------------- 事件日志
    def _open_event_file(self) -> None:
        """全量事件日志：**每次实例运行都清空重写**（只留本次运行，便于对照）。"""
        if self._event_file is not None:
            return
        path = event_log_path()
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            # utf-8-sig = 带 BOM 的 UTF-8：记事本 / PowerShell 5.1 的 Get-Content
            # 才能正确识别编码（无 BOM 会被当成 GBK 读成“乱码”）
            self._event_file = open(path, "w", encoding="utf-8-sig", buffering=1)
            self._event_file.write(f"==== 会话开始 {time.strftime('%Y-%m-%d %H:%M:%S')} "
                                   f"====\n")
        except OSError:
            self._event_file = None

    def _close_event_file(self) -> None:
        if self._event_file is not None:
            try:
                self._event_file.close()
            except OSError:
                pass
            self._event_file = None

    def _event(self, message: str) -> None:
        """只写事件日志（不进成就日志），用于全量事件记录。"""
        if self._event_file is not None:
            try:
                # 带毫秒：结算阶段（一回合的伤害/收尾）全挤在同一秒里，只有毫秒能看清先后
                self._event_file.write(
                    f"{time.strftime('%H:%M:%S')}.{int(time.time() * 1000) % 1000:03d} "
                    f"{message}\n")
            except OSError:
                pass

    # ---------------------------------------------------------------- 状态文件
    def _write_status(self, force: bool = False) -> None:
        now = time.time()
        if not force and now - self._last_status_write < STATUS_WRITE_SEC:
            return
        self._last_status_write = now
        data = self.snapshot()
        data["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        data["dll_path"] = dll_path()
        data["offsets_source"] = self.table.get("source", "")
        data["hooks"] = {key: {"rva": int(item["final_rva"]), "kind": item["kind"],
                               "symbol": item["symbol"],
                               "prologue": (item.get("prologue") or b"")[:8].hex(" "),
                               "hits": self._last_hits.get(key, 0)}
                         for key, item in (self.table.get("entries") or {}).items()}
        try:
            path = status_path()
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=1)
        except OSError:
            pass

    # ---------------------------------------------------------------- 共享内存
    def _open_map(self) -> bool:
        if self._map_view is not None:
            return True
        existing = _kernel32.OpenFileMappingW(0x0006, False, ctypes.c_wchar_p(MAP_NAME))
        if existing:
            view = _kernel32.MapViewOfFile(existing, 0x0006, 0, 0, CONFIG_SIZE)
            if view:
                magic = ctypes.c_int32.from_address(view).value
                if magic == BW_MAGIC:
                    if sole_instance():
                        # 自己已经是唯一实例 → 这块内存只可能是上次遗留的（旧实例被杀，
                        # 但它注入的 DLL 还挂在游戏里）。直接接管：接着用这块内存，
                        # 下面的 _write_config 会把新配置覆盖进去，DLL 照新配置继续报事件。
                        self._map_handle = existing
                        self._map_view = view
                        self._log("[战斗观测] 接管上次遗留的共享内存（本进程是唯一实例；"
                                  "游戏里那份 DLL 若还在，会读到下面写入的新配置）")
                        return True
                    _kernel32.UnmapViewOfFile(view)
                    _kernel32.CloseHandle(existing)
                    self._log("[战斗观测] 共享内存已存在且**还有别的监测实例在跑** → "
                              "本次不注入以免双钩（另一个实例被杀掉后会自动接管）")
                    return False
                _kernel32.UnmapViewOfFile(view)
            _kernel32.CloseHandle(existing)
        handle = _kernel32.CreateFileMappingW(-1, None, 0x04, 0, CONFIG_SIZE,
                                              ctypes.c_wchar_p(MAP_NAME))
        if not handle:
            self._log("[战斗观测] 创建共享内存失败")
            return False
        view = _kernel32.MapViewOfFile(handle, 0x0006, 0, 0, CONFIG_SIZE)
        if not view:
            _kernel32.CloseHandle(handle)
            self._log("[战斗观测] 映射共享内存失败")
            return False
        self._map_handle = handle
        self._map_view = view
        return True

    def _close_map(self) -> None:
        if self._map_view:
            _kernel32.UnmapViewOfFile(self._map_view)
            self._map_view = None
        if self._map_handle:
            _kernel32.CloseHandle(self._map_handle)
            self._map_handle = None

    def _config(self) -> BWConfig | None:
        if self._map_view is None:
            return None
        cfg = BWConfig()
        ctypes.memmove(ctypes.byref(cfg), self._map_view, CONFIG_SIZE)
        return cfg if cfg.magic == BW_MAGIC else None

    def _write_config(self, table: dict) -> bool:
        if self._map_view is None:
            return False
        cfg = BWConfig()
        cfg.magic = BW_MAGIC
        cfg.observing = 1
        cfg.log = 1
        entries = list(table["entries"].items())[:MAX_HOOKS]
        cfg.hook_count = len(entries)
        for i, (key, item) in enumerate(entries):
            cfg.hook_rva[i] = int(item["final_rva"])
            cfg.hook_kind[i] = KIND_NUMBERS.get(str(item["kind"]), KIND_UNIT)
            raw = (item.get("prologue") or b"")[:16].ljust(16, b"\x00")
            cfg.hook_prologue[i][:] = raw
            name = key.encode("utf-8", "replace")[:HOOK_NAME_LEN - 1]
            cfg.hook_name[i][:] = name.ljust(HOOK_NAME_LEN, b"\x00")
        for key, offset in FALLBACK_FIELDS.items():
            field_off = offset
            try:
                from functions.hook.index import get_index
                index, _src = get_index()
                if index is not None:
                    field_off = index.field_offset(key, offset) or offset
            except Exception:
                pass
            attr = "off_" + key
            if hasattr(cfg, attr):
                setattr(cfg, attr, int(field_off))
        ctypes.memmove(self._map_view, ctypes.byref(cfg), CONFIG_SIZE)
        return True

    # ---------------------------------------------------------------- 注入
    def _inject(self, pid: int, path: str, expect_exe: str | None = None) -> bool:
        """把 battle_watch.dll 注入游戏进程。

        ``expect_exe=None`` → 用配置里的游戏 exe 做身份校验；传空串则跳过（离线自检用）。

        流程（任何一步失败都只记日志、不改游戏状态）：
          ① 身份校验：PID 的映像必须是 ``game_path\\LimbusCompany.exe``（排除同名残留进程）；
          ② 检查进程里是否已有一份同名模块（``LoadLibraryW`` 对已加载模块只会返回旧句柄）；
          ③ 在 **SuspendWindow**（进程本来就挂起则直接借用，否则临时挂起全部线程）里
             VirtualAllocEx + WriteProcessMemory + CreateRemoteThread(LoadLibraryW)；
          ④ 窗口关闭后回读远端模块表，确认加载的确实是我们注入的这个路径。
        """
        expected = _expected_game_exe() if expect_exe is None else expect_exe
        image = _process_image_path(pid)
        if expected and image and not _same_file(image, expected):
            self._log(f"[战斗观测] 跳过 PID {pid}：映像是 {image}，与配置的游戏（{expected}）"
                      "不一致 —— 同名残留进程/别的副本，不注入")
            return False
        info = dll_info(path)
        self._log(f"[战斗观测] 准备注入 {os.path.basename(path)}（{info['size']} 字节，"
                  f"mtime {info['mtime']}，sha256 {info['sha256'][:12]}…）"
                  + (f"；目标映像 {image}" if image else ""))
        want_name = os.path.basename(path).lower()
        for name, mpath, base in remote_modules(pid):
            if name.lower() == want_name:
                self._log(f"[战斗观测] 注意：目标进程已有一份 {name}"
                          f"（{mpath or '路径未知'} @0x{base:X}）—— LoadLibraryW 会直接"
                          "返回它、不会重新加载；若它来自旧构建，本次注入不会生效")
                break

        with SuspendWindow(pid, self._log) as window:
            proc = _kernel32.OpenProcess(PROCESS_ACCESS, False, pid)
            if not proc:
                self._log("[战斗观测] 打开游戏进程失败（游戏可能以管理员权限启动过；"
                          "可尝试以管理员权限运行启动器）")
                return False
            remote = None
            try:
                wide = ctypes.c_wchar_p(path)
                size = (len(path) + 1) * 2
                remote = _kernel32.VirtualAllocEx(proc, None, size, 0x3000, 0x04)
                if not remote:
                    self._log("[战斗观测] VirtualAllocEx 失败")
                    return False
                written = ctypes.c_size_t()
                if not _kernel32.WriteProcessMemory(proc, remote, wide, size,
                                                    ctypes.byref(written)):
                    self._log("[战斗观测] WriteProcessMemory 失败")
                    return False
                kernel32 = _kernel32.GetModuleHandleW("kernel32.dll")
                load_lib = _kernel32.GetProcAddress(kernel32, b"LoadLibraryW")
                if not load_lib:
                    self._log("[战斗观测] 定位 LoadLibraryW 失败")
                    return False
                thread = _kernel32.CreateRemoteThread(proc, None, 0, load_lib, remote, 0, None)
                if not thread:
                    self._log("[战斗观测] CreateRemoteThread 失败（杀毒软件可能拦截）")
                    return False
                waited = _kernel32.WaitForSingleObject(thread, 10000)
                exit_code = wt.DWORD()
                _kernel32.GetExitCodeThread(thread, ctypes.byref(exit_code))
                _kernel32.CloseHandle(thread)
                if waited == 0x00000102:                                   # WAIT_TIMEOUT
                    self._log("[战斗观测] LoadLibraryW 超时（远程线程还没返回，可能撞上了"
                              "加载器锁；线程已恢复，下面按模块表实际结果判定）")
                elif not exit_code.value:
                    self._log("[战斗观测] DLL 加载失败（远程线程退出码为 0）")
                    return False
            finally:
                if remote:
                    _kernel32.VirtualFreeEx(proc, remote, 0, 0x8000)
                _kernel32.CloseHandle(proc)

        # ④ 回读校验（窗口已关闭，进程正常跑）：确认加载的是“这份路径”的 DLL
        if not self._verify_remote_dll(pid, path):
            return False
        self._injected_pid = pid
        self._injected_image = image
        self._injected_dll = path
        mode = "借用进程原有的挂起窗口" if window.was_suspended else "临时挂起窗口"
        self._log(f"[战斗观测] 已注入 battle_watch.dll (PID {pid}，{mode})")
        self._event(f"注入成功 PID={pid} dll={path} sha256={info['sha256'][:12]}")
        return True

    def _verify_remote_dll(self, pid: int, path: str) -> bool:
        """回读目标进程模块表，确认 battle_watch.dll 已加载且来自我们注入的路径。"""
        want_name = os.path.basename(path).lower()
        found: tuple[str, str, int] | None = None
        deadline = time.time() + MODULE_VERIFY_SECONDS
        while time.time() < deadline:
            for name, mpath, base in remote_modules(pid):
                if name.lower() == want_name:
                    found = (name, mpath, base)
                    break
            if found:
                break
            time.sleep(0.2)
        if not found:
            self._log("[战斗观测] 注入后没在目标进程里看到 battle_watch.dll"
                      "（被拦截或加载失败）")
            return False
        name, mpath, base = found
        if mpath and path and not _same_file(mpath, path):
            self._log(f"[战斗观测] 目标进程里的 {name} 来自 {mpath}，不是刚注入的 {path}"
                      " —— 进程里已有一份旧副本（同名模块不会被重新加载），本次注入未生效")
            return False
        self._remote_module = int(base)
        self._log(f"[战斗观测] 已确认目标进程加载 {name} @0x{base:X}"
                  + (f"（{mpath}）" if mpath else ""))
        return True

    # ------------------------------------------------------- 偏移量预检（注入前）
    # 顺序：先用偏移量对**本机 DLL** 校验（prologue 逐条比对，不联网）；
    # 对不上 → 云端对照（采用云端新版）；云端也对不上 → 本地重建并按需上传。
    # 具体逻辑在 functions/hook/preflight.py（同步执行，只有重建那一步才久）。
    _PREFLIGHT_TEXT = {
        "local-ok": "本地偏移量对得上本机 DLL（未联网、未重建）",
        "cloud-updated": "本地偏移量是旧版本 → 已采用云端偏移量",
        "rebuilt": "本地重建偏移量完成（校验通过；push=True 时已上传云端）",
        "rebuilt-unverified": "本地重建完成，但校验仍未通过（看上条日志）",
        "stale": "偏移量对不上本机 DLL，且不允许自动重建（钩子可能装不上）",
        "no-index": "没有任何可用索引（将用内置回退偏移）",
        "no-game-dll": "找不到 GameAssembly.dll（跳过偏移校验）",
        "error": "偏移预检异常（继续用现有索引）",
    }

    def _run_preflight(self) -> dict:
        """注入前跑一遍偏移量预检，并把选定索引固定成进程内“本次就用它”。"""
        try:
            from functions.hook.preflight import ensure_offsets_ready
            info = ensure_offsets_ready(on_log=self._log, push=True)
        except Exception as exc:  # noqa: BLE001
            info = {"verdict": "error", "detail": f"{type(exc).__name__}: {exc}"}
            self._log(f"[战斗观测] 偏移预检不可用（继续用现有索引）: {exc}")
        verdict = str(info.get("verdict") or "")
        text = self._PREFLIGHT_TEXT.get(verdict, verdict)
        self._preflight = dict(info)
        self._preflight.pop("index", None)          # 索引对象不进状态文件
        check = info.get("check") or {}
        self._log(f"[战斗观测] 偏移预检结果: {verdict}（{text}）"
                  + (f"；{check['detail']}" if check.get("detail") else "")) # type: ignore
        index = info.get("index")
        if index is not None:
            self._index_game_note = {
                "size": int((index.game or {}).get("gameassembly_size") or 0), # type: ignore
                "pe_timestamp": int((index.game or {}).get("pe_timestamp") or 0), # type: ignore
                "game_version": str((index.game or {}).get("game_version") or ""), # type: ignore
                "source": str(info.get("source") or ""),
            }
        return info

    def _verify_gameassembly(self) -> None:
        """游戏 DLL 新鲜度：进程里加载的 GameAssembly.dll 是不是磁盘上最新那份。

        ``prologue`` 自检只是“装钩前”的最后一道闸；这里给的是**可读的判断**：
        进程内模块的 PE 时间戳/映像大小/头部哈希 vs 磁盘文件。
        """
        pid = self._injected_pid
        if not pid or self._ga_verified:
            return
        remote = remote_pe_identity(pid)
        if not remote:
            self._ga_retry += 1
            if self._ga_retry <= GA_VERIFY_RETRY:
                self._log("[战斗观测] 还没枚举到进程内的 GameAssembly.dll，稍后再校验")
            return
        disk = local_pe_identity(_expected_gameassembly())
        same = pe_identity_same(remote, disk)
        self._ga_verified = True
        self._ga_note = {"remote": {k: remote.get(k) for k in ("timestamp", "size_of_image",
                                                              "entry_rva", "base", "path")},
                         "disk": {k: disk.get(k) for k in ("timestamp", "size_of_image",
                                                           "entry_rva")},
                         "same": same}
        if same:
            self._log(f"[战斗观测] 游戏 DLL 校验通过：进程内 GameAssembly.dll == 磁盘最新那份"
                      f"（PE 时间戳 0x{int(remote['timestamp']):X}，"
                      f"映像 {int(remote['size_of_image'])} 字节，基址 0x{int(remote['base']):X}）")
        else:
            self._log(f"[战斗观测] ⚠ 游戏 DLL 不一致：进程内 ts=0x{int(remote['timestamp']):X} "
                      f"size={int(remote['size_of_image'])} entry=0x{int(remote['entry_rva']):X}；"
                      f"磁盘 ts=0x{int(disk['timestamp']):X} size={int(disk['size_of_image'])} "
                      f"entry=0x{int(disk['entry_rva']):X} —— 游戏可能正在更新/加载了旧版本，"
                      "钩子会被 prologue 自检拦下（跑 `python -m functions.hook.main update`）")

    def _eject(self) -> None:
        if not self._injected_pid or not self._remote_module:
            return
        pid, module = self._injected_pid, self._remote_module
        proc = _kernel32.OpenProcess(PROCESS_ACCESS, False, pid)
        if not proc:
            return
        try:
            kernel32 = _kernel32.GetModuleHandleW("kernel32.dll")
            free_lib = _kernel32.GetProcAddress(kernel32, b"FreeLibrary")
            thread = _kernel32.CreateRemoteThread(proc, None, 0, free_lib,
                                                  ctypes.c_void_p(module), 0, None)
            if thread:
                _kernel32.WaitForSingleObject(thread, 5000)
                _kernel32.CloseHandle(thread)
        finally:
            _kernel32.CloseHandle(proc)
        self._injected_pid = None
        self._remote_module = None

    # ---------------------------------------------------------------- 事件抽取
    def _ring_rows(self, cfg: BWConfig):
        head = int(cfg.log_head)
        if head < self._drained_head:
            self._drained_head = 0
        new = head - self._drained_head
        if new <= 0:
            return [], head
        dropped = 0
        if new > LOG_RING_CAP:
            dropped = new - LOG_RING_CAP
            new = LOG_RING_CAP
        start = head - new
        rows = []
        for offset in range(new):
            raw = bytes(cfg.log_ring[(start + offset) % LOG_RING_CAP])
            text = raw.split(b"\x00", 1)[0].decode("utf-8", "replace").strip()
            if text:
                rows.append(text)
        self._drained_head = head
        if dropped:
            self._log(f"[战斗观测] 抽取过慢，丢弃了 {dropped} 行事件（可调小轮询间隔）")
        return rows, head

    # ---------------------------------------------------------- buff 关注表
    def sync_buff_watch(self, names=()) -> None:
        """把关注 buff 名（FNV-1a 64）写进共享内存关注表。

        关注表下标 = ``watched_buff_names()`` 的下标（两边同一份排序）；
        写 0 条时 DLL 会完全跳过 buff 链读取。
        """
        cfg = self._config()
        if cfg is None:
            return
        names = tuple(names)[:BUFF_WATCH_MAX]
        for i, name in enumerate(names):
            cfg.buff_watch_hashes[i] = fnv1a64(name)
        for i in range(len(names), BUFF_WATCH_MAX):
            cfg.buff_watch_hashes[i] = 0
        cfg.buff_watch_count = len(names)

    # ---------------------------------------------------------- 事件处理
    def handle_line(self, line: str) -> BattleEvent | None:
        """解析并应用一行事件（测试可直接调用）。"""
        if not line:
            return None
        parts = line.split(None, 1)
        kind = parts[0].upper()
        values = {}
        tag = ""
        if len(parts) > 1:
            for key, value in _KV_RE.findall(parts[1]):
                values[key] = int(value)
            match = re.search(r"tag=([A-Za-z0-9_]+)", parts[1])
            tag = match.group(1) if match else ""
        event = BattleEvent(kind=kind, values=values, tag=tag, raw=line, ts=time.time())
        if kind in ("INFO", "ERR", "WARN"):
            self._log(f"[战斗观测] DLL: {line}")
            self._event(f"DLL {line}")
            if kind == "ERR":
                self._log(f"[战斗观测] 提示: 版本不符就先跑 "
                          f"`python -m functions.hook.main update` 再重启游戏")
            return event
        self._event(line)
        with self._lock:
            self._last_event_ts = time.time()
        if self.verbose:
            self._log(f"[战斗观测] 事件 {line}")
        if kind == "RND":
            if tag in ANIM_TICK_TAGS:
                # 表现层动画 tick（不是回合边界！）：放行一条挂起判定，让解锁跟着动画走
                self._apply_anim_tick(tag)
            else:
                with self._lock:
                    self.state.round_seq = event.get("seq", self.state.round_seq + 1)
                    self.state.rnd_total += 1
                self.settle_turn(f"回合边界({tag or 'hook'})")
        elif kind == "SPD":
            self._apply_spd(event)
        elif kind == "VAL":
            self._apply_vitals(event)
        elif kind == "BUF":
            self._apply_buffs(event)
        elif kind == "ACT":
            self._apply_act(event)
        return event

    def _apply_anim_tick(self, tag: str) -> None:
        """表现层动画 tick：放行**一条**最早挂起的判定。

        为什么一次一条：动画按结算顺序逐个播，而结算阶段的事件全挤在一瞬间，
        所以"第 N 次动画 tick"≈"第 N 个行动"。一次放一条，解锁时机就跟着动画走；
        没有挂起项时只计数（用来看钩子活不活）。
        """
        with self._lock:
            self.state.anim_ticks_total += 1
            self.state.anim_last_tag = tag
            detail = self._flush_one_pending_locked()
        if not detail:
            return
        self._log(f"[战斗观测] ▶ 动画 tick（{tag}）放行: {detail}")
        self._write_status(force=True)

    def _apply_spd(self, event: BattleEvent) -> None:
        """速度事件：先把字段归一成整数速度，再交给规则表（``kind="speed"``，立刻置位）。

        驱动只管「SPD 事件里有什么字段、怎么把字节变成整数」；
        「哪个身份、等于几、看哪几个字段」全部由成就登记的 ``BattleRule`` 提供。
        """
        iid = event.get("iid", -1)
        oid = event.get("oid", -1)
        # os/ow 是「速度 ×1000」的定点原始值 → 一律换成整数速度；DLL v3 会额外给 osi/owi，
        # 有就优先信它（字段语义由 DLL 那边负责），没有就自己换算（v2 DLL / 老日志）。
        os_raw = event.get("os", -1)
        ow_raw = event.get("ow", -1)
        os_int = event.opt("osi")
        os_int = speed_int(os_raw) if os_int is None else os_int
        ow_int = event.opt("owi")
        ow_int = speed_int(ow_raw) if ow_int is None else ow_int
        # 有效速度：游戏 GetIntegerOfOriginSpeed 的语义 —— _overwritedSpeed >= 0 就用它，否则用 _originSpeed。
        eff_int = event.opt("eff")
        if eff_int is None or eff_int < 0:
            eff_int = ow_int if ow_raw >= 0 else os_int
        speeds = {"os": os_int, "ow": ow_int, "its": event.get("its", -1),
                  "eff": eff_int, "os_raw": os_raw, "ow_raw": ow_raw}
        hits: list[str] = []
        with self._lock:
            self.state.spd_total += 1
            if iid >= 0:
                self.state.speeds[iid] = dict(speeds, oid=oid)
                if oid > 0:
                    self.state.units[iid] = oid
            hits = self._eval_immediate_locked(
                lambda rule: rule.match_speed(oid, speeds)[0],
                lambda rule: self._speed_detail(rule, oid, speeds, event.tag))
            hits += self._eval_presence_locked()
        for detail in hits:
            self._log(f"[战斗观测] ★ {detail}")
        if event.get("iid", -1) < 0 and event.get("oid", -1) < 0:
            # 钩子命中了但不是单位对象（例如钩到了非单位函数）→ 提示
            self._log(f"[战斗观测] 注意: {event.tag} 的 SPD 事件里没有单位字段，"
                      f"可能是钩子签名/偏移不对（原始: {event.raw}）")
        # 兜底回合边界：首选边界钩子（manager_*）从未命中时，用“单位回合开始”当边界
        if event.tag == "unit_round_start" and not self._boundary_seen():
            now = time.time()
            if now - self._last_boundary_ts > 1.0:
                self._last_boundary_ts = now
                with self._lock:
                    self.state.round_seq += 1
                self.settle_turn("回合边界(unit_round_start 兜底)")

    def _boundary_seen(self) -> bool:
        """首选边界钩子是否至少命中过一次。"""
        return any(self._last_hits.get(k, 0) > 0 for k in BOUNDARY_PREFERRED)

    def _apply_act(self, event: BattleEvent) -> None:
        record = {
            "actor": event.get("actor", -1),
            "cmd": event.get("cmd", -1),
            "skid": event.get("skid", -1),
            "slot": event.get("slot", -1),
            "tier": event.get("tier", -1),
            "aoid": event.get("aoid", -1),
            "tag": event.tag,
            "round": self.state.round_seq,
        }
        with self._lock:
            self.state.acts_total += 1
            actor_oid = record["aoid"]
            if actor_oid in (-1, 0):
                actor_oid = self.state.units.get(record["actor"], -1)
            if actor_oid in (-1, 0):
                actor_oid = self.state.units.get(record["cmd"], -1)
            record["actor_oid"] = actor_oid
            self.state.skills.append(record)
            if len(self.state.skills) > 64:
                self.state.skills = self.state.skills[-64:]
            # 技能类规则：命中先记入待结算表；**不在这里置位** ——
            # 等到「技能动画结束」（收尾事件或静默期）或回合边界才结算。
            round_seq = self.state.round_seq
            for key, rule in registered_rules().items():
                if rule.kind != RULE_KIND_SKILL or key in self.state.flags:
                    continue
                if rule.match_skill(record["skid"], actor_oid, round_seq):
                    if key not in self.state.pending_flags and key not in self.state.flags:
                        self.state.pending_seq += 1
                        self.state.pending_seqs[key] = self.state.pending_seq
                        self.state.pending_flags[key] = self._skill_detail(rule, record, "待结算")
        # 动画结束的收尾事件（不同技能收尾时机不一，钩到的这两个都当结束信号）
        if event.tag in ACTION_END_TAGS:
            self.settle_turn(f"技能动画结束({event.tag})", fallback_immediate=False,
                             only_skills=True)

    def _apply_vitals(self, event: BattleEvent) -> None:
        """血量 / 理智事件：交给规则表（``kind="mental"/"hp"``，立刻置位）。

        日志只写在规则命中时（没命中就只落到 ``battle_watch.log`` 与状态文件里），
        这样成就日志不会被每秒几十条的 VAL 事件刷屏。
        """
        iid = event.get("iid", -1)
        oid = event.get("oid", -1)
        hp = event.get("hp", VITAL_UNREAD)
        mhp = event.get("mhp", VITAL_UNREAD)
        mp = event.get("mp", VITAL_UNREAD)
        info = {"oid": oid, "hp": hp, "mhp": mhp, "mp": mp,
                "tag": event.tag, "round": self.state.round_seq}
        hits: list[str] = []
        with self._lock:
            self.state.vitals_total += 1
            if iid >= 0:
                self.state.vitals[iid] = info
                if oid > 0:
                    self.state.units[iid] = oid
            hits = self._eval_immediate_locked(
                lambda rule: rule.match_vitals(oid, hp, mhp, mp),
                lambda rule: self._vitals_detail(rule, info, event.tag))
            hits += self._eval_presence_locked()
        for detail in hits:
            self._log(f"[战斗观测] ★ {detail}")

    # ---------------------------------------------------------- 规则求值与详情文本
    def _set_flag_locked(self, key: str, detail: str) -> None:
        """置位一条规则（已持有锁）。同时记下命中序号，供复合成就判先后顺序。"""
        if key in self.state.flags:
            return
        self.state.flag_counter += 1
        self.state.flags[key] = detail
        self.state.flag_seq[key] = self.state.flag_counter

    def _queue_pending_locked(self, key: str, detail: str) -> None:
        """把一条判定挂起（等动画 tick 放行），并记下先后序号。"""
        if key in self.state.flags or key in self.state.pending_immediate \
                or key in self.state.pending_flags:
            return
        self.state.pending_seq += 1
        self.state.pending_seqs[key] = self.state.pending_seq
        self.state.pending_immediate[key] = detail

    def _flush_one_pending_locked(self) -> str | None:
        """放行**最早挂起的一条**判定（已持有锁）。返回详情文本。"""
        best_key, best_seq = None, None
        for store in (self.state.pending_flags, self.state.pending_immediate):
            for key in store:
                seq = self.state.pending_seqs.get(key, 0)
                if best_seq is None or seq < best_seq:
                    best_key, best_seq = key, seq
        if best_key is None:
            return None
        detail = (self.state.pending_immediate.pop(best_key, None)
                  or self.state.pending_flags.pop(best_key, None))
        self.state.pending_seqs.pop(best_key, None)
        self._set_flag_locked(best_key, detail or "")
        return detail

    def _flush_all_pending_locked(self) -> list[str]:
        """按挂起先后放行全部（已持有锁）——回合边界 / 静默期 / 战斗结束的兜底。"""
        out: list[str] = []
        while True:
            detail = self._flush_one_pending_locked()
            if detail is None:
                break
            out.append(detail)
        return out

    def _eval_immediate_locked(self, match_fn, detail_fn) -> list[str]:
        """非技能类规则的**统一求值器**（调用方必须已持有 ``self._lock``）。

        ``match_fn(rule)`` 决定是否命中，``detail_fn(rule)`` 生成详情；
        命中就写进 ``state.flags``（同一规则只置位一次）。
        速度 / 理智 / 血量 / buff / 在场 都走这一条路——加新类型时不用改这里。
        """
        hits: list[str] = []
        for key, rule in registered_rules().items():
            if rule.kind not in RULE_KINDS_IMMEDIATE or key in self.state.flags:
                continue
            if key in self.state.pending_immediate or key in self.state.pending_flags:
                continue
            if match_fn(rule):
                detail = detail_fn(rule)
                if rule.kind in RULE_KINDS_ANIM_WAIT:
                    self._queue_pending_locked(key, detail)   # 等动画 tick 放行
                else:
                    self._set_flag_locked(key, detail)        # 速度/在场：本来就该立刻
                hits.append(detail)
        return hits

    def _eval_presence_locked(self) -> list[str]:
        """presence 类规则：目标身份出现在已观测到的单位表里就算命中。"""
        if not self.state.units:
            return []
        round_seq = self.state.round_seq
        oids = set(self.state.units.values())
        return self._eval_immediate_locked(
            lambda rule: any(rule.match_presence(oid, round_seq) for oid in oids),
            lambda rule: self._presence_detail(rule))

    def _presence_detail(self, rule) -> str:
        oid = next((o for o in self.state.units.values() if o in rule.identity_ids), -1)
        return (f"第 {self.state.round_seq} 回合 {rule.label or rule.key} 在场上"
                f"（oid={oid}，目标 {'/'.join(str(i) for i in rule.identity_ids)}）")

    def _apply_buffs(self, event: BattleEvent) -> None:
        """buff 事件：位掩码 → 关注表里的 buff 名集合 → 交给规则表（立刻置位）。"""
        iid = event.get("iid", -1)
        oid = event.get("oid", -1)
        mask = event.get("m", 0)
        names = watched_buff_names()
        present = {names[i] for i in range(min(len(names), BUFF_WATCH_MAX))
                   if mask & (1 << i)}
        info = {"oid": oid, "mask": mask, "names": sorted(present),
                "count": event.get("n", -1),
                "tag": event.tag, "round": self.state.round_seq}
        hits: list[str] = []
        with self._lock:
            self.state.buff_total += 1
            if iid >= 0:
                self.state.buffs[iid] = info
                if oid > 0:
                    self.state.units[iid] = oid
            round_seq = self.state.round_seq
            hits = self._eval_immediate_locked(
                lambda rule: rule.match_buff(oid, present, round_seq)[0],
                lambda rule: self._buff_detail(rule, info, event.tag, present))
            hits += self._eval_presence_locked()
        for detail in hits:
            self._log(f"[战斗观测] ★ {detail}")

    def _buff_detail(self, rule, info: dict, tag: str, present: set) -> str:
        hit, names = rule.match_buff(info.get("oid", -1), present, self.state.round_seq)
        return (f"第 {self.state.round_seq} 回合 {rule.label or rule.key} "
                f"身上有 buff {'/'.join(names)}（看 {'/'.join(rule.buffs)}；"
                f"该单位当前共有 {info.get('count', -1)} 个 buff；"
                f"oid={info.get('oid', -1)} via {tag}）")

    def _skill_detail(self, rule: BattleRule, record: dict, reason: str) -> str:
        label = rule.label or rule.key
        return (f"第 {self.state.round_seq} 回合结算（{reason or '回合边界'}）"
                f"{label} 技能命中（skid={record.get('skid')} tier={record.get('tier')} "
                f"actor={record.get('actor')} oid={record.get('actor_oid')} "
                f"via {record.get('tag')}）")

    def _vitals_detail(self, rule: BattleRule, info: dict, reason: str) -> str:
        label = rule.label or rule.key
        oid = info.get("oid", -1)
        hp, mhp, mp = info.get("hp", -1), info.get("mhp", -1), info.get("mp", -1)
        if rule.kind == RULE_KIND_MENTAL:
            body = f"理智(SP) {mp}，阈值 {rule.threshold_text()}"
        elif mhp > 0:
            body = f"受伤 hp={hp}/{mhp}（{hp / mhp:.0%}），阈值 {rule.threshold_text()}"
        else:
            body = f"受伤 hp={hp}/{mhp}，阈值 {rule.threshold_text()}"
        return (f"第 {self.state.round_seq} 回合 {label} {body}"
                f"（oid={oid} via {info.get('tag', '?')}）")

    def _speed_detail(self, rule: BattleRule, oid: int, speeds: dict, reason: str) -> str:
        label = rule.label or rule.key
        _matched, names = rule.match_speed(oid, speeds)
        fields = ", ".join(speed_text(speeds.get(name, -1), speeds.get(f"{name}_raw", -1))
                          if name in ("os", "ow") else f"{name}={speeds.get(name)}"
                          for name in (rule.fields or SPEED_FIELD_ORDER))
        return (f"第 {self.state.round_seq} 回合 {label} {rule.threshold_text()}"
                f"（命中字段 {','.join(names)}；{fields}；oid={oid} via {reason}）")

    # ---------------------------------------------------------------- 线程
    def _run_guarded(self) -> None:
        """任何异常都要留下痕迹：观测线程不能静默死掉。"""
        try:
            self._run()
        except Exception as exc:  # noqa: BLE001
            import traceback
            self._log(f"[战斗观测] 驱动线程异常退出: {type(exc).__name__}: {exc}")
            self._event("驱动线程异常: " + traceback.format_exc().replace("\n", " | "))

    def _run(self) -> None:
        log = self.log_callback
        self._open_event_file()
        path = dll_path()
        if not path:
            self._phase = "缺少 DLL"
            log("[战斗观测] 找不到 battle_watch.dll，跳过战斗观测"
                "（可运行 functions/achievement/hook_dll/build.ps1 编译）")
            return

        # 解析游戏 DLL 路径（用于静态读字节做桩解引用/prologue）
        pe_path = ""
        try:
            from functions.hook.paths import game_paths
            pe_path = game_paths().gameassembly
        except Exception:
            pe_path = ""
        # 注入前的偏移量预检（先用偏移量对本地 DLL 校验；对不上才云端 / 重建）
        self._run_preflight()
        self.table = build_hook_table(on_log=log, pe_path=pe_path)
        table = self.table
        self._phase = "已解析钩子表"
        if _DLL_CHOICE_NOTE:
            log(f"[战斗观测] {_DLL_CHOICE_NOTE}")
        log(f"[战斗观测] 偏移来源={table['source']}；下发 {len(table['entries'])} 个观测点：")
        log(describe_hook_table(table))
        missing = [k for k, item in table["entries"].items() if not item.get("prologue")]
        if missing:
            log(f"[战斗观测] 注意: 以下观测点没有 prologue（将跳过版本自检）: {missing}")

        if not self._open_map():
            self._phase = "共享内存失败"
            return
        if not self._write_config(table):
            self._phase = "写配置失败"
            log("[战斗观测] 写入共享内存配置失败")
            return
        # 关注 buff 表：成就侧登记了 buff 规则才写（没登记时 DLL 连 buff 链都不读）
        names = watched_buff_names()
        self.sync_buff_watch(names)
        if names:
            log(f"[战斗观测] 关注 buff {len(names)} 个: {'/'.join(names)}")
        self._write_status(force=True)
        pid = None
        starting_flag = False
        waited = 0.0
        while not self._stop.is_set():
            if pid is None or not self._pid_alive(pid):
                pid, image, note = select_game_process(self.process_name)
                if pid is None:
                    self._phase = f"等待游戏进程（{self.process_name}）"
                    if waited == 0.0:
                        log(f"[战斗观测] 等待 {self.process_name} 启动（最长 5 分钟，之后改慢轮询）")
                    elif int(waited) % 60 == 0:
                        log(f"[战斗观测] 仍在等待游戏进程（已等 {int(waited)}s）；"
                            f"钩子表已就绪，状态见 cache/achievement/battle_watch_status.json")
                    self._sleep(2.0 if waited < 300 else 10.0)
                    waited += 2.0
                    self._write_status()
                    starting_flag = True
                    continue
                else:
                    if starting_flag:
                        print(f"[战斗观测] {self.process_name} 启动，PID: {pid}，进入 hook 注入流程。")
                        starting_flag = False
                if note:
                    log(f"[战斗观测] 进程选择: PID {pid}（{image or '映像未知'}）；{note}")
                # 稳定性：Steam 拉起的第一个同名进程可能几秒就退出（引导/闪退），
                # 注进去只会白加载一份 DLL；与 mod loader 的判定约定保持一致。
                if not pid_alive_for(pid, GAME_STABLE_SECONDS):
                    log(f"[战斗观测] PID {pid} 存活不足 {GAME_STABLE_SECONDS:g}s"
                        "（疑似 Steam 引导进程/闪退），继续等真正的游戏进程")
                    pid = None
                    self._sleep(1.0)
                    continue
                if not self._inject(pid, path):
                    self._sleep(5.0)
                    continue
                waited = 0.0
                self._last_hits = {}
                # 新进程 = 可能换了游戏构建，重新校一次游戏 DLL 新鲜度
                self._ga_verified = False
                self._ga_retry = 0
                self._ga_note = {}
            cfg = self._config()
            if cfg is None:
                self._sleep(self.poll_interval)
                continue
            self._report_status(cfg)
            rows, _head = self._ring_rows(cfg)
            for line in rows:
                try:
                    self.handle_line(line)
                except Exception as exc:  # noqa: BLE001
                    log(f"[战斗观测] 事件解析失败: {line!r} {exc}")
            self._scan_hits(cfg)
            # 技能类规则的“动画结束”兜底：事件停了 SKILL_SETTLE_QUIET_SEC 就结算
            self.settle_skills_if_quiet()
            self._heartbeat()
            self._write_status()
            self._sleep(self.poll_interval)

    def _sleep(self, seconds: float) -> None:
        deadline = time.time() + seconds
        while not self._stop.is_set() and time.time() < deadline:
            time.sleep(min(0.1, max(0.01, deadline - time.time())))

    @staticmethod
    def _pid_alive(pid: int) -> bool:
        handle = _kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        _kernel32.CloseHandle(handle)
        return True

    def _scan_hits(self, cfg: BWConfig) -> None:
        """读取每个钩子的命中计数（只做可观测性：谁是活的、谁 0 次）。

        回合边界**不**靠命中计数（会和 RND 事件重复计数），而是靠 RND 事件 /
        单位回合开始事件——见 ``handle_line``。
        """
        for i, (key, _item) in enumerate(list(self.table["entries"].items())[:MAX_HOOKS]):
            hits = int(cfg.hook_hits[i])
            prev = self._last_hits.get(key, 0)
            if hits != prev:
                self._last_hits[key] = hits
                if prev == 0 and hits > 0:
                    self._log(f"[战斗观测] 观测点开始命中: {key} ×{hits}")
                    if key == "take_attack_dmg_multiplier":
                        self._log("[战斗观测] ↳ 事件链路已通（受击观测钩子活了）")

    def _heartbeat(self) -> None:
        now = time.time()
        if now - self._last_heartbeat < HEARTBEAT_SEC:
            return
        self._last_heartbeat = now
        with self._lock:
            snap = self.state.snapshot()
        hits = " ".join(f"{k}={v}" for k, v in self._last_hits.items())
        flags = list(snap.get("rule_hits") or {})
        self._log(f"[战斗观测] 心跳: 阶段={self._phase} PID={self._injected_pid} | "
                  f"事件: RND {snap['rnd_total']} / SPD {snap['spd_total']} / "
                  f"VAL {snap.get('vitals_total', 0)} / ACT {snap['acts_total']} / "
                  f"BUF {snap.get('buff_total', 0)} | "
                  f"动画 tick {snap.get('anim_ticks', 0)}（{snap.get('anim_last_tag') or '无'}） | "
                  f"单位 {snap['units']} | 本回合待结算 {snap['pending_skills']} | "
                  f"成就判定 {len(flags)} 条{('（' + ','.join(flags) + '）') if flags else ''} | "
                  f"钩子命中: {hits or '（全 0）'}")
        if not hits:
            self._log("[战斗观测] 提示: 所有观测点命中数都是 0")

    def _report_status(self, cfg: BWConfig) -> None:
        if int(cfg.gameassembly_found) and "ga" not in self._status_logged:
            self._status_logged.add("ga")
            self._phase = "GameAssembly 已加载"
            self._log("[战斗观测] 游戏已加载 GameAssembly.dll，等待装钩")
        # 游戏 DLL 新鲜度：进程内那份 vs 磁盘上最新那份（加载晚的话留着重试）
        if not self._ga_verified and int(cfg.gameassembly_found):
            self._verify_gameassembly()
        if int(cfg.verified) and "verified" not in self._status_logged:
            self._status_logged.add("verified")
            self._log("[战斗观测] prologue 自检通过")
        if int(cfg.installed) and "installed" not in self._status_logged:
            self._status_logged.add("installed")
            self._phase = "观测中（已装钩）"
            self._log(f"[战斗观测] 已装钩 {int(cfg.hook_count)} 个观测点，开始采集事件")
        error = int(cfg.last_error)
        if error and f"err{error}" not in self._status_logged:
            self._status_logged.add(f"err{error}")
            self._phase = f"DLL 错误 {error}"
            self._log(f"[战斗观测] DLL 状态: {ERROR_TEXT.get(error, error)}")
            if error == 3:
                self._log("[战斗观测] 提示: 跑一次 `python -m functions.hook.main update` "
                          "重建偏移索引后再启动游戏")

    def _log(self, message: str) -> None:
        try:
            self.log_callback(message)
        except Exception:
            pass


# 速度日志去重集合在 __init__ 里初始化（不要用类属性，会被多个实例共享）


# --------------------------------------------------------------------------- 单例入口

_watch: BattleWatch | None = None
_watch_lock = threading.Lock()


def get_watch(log_callback=None) -> BattleWatch:
    global _watch
    with _watch_lock:
        if _watch is None:
            _watch = BattleWatch(log_callback=log_callback)
        elif log_callback is not None:
            _watch.log_callback = log_callback
        return _watch


def start_battle_watch(log_callback=None, process_name: str = TARGET_PROCESS,
                      verbose: bool | None = None) -> BattleWatch:
    """启动观测。``verbose=None`` 时读设置项 ``achievement_log_verbose``（缺省 False）。"""
    watch = get_watch(log_callback)
    watch.process_name = process_name
    watch.verbose = log_verbose_enabled() if verbose is None else bool(verbose)
    watch.start()
    return watch


def log_verbose_enabled() -> bool:
    """事件行是否也写进成就日志（设置项 ``achievement_log_verbose``，缺省 false）。"""
    try:
        from functions.base.settings_manager import get_settings_manager
        value = get_settings_manager().get_setting("achievement_log_verbose")
        return bool(value) if value is not None else False
    except Exception:
        return False


def stop_battle_watch() -> None:
    global _watch
    with _watch_lock:
        if _watch is not None:
            _watch.stop()
            _watch = None


def rule_hits() -> dict:
    """所有命中过的规则（key → 详情文本；启动器界面/状态文件用）。"""
    with _watch_lock:
        watch = _watch
    if watch is None:
        return {}
    with watch._lock:
        return dict(watch.state.flags)


def settle_turn(reason: str = "") -> list:
    with _watch_lock:
        return _watch.settle_turn(reason) if _watch else []


def state_snapshot() -> dict:
    with _watch_lock:
        return _watch.snapshot() if _watch else {}


def load_status() -> dict:
    """读状态文件（启动器界面/CLI 用；观测没跑过时返回空 dict）。"""
    try:
        with open(status_path(), "r", encoding="utf-8") as fh:
            return json.load(fh) or {}
    except (OSError, ValueError):
        return {}


# --------------------------------------------------------------------------- CLI


def _print(message: str) -> None:
    print(message, flush=True)


def _probe_preflight() -> None:
    """``--probe`` 用：只做本地校验（**不联网、不重建**），看偏移量对不对得上本机 DLL。"""
    try:
        from functions.hook.preflight import ensure_offsets_ready
        info = ensure_offsets_ready(on_log=_print, allow_cloud=False, allow_rebuild=False)
    except Exception as exc:  # noqa: BLE001
        _print(f"[偏移预检] 不可用: {type(exc).__name__}: {exc}")
        return
    verdict = str(info.get("verdict") or "")
    _print(f"[偏移预检] {verdict}（"
           f"{BattleWatch._PREFLIGHT_TEXT.get(verdict, verdict)}）")
    check = info.get("check") or {}
    if check.get("detail") and verdict != "local-ok":
        _print(f"[偏移预检] {check['detail']}")
    elif verdict == "local-ok":
        _print(f"[偏移预检] {check.get('detail', '')}")
        _print("[偏移预检] （离线 --probe 不联网、不重建；云端对照/本地重建只在游戏启动时按需发生）")


def cmd_probe() -> int:
    """离线自查：钩子表 + 将要注入的 DLL + 进程身份 + 游戏 DLL 新鲜度，不注入。"""
    from functions.hook.paths import game_paths
    paths = game_paths()
    _print(f"游戏目录: {paths.root or '（未找到）'}")
    _print(f"GameAssembly.dll: {paths.gameassembly or '（未找到）'}")
    table = build_hook_table(on_log=_print, pe_path=paths.gameassembly)
    _print(f"\n偏移来源: {table['source']}；索引可用={table['index_available']}")
    _print(f"将下发 {len(table['entries'])} 个观测点:")
    _print(describe_hook_table(table))
    dll = dll_path()
    _print(f"\nbattle_watch.dll: {dll or '（未找到，需先编译）'}")
    if dll:
        info = dll_info(dll)
        _print(f"  大小 {info['size']} 字节 / mtime {info['mtime']} / "
               f"sha256 {info['sha256'][:16]}…")
    if _DLL_CHOICE_NOTE:
        _print(f"  {_DLL_CHOICE_NOTE}")
    # 偏移量预检（**只做本地校验**：不联网、不重建，适合 --probe 离线看）/ 进程身份 / 注入用 DLL
    _print("")
    _probe_preflight()
    # 进程身份：真正注入时按这张表挑 PID（映像路径优先）
    expected = _expected_game_exe()
    _print(f"\n期望的游戏进程: {expected or '（配置里没拿到游戏路径，将退化为同名第一个）'}")
    candidates = find_process_candidates(TARGET_PROCESS)
    for pid, image in candidates:
        mark = "→ 将注入" if (expected and image and _same_file(image, expected)) else "（映像不符）"
        _print(f"  同名进程 PID {pid}: {image or '（取不到映像路径）'} {mark}")
    if not candidates:
        _print("  游戏进程: 未运行")
    _print(f"\n事件日志: {event_log_path()}")
    _print(f"状态文件: {status_path()}")
    return 0


def cmd_status() -> int:
    data = load_status()
    if not data:
        _print(f"还没有观测状态（{status_path()} 不存在）——游戏还没通过启动器跑过？")
    else:
        _print(json.dumps(data, ensure_ascii=False, indent=1))
    _print("")
    path = event_log_path()
    if os.path.isfile(path):
        _print(f"---- {path} 末尾 25 行 ----")
        try:
            with open(path, "r", encoding="utf-8-sig", errors="replace") as fh:
                lines = fh.readlines()[-25:]
            for line in lines:
                _print("  " + line.rstrip())
        except OSError:
            pass
    return 0


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--probe" in argv:
        return cmd_probe()
    if "--status" in argv:
        return cmd_status()

    def log(message: str) -> None:
        print(message, flush=True)

    watch = BattleWatch(log_callback=log)
    log("[战斗观测] 独立调试模式（Ctrl+C 结束）；--probe 看钩子表、--status 看状态")
    watch.start()
    try:
        while True:
            time.sleep(5)
            snap = watch.snapshot()
            log("[战斗观测] 状态: " + ", ".join(
                f"{k}={v}" for k, v in snap.items()
                if k not in ("watched_speeds", "watched_vitals", "rules", "hook_hits")))
    except KeyboardInterrupt:
        pass
    finally:
        watch.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
