"""成就定义：<ach_railway6_100t>。"""

from functions.achievement.battle_achievements import RailwayTotalTurnAchievement

RAILWAY6_LINE_IDS = (6,)

class Railway6Under100TurnAchievement(RailwayTotalTurnAchievement):

    """Railway6Under100Turn成就类。"""
    wip = True

    def __init__(self):
        """初始化对象状态。"""
        super().__init__(
            "ach_railway6_100t",
            "六号线·百回合",
            "在折射铁路 六号线中，以 100 回合以内的总回合数通关。",
            line_ids=RAILWAY6_LINE_IDS,
            max_turn=100,
            rarity="epic",
        )
