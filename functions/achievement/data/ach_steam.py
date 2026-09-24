"""Steam玩家成就。"""

from functions.achievement.base_achievement import SteamAchievement


class AchSteam(SteamAchievement):
    """Steam玩家 - 通过Steam登录游戏。
    
    当检测到通过Steam登录游戏时解锁此成就。
    """

    def __init__(self):
        super().__init__(
            ach_id="ach_steam",
            name="Steam 玩家",
            description="通过 Steam 登录游戏",
            rarity="common"
        )