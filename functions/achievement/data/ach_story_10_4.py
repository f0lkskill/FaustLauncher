"""成就定义：<ach_story_10_4>。"""

from functions.achievement.battle_achievements import StageClearTurnAchievement

STAGE_10_4_UID_PREFIXES = ("1004", "10-4", "S10-4")
STAGE_10_4_WATCH_IDS = (10,)

class Story10_4Achievement(StageClearTurnAchievement):

    """Story104成就类。"""
    wip = True

    def __init__(self):
        """初始化对象状态。"""
        super().__init__(
            "ach_story_10_4",
            "西西弗斯",
            "通关主线剧情 10-4。",
            uid_prefixes=STAGE_10_4_UID_PREFIXES,
            max_turn=0,
            rarity="rare",
        )

    def stage_watch_ids(self) -> tuple:
        """stage监听ids相关处理。"""
        return STAGE_10_4_WATCH_IDS
