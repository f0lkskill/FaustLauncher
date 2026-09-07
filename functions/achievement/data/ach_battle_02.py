"""战斗达人成就。"""

from functions.achievement.base_achievement import BattleAchievement


class AchBattle02(BattleAchievement):
    """战斗达人 - 完成10场战斗。
    
    追踪玩家完成的战斗次数，当达到10场时解锁此成就。
    """

    def __init__(self):
        super().__init__(
            ach_id="ach_battle_02",
            name="战斗达人",
            description="完成10场战斗",
            target_count=10,
            track_deaths=False
        )