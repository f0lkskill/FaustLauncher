"""成就「将你李箱，也将我李箱。」—— LCB 罪人李箱 在回合中使用了三技能。

数据（``SkillUseAchievement`` 的构造参数，判定逻辑在 battle_watch 的规则表里）::

    identity_id = 10101                 # LCB 罪人 李箱
    skill_ids   = (1010103,)            # LCB 三技能（自带身份，最硬）
    tiers       = (3,)                  # 同上的「身份 + 槽位」写法，双保险

技能 ID 的编码是 ``<身份5位><槽位2位>``（游戏数据实测，见 ``Lang/LLC_zh-CN/Skills.json``），
所以 ``1010103`` 本身就同时锁定了「LCB 罪人李箱（10101）」和「三技能（03）」。

判定时机：技能类规则**回合边界结算**（本回合出现过就算），与其它技能成就同一套逻辑。
"""

from __future__ import annotations

from functions.achievement.battle_achievements import SkillUseAchievement

# 业务常量（游戏数据；与偏移无关，驱动不认识它们）
IDENTITY_LCB_YISANG = 10101          # LCB 罪人 李箱
SKILL_LCB_YISANG_S3 = 1010103        # 李箱 LCB 三技能


class YisangLcbThirdSkillAchievement(SkillUseAchievement):
    """战斗事件类成就：由注入 DLL 观测，回合边界结算。"""

    def __init__(self) -> None:
        super().__init__(
            ach_id="ach_yisang_lcb_s3",
            name="将你李箱，也将我李箱。",
            description="回合结束时检测到 LCB 罪人 李箱 使用了自己的三技能",
            identity_id=IDENTITY_LCB_YISANG,
            skill_ids=(SKILL_LCB_YISANG_S3,),
            tiers=(3,),
            label="LCB 罪人 李箱 三技能",
            rarity="epic",
        )
