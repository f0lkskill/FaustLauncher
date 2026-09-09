"""满分脑啡肽成就。"""

from functions.achievement.base_achievement import MemoryAchievement
from functions.achievement.memory_reader import LimbusMemoryReader


class FullEnkephalinAchievement(MemoryAchievement):
    """满分脑啡肽 - 脑啡肽容量达到100。"""

    def __init__(self):
        super().__init__(
            ach_id="ach_enkephalin_100",
            name="满分脑啡肽",
            description="脑啡肽容量达到100",
            reader_factory=LimbusMemoryReader,
            predicate=lambda value: value >= 100,
        )
        self.rarity = "common"
