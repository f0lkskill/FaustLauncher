"""成就定义：<ach_enkephalin_100>。"""


from functions.achievement.base_achievement import MemoryAchievement
from functions.achievement.memory_reader import LimbusMemoryReader

class FullEnkephalinAchievement(MemoryAchievement):

    """FullEnkephalin成就类。"""
    def __init__(self):
        """初始化对象状态。"""
        super().__init__(
            ach_id="ach_enkephalin_100",
            name="满分脑啡肽！",
            description="脑啡肽容量达到100。\n能量满满，随时准备出发！",
            reader_factory=LimbusMemoryReader,
            predicate=lambda value: value >= 100,
        )
        self.rarity = "common"
