"""主线 10-4 通关。

数据来源：battle_watch 的 ``STG`` 事件（关卡结算统计里的 ``_uid``）——
就是"六号线"那条成就用的同一个钩子，这里改用 uid 判定具体关卡。

⚠ 关卡 uid 待实测校准：本机 dump / 语言包里都查不到"10-4"到内部关卡 id 的映射
（dump 里的 ``StageScript_10xx`` 是别的内容）。先按几种可能的写法都匹配上，
打过一次之后看日志里这行即可一行改准：

    [战斗观测] ★ 关卡结算: uid=????????? 通关回合=NN 阵亡=N EX=N
"""
from functions.achievement.battle_achievements import StageClearTurnAchievement

# 10-4 关卡 uid 的候选写法（前缀匹配，覆盖 "1004xx" / "10-4" 这类）
STAGE_10_4_UID_PREFIXES = ("1004", "10-4", "S10-4")
# 关注表用的**数字前缀**：DLL 按十进制前缀匹配（1004 命中 1004 / 100401 / 1004012…），
# 所以先给粗粒度目标即可 —— 存档里以前打过的 10-4 一进游戏就会被 CLR 报上来。
STAGE_10_4_WATCH_IDS = (1004, 104)


class Story10_4Achievement(StageClearTurnAchievement):
    """通关主线 10-4。"""

    def __init__(self):
        super().__init__(
            "ach_story_10_4",
            "第 10 章 · 4 节",
            "通关主线剧情 10-4。",
            uid_prefixes=STAGE_10_4_UID_PREFIXES,
            max_turn=0,          # 不限回合，通关即可
            rarity="rare",
        )

    def stage_watch_ids(self) -> tuple:
        """告诉驱动：为这条成就盯住存档里这几个关卡前缀（回溯判定）。"""
        return STAGE_10_4_WATCH_IDS
