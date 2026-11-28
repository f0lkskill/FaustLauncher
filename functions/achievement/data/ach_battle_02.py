"""成就定义：<ach_battle_02>。"""


from functions.achievement.base_achievement import BattleAchievement

class AchBattle02(BattleAchievement):

    """AchBattle02类。"""
    def __init__(self):
        """初始化对象状态。"""
        super().__init__(
            ach_id="ach_battle_02",
            name="渐入佳境",
            description="完成任意 10 场战斗。",
            target_count=10,
            track_deaths=False
        )
