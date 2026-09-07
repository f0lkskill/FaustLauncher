"""十连券收集者 I 成就。"""

from functions.achievement.base_achievement import CollectionAchievement


# 十连券物品ID列表
TEN_PULL_IDS = [102, 103, 104, 105, 106, 107, 108, 109, 110]


class AchTenPull1(CollectionAchievement):
    """十连券收集者 I - 拥有1种以上的十连券。
    
    当玩家拥有至少1种不同的十连券时解锁此成就。
    """

    def __init__(self):
        super().__init__(
            ach_id="ach_ten_pull_1",
            name="十连券收集者 I",
            description="拥有1种以上的十连券",
            required_count=1,
            item_ids=TEN_PULL_IDS
        )