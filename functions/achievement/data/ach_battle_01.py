"""初次战斗成就。"""

from functions.achievement.base_achievement import BattleAchievement


class AchBattle01(BattleAchievement):
    """初次战斗 - 完成1场战斗。
    
    追踪玩家完成的战斗次数，当达到1场时解锁此成就。
    """

    def __init__(self):
        super().__init__(
            ach_id="ach_battle_01",
            name="初次战斗",
            description="完成1场战斗",
            target_count=1,
            track_deaths=False
        )