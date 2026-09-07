"""物品收藏家成就。"""

from functions.achievement.base_achievement import CollectionAchievement


class AchTotal10(CollectionAchievement):
    """物品收藏家 - 拥有10种不同的稀有物品。
    
    当玩家拥有至少10种不同的稀有物品时解锁此成就。
    稀有物品包括：提取券、十连券、必得券、自选券等。
    """

    def __init__(self):
        super().__init__(
            ach_id="ach_total_10",
            name="物品收藏家",
            description="拥有10种不同的稀有物品",
            required_count=10,
            item_ids=None  # 统计所有稀有物品
        )