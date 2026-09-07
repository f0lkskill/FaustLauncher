"""无伤通关成就。"""

from functions.achievement.base_achievement import BattleAchievement


class AchBattle04(BattleAchievement):
    """无伤通关 - 战斗中没有角色死亡。
    
    当玩家完成一场战斗且没有任何角色死亡时解锁此成就。
    需要追踪战斗中的角色死亡情况。
    """

    def __init__(self):
        super().__init__(
            ach_id="ach_battle_04",
            name="无伤通关",
            description="战斗中没有角色死亡",
            target_count=1,
            track_deaths=True
        )