"""成就定义：<ach_battle_01>。"""


from functions.achievement.base_achievement import BattleAchievement

class AchBattle01(BattleAchievement):

    """AchBattle01类。"""
    def __init__(self):
        """初始化对象状态。"""
        super().__init__(
            ach_id="ach_battle_01",
            name="小试牛刀",
            description="完成任意 1 场战斗。",
            target_count=1,
            track_deaths=False
        )
