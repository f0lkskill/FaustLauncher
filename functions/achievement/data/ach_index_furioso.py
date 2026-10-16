
from __future__ import annotations

from functions.achievement.battle_achievements import SkillUseAchievement

IDENTITY_YISANG_INDEX_PROXY = 10115
SKILL_YISANG_FURIOSO = 1011505
FURIOSO_REPLICA_IDS = (134711, 138010, 955110)

class IndexFuriosoReplicaAchievement(SkillUseAchievement):

    def __init__(self) -> None:
        super().__init__(
            ach_id="ach_index_furioso_replica",
            name="仿造的一生",
            description="使用 食指父辈-李箱 进行一次 Furioso-Replica。\n '我听到海浪的声音了。'",
            identity_id=IDENTITY_YISANG_INDEX_PROXY,
            skill_ids=(SKILL_YISANG_FURIOSO,),
            gated_skill_ids=FURIOSO_REPLICA_IDS,
            label="食指父辈-李箱 Furioso-Replica",
            rarity="uncommon",
        )
