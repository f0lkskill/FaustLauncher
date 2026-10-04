"""折射铁路 六号线：整条线 100 回合以内通关。

**数据来源**：``RailwayDungeonHistoryDataByCollection::GetTotalClearTurn()`` ——
就是进线路之前游戏显示的那个"你的最好回合数"（整条线的总回合）。
Player.log 里没有这个数，只能靠 battle_watch 的 ``RWT`` 事件。

⚠ 线路号（宿主对象上的 ``_collectionId``）待实测确认：日志里会打
``[战斗观测] ★ 铁路记录: 线路=N 总回合=N``，如果不是 6 就改下面一行。
"""
from functions.achievement.battle_achievements import RailwayTotalTurnAchievement

# 六号线的线路号（_collectionId）
RAILWAY6_LINE_IDS = (6,)


class Railway6Under100TurnAchievement(RailwayTotalTurnAchievement):
    """六号线：整条线 100 回合以内通关。"""

    #: 开发中：铁路"总回合"数据源还没定位成功（详见文件头）。
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
