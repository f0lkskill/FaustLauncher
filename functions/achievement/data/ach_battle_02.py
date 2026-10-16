
from functions.achievement.base_achievement import BattleAchievement

class AchBattle02(BattleAchievement):

    def __init__(self):
        super().__init__(
            ach_id="ach_battle_02",
            name="渐入佳境",
            description="完成任意 10 场战斗。",
            target_count=10,
            track_deaths=False
        )
