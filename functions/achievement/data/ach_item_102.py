"""十连提取券成就。"""

from functions.achievement.base_achievement import ItemAchievement


class AchItem102(ItemAchievement):
    """十连券持有者 - 拥有1张十连提取券。
    
    当玩家获得十连提取券（物品ID: 102）时解锁此成就。
    """

    def __init__(self):
        super().__init__(
            ach_id="ach_item_102",
            name="十连券持有者",
            description="拥有1张十连提取券",
            item_id=102
        )