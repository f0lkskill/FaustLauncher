"""自选券收藏家成就。"""

from functions.achievement.base_achievement import ItemAchievement


# 自选券物品ID列表
SELF_SELECT_IDS = [501, 502, 601, 751]


class AchSelfSelect(ItemAchievement):
    """自选券收藏家 - 拥有1张赛季人格自选券。
    
    当玩家获得任意赛季人格自选券时解锁此成就。
    """

    def __init__(self):
        super().__init__(
            ach_id="ach_self_select",
            name="自选券收藏家",
            description="拥有1张赛季人格自选券",
            item_id=501  # 使用第一个自选券ID作为主要检测
        )