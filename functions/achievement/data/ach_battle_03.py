"""成就定义：<ach_battle_03>。"""


from functions.achievement.base_achievement import BattleAchievement

class AchBattle03(BattleAchievement):

    """AchBattle03类。"""
    def __init__(self):
        """初始化对象状态。"""
        super().__init__(
            ach_id="ach_battle_03",
            name="我的拳头想喝血了！",
            description="完成任意 100 场战斗。",
            target_count=100,
            track_deaths=False
        )
