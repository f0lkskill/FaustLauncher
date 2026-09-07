"""第2赛季必得券成就。"""

from functions.achievement.base_achievement import ItemAchievement


class AchSeason2Guaranteed(ItemAchievement):
    """第2赛季必得券持有者 - 拥有1张[第2赛季]3★人格必得十连提取券。
    
    当玩家获得第2赛季3★人格必得十连提取券（物品ID: 105）时解锁此成就。
    """

    def __init__(self):
        super().__init__(
            ach_id="ach_season_2_guaranteed",
            name="第2赛季必得券持有者",
            description="拥有1张[第2赛季]3★人格必得十连提取券",
            item_id=105
        )