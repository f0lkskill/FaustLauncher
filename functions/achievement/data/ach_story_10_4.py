from functions.achievement.battle_achievements import StageClearTurnAchievement

STAGE_10_4_UID_PREFIXES = ("1004", "10-4", "S10-4")
STAGE_10_4_WATCH_IDS = (10,)

class Story10_4Achievement(StageClearTurnAchievement):

    wip = True

    def __init__(self):
        super().__init__(
            "ach_story_10_4",
            "西西弗斯",
            "通关主线剧情 10-4。",
            uid_prefixes=STAGE_10_4_UID_PREFIXES,
            max_turn=0,
            rarity="rare",
        )

    def stage_watch_ids(self) -> tuple:
        return STAGE_10_4_WATCH_IDS
