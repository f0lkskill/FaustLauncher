"""成就定义：<ach_heathcliff_sunshower_hurt>。"""


from __future__ import annotations

from functions.achievement.battle_achievements import DamageTakenAchievement

IDENTITY_HEATHCLIFF_SUNSHOWER = 10705
HP_RATIO = 1.0

class HeathcliffSunshowerHurtAchievement(DamageTakenAchievement):

    """HeathcliffSunshowerHurt成就类。"""
    def __init__(self) -> None:
        """初始化对象状态。"""
        super().__init__(
            ach_id="ach_heathcliff_sunshower_hurt",
            name="神也会受伤吗？",
            description="脑叶公司E.G.O::狐雨-希斯克里夫 受到任意伤害。",
            identity_ids=(IDENTITY_HEATHCLIFF_SUNSHOWER,),
            ratio=HP_RATIO,
            label="狐雨 希斯克里夫",
            rarity="uncommon",
        )
