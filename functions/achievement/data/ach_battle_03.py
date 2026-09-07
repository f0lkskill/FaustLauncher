"""战斗大师成就。"""

from functions.achievement.base_achievement import BattleAchievement


class AchBattle03(BattleAchievement):
    """战斗大师 - 完成100场战斗。
    
    追踪玩家完成的战斗次数，当达到100场时解锁此成就。
    """

    def __init__(self):
        super().__init__(
            ach_id="ach_battle_03",
            name="战斗大师",
            description="完成100场战斗",
            target_count=100,
            track_deaths=False
        )