
from __future__ import annotations

from functions.achievement.battle_achievements import MentalThresholdAchievement

IDENTITY_RODION_DESPAIR_KNIGHT = 10913
IDENTITY_DON_QUIXOTE_HATRED_QUEEN = 10312
MENTAL_THRESHOLD = 0

class MagicalGirlTragedyAchievement(MentalThresholdAchievement):

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
