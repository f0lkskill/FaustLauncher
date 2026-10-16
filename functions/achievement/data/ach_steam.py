
from functions.achievement.base_achievement import SteamAchievement

class AchSteam(SteamAchievement):

    def __init__(self):
        super().__init__(
            ach_id="ach_steam",
            name="Steam 玩家",
            description="通过 Steam 登录游戏",
            rarity="common"
        )
