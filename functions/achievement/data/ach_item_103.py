"""3★人格必得十连提取券成就。"""

from functions.achievement.base_achievement import ItemAchievement


class AchItem103(ItemAchievement):
    """必得券持有者 - 拥有1张3★人格必得十连提取券。
    
    当玩家获得3★人格必得十连提取券（物品ID: 103）时解锁此成就。
    """

    def __init__(self):
        super().__init__(
            ach_id="ach_guaranteed_general",
            name="必得券持有者",
            description="拥有1张3★人格必得十连提取券",
            item_id=103
        )