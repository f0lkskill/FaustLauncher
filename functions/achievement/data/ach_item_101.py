"""提取券成就。"""

from functions.achievement.base_achievement import ItemAchievement


class AchItem101(ItemAchievement):
    """提取券持有者 - 拥有1张提取券。
    
    当玩家获得提取券（物品ID: 101）时解锁此成就。
    """

    def __init__(self):
        super().__init__(
            ach_id="ach_item_101",
            name="提取券持有者",
            description="拥有1张提取券",
            item_id=101
        )