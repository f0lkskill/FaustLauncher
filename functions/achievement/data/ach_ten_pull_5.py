"""十连券大师成就。"""

from functions.achievement.base_achievement import CollectionAchievement


# 十连券物品ID列表
TEN_PULL_IDS = [102, 103, 104, 105, 106, 107, 108, 109, 110]


class AchTenPull5(CollectionAchievement):
    """十连券大师 - 拥有5种以上的十连券。
    
    当玩家拥有至少5种不同的十连券时解锁此成就。
    """

    def __init__(self):
        super().__init__(
            ach_id="ach_ten_pull_5",
            name="十连券大师",
            description="拥有5种以上的十连券",
            required_count=5,
            item_ids=TEN_PULL_IDS
        )