
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

from functions.achievement import log_sink

BW_MAGIC_V5 = 0x34574246
BW_MAGIC = 0x36574246
MAP_NAME = "Local\\FaustLauncher_BattleWatch"
LOG_RING_CAP = 512
LOG_LINE_MAX = 255
MAX_HOOKS = 40
STAGE_WATCH_MAX = 32
NCL_SEEN_MAX = 96
HOOK_NAME_LEN = 40
TARGET_PROCESS = "LimbusCompany.exe"

BUFF_WATCH_MAX = 32

def fnv1a64(text) -> int:
    data = text.encode("utf-8", "replace") if isinstance(text, str) else bytes(text)
    h = 0xCBF29CE484222325
    for byte in data:
        h ^= byte
        h = (h * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return h

KIND_PLAIN = 0
KIND_UNIT = 1
KIND_UNIT_INT_BOOL = 2
KIND_UNIT_GET_INT = 3
KIND_ACTION_INT = 4
KIND_DAMAGE_ACTION = 5
KIND_SKV = 6
KIND_STAGE_STAT = 7
KIND_RAILWAY_TOTAL = 8
KIND_CACHE_SELF = 9
KIND_NODE_STATE = 10
KIND_CACHE_ARG1 = 11
KIND_RAILWAY_NODE = 12
KIND_RAILWAY_HIST = 13
KIND_STAGE_NODE_ID = 14
KIND_RAILWAY_UI_TEXT = 15
KIND_NUMBERS = {"plain": KIND_PLAIN, "unit": KIND_UNIT,
                "unit_int_bool": KIND_UNIT_INT_BOOL, "unit_get_int": KIND_UNIT_GET_INT,
                "action_int": KIND_ACTION_INT, "damage_action": KIND_DAMAGE_ACTION,
                "skv": KIND_SKV, "stage_stat": KIND_STAGE_STAT,
                "railway_total": KIND_RAILWAY_TOTAL, "cache_self": KIND_CACHE_SELF,
                "node_state": KIND_NODE_STATE, "cache_arg1": KIND_CACHE_ARG1,
                "railway_node": KIND_RAILWAY_NODE, "railway_hist": KIND_RAILWAY_HIST,
                "stage_node_id": KIND_STAGE_NODE_ID,
                "railway_ui_text": KIND_RAILWAY_UI_TEXT}

SPEED_SCALE = 1000

VITAL_UNREAD = -1000

SPEED_FIELD_ORDER = ("os", "ow", "its", "eff")

def speed_int(raw: int) -> int:
    if raw is None:
        return -1
    if raw < 0:
        return -1
    return raw // SPEED_SCALE

def speed_text(value: int, raw: int) -> str:
    if raw is None or raw < 0:
        return "未掷"
    return f"{value}(raw {raw})"

RULE_KIND_SKILL = "skill"
RULE_KIND_SPEED = "speed"
RULE_KIND_MENTAL = "mental"
RULE_KIND_HP = "hp"
RULE_KIND_BUFF = "buff"
RULE_KIND_PRESENCE = "presence"
RULE_KINDS = (RULE_KIND_SKILL, RULE_KIND_SPEED, RULE_KIND_MENTAL, RULE_KIND_HP,
              RULE_KIND_BUFF, RULE_KIND_PRESENCE)
RULE_KINDS_IMMEDIATE = (RULE_KIND_SPEED, RULE_KIND_MENTAL, RULE_KIND_HP,
                        RULE_KIND_BUFF, RULE_KIND_PRESENCE)

@dataclass(frozen=True)
class BattleRule:

    key: str
    label: str = ""
    kind: str = RULE_KIND_SKILL
    identity_ids: tuple[int, ...] = ()
    skill_ids: tuple[int, ...] = ()
    tiers: tuple[int, ...] = ()
    gated_skill_ids: tuple[int, ...] = ()
    threshold: int = 0
    ratio: float = 1.0
    fields: tuple[str, ...] = ()
    buffs: tuple[str, ...] = ()
    any_skill: bool = False
    max_round: int = 0
    min_round: int = 0

    def round_ok(self, round_seq: int) -> bool:
        if self.max_round and round_seq > self.max_round:
            return False
        if self.min_round and round_seq < self.min_round:
            return False
        return True

    def match_skill(self, skid: int, actor_oid: int, round_seq: int = 0) -> bool:
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
        if self.kind != RULE_KIND_BUFF or oid not in self.identity_ids:
            return False, ()
        if not self.round_ok(round_seq):
            return False, ()
        hit = tuple(n for n in self.buffs if n in names)
        return bool(hit), hit

    def match_presence(self, oid: int, round_seq: int = 0) -> bool:
        return (self.kind == RULE_KIND_PRESENCE and oid in self.identity_ids
                and self.round_ok(round_seq))

    def match_vitals(self, oid: int, hp: int, mhp: int, mp: int) -> bool:
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
        if self.kind != RULE_KIND_SPEED or oid not in self.identity_ids:
            return False, ()
        names = self.fields or SPEED_FIELD_ORDER
        hit = tuple(name for name in names if speeds.get(name) == self.threshold)
        return bool(hit), hit

    def threshold_text(self) -> str:
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
    with _rules_lock:
        rules = list(_rules.values())
    ids: set[int] = set()
    for rule in rules:
        ids.update(rule.identity_ids)
    return ids

def watched_buff_names() -> tuple[str, ...]:
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
    names = watched_buff_names()
    with _watch_lock:
        watch = _watch
    if watch is not None:
        watch.sync_buff_watch(names)
    return names

def rule_hit(key: str) -> str | None:
    with _watch_lock:
        watch = _watch
    if watch is None:
        return None
    return watch.rule_detail(key)

def rule_order(key: str) -> int:
    with _watch_lock:
        watch = _watch
    if watch is None:
        return 0
    return watch.rule_order(key)

def rule_live(key: str) -> bool:
    with _watch_lock:
        watch = _watch
    if watch is None:
        return False
    return watch.rule_live(key)

BOUNDARY_PREFERRED = ("manager_init", "manager_on_round_start_before")
BOUNDARY_FALLBACK = ("unit_round_start",)

ANIM_TICK_TAGS = ("skv_start", "skv_complete", "skv_end")
ANIM_RELEASE_TAGS = ("skv_end",)

RULE_KINDS_ANIM_WAIT = ("hp", "mental", "buff")
PENDING_REASON = "待动画结束"

def _stamp_reason(detail: str, reason: str) -> str:
    if not reason:
        return detail
    if PENDING_REASON in detail:
        return detail.replace(PENDING_REASON, reason)
    if reason in detail:
        return detail
    return f"{detail}（{reason}）"

ACTION_END_TAGS: tuple[str, ...] = ()
ROUND_BOUNDARY_DEDUPE_SEC = 4.0
NEW_BATTLE_GAP_SEC = 120.0
SKILL_SETTLE_QUIET_SEC = 2.5
SKILL_SETTLE_QUIET_TICKED_SEC = 15.0
FIRST_ANIM_GRACE_SEC = 10.0
SAMPLER_TAG = "sampler"

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

FALLBACK_HOOKS: dict[str, tuple[str, int, str]] = {
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
    "skv_start": ("BattleSkillViewBase::Skill_Start", 0x9B4D80, "skv"),
    "skv_complete": ("BattleSkillViewBase::Skill_Complete", 0x9BD810, "skv"),
    "skv_end": ("BattleSkillViewBase::Skill_End", 0x9475C0, "skv"),
    "stage_statistic": ("StageStatisticPopupData::.ctor", 0x13C8DE0, "stage_stat"),
    "railway_total": ("RailwayDungeonHistoryDataByCollection::GetTotalClearTurn",
                      0x1A83AF0, "railway_total"),
    "stage_clear_info": ("UserStageClearInfoData::UpdateData", 0x18E62D0, "cache_self"),
    "stage_clear_query": ("UserStageClearInfoData::GetData", 0x18E6300, "cache_self"),
    "stage_clear_last": ("UserStageClearInfoData::GetLastClearData", 0x18E63E0, "cache_self"),
    "node_cleared": ("UserStageNodeStateData::IsNodeCleared", 0x18B0A30, "node_state"),
    "node_clear_state": ("UserStageNodeStateData::GetClearNodeState", 0x18B0630, "node_state"),
    "node_cleared_short": ("UserStageNodeStateData::IsNodeCleared", 0x18B0AB0, "cache_self"),
    "stage_progress": ("UserStageNodeStateData::UpdateData", 0x18AFFE0, "cache_arg1"),
    "railway_node": ("RailwayDungeonFormerSaveData::.ctor", 0x18B38D0, "railway_node"),
    "railway_hist": ("RailwayDungeonHistoryDataByCollection::.ctor", 0x1A83860, "railway_hist"),
    "stage_node_id": ("StageNodeIdInfo::SetData", 0x12636F0, "stage_node_id"),
    "railway_ui_text": ("RailwayDungeonMapUpperUILine1002::UpdateUI", 0x1A4E500,
                        "railway_ui_text"),
}
FALLBACK_FIELDS: dict[str, int] = {
    "unit_instance_id": 0x60,
    "unit_origin_id": 0x64,
    "unit_origin_speed": 0xCC,
    "unit_overwrited_speed": 0xD0,
    "unit_int_speed_turn": 0x184,
    "unit_state": 0x148,
    "state_hp": 0x148,
    "state_max_hp": 0x11C,
    "state_mp": 0x158,
    "unit_buff_detail": 0xE0,
    "buff_detail_list": 0x10,
    "buff_model_data": 0x68,
    "buff_static_id": 0x18,
    "action_skill": 0x20,
    "action_commander_id": 0xB4,
    "action_actor_id": 0xBC,
    "skill_data": 0x10,
    "skill_id": 0x10,
    "skill_tier": 0x40,
    "skv_attacker_iid": 0x120,
    "stage_slot_list": 0x10,
    "slot_uid": 0x10,
    "slot_clear_turn": 0x18,
    "slot_dead_count": 0x1C,
    "slot_ex_cleared": 0x20,
    "railway_collection_id": 0x10,
    "stage_clear_list": 0x18,
    "clear_info_list": 0x10,
    "clear_info_id": 0x10,
    "chapter_subs": 0x18,
    "sub_nodes": 0x18,
    "node_id": 0x10,
    "node_clear_type": 0x14,
    "node_clear_number": 0x18,
    "railway_node_id": 0x10,
    "railway_node_turn": 0x14,
    "railway_ui_text": 0x28,
    "tmp_text": 0xE0,
}
NO_STUB_RESOLVE = {"take_attack_dmg_multiplier"}

class BWConfig(ctypes.Structure):

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
        ("off_skv_attacker_iid", ctypes.c_int32),
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
        ("buff_watch_count", ctypes.c_int32),
        ("buff_watch_hashes", ctypes.c_uint64 * BUFF_WATCH_MAX),
        ("off_stage_slot_list", ctypes.c_int32),
        ("off_slot_uid", ctypes.c_int32),
        ("off_slot_clear_turn", ctypes.c_int32),
        ("off_slot_dead_count", ctypes.c_int32),
        ("off_slot_ex_cleared", ctypes.c_int32),
        ("off_railway_collection_id", ctypes.c_int32),
        ("off_stage_clear_list", ctypes.c_int32),
        ("off_clear_info_list", ctypes.c_int32),
        ("off_clear_info_id", ctypes.c_int32),
        ("stage_watch_count", ctypes.c_int32),
        ("stage_watch_ids", ctypes.c_int32 * STAGE_WATCH_MAX),
        ("stage_clear_data", ctypes.c_int64),
        ("stage_seen_mask", ctypes.c_int32),
        ("stage_diag_done", ctypes.c_int32),
        ("ncl_seen", ctypes.c_int32 * NCL_SEEN_MAX),
        ("ncl_seen_count", ctypes.c_int32),
        ("stage_progress_list", ctypes.c_int64),
        ("off_chapter_subs", ctypes.c_int32),
        ("off_sub_nodes", ctypes.c_int32),
        ("off_node_id", ctypes.c_int32),
        ("off_node_clear_type", ctypes.c_int32),
        ("off_node_clear_number", ctypes.c_int32),
        ("off_railway_node_id", ctypes.c_int32),
        ("off_railway_node_turn", ctypes.c_int32),
        ("off_railway_ui_text", ctypes.c_int32),
        ("off_tmp_text", ctypes.c_int32),
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

TH32CS_SNAPTHREAD = 0x00000004
TH32CS_SNAPMODULE = 0x00000008
TH32CS_SNAPMODULE32 = 0x00000010
THREAD_SUSPEND_RESUME = 0x0002
PROCESS_QUERY_LIMITED = 0x1000
SYNCHRONIZE = 0x00100000
SUSPEND_FAILED = 0xFFFFFFFF
GAME_STABLE_SECONDS = 1.0
SUSPEND_WAIT_SECONDS = 15.0
MODULE_VERIFY_SECONDS = 5.0
GA_VERIFY_RETRY = 3
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

_DLL_CHOICE_NOTE = ""

def _process_image_path(pid: int) -> str:
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

_SOLE_INSTANCE = False

def set_sole_instance(value: bool = True) -> None:
    global _SOLE_INSTANCE
    _SOLE_INSTANCE = bool(value)

def sole_instance() -> bool:
    return _SOLE_INSTANCE

def find_process_id(process_name: str = TARGET_PROCESS) -> int | None:
    candidates = find_process_candidates(process_name)
    return candidates[0][0] if candidates else None

def pid_alive_for(pid: int, seconds: float) -> bool:
    handle = _kernel32.OpenProcess(SYNCHRONIZE, False, pid)
    if not handle:
        return False
    try:
        return _kernel32.WaitForSingleObject(handle, int(seconds * 1000)) == 0x00000102
    finally:
        _kernel32.CloseHandle(handle)

def remote_modules(pid: int) -> list[tuple[str, str, int]]:
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
    if not a or not b:
        return False
    for key in ("timestamp", "size_of_image", "entry_rva"):
        if int(a.get(key) or 0) != int(b.get(key) or 0):
            return False
    return True

def local_pe_identity(path: str) -> dict:
    try:
        with open(path, "rb") as fh:
            return _parse_pe_header(fh.read(PE_HEADER_BYTES))
    except OSError:
        return {"timestamp": 0, "size_of_image": 0, "entry_rva": 0, "header_sha256": ""}

def remote_pe_identity(pid: int, module_name: str = "gameassembly.dll") -> dict:
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

def _process_thread_ids(pid: int) -> list[int]:
    snapshot = _kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0)
    if not snapshot or snapshot == -1:
        return []
    out: list[int] = []
    try:
        entry = THREADENTRY32()
        entry.dwSize = ctypes.sizeof(THREADENTRY32)
        ok = _kernel32.Thread32First(snapshot, ctypes.byref(entry))
        while ok:
            if int(entry.th32OwnerProcessID) == pid:
                out.append(int(entry.th32ThreadID))
            ok = _kernel32.Thread32Next(snapshot, ctypes.byref(entry))
    finally:
        _kernel32.CloseHandle(snapshot)
    return out

def process_thread_suspend_state(pid: int) -> tuple[int, int]:
    own_tid = int(_kernel32.GetCurrentThreadId())
    total = 0
    suspended = 0
    for tid in _process_thread_ids(pid):
        if tid == own_tid:
            continue
        handle = _kernel32.OpenThread(THREAD_SUSPEND_RESUME, False, tid)
        if not handle:
            continue
        try:
            prev = int(_kernel32.SuspendThread(handle))
            if prev == SUSPEND_FAILED:
                continue
            total += 1
            if prev > 0:
                suspended += 1
            _kernel32.ResumeThread(handle)
        finally:
            _kernel32.CloseHandle(handle)
    return total, suspended

class SuspendWindow:

    def __init__(self, pid: int, log=None) -> None:
        self.pid = pid
        self.log = log or (lambda _m: None)
        self.thread_ids: list[int] = []
        self.owned: list[int] = []
        self.already = 0
        self.was_suspended = False

    def _enumerate_threads(self) -> list[int]:
        return _process_thread_ids(self.pid)

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
                    _kernel32.ResumeThread(handle)
            finally:
                _kernel32.CloseHandle(handle)
        total = len(self.thread_ids)
        self.was_suspended = bool(total) and not self.owned and self.already >= total
        if self.was_suspended:
            self.log(f"[BattleWatch] 检测到游戏进程已处于挂起态（{total}/{total} 个线程挂起）"
                     "→ 直接在这个挂起窗口内注入")
        elif self.owned:
            self.log(f"[BattleWatch] 已建立注入窗口：挂起 {len(self.owned)} 个线程"
                     f"（共 {total} 个，其中 {self.already} 个本来就挂起）")
        else:
            self.log(f"[BattleWatch] 未能挂起任何线程（共 {total} 个），按普通方式注入")
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
            self.log(f"[BattleWatch] 注入窗口关闭：恢复 {len(self.owned)} 个线程")
        self.owned = []
        return False

def _project_root() -> str:
    try:
        from functions.base.common.path_utils import get_app_root
        return get_app_root()
    except Exception:  # noqa: BLE001
        here = os.path.dirname(os.path.abspath(__file__))
        return os.path.abspath(os.path.join(here, "..", ".."))

def _pick_newest_dll(candidates: list[str]) -> tuple[str, str]:
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

_KV_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)=(\S+)")

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
        if key not in self.values:
            return None
        try:
            return int(self.values[key])
        except (TypeError, ValueError):
            return None

    def text(self, key: str, default: str = "") -> str:
        value = self.values.get(key, default)
        return default if value is None else str(value)

@dataclass
class BattleState:
    round_seq: int = 0
    units: dict = field(default_factory=dict)
    speeds: dict = field(default_factory=dict)
    vitals: dict = field(default_factory=dict)
    buffs: dict = field(default_factory=dict)
    skills: list = field(default_factory=list)
    flags: dict = field(default_factory=dict)
    flag_seq: dict = field(default_factory=dict)
    pending_flags: dict = field(default_factory=dict)
    pending_immediate: dict = field(default_factory=dict)
    pending_seqs: dict = field(default_factory=dict)
    pending_seq: int = 0
    pending_group: dict = field(default_factory=dict)
    groups: dict = field(default_factory=lambda: {0: {"oid": -1, "keys": [], "open": True}})
    released_groups: set = field(default_factory=set)
    cur_group: int = 0
    next_group: int = 1
    unit_group: dict = field(default_factory=dict)
    round_anim_seen: bool = False
    group_binding: int = -1
    bound_iid: int = -1
    group_flushes: int = 0
    anim_open: bool = False
    stray_anim_ends: int = 0
    anim_ticks_total: int = 0
    anim_ticks_with_iid: int = 0
    anim_last_tag: str = ""
    acts_total: int = 0
    spd_total: int = 0
    vitals_total: int = 0
    buff_total: int = 0
    stage_clears: dict = field(default_factory=dict)
    stage_last: dict = field(default_factory=dict)
    stage_total: int = 0
    railway_totals: dict = field(default_factory=dict)
    railway_last: dict = field(default_factory=dict)
    railway_nodes: dict = field(default_factory=dict)
    stage_labels: dict = field(default_factory=dict)
    railway_ui_text: dict = field(default_factory=dict)
    rnd_total: int = 0
    settled_by: str = ""
    flag_counter: int = 0

    def snapshot(self) -> dict:
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
            "rule_pending_groups": {k: g for k, g in sorted(self.pending_group.items())},
            "action_groups": {g: {"oid": v.get("oid", -1), "keys": list(v.get("keys") or ()),
                                  "open": bool(v.get("open"))}
                             for g, v in sorted(self.groups.items())},
            "released_groups": sorted(self.released_groups),
            "group_binding": self.group_binding,
            "bound_iid": self.bound_iid,
            "group_flushes": self.group_flushes,
            "anim_open": self.anim_open,
            "stray_anim_ends": self.stray_anim_ends,
            "round_anim_seen": self.round_anim_seen,
            "unit_group": {o: g for o, g in sorted(self.unit_group.items())},
            "anim_ticks": self.anim_ticks_total,
            "anim_ticks_with_iid": self.anim_ticks_with_iid,
            "anim_last_tag": self.anim_last_tag,
            "watched_speeds": speeds,
            "watched_vitals": vitals,
            "watched_buffs": buffs,
            "watched_buff_names": list(watched_buff_names()),
            "buff_total": self.buff_total,
        }

def _read_at_rva(pe, rva: int, size: int) -> bytes:
    try:
        return pe.read_at_rva(rva, size)
    except Exception:
        return b""

def resolve_stub(pe, rva: int, names: dict, max_hops: int = 4,
                 on_log=None) -> tuple[int, list]:
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
        log(f"[BattleWatch] 0x{current:X} ({names.get(current, '?')}) 是{kind}"
            f" → 改钩 0x{target:X} ({names.get(target, '?')})")
        current = target
    return current, hops

def build_hook_table(on_log=None, pe_path: str = "") -> dict:
    log = on_log or (lambda _m: None)
    entries: dict[str, dict] = {}
    source = "fallback"

    for key, (symbol, rva, kind) in FALLBACK_HOOKS.items():
        entries[key] = {"key": key, "symbol": symbol, "rva": rva, "kind": kind,
                        "prologue": "", "source": "fallback"}

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
        log(f"[BattleWatch] hook_index 不可用，使用内置回退偏移: {exc}")

    names: dict[int, str] = {}
    if index is not None:
        for key, item in (index.symbols.get("methods") or {}).items():
            rva = int(item.get("rva") or 0) if isinstance(item, dict) else int(item or 0)
            if rva:
                names.setdefault(rva, key)

    pe = None
    if pe_path and os.path.isfile(pe_path):
        try:
            from functions.hook.pe import PeFile
            pe = PeFile(pe_path)
        except Exception as exc:  # noqa: BLE001
            log(f"[BattleWatch] 读取 GameAssembly.dll 节表失败（跳过桩解引用）: {exc}")
    resolved: dict[str, dict] = {}
    used_rva: dict[int, str] = {}
    configured_rva = {int(item["rva"]): key for key, item in entries.items()}
    for key, item in entries.items():
        rva = int(item["rva"])
        if pe is not None and key not in NO_STUB_RESOLVE:
            final, hops = resolve_stub(pe, rva, names, on_log=log)
            if final != rva:
                other = configured_rva.get(final)
                if other and other != key:
                    log(f"[BattleWatch] {key} 的尾调用桩指向 {other} 的地址 0x{final:X} —— 不跟随"
                        f"（跟随会吃掉 {other} 这个观测点，且两者 detour 类型不同），"
                        f"改为直接钩桩本身 0x{rva:X}")
                    final, hops = rva, []
                elif not names.get(final):
                    log(f"[BattleWatch] {key} 的尾调用桩指向未知地址 0x{final:X}"
                        f"（符号表里查不到该符号）—— 不跟随，改为直接钩桩本身 0x{rva:X}")
                    final, hops = rva, []
            item["stub_hops"] = [list(h) for h in hops]
            rva = final
        item["final_rva"] = rva
        if pe is not None and (not item["prologue"] or item.get("stub_hops")):
            data = pe.prologue(rva, 16)
            if data and len(data) == 16:
                item["prologue"] = data
                item["prologue_self_read"] = True
        key_owner = used_rva.get(rva)
        if key_owner is not None:
            log(f"[BattleWatch] {key} 与 {key_owner} 指向同一地址 0x{rva:X}，"
                f"已合并（{HOOK_MERGE_WARN}）")
            resolved[key_owner].setdefault("merged_keys", []).append(key)
            continue
        used_rva[rva] = key
        resolved[key] = item

    dropped: list[str] = []
    if index is not None:
        dropped = [k for k, v in resolved.items() if v.get("prologue_self_read")]
        for k in dropped:
            resolved.pop(k, None)
        if dropped:
            log(f"[BattleWatch] 丢弃 {len(dropped)} 个**索引里没有**的观测点（它们的 RVA 只能"
                f"沿用代码里写死的旧值，prologue 又只能本机现读自证，装钩有把游戏改崩的风险）: "
                f"{', '.join(dropped)}")
            log("[BattleWatch] 想恢复它们：跑一次 python -m functions.hook.main update 重建索引"
                "（索引里现在会包含这些观测点，RVA/prologue 都来自当前游戏版本）")

    if len(resolved) > MAX_HOOKS:
        log(f"[BattleWatch] 候选 {len(resolved)} 个超过 DLL 上限 {MAX_HOOKS}，只取前 {MAX_HOOKS} 个")
        resolved = {k: v for k, v in list(resolved.items())[:MAX_HOOKS]}
    return {"entries": resolved, "source": source, "names": names,
            "index_available": index is not None,
            "dropped_self_read": dropped}

def describe_hook_table(table: dict) -> str:
    lines = []
    for i, (key, item) in enumerate(table["entries"].items()):
        pro = (item.get("prologue") or b"")[:8]
        lines.append(f"    [{i:2}] {key:32} 0x{int(item['final_rva']):X} "
                     f"kind={item['kind']:14} prologue={pro.hex(' ')}"
                     + (f"  已合并: {item['merged_keys']}" if item.get("merged_keys") else ""))
    return "\n" + "\n".join(lines)

class BattleWatch:

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
        self._last_anim_tick_ts = 0.0
        self._last_anim_release_ts = 0.0
        self._last_round_boundary_ts = 0.0
        self._battle_ended = False
        self._event_file = None
        self._event_to_sink = False
        self._phase = "未启动"
        self._injected_image = ""
        self._injected_dll = ""
        self._ga_verified = False
        self._ga_retry = 0
        self._ga_note: dict = {}
        self._index_game_note: dict = {}
        self._preflight: dict = {}

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
        settled: list[str] = []
        with self._lock:
            pending = list(self.state.skills)
            self.state.skills.clear()
            if pending:
                self.state.settled_by = reason
            flushed = self._flush_all_pending_locked(reason or "回合边界")
            if flushed:
                self.state.settled_by = reason
                settled.extend(flushed)
            if fallback_immediate:
                suffix = f"{reason or '回合边界'}兜底"
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
                more = self._flush_all_pending_locked(suffix)
                if more:
                    settled.extend(more)
        if only_skills and not settled and not pending:
            return pending
        for detail in settled:
            self._log(f"[BattleWatch] ★ {detail}")
        self._write_status(force=True)
        return pending

    def settle_skills_if_quiet(self, reason: str = "动画结束（静默兜底）") -> bool:
        with self._lock:
            if not self.state.pending_flags and not self.state.pending_immediate:
                return False
            ts = max(self._last_event_ts, self._last_anim_tick_ts)
            quiet = time.time() - ts
            ticked = self.state.anim_ticks_total > 0
            round_ticked = self.state.round_anim_seen
        limit = SKILL_SETTLE_QUIET_TICKED_SEC if ticked else SKILL_SETTLE_QUIET_SEC
        if not round_ticked:
            limit = max(limit, FIRST_ANIM_GRACE_SEC)
        if quiet < limit:
            return False
        return bool(self.settle_turn(reason, fallback_immediate=False,
                                     only_skills=True))

    def mark_battle_end(self) -> None:
        with self._lock:
            self._battle_ended = True

    def rule_detail(self, key: str) -> str | None:
        with self._lock:
            detail = self.state.flags.get(key)
        return detail or None

    def rule_order(self, key: str) -> int:
        with self._lock:
            return int(self.state.flag_seq.get(key, 0))

    def rule_live(self, key: str) -> bool:
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

    def _open_event_file(self) -> None:
        if self._event_file is not None or self._event_to_sink:
            return
        if log_sink.installed():
            self._event_to_sink = True
            self._event(f"==== 战斗观测会话开始 {time.strftime('%Y-%m-%d %H:%M:%S')} ====")
            return
        path = event_log_path()
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
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
        if self._event_to_sink or log_sink.installed():
            self._event_to_sink = True
            if log_sink.write(message, "BattleWatch"):
                return
        if self._event_file is not None:
            try:
                self._event_file.write(
                    log_sink.format_line(message, area="BattleWatch") + "\n")
            except OSError:
                pass

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
                        self._map_handle = existing
                        self._map_view = view
                        self._log("[BattleWatch] 接管上次遗留的共享内存（本进程是唯一实例；"
                                  "游戏里那份 DLL 若还在，会读到下面写入的新配置）")
                        return True
                    _kernel32.UnmapViewOfFile(view)
                    _kernel32.CloseHandle(existing)
                    self._log("[BattleWatch] 共享内存已存在且**还有别的监测实例在跑** → "
                              "本次不注入以免双钩（另一个实例被杀掉后会自动接管）")
                    return False
                _kernel32.UnmapViewOfFile(view)
            _kernel32.CloseHandle(existing)
        handle = _kernel32.CreateFileMappingW(-1, None, 0x04, 0, CONFIG_SIZE,
                                              ctypes.c_wchar_p(MAP_NAME))
        if not handle:
            self._log("[BattleWatch] 创建共享内存失败")
            return False
        view = _kernel32.MapViewOfFile(handle, 0x0006, 0, 0, CONFIG_SIZE)
        if not view:
            _kernel32.CloseHandle(handle)
            self._log("[BattleWatch] 映射共享内存失败")
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
        cfg = BWConfig.from_address(self._map_view)
        return cfg if cfg.magic == BW_MAGIC else None

    def _config_snapshot(self) -> BWConfig | None:
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
        prev = self._config()
        if prev is not None:
            cfg.buff_watch_count = int(prev.buff_watch_count)
            for i in range(BUFF_WATCH_MAX):
                cfg.buff_watch_hashes[i] = int(prev.buff_watch_hashes[i])
        ctypes.memmove(self._map_view, ctypes.byref(cfg), CONFIG_SIZE)
        return True

    def _inject(self, pid: int, path: str, expect_exe: str | None = None) -> bool:
        expected = _expected_game_exe() if expect_exe is None else expect_exe
        image = _process_image_path(pid)
        if expected and image and not _same_file(image, expected):
            self._log(f"[BattleWatch] 跳过 PID {pid}：映像是 {image}，与配置的游戏（{expected}）"
                      "不一致 —— 同名残留进程/别的副本，不注入")
            return False
        info = dll_info(path)
        self._log(f"[BattleWatch] 准备注入 {os.path.basename(path)}（{info['size']} 字节，"
                  f"mtime {info['mtime']}，sha256 {info['sha256'][:12]}…）"
                  + (f"；目标映像 {image}" if image else ""))
        want_name = os.path.basename(path).lower()
        for name, mpath, base in remote_modules(pid):
            if name.lower() == want_name:
                self._log(f"[BattleWatch] 注意：目标进程已有一份 {name}"
                          f"（{mpath or '路径未知'} @0x{base:X}）—— LoadLibraryW 会直接"
                          "返回它、不会重新加载；若它来自旧构建，本次注入不会生效")
                break

        with SuspendWindow(pid, self._log) as window:
            proc = _kernel32.OpenProcess(PROCESS_ACCESS, False, pid)
            if not proc:
                self._log("[BattleWatch] 打开游戏进程失败（游戏可能以管理员权限启动过；"
                          "可尝试以管理员权限运行启动器）")
                return False
            remote = None
            try:
                wide = ctypes.c_wchar_p(path)
                size = (len(path) + 1) * 2
                remote = _kernel32.VirtualAllocEx(proc, None, size, 0x3000, 0x04)
                if not remote:
                    self._log("[BattleWatch] VirtualAllocEx 失败")
                    return False
                written = ctypes.c_size_t()
                if not _kernel32.WriteProcessMemory(proc, remote, wide, size,
                                                    ctypes.byref(written)):
                    self._log("[BattleWatch] WriteProcessMemory 失败")
                    return False
                kernel32 = _kernel32.GetModuleHandleW("kernel32.dll")
                load_lib = _kernel32.GetProcAddress(kernel32, b"LoadLibraryW")
                if not load_lib:
                    self._log("[BattleWatch] 定位 LoadLibraryW 失败")
                    return False
                thread = _kernel32.CreateRemoteThread(proc, None, 0, load_lib, remote, 0, None)
                if not thread:
                    self._log("[BattleWatch] CreateRemoteThread 失败（杀毒软件可能拦截）")
                    return False
                waited = _kernel32.WaitForSingleObject(thread, 10000)
                exit_code = wt.DWORD()
                _kernel32.GetExitCodeThread(thread, ctypes.byref(exit_code))
                _kernel32.CloseHandle(thread)
                if waited == 0x00000102:
                    self._log("[BattleWatch] LoadLibraryW 超时（远程线程还没返回，可能撞上了"
                              "加载器锁；线程已恢复，下面按模块表实际结果判定）")
                elif not exit_code.value:
                    self._log("[BattleWatch] DLL 加载失败（远程线程退出码为 0）")
                    return False
            finally:
                if remote:
                    _kernel32.VirtualFreeEx(proc, remote, 0, 0x8000)
                _kernel32.CloseHandle(proc)

        if not self._verify_remote_dll(pid, path):
            return False
        self._injected_pid = pid
        self._injected_image = image
        self._injected_dll = path
        mode = "借用进程原有的挂起窗口" if window.was_suspended else "临时挂起窗口"
        self._log(f"[BattleWatch] 已注入 battle_watch.dll (PID {pid}，{mode})")
        self._event(f"注入成功 PID={pid} dll={path} sha256={info['sha256'][:12]}")
        return True

    def _verify_remote_dll(self, pid: int, path: str) -> bool:
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
            self._log("[BattleWatch] 注入后没在目标进程里看到 battle_watch.dll"
                      "（被拦截或加载失败）")
            return False
        name, mpath, base = found
        if mpath and path and not _same_file(mpath, path):
            self._log(f"[BattleWatch] 目标进程里的 {name} 来自 {mpath}，不是刚注入的 {path}"
                      " —— 进程里已有一份旧副本（同名模块不会被重新加载），本次注入未生效")
            return False
        self._remote_module = int(base)
        self._log(f"[BattleWatch] 已确认目标进程加载 {name} @0x{base:X}"
                  + (f"（{mpath}）" if mpath else ""))
        return True

    _PREFLIGHT_TEXT = {
        "local-ok": "本地偏移量对得上本机 DLL（未联网、未重建）",
        "cloud-cached": "采用云端偏移量（本地缓存的那份对得上本机 DLL，未联网）",
        "cloud-updated": "本地偏移量是旧版本 → 已采用云端偏移量",
        "rebuilt": "本地重建偏移量（历史状态，客户端已不再产生）",
        "rebuilt-unverified": "本地重建未通过校验（历史状态）",
        "stale": "偏移量对不上本机 DLL，客户端不重建（钩子可能装不上）",
        "no-index": "没有任何可用索引（将用内置回退偏移）",
        "no-game-dll": "找不到 GameAssembly.dll（跳过偏移校验）",
        "error": "偏移预检异常（继续用现有索引）",
    }

    def _run_preflight(self) -> dict:
        try:
            from functions.hook.preflight import ensure_offsets_ready
            info = ensure_offsets_ready(on_log=self._log)
        except Exception as exc:  # noqa: BLE001
            info = {"verdict": "error", "detail": f"{type(exc).__name__}: {exc}"}
            self._log(f"[BattleWatch] 偏移预检不可用（继续用现有索引）: {exc}")
        verdict = str(info.get("verdict") or "")
        text = self._PREFLIGHT_TEXT.get(verdict, verdict)
        self._preflight = dict(info)
        self._preflight.pop("index", None)
        check = info.get("check") or {}
        self._log(f"[BattleWatch] 偏移预检结果: {verdict}（{text}）"
                  + (f"；{check['detail']}" if check.get("detail") else "")) # type: ignore
        index = info.get("index")
        if index is not None:
            game = index.game or {}
            self._index_game_note = {
                "size": int(game.get("gameassembly_size") or 0),
                "pe_timestamp": int(game.get("pe_timestamp") or 0),
                "game_version": str(game.get("game_version") or ""),
                "game_build_id": str(game.get("game_build_id") or ""),
                "game_updated_at": str(game.get("game_updated_at") or ""),
                "generated_at": str(getattr(index, "generated_at", "") or ""),
                "source": str(info.get("source") or ""),
            }
        return info

    def _wait_fully_suspended(self, pid: int, timeout: float = SUSPEND_WAIT_SECONDS) -> bool:
        deadline = time.time() + timeout
        announced = False
        while time.time() < deadline and not self._stop.is_set():
            total, suspended = process_thread_suspend_state(pid)
            if total and suspended >= total:
                self._log(f"[BattleWatch] 已等到游戏进程完全挂起（{suspended}/{total} 个线程）"
                          "→ 在这个窗口内校验偏移并注入")
                return True
            if not announced:
                self._log(f"[BattleWatch] 等待游戏进程完全挂起（当前 {suspended}/{total} 个线程挂起，"
                          f"最多等 {timeout:.0f}s；超时则按常规挂起窗口注入）")
                announced = True
            self._sleep(0.2)
        if not self._stop.is_set():
            self._log(f"[BattleWatch] {timeout:.0f}s 内未出现完全挂起窗口 → 按常规方式注入")
        return False

    def _refresh_hook_table(self, log, pe_path: str) -> bool:
        self._run_preflight()
        table = build_hook_table(on_log=log, pe_path=pe_path)
        self.table = table
        log(f"[BattleWatch] 注入前钩子表就绪: 来源={table['source']}，"
            f"{len(table['entries'])} 个观测点")
        if not self._write_config(table):
            log("[BattleWatch] 注入前写入钩子配置失败，本次注入跳过")
            return False
        names = _sync_buff_watch()
        if names:
            log(f"[BattleWatch] 注入前关注 buff 表已写入 {len(names)} 个: {'/'.join(names)}")
        watch = get_watch()
        stage_ids = observe_stage_ids()
        if stage_ids and watch is not None:
            watch.sync_stage_watch(stage_ids)
        return True

    def _verify_gameassembly(self) -> None:
        pid = self._injected_pid
        if not pid or self._ga_verified:
            return
        remote = remote_pe_identity(pid)
        if not remote:
            self._ga_retry += 1
            if self._ga_retry <= GA_VERIFY_RETRY:
                self._log("[BattleWatch] 还没枚举到进程内的 GameAssembly.dll，稍后再校验")
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
            self._log(f"[BattleWatch] 游戏 DLL 校验通过：进程内 GameAssembly.dll == 磁盘最新那份"
                      f"（PE 时间戳 0x{int(remote['timestamp']):X}，"
                      f"映像 {int(remote['size_of_image'])} 字节，基址 0x{int(remote['base']):X}）")
        else:
            self._log(f"[BattleWatch] ⚠ 游戏 DLL 不一致：进程内 ts=0x{int(remote['timestamp']):X} "
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
            self._log(f"[BattleWatch] 抽取过慢，丢弃了 {dropped} 行事件（可调小轮询间隔）")
        return rows, head

    def sync_buff_watch(self, names=()) -> None:
        cfg = self._config()
        if cfg is None:
            self._log("[BattleWatch] ⚠ 关注 buff 表没写进去：共享内存配置不可用（magic 不对？）")
            return None
        names = tuple(names)[:BUFF_WATCH_MAX]
        for i, name in enumerate(names):
            cfg.buff_watch_hashes[i] = fnv1a64(name)
        for i in range(len(names), BUFF_WATCH_MAX):
            cfg.buff_watch_hashes[i] = 0
        cfg.buff_watch_count = len(names)
        readback = (int(cfg.buff_watch_count), int(cfg.buff_watch_hashes[0]),
                    int(cfg.buff_watch_hashes[1]))
        return readback # type: ignore

    def sync_stage_watch(self, stage_ids=()) -> int:
        cfg = self._config()
        if cfg is None:
            self._log("[BattleWatch] ⚠ 关注关卡表没写进去：共享内存配置不可用（magic 不对？）")
            return 0
        ids = [int(v) for v in stage_ids][:STAGE_WATCH_MAX]
        for i in range(STAGE_WATCH_MAX):
            cfg.stage_watch_ids[i] = ids[i] if i < len(ids) else 0
        cfg.stage_watch_count = len(ids)
        cfg.stage_seen_mask = 0
        if ids:
            self._log(f"[BattleWatch] 关注关卡 {len(ids)} 个: "
                      f"{'/'.join(str(v) for v in ids[:8])}"
                      f"{'…' if len(ids) > 8 else ''}")
        return int(cfg.stage_watch_count)

    def handle_line(self, line: str) -> BattleEvent | None:
        if not line:
            return None
        parts = line.split(None, 1)
        kind = parts[0].upper()
        values = {}
        tag = ""
        if len(parts) > 1:
            for key, value in _KV_RE.findall(parts[1]):
                try:
                    values[key] = int(value)
                except ValueError:
                    values[key] = value
            match = re.search(r"tag=([A-Za-z0-9_]+)", parts[1])
            tag = match.group(1) if match else ""
        event = BattleEvent(kind=kind, values=values, tag=tag, raw=line, ts=time.time())
        if kind in ("INFO", "ERR", "WARN"):
            self._log(f"[BattleWatch] DLL: {line}")
            self._event(f"DLL {line}")
            if kind == "ERR":
                self._log(f"[BattleWatch] 提示: 版本不符就先跑 "
                          f"`python -m functions.hook.main update` 再重启游戏")
            return event
        self._event(line)
        with self._lock:
            self._last_event_ts = time.time()
        if self.verbose:
            self._log(f"[BattleWatch] 事件 {line}")
        if kind == "RND":
            if tag in ANIM_TICK_TAGS:
                self._apply_anim_tick(tag, event.get("iid", -1))
            else:
                now = time.time()
                with self._lock:
                    self.state.rnd_total += 1
                    dup = (tag in BOUNDARY_PREFERRED
                           and now - self._last_round_boundary_ts
                           < ROUND_BOUNDARY_DEDUPE_SEC)
                    if not dup:
                        gap = now - self._last_round_boundary_ts
                        new_battle = (self._battle_ended
                                      or (self._last_round_boundary_ts > 0
                                          and gap > NEW_BATTLE_GAP_SEC))
                        self._last_round_boundary_ts = now
                        if new_battle:
                            self._battle_ended = False
                            self.state.round_seq = 1
                            self._log(f"[BattleWatch] 新战斗开始（距上次回合边界 {gap:.0f}s）"
                                      "→ 回合计数重置为第 1 回合")
                        else:
                            self.state.round_seq = event.get("seq", self.state.round_seq + 1)
                if not dup:
                    self.settle_turn(f"回合边界({tag or 'hook'})")
                    self._begin_action_batch()
                elif self.verbose:
                    self._log(f"[BattleWatch] 回合边界({tag}) 与上一次同回合（{ROUND_BOUNDARY_DEDUPE_SEC:.0f}s 内）→ 不重复计数")
        elif kind == "BUFDIAG":
            self._event(f"DLL {line}")
        elif kind == "SPD":
            self._apply_spd(event)
        elif kind == "VAL":
            self._apply_vitals(event)
        elif kind == "BUF":
            self._apply_buffs(event)
        elif kind == "ACT":
            self._apply_act(event)
        elif kind == "STG":
            self._apply_stage_stat(event)
        elif kind == "RWT":
            self._apply_railway_total(event)
        elif kind == "CLR":
            self._apply_stage_clear(event)
        elif kind == "CLRD":
            ids = event.text("ids", "")
            count = event.get("n", 0)
            self._log(f"[BattleWatch] ★ 存档里的关卡 id 样本（关注表未命中，n={count}）: {ids}")
        elif kind == "NCL":
            self._apply_node_state(event)
        elif kind == "SNI":
            self._apply_stage_node_id(event)
        elif kind == "RUT":
            self._apply_railway_ui_text(event)
        return event

    def _apply_anim_tick(self, tag: str, iid: int = -1) -> None:
        now = time.time()
        with self._lock:
            self.state.anim_ticks_total += 1
            self.state.anim_last_tag = tag
            self.state.round_anim_seen = True
            self._last_anim_tick_ts = now
            if iid >= 0:
                self.state.anim_ticks_with_iid += 1
            if tag not in ANIM_RELEASE_TAGS:
                self.state.anim_open = True
                if iid >= 0:
                    self._bind_group_locked(iid)
                detail = None
            elif not self.state.anim_open:
                self.state.stray_anim_ends += 1
                detail = None
            elif iid >= 0:
                self._last_anim_release_ts = now
                self.state.anim_open = False
                gid = self.state.group_binding
                if gid < 0:
                    detail = None
                else:
                    oid = self.state.groups.get(gid, {}).get("oid", -1)
                    reason = f"动画结束(oid={oid})" if oid > 0 else "动画结束"
                    out = self._release_group_locked(gid, reason)
                    self.state.group_flushes += 1
                    detail = "；".join(out) if out else None
            else:
                self._last_anim_release_ts = now
                self.state.anim_open = False
                detail = self._flush_one_pending_locked("动画结束")
        if not detail:
            return
        self._log(f"[BattleWatch] ▶ 动画结束（{tag}）放行: {detail}")
        self._write_status(force=True)

    def _apply_spd(self, event: BattleEvent) -> None:
        iid = event.get("iid", -1)
        oid = event.get("oid", -1)
        os_raw = event.get("os", -1)
        ow_raw = event.get("ow", -1)
        os_int = event.opt("osi")
        os_int = speed_int(os_raw) if os_int is None else os_int
        ow_int = event.opt("owi")
        ow_int = speed_int(ow_raw) if ow_int is None else ow_int
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
            self._log(f"[BattleWatch] ★ {detail}")
        if event.get("iid", -1) < 0 and event.get("oid", -1) < 0:
            self._log(f"[BattleWatch] 注意: {event.tag} 的 SPD 事件里没有单位字段，"
                      f"可能是钩子签名/偏移不对（原始: {event.raw}）")
        if event.tag == "unit_round_start" and not self._boundary_seen():
            now = time.time()
            if now - self._last_boundary_ts > 1.0:
                self._last_boundary_ts = now
                with self._lock:
                    self.state.round_seq += 1
                self.settle_turn("回合边界(unit_round_start 兜底)")
                self._begin_action_batch()

    def _boundary_seen(self) -> bool:
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
            round_seq = self.state.round_seq
            for key, rule in registered_rules().items():
                if rule.kind != RULE_KIND_SKILL or key in self.state.flags:
                    continue
                if rule.match_skill(record["skid"], actor_oid, round_seq):
                    if key not in self.state.pending_flags and key not in self.state.flags:
                        self.state.pending_seq += 1
                        self.state.pending_seqs[key] = self.state.pending_seq
                        self.state.pending_flags[key] = self._skill_detail(
                            rule, record, PENDING_REASON)
                        self._assign_group_locked(key)
            if event.tag in ("take_attack_dmg_multiplier", "action_on_end_turn"):
                self._mark_group_actor_locked(actor_oid)
            if event.tag == "action_done_with_action":
                skid = record["skid"]
                if skid and skid > 0:
                    self._mark_group_actor_locked(skid // 100)
                self._open_group_locked()
        if ACTION_END_TAGS and event.tag in ACTION_END_TAGS:  # pragma: no cover - 默认空
            self.settle_turn(f"技能动画结束({event.tag})", fallback_immediate=False,
                             only_skills=True)

    def _apply_vitals(self, event: BattleEvent) -> None:
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
            if oid > 0 and event.tag != SAMPLER_TAG:
                self.state.unit_group[oid] = self.state.cur_group
            hits = self._eval_immediate_locked(
                lambda rule: rule.match_vitals(oid, hp, mhp, mp),
                lambda rule: self._vitals_detail(rule, info, event.tag),
                unit_oid=oid)
            hits += self._eval_presence_locked()
        for detail in hits:
            self._log(f"[BattleWatch] ★ {detail}")

    def _set_flag_locked(self, key: str, detail: str) -> None:
        if key in self.state.flags:
            return
        self.state.flag_counter += 1
        self.state.flags[key] = detail
        self.state.flag_seq[key] = self.state.flag_counter

    def _begin_action_batch(self) -> None:
        with self._lock:
            st = self.state
            st.groups = {0: {"oid": -1, "keys": [], "open": True}}
            st.released_groups = set()
            st.cur_group = 0
            st.next_group = 1
            st.group_binding = -1
            st.bound_iid = -1
            st.anim_open = False
            st.round_anim_seen = False
            st.unit_group.clear()
            st.pending_group.clear()

    def _open_group_locked(self) -> int:
        st = self.state
        gid = st.next_group
        st.next_group += 1
        st.groups[gid] = {"oid": -1, "keys": [], "open": True}
        st.cur_group = gid
        return gid

    def _assign_group_locked(self, key: str, unit_oid: int = -1) -> int:
        st = self.state
        gid = st.cur_group
        if unit_oid > 0:
            recorded = st.unit_group.get(unit_oid, -1)
            if recorded >= 0 and recorded in st.groups and recorded not in st.released_groups:
                gid = recorded
        if gid in st.released_groups or gid not in st.groups:
            gid = self._open_group_locked()
        st.groups[gid].setdefault("keys", []).append(key)
        st.pending_group[key] = gid
        return gid

    def _mark_group_actor_locked(self, oid: int) -> None:
        if oid <= 0:
            return
        st = self.state
        group = st.groups.get(st.cur_group)
        if group is None:
            return
        if group.get("oid", -1) <= 0:
            group["oid"] = oid

    def _release_group_locked(self, gid: int, reason: str = "动画结束") -> list[str]:
        st = self.state
        group = st.groups.pop(gid, None)
        st.released_groups.add(gid)
        if st.group_binding == gid:
            st.group_binding = -1
            st.bound_iid = -1
        if not group:
            return []
        out: list[str] = []
        for key in list(group.get("keys") or ()):
            detail = (st.pending_immediate.pop(key, None)
                      or st.pending_flags.pop(key, None))
            st.pending_seqs.pop(key, None)
            st.pending_group.pop(key, None)
            if detail is None:
                continue
            detail = _stamp_reason(detail, reason)
            self._set_flag_locked(key, detail)
            out.append(detail)
        return out

    def _bind_group_locked(self, iid: int) -> int:
        st = self.state
        if st.group_binding >= 0:
            return st.group_binding
        candidates = [g for g in sorted(st.groups) if st.groups[g].get("keys")]
        if not candidates:
            return -1
        oid = st.units.get(iid, -1) if iid >= 0 else -1
        pick = -1
        if oid > 0:
            for gid in candidates:
                if st.groups[gid].get("oid") == oid:
                    pick = gid
                    break
        if pick < 0:
            pick = candidates[0]
        st.group_binding = pick
        st.bound_iid = iid
        return pick

    def _queue_pending_locked(self, key: str, detail: str, unit_oid: int = -1) -> None:
        if key in self.state.flags or key in self.state.pending_immediate \
                or key in self.state.pending_flags:
            return
        self.state.pending_seq += 1
        self.state.pending_seqs[key] = self.state.pending_seq
        self.state.pending_immediate[key] = detail
        self._assign_group_locked(key, unit_oid)

    def _flush_one_pending_locked(self, reason: str = "") -> str | None:
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
        self.state.pending_group.pop(best_key, None)
        if reason and detail:
            detail = _stamp_reason(detail, reason)
        self._set_flag_locked(best_key, detail or "")
        return detail

    def _flush_all_pending_locked(self, reason: str = "") -> list[str]:
        st = self.state
        out: list[str] = []
        for gid in sorted(st.groups):
            out.extend(self._release_group_locked(gid, reason or "回合边界"))
        while True:
            detail = self._flush_one_pending_locked(reason)
            if detail is None:
                break
            out.append(detail)
        return out

    def _eval_immediate_locked(self, match_fn, detail_fn, unit_oid: int = -1) -> list[str]:
        hits: list[str] = []
        for key, rule in registered_rules().items():
            if rule.kind not in RULE_KINDS_IMMEDIATE or key in self.state.flags:
                continue
            if key in self.state.pending_immediate or key in self.state.pending_flags:
                continue
            if match_fn(rule):
                detail = detail_fn(rule)
                if rule.kind in RULE_KINDS_ANIM_WAIT:
                    self._queue_pending_locked(key, detail, unit_oid)
                else:
                    self._set_flag_locked(key, detail)
                hits.append(detail)
        return hits

    def _eval_presence_locked(self) -> list[str]:
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

    def _apply_stage_stat(self, event: BattleEvent) -> None:
        uid = event.text("uid", "")
        turn = event.get("turn", -1)
        dead = event.get("dead", -1)
        ex = event.get("ex", 0)
        with self._lock:
            self.state.stage_total += 1
            info = {"uid": uid, "turn": int(turn), "dead": int(dead),
                    "ex": int(ex or 0), "ts": time.time()}
            self.state.stage_last = info
            if uid and uid != "?":
                self.state.stage_clears[uid] = info
        self._log(f"[BattleWatch] ★ 关卡结算: uid={uid or '?'} 通关回合={turn} "
                  f"阵亡={dead} EX={1 if ex else 0}")

    def _apply_stage_clear(self, event: BattleEvent) -> None:
        stage = event.get("stage", 0)
        cleared = event.get("cleared", 0)
        if not stage or not cleared:
            return
        uid = str(stage)
        with self._lock:
            self.state.stage_clears[uid] = {
                "uid": uid, "turn": -1, "dead": -1, "ex": 0,
                "cleared": True, "ts": time.time(),
            }
        self._log(f"[BattleWatch] ★ 存档记录: 关卡 {stage} 已通关（回溯判定）")

    def _apply_node_state(self, event: BattleEvent) -> None:
        if not event.get("cleared", 0):
            return
        main = event.get("main", 0)
        sub = event.get("sub", 0)
        node = event.get("node", 0)
        idx = event.get("idx", 0)
        sidx = event.get("sidx", 0)
        ts = time.time()
        keys = []
        if idx:
            keys.append(f"{main}-{idx}")
        if sidx and idx:
            keys.append(f"{main}-{sidx}-{idx}")
        keys += [str(sub), str(node), f"{main}:{sub}:{node}"]
        with self._lock:
            for label, info in self.state.stage_labels.items():
                if int(info.get("stage", 0)) == int(node):
                    keys.append(label)
        with self._lock:
            for key in keys:
                self.state.stage_clears[key] = {
                    "uid": key, "turn": -1, "dead": -1, "ex": 0,
                    "cleared": True, "ts": ts,
                }
        self._log(f"[BattleWatch] ★ 关卡已通关（游戏查询）: 章{main} 第{idx}关 "
                  f"(小节id={sub} 节点id={node})")

    def _apply_stage_node_id(self, event: BattleEvent) -> None:
        chapter = event.get("chapter", 0)
        node = event.get("node", 0)
        stage = event.get("stage", 0)
        state = event.get("state", 0)
        part = event.get("part", 0)
        if chapter <= 0 or node <= 0:
            return
        key = f"{chapter}-{node}"
        with self._lock:
            self.state.stage_labels[key] = {"chapter": chapter, "node": node,
                                            "stage": stage, "part": part}
            if state:
                self.state.stage_clears[key] = {
                    "uid": key, "turn": -1, "dead": -1, "ex": 0,
                    "cleared": True, "ts": time.time(),
                }
        self._log(f"[BattleWatch] ★ 关卡身份: {key} 关卡id={stage} 状态={state}"
                  + ("（已通关）" if state else ""))

    def _apply_railway_ui_text(self, event: BattleEvent) -> None:
        raw = event.text("text", "").strip()
        if not raw:
            return
        digits = "".join(ch for ch in raw if ch.isdigit())
        if not digits:
            return
        value = int(digits)
        now = time.time()
        with self._lock:
            line = int(self.state.railway_last.get("line", -1) or -1)
            seen_at = float(self.state.railway_last.get("ts", 0) or 0)
            if line >= 0 and (now - seen_at) < 60.0:
                self.state.railway_totals[line] = value
            self.state.railway_ui_text = {"text": raw, "value": value, "line": line}
        line_text = f"{line}" if line >= 0 else "?"
        self._log(f"[BattleWatch] ★ 铁路界面显示: 「{raw}」→ {value}（线路={line_text}）")

    def _apply_railway_total(self, event: BattleEvent) -> None:
        node = event.opt("node")
        if node is not None:
            turn = event.get("turn", -1)
            with self._lock:
                self.state.railway_nodes[int(node)] = int(turn)
            self._log(f"[BattleWatch] ★ 铁路节点记录: node={node} 通关回合={turn}")
            return
        line = event.get("line", -1)
        total = event.get("total", -1)
        with self._lock:
            if line >= 0:
                self.state.railway_totals[int(line)] = int(total)
            self.state.railway_last = {"line": int(line), "total": int(total), "ts": time.time()}
        vals = event.text("vals", "")
        extra = f" 各节点原始值={vals}" if vals else ""
        self._log(f"[BattleWatch] ★ 铁路记录: 线路={line} 总回合={total} "
                  f"节点数={event.get('nodes', -1)}{extra}")

    def _apply_buffs(self, event: BattleEvent) -> None:
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
            if oid > 0 and event.tag != SAMPLER_TAG:
                self.state.unit_group[oid] = self.state.cur_group
            round_seq = self.state.round_seq
            hits = self._eval_immediate_locked(
                lambda rule: rule.match_buff(oid, present, round_seq)[0],
                lambda rule: self._buff_detail(rule, info, event.tag, present),
                unit_oid=oid)
            hits += self._eval_presence_locked()
        for detail in hits:
            self._log(f"[BattleWatch] ★ {detail}")

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

    def _run_guarded(self) -> None:
        try:
            self._run()
        except Exception as exc:  # noqa: BLE001
            import traceback
            self._log(f"[BattleWatch] 驱动线程异常退出: {type(exc).__name__}: {exc}")
            self._event("驱动线程异常: " + traceback.format_exc().replace("\n", " | "))

    def _run(self) -> None:
        log = self.log_callback
        self._open_event_file()
        path = dll_path()
        if not path:
            self._phase = "缺少 DLL"
            log("[BattleWatch] 找不到 battle_watch.dll，跳过战斗观测"
                "（可运行 functions/achievement/hook_dll/build.ps1 编译）")
            return

        pe_path = ""
        try:
            from functions.hook.paths import game_paths
            pe_path = game_paths().gameassembly
        except Exception:
            pe_path = ""
        self._run_preflight()
        self.table = build_hook_table(on_log=log, pe_path=pe_path)
        table = self.table
        self._phase = "已解析钩子表"
        if _DLL_CHOICE_NOTE:
            log(f"[BattleWatch] {_DLL_CHOICE_NOTE}")
        log(f"[BattleWatch] 偏移来源={table['source']}；下发 {len(table['entries'])} 个观测点：")
        log(describe_hook_table(table))
        missing = [k for k, item in table["entries"].items() if not item.get("prologue")]
        if missing:
            log(f"[BattleWatch] 注意: 以下观测点没有 prologue（将跳过版本自检）: {missing}")

        if not self._open_map():
            self._phase = "共享内存失败"
            return
        if not self._write_config(table):
            self._phase = "写配置失败"
            log("[BattleWatch] 写入共享内存配置失败")
            return
        names = watched_buff_names()
        readback = self.sync_buff_watch(names)
        if names and readback is not None:
            log(f"[BattleWatch] 关注 buff 回读: count={readback[0]} "
                f"hash0=0x{readback[1]:016X} hash1=0x{readback[2]:016X}"
                f"（Python 端 hash0=0x{fnv1a64(names[0]):016X}）")
        if names:
            log(f"[BattleWatch] 关注 buff {len(names)} 个: {'/'.join(names)}")
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
                        log(f"[BattleWatch] 等待 {self.process_name} 启动（最长 5 分钟，之后改慢轮询）")
                    elif int(waited) % 60 == 0:
                        log(f"[BattleWatch] 仍在等待游戏进程（已等 {int(waited)}s）；"
                            f"钩子表已就绪，状态见 cache/achievement/battle_watch_status.json")
                    self._sleep(2.0 if waited < 300 else 10.0)
                    waited += 2.0
                    self._write_status()
                    starting_flag = True
                    continue
                else:
                    if starting_flag:
                        print(f"[BattleWatch] {self.process_name} 启动，PID: {pid}，进入 hook 注入流程。")
                        starting_flag = False
                if note:
                    log(f"[BattleWatch] 进程选择: PID {pid}（{image or '映像未知'}）；{note}")
                if not pid_alive_for(pid, GAME_STABLE_SECONDS):
                    log(f"[BattleWatch] PID {pid} 存活不足 {GAME_STABLE_SECONDS:g}s"
                        "（疑似 Steam 引导进程/闪退），继续等真正的游戏进程")
                    pid = None
                    self._sleep(1.0)
                    continue
                self._wait_fully_suspended(pid)
                if not self._refresh_hook_table(log, pe_path):
                    pid = None
                    self._sleep(5.0)
                    continue
                if not self._inject(pid, path):
                    self._sleep(5.0)
                    continue
                waited = 0.0
                self._last_hits = {}
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
                    log(f"[BattleWatch] 事件解析失败: {line!r} {exc}")
            self._scan_hits(cfg)
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
        for i, (key, _item) in enumerate(list(self.table["entries"].items())[:MAX_HOOKS]):
            hits = int(cfg.hook_hits[i])
            prev = self._last_hits.get(key, 0)
            if hits != prev:
                self._last_hits[key] = hits
                if prev == 0 and hits > 0:
                    self._log(f"[BattleWatch] 观测点开始命中: {key} ×{hits}")
                    if key == "take_attack_dmg_multiplier":
                        self._log("[BattleWatch] ↳ 事件链路已通（受击观测钩子活了）")

    def _heartbeat(self) -> None:
        now = time.time()
        if now - self._last_heartbeat < HEARTBEAT_SEC:
            return
        self._last_heartbeat = now
        with self._lock:
            snap = self.state.snapshot()
        hits = " ".join(f"{k}={v}" for k, v in self._last_hits.items())
        flags = list(snap.get("rule_hits") or {})
        self._log(f"[BattleWatch] 心跳: 阶段={self._phase} PID={self._injected_pid} | "
                  f"事件: RND {snap['rnd_total']} / SPD {snap['spd_total']} / "
                  f"VAL {snap.get('vitals_total', 0)} / ACT {snap['acts_total']} / "
                  f"BUF {snap.get('buff_total', 0)} | "
                  f"动画 tick {snap.get('anim_ticks', 0)}"
                  f"（{snap.get('anim_last_tag') or '无'}，带 iid {snap.get('anim_ticks_with_iid', 0)}） | "
                  f"单位 {snap['units']} | 本回合待结算 {snap['pending_skills']} | "
                  f"行动分组 {len(snap.get('action_groups') or {})}"
                  f"（待放行 {len(snap.get('rule_pending_groups') or {})}，"
                  f"已按动画放行 {snap.get('group_flushes', 0)} 组） | "
                  f"成就判定 {len(flags)} 条{('（' + ','.join(flags) + '）') if flags else ''} | "
                  f"钩子命中: {hits or '（全 0）'}")
        if not hits:
            self._log("[BattleWatch] 提示: 所有观测点命中数都是 0")

    def _report_status(self, cfg: BWConfig) -> None:
        if int(cfg.gameassembly_found) and "ga" not in self._status_logged:
            self._status_logged.add("ga")
            self._phase = "GameAssembly 已加载"
            self._log("[BattleWatch] 游戏已加载 GameAssembly.dll，等待装钩")
        if not self._ga_verified and int(cfg.gameassembly_found):
            self._verify_gameassembly()
        if int(cfg.verified) and "verified" not in self._status_logged:
            self._status_logged.add("verified")
            self._log("[BattleWatch] prologue 自检通过")
        if int(cfg.installed) and "installed" not in self._status_logged:
            self._status_logged.add("installed")
            self._phase = "观测中（已装钩）"
            self._log(f"[BattleWatch] 已装钩 {int(cfg.hook_count)} 个观测点，开始采集事件")
        error = int(cfg.last_error)
        if error and f"err{error}" not in self._status_logged:
            self._status_logged.add(f"err{error}")
            self._phase = f"DLL 错误 {error}"
            self._log(f"[BattleWatch] DLL 状态: {ERROR_TEXT.get(error, error)}")
            if error == 3:
                self._log("[BattleWatch] 提示: 跑一次 `python -m functions.hook.main update` "
                          "重建偏移索引后再启动游戏")

    def _log(self, message: str) -> None:
        for _mark in ("★ 关卡已通关", "★ 关卡身份", "★ 铁路界面显示",
                      "★ 铁路节点记录", "★ 铁路记录"):
            if _mark in message:
                return
        try:
            self.log_callback(message)
        except Exception:
            pass

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
    watch = get_watch(log_callback)
    watch.process_name = process_name
    watch.verbose = log_verbose_enabled() if verbose is None else bool(verbose)
    watch.start()
    return watch

def log_verbose_enabled() -> bool:
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
    with _watch_lock:
        watch = _watch
    if watch is None:
        return {}
    with watch._lock:
        return dict(watch.state.flags)

def settle_turn(reason: str = "") -> list:
    with _watch_lock:
        return _watch.settle_turn(reason) if _watch else []

def mark_battle_end() -> None:
    with _watch_lock:
        if _watch is not None:
            _watch.mark_battle_end()

def stage_clears() -> dict:
    with _watch_lock:
        watch = _watch
    if watch is None:
        return {}
    with watch._lock:
        return {k: dict(v) for k, v in watch.state.stage_clears.items()}

def stage_last() -> dict:
    with _watch_lock:
        watch = _watch
    if watch is None:
        return {}
    with watch._lock:
        return dict(watch.state.stage_last)

def railway_nodes() -> dict:
    with _watch_lock:
        watch = _watch
    if watch is None:
        return {}
    with watch._lock:
        return {int(k): int(v) for k, v in watch.state.railway_nodes.items()}

def observe_stage_ids() -> tuple[int, ...]:
    ids: list[int] = []
    try:
        from functions.achievement.achievements import achievements
    except Exception:  # noqa: BLE001
        return ()
    for ach in achievements:
        getter = getattr(ach, "stage_watch_ids", None)
        if not callable(getter):
            continue
        try:
            for value in getter() or ():
                number = int(value)
                if number and number not in ids:
                    ids.append(number)
        except Exception:  # noqa: BLE001
            continue
    return tuple(ids[:STAGE_WATCH_MAX])

def railway_totals() -> dict:
    with _watch_lock:
        watch = _watch
    if watch is None:
        return {}
    with watch._lock:
        return {int(k): int(v) for k, v in watch.state.railway_totals.items()}

def state_snapshot() -> dict:
    with _watch_lock:
        return _watch.snapshot() if _watch else {}

def load_status() -> dict:
    try:
        with open(status_path(), "r", encoding="utf-8") as fh:
            return json.load(fh) or {}
    except (OSError, ValueError):
        return {}

def _print(message: str) -> None:
    print(message, flush=True)

def _probe_preflight() -> None:
    try:
        from functions.hook.preflight import ensure_offsets_ready
        info = ensure_offsets_ready(on_log=_print, allow_cloud=False)
    except Exception as exc:  # noqa: BLE001
        _print(f"[OffsetProbe] 不可用: {type(exc).__name__}: {exc}")
        return
    verdict = str(info.get("verdict") or "")
    _print(f"[OffsetProbe] {verdict}（"
           f"{BattleWatch._PREFLIGHT_TEXT.get(verdict, verdict)}）")
    check = info.get("check") or {}
    if check.get("detail") and verdict != "local-ok":
        _print(f"[OffsetProbe] {check['detail']}")
    elif verdict == "local-ok":
        _print(f"[OffsetProbe] {check.get('detail', '')}")
        _print("[OffsetProbe] （离线 --probe 不联网、不重建；云端对照只在游戏启动时按需发生）")

def cmd_probe() -> int:
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
    _print("")
    _probe_preflight()
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
    log("[BattleWatch] 独立调试模式（Ctrl+C 结束）；--probe 看钩子表、--status 看状态")
    watch.start()
    try:
        while True:
            time.sleep(5)
            snap = watch.snapshot()
            log("[BattleWatch] 状态: " + ", ".join(
                f"{k}={v}" for k, v in snap.items()
                if k not in ("watched_speeds", "watched_vitals", "rules", "hook_hits")))
    except KeyboardInterrupt:
        pass
    finally:
        watch.stop()
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
