"""成就「魔法少女的悲剧」—— 让任意一位魔法少女陷入负理智状态。

魔法少女 = 脑叶公司的四位「魔法少女」异常体（绝望骑士 / 憎恶女王 / …）。
本作里能上场的两位，以及它们对应的 E.G.O 人格（游戏数据实测）::

    10913  罗佳      脑叶公司E.G.O:: 泪锋之剑      ← 绝望骑士（Knight of Despair）的 E.G.O
    10312  堂吉诃德  脑叶公司E.G.O:: 以爱与憎之名  ← 憎恶女王（Queen of Hatred）的 E.G.O

判定数据（``MentalThresholdAchievement`` 的构造参数）::

    identity_ids = (10913, 10312)
    threshold    = 0          # 理智(SP) < 0 即命中

为什么是「理智 < 0」：``CharacterState._mp``（``BattleUnitModel._state[0x148]`` → ``+0x158``，
ObscuredInt）就是界面上的理智(SP)，同类的 ``_maxMp = 45`` / ``_minMp = -45`` 常量正是它的
上下限 —— 负数理智 = 陷入恐慌（SAN 掉光）。观测到就**立刻**解锁，回合边界再兜底复核一次。
"""

from __future__ import annotations

from functions.achievement.battle_achievements import MentalThresholdAchievement

# ---- 业务常量（游戏数据；与偏移无关，驱动不认识它们）----
IDENTITY_RODION_DESPAIR_KNIGHT = 10913   # 脑叶公司E.G.O:: 泪锋之剑 罗佳（绝望骑士的 E.G.O）
IDENTITY_DON_QUIXOTE_HATRED_QUEEN = 10312  # 脑叶公司E.G.O:: 以爱与憎之名 堂吉诃德（憎恶女王的 E.G.O）
MENTAL_THRESHOLD = 0                     # 理智(SP) < 0


class MagicalGirlTragedyAchievement(MentalThresholdAchievement):
    """战斗事件类成就：观测单位理智（VAL 事件的 mp 字段）。"""

    def __init__(self) -> None:
        super().__init__(
            ach_id="ach_magical_girl_tragedy",
            name="魔法少女的悲剧",
            description="让任意一位魔法少女陷入负理智状态。",
            identity_ids=(IDENTITY_RODION_DESPAIR_KNIGHT,
                          IDENTITY_DON_QUIXOTE_HATRED_QUEEN),
            threshold=MENTAL_THRESHOLD,
            label="魔法少女（绝望骑士·罗佳 / 憎恶女王·堂吉诃德）",
            rarity="uncommon",
        )