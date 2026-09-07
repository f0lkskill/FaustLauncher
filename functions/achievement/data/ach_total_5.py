"""物品收集者成就。"""

from functions.achievement.base_achievement import CollectionAchievement


class AchTotal5(CollectionAchievement):
    """物品收集者 - 拥有5种不同的稀有物品。
    
    当玩家拥有至少5种不同的稀有物品时解锁此成就。
    稀有物品包括：提取券、十连券、必得券、自选券等。
    """

    def __init__(self):
        super().__init__(
            ach_id="ach_total_5",
            name="物品收集者",
            description="拥有5种不同的稀有物品",
            required_count=5,
            item_ids=None  # 统计所有稀有物品
        )