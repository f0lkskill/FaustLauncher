"""战斗类成就的基类 —— 把「判定数据」和「判定逻辑」拆开的一层。

思路：**成就只声明数据**（哪个身份、哪个技能、什么阈值），观测与判定都在
``functions.achievement.battle_watch`` 里做。基类构造时把数据登记成一条
``battle_watch.BattleRule``，``check()`` 只读观测结果 —— 所以加一个新成就
基本只需要写一个 ``__init__``，不用碰 DLL / 驱动。

现成的基类（都用关键字参数，阈值也是数据）::

    SkillUseAchievement(ach_id=..., name=..., description=...,
                        identity_id=10115, tiers=(3,))          # 身份 + 技能槽位
    SkillUseAchievement(..., identity_id=10101, skill_ids=(1010103,))  # 或直接给技能 ID
    SkillUseAchievement(..., identity_id=10916, any_skill=True)        # 用了任意技能

    SpeedValueAchievement(..., identity_ids=(10212,), value=9)
        # 这些身份任一「速度 == 9」时解锁（fields 可指定看哪几个速度字段）

    MentalThresholdAchievement(..., identity_ids=(10913, 10312), threshold=0)
        # 这些身份任一「理智(SP) < 0」时解锁（负数理智 = 恐慌）

    DamageTakenAchievement(..., identity_ids=(10705,), ratio=1.0)
        # 这些身份任一「hp < 最大血量 × ratio」时解锁（ratio=1.0 = 掉过血）

    BuffPresentAchievement(..., identity_ids=(10813,), buffs=("HanafudaTwo",),
                           max_round=1)
        # 这些身份身上有指定 buff 时解锁（buff 名 = Bufs.json 的字符串 id）

    FieldPresenceAchievement(..., identity_ids=(10716,))
        # “场上存在某身份”（常给复合成就当状态条件）

    CompositeAchievement(...)  # 复合主类：require 表达式 / chain 顺序 / implied 蕴含

技能 / 速度 / 理智 / 血量 / buff / 在场 都支持 **回合窗口** ``max_round`` / ``min_round``
（0 = 不限，首个回合=1）。

规律（与规则表 ``kind`` 一一对应）：

- ``skill``：**技能动画结束**（表现层 ``skv_end`` tick；静默期/回合边界只做兜底）结算；
  ⚠ 别用 ``action_done_with_action`` 这类收尾回调 —— 实测它们全在一整个回合的结算
  瞬间（动画开播**之前**）到齐；
- ``speed`` / ``presence``：观测到就**立刻**置位，回合边界还会兜底复核一次；
- ``mental`` / ``hp`` / ``buff``：命中后先挂起，**跟着“自己那个行动组”的动画结束一起放行**
  （battle_watch 的「行动分组」一节：一个行动里的技能/血量/理智/buff 判定在那手动画
  结束时**一起**落地，而不是全部堆在第一个动画后面）；
  （实测这游戏的值变化全在结算瞬间，立刻置位等于"回合一开始就解锁"）；
- 想要更复杂的规则：继承 ``BattleRuleAchievement``，用 ``rules=(BattleRule(...),)``
  直接给规则；
- 想加新*类别*的判定：在 ``battle_watch`` 里加 ``RULE_KIND_*`` + 对应的 ``match_*``，
  这里加一个薄薄的数据类即可；
- **业务常量（身份/技能 ID、buff 名、阈值）写在各自的成就模块里**，驱动不认识它们；
- **一个文件可以写多个成就派生类**（注册时会自动全部实例化，见 ``achievements.py``）。
"""

from __future__ import annotations

import ast as _ast
from dataclasses import dataclass

from functions.achievement import battle_watch
from functions.achievement.base_achievement import BaseAchievement


class BattleRuleAchievement(BaseAchievement):
    """战斗事件类成就基类：数据 = 一组 ``BattleRule``，结果由 battle_watch 判定。

    ``battle_driven = True`` 会被 ``hook.AchievementHook._check_battle_achievements``
    轮询；``check()`` 只是读结果，开销极低。
    """

    battle_driven = True

    def __init__(self, ach_id: str, name: str, description: str,
                 rules=(), rarity: str = "common"):
        """战斗事件类成就基类构造函数。

        注册 ``BattleRule`` 到 ``battle_watch``，``check()`` 只是读结果。

        Args:
            ach_id (str): 成就 ID
            name (str): 名称
            description (str): 描述
            rules (tuple, optional): 规则列表。 Defaults to ().
            rarity (str, optional): 稀有度。 Defaults to "common".
        """
        super().__init__(ach_id, name, description, rarity)
        self.detail = ""                      # 命中详情（日志/界面用）
        # 登记规则（重复 key 以最后一次为准；成就模块可能被重复导入）
        self.rules = tuple(battle_watch.register_rule(rule) for rule in rules)

    @property
    def rule_keys(self) -> tuple[str, ...]:
        return tuple(rule.key for rule in self.rules)

    def check(self) -> bool:
        """只读观测端结果；未注入/未观测到时保持未解锁。"""
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


class SkillUseAchievement(BattleRuleAchievement):
    """「某个身份使用了某个技能」—— 回合边界结算（与李箱三技能成就同逻辑）。

    参数（三选一或组合）：
        ``skill_ids``       完整技能 ID（最硬，如 ``1010103``）
        ``tiers``           技能槽位（1/2/3/4），配合 ``identity_id`` 拼出
                            ``identity_id * 100 + tier``
        ``gated_skill_ids`` ID 里不带身份的技能（例如被转化后的技能），
                            此时额外要求 actor 身份 == ``identity_id``
    """

    def __init__(self, *, ach_id: str, name: str, description: str,
                 identity_id: int = 0, skill_ids=(), tiers=(), gated_skill_ids=(),
                 any_skill: bool = False, max_round: int = 0, min_round: int = 0,
                 label: str = "", rarity: str = "epic"):
        """「某身份用了某技能」类成就。

        Args:
            ach_id/name/description: 成就基本信息
            identity_id: 目标身份（5 位）
            skill_ids / tiers / gated_skill_ids: 三种锁定技能 ID 的写法（任一命中）
            any_skill: True = “用了任意技能”（只看身份，不看具体技能 ID）
            max_round / min_round: 只在指定回合窗口内生效（0 = 不限；首个回合用 max_round=1）
        """
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
    """「某个身份的速度等于某个值」—— 观测到就立刻解锁（回合边界兜底复核）。

    ``fields`` 指定看哪几个速度字段（``os``/``ow``/``its``/``eff``），默认全部都看。
    """

    def __init__(self, *, ach_id: str, name: str, description: str,
                 identity_ids, value: int, fields=(), label: str = "",
                 rarity: str = "common"):
        """速度战斗事件类成就基类构造函数。

        注册 ``BattleRule`` 到 ``battle_watch``，``check()`` 只是读结果。

        Args:
            ach_id (str): 成就 ID
            name (str): 名称
            description (str): 描述
            identity_ids (_type_): 身份
            value (int): 值
            fields (tuple, optional): 速度字段。 Defaults to ().
            label (str, optional): 标签。 Defaults to "".
            rarity (str, optional): 稀有度。 Defaults to "common".
        """
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
    """「某个身份的理智(SP) 跌破阈值」—— 观测到就立刻解锁。

    ``threshold=0`` 即「负数理智」（陷入恐慌）；``_mp`` 的取值范围是 ±45。
    """

    def __init__(self, *, ach_id: str, name: str, description: str,
                 identity_ids, threshold: int = 0, label: str = "",
                 rarity: str = "legendary"):
        """战斗事件类成就基类构造函数。

        注册 ``BattleRule`` 到 ``battle_watch``，``check()`` 只是读结果。

        Args:
            ach_id (str): 成就 ID
            name (str): 名称
            description (str): 描述
            identity_ids (_type_): 身份
            threshold (int, optional): 阈值。 Defaults to 0.
            label (str, optional): 标签。 Defaults to "".
            rarity (str, optional): 稀有度。 Defaults to "legendary".
        """
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
    """「某个身份受伤了」—— 观测到 hp 低于最大血量的占比就立刻解锁。

    ``ratio=1.0``（默认）= 只要掉过血就算；想收紧成「残血」就传 ``ratio=0.5``。
    """

    def __init__(self, *, ach_id: str, name: str, description: str,
                 identity_ids, ratio: float = 1.0, label: str = "",
                 rarity: str = "common"):
        """初始化伤害承受成就。

        Args:
            ach_id (str): 成就ID
            name (str): 成就名称
            description (str): 成就描述
            identity_ids (_type_): 身份IDs
            ratio (float, optional): 血量占比阈值。 Defaults to 1.0.
            label (str, optional): 标签。 Defaults to "".
            rarity (str, optional): 稀有度。 Defaults to "common".
        """
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
    """「某身份身上有指定 buff」—— 观测到（且在回合窗口内）就立刻解锁。

    ``buffs`` 用的是 **Bufs.json 里的字符串 id**（不是数字），例如
    ``"HanafudaTwo"``（组札-芒上月）、``"FutureEyeOnRodion"``（预知眼）；
    驱动会把名字哈希后放进关注表，DLL 只在命中关注表时才上报（不配规则零开销）。

    ``max_round=1`` 就是「首个回合（及之前）出现就算」—— 比如「第一回合开始时
    是否带着某 buff」。
    """

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
    """「场上存在某身份」—— 只要观测到该身份的单位出现就解锁。

    给复合成就当“状态条件”用（例如“场上是否存在拇指子辈希斯克里夫”）。
    """

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


# ============================================================
# 复合成就（主类）
# ============================================================

@dataclass(frozen=True)
class Condition:
    """复合成就里的一个“条件”：一条 ``BattleRule`` + 一个短名（供表达式引用）。

    ``state_only=True`` 表示这是个**状态**条件：检查的那一刻拿当前观测重判，
    而不是看它什么时候被记录过。例：
    “满足前面两步后，场上是否存在拇指子辈希斯克里夫” —— 他从第一回合就在场，
    如果当成了事件顺序，先后关系会不对。
    """

    key: str                    # 表达式里用的短名（如 "skill" / "buff" / "ally"）
    rule: "battle_watch.BattleRule"
    state_only: bool = False


def _condition(key: str, rule: "battle_watch.BattleRule",
               state_only: bool = False) -> Condition:
    return Condition(key=key, rule=rule, state_only=state_only)


class CompositeAchievement(BattleRuleAchievement):
    """复合成就**主类**：把多个条件按任意组合拼成一个成就。

    构造（三者可以混用）::

        # 全部满足（AND）——不传 require 时默认就是全部 AND
        CompositeAchievement(..., conditions=(c1, c2, c3))

        # 任意组合（安全布尔表达式：只允许 条件名 / and / or / not / 括号）
        CompositeAchievement(..., conditions=(c1, c2, c3), require="a and (b or c)")

        # 顺序链：先 a → 再 b → 再 c（每一步必须在前面那步之后才满足）
        CompositeAchievement.chain(..., conditions=(c1, c2, c3))

        # 蕴含：“满足 1 就算同时满足了 2”（在 1 的完成条件下也完成 2）
        CompositeAchievement(..., conditions=(c1, c2), require="a",
                             implied=(("1", "2"),))

    判定时机：监控线程每秒轮询一次；技能类条件本身已经是**技能动画结束**才置位
    （见 battle_watch 的 ``skv_end`` 放行 / 静默结算），所以复合成就也在那之后
    才会满足。

    ⚠ 写 ``chain`` 时注意谁先谁后：像"常驻 buff + 玩家出手"这种组合，buff 从开局就
    在（第一次采样必然早于出手），链必须写成 ``("buff", "skill")``；写反了 rule_order
    永远不满足，成就永远不会触发。
    """

    def __init__(self, *, ach_id: str, name: str, description: str,
                 conditions, require: str = "", chain=(), implied=(),
                 label: str = "", rarity: str = "common"):
        conditions = tuple(conditions)
        if not conditions:
            raise ValueError("CompositeAchievement 至少需要一个条件")
        self.conditions = conditions
        self.require = (require or "").strip()
        self.chain = _normalize_chain(chain)
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

    # ---- 便捷构造 ----
    @classmethod
    def all_of(cls, **kwargs) -> "CompositeAchievement":
        """全部条件都满足（AND）。"""
        return cls(**kwargs)

    @classmethod
    def any_of(cls, *, conditions, **kwargs) -> "CompositeAchievement":
        """任一条件满足（OR）。"""
        expr = " or ".join(f"({c.key})" for c in conditions)
        return cls(conditions=conditions, require=expr, **kwargs)

    @classmethod
    def chain(cls, *, conditions, **kwargs) -> "CompositeAchievement":
        """顺序链：按 conditions 的顺序依次满足。"""
        keys = tuple(c.key for c in conditions)
        return cls(conditions=conditions, chain=keys,
                   require=" and ".join(f"({k})" for k in keys), **kwargs)

    # ---- 判定 ----
    def _satisfied(self) -> dict:
        """每个条件是否满足：事件条件看记录，状态条件看当前观测。"""
        state = {}
        for cond in self.conditions:
            hit = bool(battle_watch.rule_hit(cond.rule.key))
            if cond.state_only:
                hit = hit or bool(battle_watch.rule_live(cond.rule.key))
            state[cond.key] = hit
        # 蕴含：src 满足 → dst 视为满足（可传递，跑几轮直到稳定）
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
        """顺序约束：chain 里的每一对都必须“先满足前者、再满足后者”。

        注意 chain 里写的是**条件短名**，要映射到 rule key 才能问驱动要命中序号。
        """
        order = {cond.key: battle_watch.rule_order(cond.rule.key)
                 for cond in self.conditions}
        for first, second in self.chain:
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


# ============================================================
# 表达式工具（只允许条件名 + and/or/not/括号，用 ast 解析）
# ============================================================

def _validate_expr(expr: str, allowed: set) -> None:
    """校验表达式合法（否则构造时就报错，不会等运行时静默失败）。"""
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
    """安全求值：只允许 Name/BoolOp/UnaryOp（构造时已校验）。"""
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
    """把 chain 归一成 ((a,b), (b,c)) 形式的顺序对。

    支持 ``("a", "b", "c")`` 简写（= a→b→c）与 ``(("a","b"), ...)``。
    """
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
