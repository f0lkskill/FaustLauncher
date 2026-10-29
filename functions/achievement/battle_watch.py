
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

STAGE_WATCH_MAX = 32
TARGET_PROCESS = "LimbusCompany.exe"

#: 事件从哪来：WarpHook 的共享宿主（P5 起唯一引擎）。

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

STATUS_WRITE_SEC = 2.0

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
    "railway_total": ("LimbusCompany.RailwayDungeon.HistoryLibs.RailwayDungeonHistoryDataByCollection::GetTotalClearTurn",
                      0x1A83AF0, "railway_total"),
    "stage_clear_info": ("UserStageClearInfoData::UpdateData", 0x18E62D0, "cache_self"),
    "stage_clear_query": ("UserStageClearInfoData::GetData", 0x18E6300, "cache_self"),
    "stage_clear_last": ("UserStageClearInfoData::GetLastClearData", 0x18E63E0, "cache_self"),
    "node_cleared": ("UserStageNodeStateData::IsNodeCleared", 0x18B0A30, "node_state"),
    "node_clear_state": ("UserStageNodeStateData::GetClearNodeState", 0x18B0630, "node_state"),
    "node_cleared_short": ("UserStageNodeStateData::IsNodeCleared", 0x18B0AB0, "cache_self"),
    "stage_progress": ("UserStageNodeStateData::UpdateData", 0x18AFFE0, "cache_arg1"),
    "railway_node": ("RailwayDungeonFormerSaveData::.ctor", 0x18B38D0, "railway_node"),
    "railway_hist": ("LimbusCompany.RailwayDungeon.HistoryLibs.RailwayDungeonHistoryDataByCollection::.ctor", 0x1A83860, "railway_hist"),
    "stage_node_id": ("StageNodeIdInfo::SetData", 0x12636F0, "stage_node_id"),
    "railway_ui_text": ("LimbusCompany.RailwayDungeon.UI.RailwayDungeonMapUpperUILine1002::UpdateUI", 0x1A4E500,
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
    "skv_attacker_iid": 0x130,
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

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_HANDLE = ctypes.c_void_p

_kernel32.CloseHandle.argtypes = [_HANDLE]
_kernel32.OpenProcess.restype = _HANDLE
_kernel32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
_kernel32.QueryFullProcessImageNameW.argtypes = [_HANDLE, wt.DWORD, ctypes.c_wchar_p,
                                                 ctypes.POINTER(wt.DWORD)]
_kernel32.GetProcessTimes.argtypes = [_HANDLE, ctypes.POINTER(wt.FILETIME),
                                      ctypes.POINTER(wt.FILETIME),
                                      ctypes.POINTER(wt.FILETIME),
                                      ctypes.POINTER(wt.FILETIME)]

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

PROCESS_QUERY_LIMITED = 0x1000

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

def _project_root() -> str:
    try:
        from functions.base.common.path_utils import get_app_root
        return get_app_root()
    except Exception:  # noqa: BLE001
        here = os.path.dirname(os.path.abspath(__file__))
        return os.path.abspath(os.path.join(here, "..", ".."))

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

class BattleWatch:

    def __init__(self, log_callback=None, poll_interval: float = 0.25,
                 process_name: str = TARGET_PROCESS, verbose: bool = False) -> None:
        self.log_callback = log_callback or (lambda _m: None)
        # 钩子全在 WarpHook：配置即钩子，加减一条不用重编 C，游戏跑着也能换表。
        # 事件从宿主共享内存里泵出来，照样走 :meth:`handle_line` 喂规则引擎。
        self._source = None
        self.poll_interval = max(0.1, float(poll_interval))
        self.process_name = process_name
        self.verbose = verbose
        self.state = BattleState()

        self._lock = threading.Lock()
        self._status_logged: set[str] = set()
        self._last_hits: dict[str, int] = {}
        self._boundary_keys: set[str] = set()
        self._last_event_ts = 0.0
        self._last_status_write = 0.0
        self._last_boundary_ts = 0.0
        self._last_anim_tick_ts = 0.0
        self._last_anim_release_ts = 0.0
        self._last_round_boundary_ts = 0.0
        self._battle_ended = False
        self._event_file = None
        self._event_to_sink = False
        self._phase = "未启动"

    def start(self) -> bool:
        if self.running:
            return True
        return self._start_warp()

    def _start_warp(self) -> bool:
        """用 WarpHook 挂钩子：事件照样走 :meth:`handle_line`，规则引擎不用改。"""
        from functions.achievement.warp_source import WarpSource
        source = WarpSource(self, log=self._log)
        if not source.attach():
            self._log("[BattleWatch] WarpHook 引擎没起来，成就事件不会产生")
            return False
        self._source = source
        source.start()
        self._phase = "WarpHook 引擎"
        self._write_status(force=True)
        return True

    def stop(self) -> None:
        if self._source is not None:
            self._source.stop()
            self._source = None
        self._close_event_file()

    @property
    def running(self) -> bool:
        return bool(self._source is not None and self._source.running)

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
        snap["hook_hits"] = dict(self._last_hits)
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
        try:
            path = status_path()
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=1)
        except OSError:
            pass



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

def cmd_probe() -> int:
    from functions.hook.paths import game_paths
    from functions.achievement.warp_source import build_hooks
    paths = game_paths()
    _print(f"游戏目录: {paths.root or '（未找到）'}")
    _print(f"GameAssembly.dll: {paths.gameassembly or '（未找到）'}")
    hooks = build_hooks()
    events = [h for h in hooks if h.get("event")]
    _print(f"\nWarpHook 钩子表: {len(hooks)} 条（事件 {len(events)} / 只缓存 "
           f"{len(hooks) - len(events)}）")
    for h in hooks:
        mark = f"事件#{h['event']}" if h.get("event") else "只缓存"
        extra = ""
        if h.get("ret_kind"):
            extra = f" ret={h['ret_kind']}"
        _print(f"  [{mark}] {h['klass']}::{h['method']} argc={h['argc']} "
               f"reads={len(h.get('reads') or ())}{extra}")
    _print("")
    expected = _expected_game_exe()
    _print(f"期望的游戏进程: {expected or '（配置里没拿到游戏路径，将退化为同名第一个）'}")
    candidates = find_process_candidates(TARGET_PROCESS)
    for pid, image in candidates:
        mark = ("→ 游戏在跑" if (expected and image and _same_file(image, expected))
                else "（映像不符）")
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
    log("[BattleWatch] 钩子由 WarpHook 宿主执行，游戏需经启动器启动并注入 warp_host.dll")
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
