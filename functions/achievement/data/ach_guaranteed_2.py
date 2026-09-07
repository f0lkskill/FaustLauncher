"""必得券收集者成就。"""

from functions.achievement.base_achievement import CollectionAchievement


# 必得券物品ID列表
GUARANTEED_IDS = [103, 104, 105, 106, 107, 108, 109, 110]


class AchGuaranteed2(CollectionAchievement):
    """必得券收集者 - 拥有2种以上的必得券。
    
    当玩家拥有至少2种不同的必得券时解锁此成就。
    """

    def __init__(self):
        super().__init__(
            ach_id="ach_guaranteed_2",
            name="必得券收集者",
            description="拥有2种以上的必得券",
            required_count=2,
            item_ids=GUARANTEED_IDS
        )