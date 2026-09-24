"""战斗达人成就。"""

from functions.achievement.base_achievement import BattleAchievement


class AchBattle02(BattleAchievement):
    """渐入佳境 - 完成10场战斗。
    
    追踪玩家完成的战斗次数，当达到10场时解锁此成就。
    """

    def __init__(self):
        super().__init__(
            ach_id="ach_battle_02",
            name="渐入佳境",
            description="完成任意 10 场战斗。",
            target_count=10,
            track_deaths=False
        )