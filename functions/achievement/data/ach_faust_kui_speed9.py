
from __future__ import annotations

from functions.achievement.battle_achievements import SpeedValueAchievement

IDENTITY_FAUST_KUISHOU = 10212
SPEED_TARGET = 9

class FaustKuiSpeedNineAchievement(SpeedValueAchievement):

    def __init__(self) -> None:
        super().__init__(
            ach_id="ach_faust_kui_speed9",
            name="呃啊，我脚崴了",
            description="浮士德-魁首速度卡在 9 速。\n我缺的重投谁给我补啊！",
            identity_ids=(IDENTITY_FAUST_KUISHOU,),
            value=SPEED_TARGET,
            fields=("os", "ow", "its", "eff"),
            label="黑兽-卯 魁首 浮士德",
            rarity="rare",
        )
