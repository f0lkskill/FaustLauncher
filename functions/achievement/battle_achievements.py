
from __future__ import annotations

import ast as _ast
from dataclasses import dataclass

from functions.achievement import battle_watch
from functions.achievement.base_achievement import BaseAchievement

class BattleRuleAchievement(BaseAchievement):

    battle_driven = True

    def __init__(self, ach_id: str, name: str, description: str,
                 rules=(), rarity: str = "common"):
        super().__init__(ach_id, name, description, rarity)
        self.detail = ""
        self.rules = tuple(battle_watch.register_rule(rule) for rule in rules)

    @property
    def rule_keys(self) -> tuple[str, ...]:
        return tuple(rule.key for rule in self.rules)

    def check(self) -> bool:
        if self.unlocked:
            return True
        try:
            for rule in self.rules:
                detail = battle_watch.rule_hit(rule.key)
                if detail:
                    self.detail = detail
                    self.mark_unlocked()
                    break
        except Exception:
            return False
        return self.unlocked

class StageClearTurnAchievement(BaseAchievement):

    battle_driven = True

    def __init__(self, ach_id: str, name: str, description: str,
                 uid_prefixes=(), max_turn: int = 0, require_ex: bool = False,
                 max_dead: int = -1, rarity: str = "epic"):
        super().__init__(ach_id, name, description, rarity)
        self.uid_prefixes = tuple(str(p) for p in uid_prefixes)
        self.max_turn = int(max_turn)
        self.require_ex = bool(require_ex)
        self.max_dead = int(max_dead)
        self.detail = ""

    def _uid_matches(self, uid: str) -> bool:
        if not self.uid_prefixes:
            return True
        return any(uid.startswith(p) for p in self.uid_prefixes)

    def stage_watch_ids(self) -> tuple:
        return ()

    def check(self) -> bool:
        if self.unlocked:
            return True
        try:
            clears = battle_watch.stage_clears()
        except Exception:  # noqa: BLE001
            return False
        for uid, info in clears.items():
            if not self._uid_matches(str(uid)):
                continue
            turn = int(info.get("turn", -1))
            cleared = bool(info.get("cleared"))
            if turn < 0 and not (cleared and not self.max_turn):
                continue
            if self.max_turn and turn > self.max_turn:
                continue
            if self.require_ex and not int(info.get("ex", 0)):
                continue
            dead = int(info.get("dead", -1))
            if self.max_dead >= 0 and dead > self.max_dead:
                continue
            limit = f"≤{self.max_turn}T" if self.max_turn else "不限回合"
            turn_text = f"{turn}T" if turn >= 0 else "已通关（存档记录）"
            self.detail = (f"{self.name}：关卡 uid={uid} {turn_text}"
                           f"（阈值 {limit}，阵亡={dead}）")
            self.mark_unlocked()
            return True
        return False

class RailwayTotalTurnAchievement(BaseAchievement):

    battle_driven = True

    def __init__(self, ach_id: str, name: str, description: str,
                 line_ids=(), max_turn: int = 0, node_prefixes=(),
                 rarity: str = "epic"):
        super().__init__(ach_id, name, description, rarity)
        self.line_ids = tuple(int(x) for x in line_ids)
        self.max_turn = int(max_turn)
        self.node_prefixes = tuple(str(p) for p in node_prefixes)
        self.detail = ""

    def _node_total(self) -> tuple:
        try:
            nodes = battle_watch.railway_nodes()
        except Exception:  # noqa: BLE001
            return -1, 0
        if not nodes:
            return -1, 0
        total = 0
        used = 0
        for node_id, turn in nodes.items():
            if self.node_prefixes and not str(node_id).startswith(self.node_prefixes):
                continue
            total += max(0, int(turn))
            used += 1
        return (total, used) if used else (-1, 0)

    def check(self) -> bool:
        if self.unlocked:
            return True
        limit = f"≤{self.max_turn}T" if self.max_turn else "不限回合"
        try:
            totals = battle_watch.railway_totals()
        except Exception:  # noqa: BLE001
            totals = {}
        for line, total in totals.items():
            if self.line_ids and int(line) not in self.line_ids:
                continue
            if int(total) < 0 or (self.max_turn and int(total) > self.max_turn):
                continue
            self.detail = f"{self.name}：线路 {line} 总回合={total}（阈值 {limit}）"
            self.mark_unlocked()
            return True
        total, used = self._node_total()
        if total >= 0 and not (self.max_turn and total > self.max_turn):
            self.detail = (f"{self.name}：{used} 个节点的通关回合合计={total}"
                           f"（阈值 {limit}，来自存档节点记录）")
            self.mark_unlocked()
            return True
        return False

class SkillUseAchievement(BattleRuleAchievement):

    def __init__(self, *, ach_id: str, name: str, description: str,
                 identity_id: int = 0, skill_ids=(), tiers=(), gated_skill_ids=(),
                 any_skill: bool = False, max_round: int = 0, min_round: int = 0,
                 label: str = "", rarity: str = "epic"):
        rule = battle_watch.BattleRule(
            key=ach_id,
            label=label or (f"身份 {identity_id}" if identity_id else ach_id),
            kind=battle_watch.RULE_KIND_SKILL,
            identity_ids=(identity_id,) if identity_id else (),
            skill_ids=tuple(skill_ids),
            tiers=tuple(tiers),
            gated_skill_ids=tuple(gated_skill_ids),
            any_skill=bool(any_skill),
            max_round=int(max_round),
            min_round=int(min_round),
        )
        super().__init__(ach_id, name, description, rules=(rule,), rarity=rarity)
        self.identity_id = identity_id
        self.skill_ids = tuple(skill_ids)
        self.tiers = tuple(tiers)
        self.gated_skill_ids = tuple(gated_skill_ids)

class SpeedValueAchievement(BattleRuleAchievement):

    def __init__(self, *, ach_id: str, name: str, description: str,
                 identity_ids, value: int, fields=(), label: str = "",
                 rarity: str = "common"):
        rule = battle_watch.BattleRule(
            key=ach_id,
            label=label or " / ".join(f"身份 {i}" for i in identity_ids),
            kind=battle_watch.RULE_KIND_SPEED,
            identity_ids=tuple(identity_ids),
            threshold=int(value),
            fields=tuple(fields),
        )
        super().__init__(ach_id, name, description, rules=(rule,), rarity=rarity)
        self.identity_ids = tuple(identity_ids)
        self.value = int(value)
        self.fields = tuple(fields)

class MentalThresholdAchievement(BattleRuleAchievement):

    def __init__(self, *, ach_id: str, name: str, description: str,
                 identity_ids, threshold: int = 0, label: str = "",
                 rarity: str = "legendary"):
        rule = battle_watch.BattleRule(
            key=ach_id,
            label=label or " / ".join(f"身份 {i}" for i in identity_ids),
            kind=battle_watch.RULE_KIND_MENTAL,
            identity_ids=tuple(identity_ids),
            threshold=int(threshold),
        )
        super().__init__(ach_id, name, description, rules=(rule,), rarity=rarity)
        self.identity_ids = tuple(identity_ids)
        self.threshold = int(threshold)

class DamageTakenAchievement(BattleRuleAchievement):

    def __init__(self, *, ach_id: str, name: str, description: str,
                 identity_ids, ratio: float = 1.0, label: str = "",
                 rarity: str = "common"):
        rule = battle_watch.BattleRule(
            key=ach_id,
            label=label or " / ".join(f"身份 {i}" for i in identity_ids),
            kind=battle_watch.RULE_KIND_HP,
            identity_ids=tuple(identity_ids),
            ratio=float(ratio),
        )
        super().__init__(ach_id, name, description, rules=(rule,), rarity=rarity)
        self.identity_ids = tuple(identity_ids)
        self.ratio = float(ratio)

class BuffPresentAchievement(BattleRuleAchievement):

    def __init__(self, *, ach_id: str, name: str, description: str,
                 identity_ids, buffs, max_round: int = 0, min_round: int = 0,
                 label: str = "", rarity: str = "common"):
        rule = battle_watch.BattleRule(
            key=ach_id,
            label=label or " / ".join(f"身份 {i}" for i in identity_ids),
            kind=battle_watch.RULE_KIND_BUFF,
            identity_ids=tuple(identity_ids),
            buffs=tuple(buffs),
            max_round=int(max_round),
            min_round=int(min_round),
        )
        super().__init__(ach_id, name, description, rules=(rule,), rarity=rarity)
        self.identity_ids = tuple(identity_ids)
        self.buffs = tuple(buffs)

class FieldPresenceAchievement(BattleRuleAchievement):

    def __init__(self, *, ach_id: str, name: str, description: str,
                 identity_ids, max_round: int = 0, min_round: int = 0,
                 label: str = "", rarity: str = "common"):
        rule = battle_watch.BattleRule(
            key=ach_id,
            label=label or " / ".join(f"身份 {i}" for i in identity_ids),
            kind=battle_watch.RULE_KIND_PRESENCE,
            identity_ids=tuple(identity_ids),
            max_round=int(max_round),
            min_round=int(min_round),
        )
        super().__init__(ach_id, name, description, rules=(rule,), rarity=rarity)
        self.identity_ids = tuple(identity_ids)

@dataclass(frozen=True)
class Condition:

    key: str
    rule: "battle_watch.BattleRule"
    state_only: bool = False

def _condition(key: str, rule: "battle_watch.BattleRule",
               state_only: bool = False) -> Condition:
    return Condition(key=key, rule=rule, state_only=state_only)

class CompositeAchievement(BattleRuleAchievement):

    def __init__(self, *, ach_id: str, name: str, description: str,
                 conditions, require: str = "", chain=(), implied=(),
                 label: str = "", rarity: str = "common"):
        conditions = tuple(conditions)
        if not conditions:
            raise ValueError("CompositeAchievement 至少需要一个条件")
        self.conditions = conditions
        self.require = (require or "").strip()
        self.chain = _normalize_chain(chain) # type: ignore
        self.implied = tuple((str(a), str(b)) for a, b in implied)
        if self.require:
            _validate_expr(self.require, {c.key for c in conditions})
        for src, dst in self.implied:
            keys = {c.key for c in conditions}
            if src not in keys or dst not in keys:
                raise ValueError(f"implied 里的条件名必须都在 conditions 里: {src}→{dst}")
        super().__init__(ach_id, name, description,
                         rules=tuple(c.rule for c in conditions),
                         rarity=rarity)

    @classmethod
    def all_of(cls, **kwargs) -> "CompositeAchievement":
        return cls(**kwargs)

    @classmethod
    def any_of(cls, *, conditions, **kwargs) -> "CompositeAchievement":
        expr = " or ".join(f"({c.key})" for c in conditions)
        return cls(conditions=conditions, require=expr, **kwargs)

    @classmethod
    def chain(cls, *, conditions, **kwargs) -> "CompositeAchievement":
        keys = tuple(c.key for c in conditions)
        return cls(conditions=conditions, chain=keys,
                   require=" and ".join(f"({k})" for k in keys), **kwargs)

    def _satisfied(self) -> dict:
        state = {}
        for cond in self.conditions:
            hit = bool(battle_watch.rule_hit(cond.rule.key))
            if cond.state_only:
                hit = hit or bool(battle_watch.rule_live(cond.rule.key))
            state[cond.key] = hit
        for _ in range(4):
            changed = False
            for src, dst in self.implied:
                if state.get(src) and not state.get(dst):
                    state[dst] = True
                    changed = True
            if not changed:
                break
        return state

    def _chain_ok(self) -> bool:
        order = {cond.key: battle_watch.rule_order(cond.rule.key)
                 for cond in self.conditions}
        for first, second in self.chain: # type: ignore
            o1 = order.get(first, 0)
            o2 = order.get(second, 0)
            if not (o1 and o2 and o1 < o2):
                return False
        return True

    def check(self) -> bool:
        if self.unlocked:
            return True
        try:
            state = self._satisfied()
            if self.require:
                ok = _eval_expr(self.require, state)
            else:
                ok = all(state.values())
            if ok and self.chain and not self._chain_ok():
                ok = False
            if ok:
                self.detail = self._detail(state, ok=True)
                self.mark_unlocked()
            else:
                self.detail = self._detail(state, ok=False)
        except Exception:
            return False
        return self.unlocked

    def _detail(self, state: dict, ok: bool) -> str:
        parts = []
        for cond in self.conditions:
            mark = "√" if state.get(cond.key) else "×"
            parts.append(f"{mark}{cond.key}[{cond.rule.label or cond.rule.key}]")
        head = "全部条件满足" if ok else "条件进度"
        return f"{head}: {' '.join(parts)}" + (f"（require={self.require}）" if self.require else "")

def _validate_expr(expr: str, allowed: set) -> None:
    tree = _ast.parse(expr, mode="eval")
    for node in _ast.walk(tree):
        if isinstance(node, (_ast.BoolOp, _ast.UnaryOp, _ast.Name, _ast.Load,
                             _ast.And, _ast.Or, _ast.Not)):
            continue
        if isinstance(node, _ast.Expression):
            continue
        raise ValueError(f"require 表达式只允许条件名与 and/or/not/括号: {expr!r}")
    names = {n.id for n in _ast.walk(tree) if isinstance(n, _ast.Name)}
    unknown = names - set(allowed)
    if unknown:
        raise ValueError(f"require 里出现了未定义的条件名: {sorted(unknown)}")

def _eval_expr(expr: str, values: dict) -> bool:
    tree = _ast.parse(expr, mode="eval")
    return bool(_eval_node(tree.body, values))

def _eval_node(node, values: dict):
    if isinstance(node, _ast.Name):
        return bool(values.get(node.id))
    if isinstance(node, _ast.BoolOp):
        results = [_eval_node(v, values) for v in node.values]
        if isinstance(node.op, _ast.And):
            return all(results)
        return any(results)
    if isinstance(node, _ast.UnaryOp) and isinstance(node.op, _ast.Not):
        return not _eval_node(node.operand, values)
    if isinstance(node, _ast.Constant):
        return bool(node.value)
    raise ValueError(f"不支持的表达式节点: {type(node).__name__}")

def _normalize_chain(chain) -> tuple:
    chain = tuple(chain)
    if not chain:
        return ()
    if all(isinstance(item, str) for item in chain):
        return tuple((chain[i], chain[i + 1]) for i in range(len(chain) - 1))
    pairs = []
    for item in chain:
        pair = tuple(item)
        if len(pair) != 2:
            raise ValueError(f"chain 每一项要是 (前, 后): {item!r}")
        pairs.append((str(pair[0]), str(pair[1])))
    return tuple(pairs)
