"""战斗类成就的基类 —— 把「判定数据」和「判定逻辑」拆开的一层。

思路：**成就只声明数据**（哪个身份、哪个技能、什么阈值），观测与判定都在
``functions.achievement.battle_watch`` 里做。基类构造时把数据登记成一条
``battle_watch.BattleRule``，``check()`` 只读观测结果 —— 所以加一个新成就
基本只需要写一个 ``__init__``，不用碰 DLL / 驱动。

现成的四类基类（都用关键字参数，阈值也是数据）::

    SkillUseAchievement(ach_id=..., name=..., description=...,
                        identity_id=10115, tiers=(3,))          # 身份 + 技能槽位
    SkillUseAchievement(..., identity_id=10101, skill_ids=(1010103,))  # 或直接给技能 ID

    SpeedValueAchievement(..., identity_ids=(10212,), value=9)
        # 这些身份任一「速度 == 9」时解锁（fields 可指定看哪几个速度字段）

    MentalThresholdAchievement(..., identity_ids=(10913, 10312), threshold=0)
        # 这些身份任一「理智(SP) < 0」时解锁（负数理智 = 恐慌）

    DamageTakenAchievement(..., identity_ids=(10705,), ratio=1.0)
        # 这些身份任一「hp < 最大血量 × ratio」时解锁（ratio=1.0 = 掉过血）

规律（与规则表 ``kind`` 一一对应）：

- ``skill``：**回合边界结算**；
- ``speed`` / ``mental`` / ``hp``：观测到就**立刻**置位，回合边界还会兜底复核一次；
- 想要更复杂的规则：继承 ``BattleRuleAchievement``，用 ``rules=(BattleRule(...),)``
  直接给规则；
- 想加新*类别*的判定（例如「某身份获得了某 buff」）：在 ``battle_watch`` 里加
  ``RULE_KIND_*`` + 对应的 ``match_*``，这里加一个薄薄的数据类即可；
- **业务常量（身份/技能 ID、阈值）写在各自的成就模块里**，驱动不认识它们。
"""

from __future__ import annotations

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
                 label: str = "", rarity: str = "epic"):
        """战斗事件类成就基类构造函数。

        注册 ``BattleRule`` 到 ``battle_watch``，``check()`` 只是读结果。

        Args:
            ach_id (str): 成就 ID
            name (str): 名称
            description (str): 描述
            identity_id (int, optional): 身份。 Defaults to 0.
            skill_ids (tuple, optional): 完整技能 ID。 Defaults to ().
            tiers (tuple, optional): 技能槽位。 Defaults to ().
            gated_skill_ids (tuple, optional): ID 里不带身份的技能。 Defaults to ().
            label (str, optional): 标签。 Defaults to "".
            rarity (str, optional): 稀有度。 Defaults to "epic".
        """
        rule = battle_watch.BattleRule(
            key=ach_id,
            label=label or (f"身份 {identity_id}" if identity_id else ach_id),
            kind=battle_watch.RULE_KIND_SKILL,
            identity_ids=(identity_id,) if identity_id else (),
            skill_ids=tuple(skill_ids),
            tiers=tuple(tiers),
            gated_skill_ids=tuple(gated_skill_ids),
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
