from functions.achievement.battle_achievements import RailwayTotalTurnAchievement

RAILWAY6_LINE_IDS = (6,)

class Railway6Under100TurnAchievement(RailwayTotalTurnAchievement):

    wip = True

    def __init__(self):
        super().__init__(
            "ach_railway6_100t",
            "六号线·百回合",
            "在折射铁路 六号线中，以 100 回合以内的总回合数通关。",
            line_ids=RAILWAY6_LINE_IDS,
            max_turn=100,
            rarity="epic",
        )
