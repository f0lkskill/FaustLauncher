
from functions.achievement.base_achievement import BattleAchievement

class AchBattle01(BattleAchievement):

    def __init__(self):
        super().__init__(
            ach_id="ach_battle_01",
            name="小试牛刀",
            description="完成任意 1 场战斗。",
            target_count=1,
            track_deaths=False
        )
