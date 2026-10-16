
from __future__ import annotations

from functions.achievement.battle_achievements import SkillUseAchievement

IDENTITY_LCB_YISANG = 10101
SKILL_LCB_YISANG_S3 = 1010103

class YisangLcbThirdSkillAchievement(SkillUseAchievement):

    def __init__(self) -> None:
        super().__init__(
            ach_id="ach_yisang_lcb_s3",
            name="将你李箱，也将我李箱。",
            description="让 LCB 罪人李箱 使用自己的三技能。",
            identity_id=IDENTITY_LCB_YISANG,
            skill_ids=(SKILL_LCB_YISANG_S3,),
            tiers=(3,),
            label="LCB 罪人 李箱 三技能",
            rarity="epic",
        )
