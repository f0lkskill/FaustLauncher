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
                               心跳 / 速度与理智判定 / 成就置位；**不刷事件**

事件行默认不进成就日志（``verbose=True``，或设置项 ``achievement_log_verbose`` 才进）。
两个日志都在每次实例启动时清空重写（只保留本次运行）。

判定规则（``BattleRule``）—— 成就侧只登记数据，判定在驱动侧::

    BattleRule(key="ach_x", kind="skill",  identity_ids=(10101,), skill_ids=(1010103,))
    BattleRule(key="ach_y", kind="mental", identity_ids=(10913, 10312), threshold=0)
    BattleRule(key="ach_z", kind="hp",     identity_ids=(10705,), ratio=1.0)

- ``kind="skill"``：ACT 事件里出现 ``skill_ids``（技能 ID 自带身份）或
  （``gated_skill_ids`` 且 actor 身份 == ``identity_ids``）；**回合边界结算**（与李箱成就同逻辑）
- ``kind="mental"``：观察到该身份的 ``mp < threshold`` 就**立刻**置位
- ``kind="hp"``：观察到 ``hp < mhp * ratio``（默认 1.0 = 只要掉血就算受伤）就立刻置位

游戏数据 id（业务常量，与偏移无关）：``10101`` LCB 罪人李箱、``10212`` 黑兽-卯 魁首浮士德、
``10115`` 蜘蛛巢 食指 父辈 李箱、``10913`` 脑叶公司E.G.O::泪锋之剑 罗佳（绝望骑士）、
``10312`` 脑叶公司E.G.O::以爱与憎之名 堂吉诃德（憎恶女王）、``10705`` 脑叶公司E.G.O::狐雨 希斯克利夫，
``1010103`` 李箱 LCB 三技能（技能 id = ``<身份5位><槽位2位>``）。
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

BW_MAGIC = 0x33574246            # "FBW3"（v2=FBW2；v3 加了血量/理智字段偏移 → 布局变了）
MAP_NAME = "Local\\FaustLauncher_BattleWatch"
LOG_RING_CAP = 512
LOG_LINE_MAX = 255
MAX_HOOKS = 12
HOOK_NAME_LEN = 40
TARGET_PROCESS = "LimbusCompany.exe"

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

# --------------------------------------------------------------------------- 游戏数据

IDENTITY_FAUST_KUISHOU = 10212       # 黑兽 - 卯 魁首 浮士德
IDENTITY_RODION_DESPAIR_KNIGHT = 10913   # 脑叶公司E.G.O::泪锋之剑 罗佳（绝望骑士，魔法少女）
IDENTITY_DON_QUIXOTE_HATRED_QUEEN = 10312  # 脑叶公司E.G.O::以爱与憎之名 堂吉诃德（憎恶女王）
SKILL_LCB_YISANG_S3 = 1010103        # 李箱 LCB 三技能（skillId = 身份*100 + 槽位）
SPEED_TARGET = 9

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

# 速度判定看哪些字段（值都是**整数速度**：os/ow/eff 已归一化，its 本来就是整数）：
# os=_originSpeed（本回合掷出的速度）、ow=_overwritedSpeed（被技能覆盖后的速度）、
# its=_thisTurnIntSpeedOnCmdPhase（命令阶段快照，回合开始那一刻还是上一回合的值，别当唯一依据）、
# eff=有效速度（游戏 GetIntegerOfOriginSpeed 的语义：ow>=0 用 ow，否则用 os）。
# 任一等于目标值即命中，命中时成就会写明是哪个字段——想收紧就改这里。
SPEED_FIELDS = ("os", "ow", "its", "eff")


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
RULE_KIND_SKILL = "skill"        # ACT 里出现目标技能 → 回合边界结算（与李箱成就同逻辑）
RULE_KIND_MENTAL = "mental"      # 理智(SP) 低于阈值 → 立刻置位
RULE_KIND_HP = "hp"              # 血量低于最大血量的比例 → 立刻置位
RULE_KINDS = (RULE_KIND_SKILL, RULE_KIND_MENTAL, RULE_KIND_HP)


@dataclass(frozen=True)
class BattleRule:
    """一条可数据化的战斗判定规则（成就基类构造时登记，驱动每帧拿它比对事件）。

    匹配技能（``kind="skill"``）有三种写法，任一命中即可：

    1. ``skill_ids``：完整技能 ID（自带身份，最硬，如 ``1010103``）；
    2. ``identity_ids`` + ``tiers``：按「技能 ID = 身份×100 + 槽位」拼，
       例如 ``identity_ids=(10115,), tiers=(3,)`` 就是「10115 的三技能」；
    3. ``gated_skill_ids``：ID 里不带身份的技能（例如被转化后的技能），
       此时额外要求 actor 身份在 ``identity_ids`` 里，避免敌人用同名技能误触发。
    """

    key: str                                  # 规则名（= 成就 id，成就侧按它取结果）
    label: str = ""                           # 日志里显示的可读名
    kind: str = RULE_KIND_SKILL
    identity_ids: tuple[int, ...] = ()        # 目标身份（5 位身份 ID）
    skill_ids: tuple[int, ...] = ()           # kind=skill：完整技能 ID
    tiers: tuple[int, ...] = ()               # kind=skill：技能槽位（1/2/3/4）
    gated_skill_ids: tuple[int, ...] = ()     # kind=skill：需 actor 身份匹配的技能 ID
    threshold: int = 0                        # kind=mental：mp < threshold
    ratio: float = 1.0                        # kind=hp：hp < mhp * ratio

    # 匹配
    def match_skill(self, skid: int, actor_oid: int) -> bool:
        """技能 ID / 技能身份槽位 / 受控技能 ID 三种写法任一命中。"""
        if skid is not None and skid >= 0:
            if skid in self.skill_ids:
                return True
            if self.tiers and (skid // 100) in self.identity_ids and (skid % 100) in self.tiers:
                return True
            if skid in self.gated_skill_ids and actor_oid in self.identity_ids:
                return True
        return False

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

    def threshold_text(self) -> str:
        """阈值的人类可读写法（写进成就详情/日志）。"""
        if self.kind == RULE_KIND_MENTAL:
            return f"理智 < {self.threshold}"
        if self.kind == RULE_KIND_HP:
            return f"血量 < 最大血量的 {self.ratio:.0%}"
        return "技能命中"


_rules: dict[str, BattleRule] = {}
_rules_lock = threading.Lock()


def register_rule(rule) -> BattleRule:
    """登记一条判定规则（重复 key 以最后一次为准）。支持传 dict。"""
    if isinstance(rule, dict):
        rule = BattleRule(**rule)
    with _rules_lock:
        _rules[rule.key] = rule
    return rule


def registered_rules() -> dict[str, BattleRule]:
    with _rules_lock:
        return dict(_rules)


def clear_rules() -> None:
    with _rules_lock:
        _rules.clear()


def watched_identities() -> set[int]:
    """所有规则里出现过的目标身份（状态文件只保留这些单位的血量/理智）。"""
    with _rules_lock:
        rules = list(_rules.values())
    ids: set[int] = set()
    for rule in rules:
        ids.update(rule.identity_ids)
    return ids


def rule_hit(key: str) -> str | None:
    """规则是否命中过；命中返回详情文本（未命中/没观测到返回 None）。"""
    with _watch_lock:
        watch = _watch
    if watch is None:
        return None
    return watch.rule_detail(key)

# 回合边界信号：这些钩子的命中计数增加 = 新回合（或每单位回合开始的第一次）
BOUNDARY_PREFERRED = ("manager_init", "manager_on_round_start_before")
BOUNDARY_FALLBACK = ("unit_round_start",)

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


def find_process_id(process_name: str = TARGET_PROCESS) -> int | None:
    wanted = process_name.lower()
    if not wanted.endswith(".exe"):
        wanted += ".exe"
    snapshot = _kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not snapshot or snapshot == -1:
        return None
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        ok = _kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while ok:
            if str(entry.szExeFile).lower() == wanted:
                return int(entry.th32ProcessID)
            ok = _kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        _kernel32.CloseHandle(snapshot)
    return None


def _project_root() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.abspath(os.path.join(here, "..", ".."))


def dll_path() -> str:
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
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    return ""


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
    speeds: dict = field(default_factory=dict)       # instanceID → {os,ow,its,eff,oid,os_raw,ow_raw}（整数速度）
    vitals: dict = field(default_factory=dict)       # instanceID → {oid,hp,mhp,mp,tag,round}
    skills: list = field(default_factory=list)       # 本回合 ACTION 事件（未结算）
    flags: dict = field(default_factory=dict)        # 规则 key → 命中详情（含本回合已结算的）
    pending_flags: dict = field(default_factory=dict)  # 技能类规则本回合待结算：key → 详情
    acts_total: int = 0
    spd_total: int = 0
    vitals_total: int = 0
    rnd_total: int = 0
    settled_by: str = ""
    faust_kui_speed_nine: bool = False
    faust_kui_speed_detail: str = ""

    def snapshot(self) -> dict:
        faust = {iid: info for iid, info in self.speeds.items()
                 if info.get("oid") == IDENTITY_FAUST_KUISHOU}
        watched = watched_identities()
        vitals = {iid: info for iid, info in self.vitals.items()
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
            "rule_hits": dict(self.flags),
            "rule_pending": sorted(self.pending_flags),
            # 兼容旧状态文件字段（李箱成就现在是规则驱动）
            "yisang_lcb_s3_used": "ach_yisang_lcb_s3" in self.flags,
            "yisang_lcb_s3_detail": self.flags.get("ach_yisang_lcb_s3", ""),
            "faust_kui_speed_nine": self.faust_kui_speed_nine,
            "faust_kui_speed_detail": self.faust_kui_speed_detail,
            "faust_speeds": faust,
            "watched_vitals": vitals,
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
            log(f"[战斗观测] {key} 与 {key_owner} 指向同一地址 0x{rva:X}，"
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
        self._last_heartbeat = 0.0
        self._last_status_write = 0.0
        self._last_boundary_ts = 0.0
        self._event_file = None
        self._phase = "未启动"
        self._speed_log_seen: set = set()

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

    def settle_turn(self, reason: str = "") -> list:
        """结算本回合：技能类规则置位 + 血量/理智类规则兜底复核。

        返回本回合已结算的技能事件列表。注意：``_write_status`` 必须在**锁外**调用
        （它内部会 ``snapshot()`` 再拿同一把非重入锁）。
        """
        settled: list[tuple[str, str]] = []
        with self._lock:
            pending = list(self.state.skills)
            self.state.skills.clear()
            if pending:
                self.state.settled_by = reason
            for key, detail in list(self.state.pending_flags.items()):
                self.state.pending_flags.pop(key, None)
                if key in self.state.flags:
                    continue
                self.state.flags[key] = detail
                settled.append((key, detail))
            # 兜底：用最后观测到的血量/理智再判一次（本回合一条 VAL 都没来时也不会漏）
            for key, rule in registered_rules().items():
                if rule.kind == RULE_KIND_SKILL or key in self.state.flags:
                    continue
                for info in self.state.vitals.values():
                    if rule.match_vitals(info.get("oid", -1), info.get("hp", VITAL_UNREAD),
                                         info.get("mhp", VITAL_UNREAD),
                                         info.get("mp", VITAL_UNREAD)):
                        detail = self._vitals_detail(rule, info,
                                                     f"{reason or '回合边界'}兜底")
                        self.state.flags[key] = detail
                        settled.append((key, detail))
                        break
        for _key, detail in settled:
            self._log(f"[战斗观测] ★ {detail}")
        self._write_status(force=True)
        return pending

    def rule_detail(self, key: str) -> str | None:
        """规则是否命中；命中返回详情文本（未命中返回 None）。"""
        with self._lock:
            detail = self.state.flags.get(key)
        return detail or None

    def snapshot(self) -> dict:
        with self._lock:
            snap = self.state.snapshot()
        snap["phase"] = self._phase
        snap["injected_pid"] = self._injected_pid
        snap["hook_hits"] = dict(self._last_hits)
        return snap

    # ---------------------------------------------------------------- 事件日志
    def _open_event_file(self) -> None:
        """全量事件日志：**每次实例运行都清空重写**（只留本次运行，便于对照）。"""
        if self._event_file is not None:
            return
        path = event_log_path()
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            self._event_file = open(path, "w", encoding="utf-8", buffering=1)
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
                self._event_file.write(f"{time.strftime('%H:%M:%S')} {message}\n")
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
            _kernel32.CloseHandle(existing)
            if view:
                magic = ctypes.c_int32.from_address(view).value
                _kernel32.UnmapViewOfFile(view)
                if magic == BW_MAGIC:
                    self._log("[战斗观测] 共享内存已存在（上次未正常退出或另一实例在跑），"
                              "本次不注入以免双钩")
                    return False
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
    def _inject(self, pid: int, path: str) -> bool:
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
            if not _kernel32.WriteProcessMemory(proc, remote, wide, size, ctypes.byref(written)):
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
            _kernel32.WaitForSingleObject(thread, 10000)
            exit_code = wt.DWORD()
            _kernel32.GetExitCodeThread(thread, ctypes.byref(exit_code))
            _kernel32.CloseHandle(thread)
            if not exit_code.value:
                self._log("[战斗观测] DLL 加载失败（远程线程退出码为 0）")
                return False
            self._injected_pid = pid
            self._remote_module = int(exit_code.value)
            self._log(f"[战斗观测] 已注入 battle_watch.dll (PID {pid})")
            self._event(f"注入成功 PID={pid}")
            return True
        finally:
            if remote:
                _kernel32.VirtualFreeEx(proc, remote, 0, 0x8000)
            _kernel32.CloseHandle(proc)

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
        if self.verbose:
            self._log(f"[战斗观测] 事件 {line}")
        if kind == "RND":
            with self._lock:
                self.state.round_seq = event.get("seq", self.state.round_seq + 1)
                self.state.rnd_total += 1
            self.settle_turn(f"回合边界({tag or 'hook'})")
        elif kind == "SPD":
            self._apply_spd(event)
        elif kind == "VAL":
            self._apply_vitals(event)
        elif kind == "ACT":
            self._apply_act(event)
        return event

    def _apply_spd(self, event: BattleEvent) -> None:
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
        info = {"oid": oid, "os": os_int, "ow": ow_int,
                "its": event.get("its", -1), "eff": eff_int,
                "os_raw": os_raw, "ow_raw": ow_raw}
        with self._lock:
            self.state.spd_total += 1
            if iid >= 0:
                self.state.speeds[iid] = info
                if oid > 0:
                    self.state.units[iid] = oid
            if oid == IDENTITY_FAUST_KUISHOU:
                if not self.state.faust_kui_speed_nine:
                    matched = [name for name in SPEED_FIELDS if info.get(name) == SPEED_TARGET]
                    if matched:
                        self.state.faust_kui_speed_nine = True
                        self.state.faust_kui_speed_detail = (
                            f"第 {self.state.round_seq} 回合 浮士德-魁首 速度={SPEED_TARGET}"
                            f"（命中字段 {','.join(matched)}；os={speed_text(os_int, os_raw)} "
                            f"ow={speed_text(ow_int, ow_raw)} its={info.get('its')} "
                            f"eff={eff_int} via {event.tag}）")
                        self._log(f"[战斗观测] ★ {self.state.faust_kui_speed_detail}")
                key = (self.state.round_seq, tuple(sorted((k, v) for k, v in info.items()
                                                          if k != "oid")))
                if key not in self._speed_log_seen:
                    self._speed_log_seen.add(key)
                    self._log(f"[战斗观测] 浮士德-魁首 速度: 有效={eff_int}"
                              f"（os={speed_text(os_int, os_raw)} "
                              f"ow={speed_text(ow_int, ow_raw)} its={info.get('its')}"
                              f"；{event.tag}, iid={iid}）")
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
            # 技能类规则：命中先记在本回合待结算表（回合边界才置位，与旧李箱成就同逻辑）
            for key, rule in registered_rules().items():
                if rule.kind != RULE_KIND_SKILL or key in self.state.flags:
                    continue
                if rule.match_skill(record["skid"], actor_oid):
                    self.state.pending_flags.setdefault(
                        key, self._skill_detail(rule, record, "待结算"))
        # 与两个成就相关的技能额外提醒
        if record["skid"] == SKILL_LCB_YISANG_S3 or record["actor_oid"] == 10101:
            self._log(f"[战斗观测] 行动完成: skid={record['skid']} slot={record['slot']} "
                      f"tier={record['tier']} actor={record['actor']} "
                      f"(oid={record['actor_oid']}) via {record['tag']}")

    def _apply_vitals(self, event: BattleEvent) -> None:
        """血量 / 理智事件：命中规则当场置位（不等回合结束）。

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
            for key, rule in registered_rules().items():
                if rule.kind == RULE_KIND_SKILL or key in self.state.flags:
                    continue
                if rule.match_vitals(oid, hp, mhp, mp):
                    detail = self._vitals_detail(rule, info, event.tag)
                    self.state.flags[key] = detail
                    hits.append(detail)
        for detail in hits:
            self._log(f"[战斗观测] ★ {detail}")

    # ---------------------------------------------------------- 规则详情文本
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
        self.table = build_hook_table(on_log=log, pe_path=pe_path)
        table = self.table
        self._phase = "已解析钩子表"
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
        self._write_status(force=True)

        pid = None
        waited = 0.0
        while not self._stop.is_set():
            if pid is None or not self._pid_alive(pid):
                pid = find_process_id(self.process_name)
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
                    continue
                if not self._inject(pid, path):
                    self._sleep(5.0)
                    continue
                waited = 0.0
                self._last_hits = {}
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
                  f"VAL {snap.get('vitals_total', 0)} / ACT {snap['acts_total']} | "
                  f"单位 {snap['units']} | 本回合待结算 {snap['pending_skills']} | "
                  f"成就判定 {len(flags)} 条{('（' + ','.join(flags) + '）') if flags else ''} | "
                  f"钩子命中: {hits or '（全 0）'}")
        if not hits:
            self._log("[战斗观测] 提示: 所有观测点命中数都是 0 —— 说明这些函数当前没被调用，"
                      "把这段日志发我（或跑 --probe 看钩子表）")

    def _report_status(self, cfg: BWConfig) -> None:
        if int(cfg.gameassembly_found) and "ga" not in self._status_logged:
            self._status_logged.add("ga")
            self._phase = "GameAssembly 已加载"
            self._log("[战斗观测] 游戏已加载 GameAssembly.dll，等待装钩")
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


def yisang_lcb_used_s3() -> bool:
    """兼容旧 API：李箱三技能成就（现在是规则 ``ach_yisang_lcb_s3`` 驱动）。"""
    return rule_hit("ach_yisang_lcb_s3") is not None


def faust_kui_speed_nine() -> bool:
    with _watch_lock:
        return bool(_watch and _watch.state.faust_kui_speed_nine)


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


def cmd_probe() -> int:
    """离线自查：打印将要下发的钩子表（含尾调用桩解引用结果），不注入。"""
    from functions.hook.paths import game_paths
    paths = game_paths()
    _print(f"游戏目录: {paths.root or '（未找到）'}")
    _print(f"GameAssembly.dll: {paths.gameassembly or '（未找到）'}")
    table = build_hook_table(on_log=_print, pe_path=paths.gameassembly)
    _print(f"\n偏移来源: {table['source']}；索引可用={table['index_available']}")
    _print(f"将下发 {len(table['entries'])} 个观测点:")
    _print(describe_hook_table(table))
    _print(f"\nbattle_watch.dll: {dll_path() or '（未找到，需先编译）'}")
    _print(f"事件日志: {event_log_path()}")
    _print(f"状态文件: {status_path()}")
    running = find_process_id(TARGET_PROCESS)
    _print(f"游戏进程: {'PID ' + str(running) if running else '未运行'}")
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
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
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
                f"{k}={v}" for k, v in snap.items() if k not in ("faust_speeds", "hook_hits")))
    except KeyboardInterrupt:
        pass
    finally:
        watch.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
