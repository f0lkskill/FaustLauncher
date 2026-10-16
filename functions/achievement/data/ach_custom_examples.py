
from __future__ import annotations

from functions.achievement import battle_watch
from functions.achievement.battle_achievements import (
    BuffPresentAchievement,
    CompositeAchievement,
    Condition,
)

IDENTITY_ISHMAEL_TING_REP = 10813
IDENTITY_RODION_THUMB_CAPO = 10916
IDENTITY_HEATHCLIFF_THUMB_PROXY = 10716
BUFF_HANAFUDA_TWO = "HanafudaTwo"
BUFF_FUTURE_EYE = "FutureEyeOnRodion"

class DeadHandAchievement(BuffPresentAchievement):

    def __init__(self) -> None:
        super().__init__(
            ach_id="ach_dead_hand",
            name="这他妈的烂牌！",
            description="定事务所代表-以实玛利 在战斗的首个回合抽到「组札-芒上月」。",
            identity_ids=(IDENTITY_ISHMAEL_TING_REP,),
            buffs=(BUFF_HANAFUDA_TWO,),
            max_round=1,
            label="定事务所代表 以实玛利",
            rarity="uncommon",
        )

class HeartHeartAchievement(CompositeAchievement):

    def __init__(self) -> None:
        skill = Condition(
            key="skill",
            rule=battle_watch.BattleRule(
                key="ach_heart_heart.skill",
                label="拇指 父辈 罗佳 使用任意技能",
                kind=battle_watch.RULE_KIND_SKILL,
                identity_ids=(IDENTITY_RODION_THUMB_CAPO,),
                any_skill=True,
            ),
        )
        eyebuff = Condition(
            key="eyebuff",
            rule=battle_watch.BattleRule(
                key="ach_heart_heart.buff",
                label="拇指 父辈 罗佳 带有 预知眼",
                kind=battle_watch.RULE_KIND_BUFF,
                identity_ids=(IDENTITY_RODION_THUMB_CAPO,),
                buffs=(BUFF_FUTURE_EYE,),
            ),
        )
        ally = Condition(
            key="ally",
            rule=battle_watch.BattleRule(
                key="ach_heart_heart.ally",
                label="拇指 子辈 希斯克里夫 在场",
                kind=battle_watch.RULE_KIND_PRESENCE,
                identity_ids=(IDENTITY_HEATHCLIFF_THUMB_PROXY,),
            ),
            state_only=True,
        )
        super().__init__(
            ach_id="ach_heart_heart",
            name="心脏，心脏！",
            description="让 拇指子辈，希斯克里夫 触发一次追击。",
            conditions=(skill, eyebuff, ally),
            chain=("eyebuff", "skill"),
            require="skill and eyebuff and ally",
            label="心脏，心脏！",
            rarity="rare",
        )
