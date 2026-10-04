"""折射铁路 六号线：100 回合以内通关。

**数据来源**：只有内存里有。铁路（玩家口中的一号线/二号线/六号线…）的通关回合数
在 ``Player.log`` 里完全不存在（Railway/Turn 一个都搜不到），所以走 battle_watch 的
``STG`` 事件 —— 它挂钩 ``StageStatisticPopupData`` 的构造函数，读每个 slot 的
``_clearTurn``（见 dump.cs: StageStatisticPopupSlotData）。

**关卡 uid**：六号线关卡形如 ``1095x``（dump.cs 里有 ``StageScript_10950Railway6``），
所以用前缀 ``1095`` 判定"这一关属于六号线"。等实测到真实 uid 后按需要收紧。
"""
from functions.achievement.battle_achievements import StageClearTurnAchievement

# 六号线关卡 uid 前缀（铁路关卡 id 形如 1095x）
RAILWAY6_UID_PREFIXES = ("1095",)


class Railway6Under100TurnAchievement(StageClearTurnAchievement):
    """六号线：100 回合以内通关任意一关。"""

    def __init__(self):
        super().__init__(
            "ach_railway6_100t",
            "六号线·百回合",
            "在折射铁路 六号线中，用 100 回合以内通关。",
            uid_prefixes=RAILWAY6_UID_PREFIXES,
            max_turn=100,
            rarity="epic",
        )
