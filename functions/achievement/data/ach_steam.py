"""成就定义：<ach_steam>。"""


from functions.achievement.base_achievement import SteamAchievement

class AchSteam(SteamAchievement):

    """AchSteam类。"""
    def __init__(self):
        """初始化对象状态。"""
        super().__init__(
            ach_id="ach_steam",
            name="Steam 玩家",
            description="通过 Steam 登录游戏",
            rarity="common"
        )
