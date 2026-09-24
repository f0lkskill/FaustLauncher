"""成就「呃啊，我脚崴了」—— 浮士德-魁首 速度为 9。

数据（``SpeedValueAchievement`` 的构造参数，判定逻辑在 battle_watch 的规则表里）::

    identity_ids = (10212,)                  # 黑兽 - 卯 魁首 浮士德
    value        = 9                         # 速度 == 9
    fields       = ("os", "ow", "its", "eff")# 速度事件里的四个字段任一命中即可

关于 ``fields``（SPD 事件字段，驱动已归一成**整数速度**）：

| 字段 | 含义 |
|---|---|
| ``os`` | ``_originSpeed``：本回合掷出的速度 |
| ``ow`` | ``_overwritedSpeed``：被技能/效果覆盖后的速度 |
| ``its`` | ``_thisTurnIntSpeedOnCmdPhase``：命令阶段快照（回合开始那一刻还是上一回合的值，只能当参考） |
| ``eff`` | 有效速度：游戏 ``GetIntegerOfOriginSpeed`` 的语义（``ow >= 0`` 用 ``ow``，否则用 ``os``） |

原始字段是「速度 ×1000」的定点数（如 14518 = 14.518），驱动侧已完成换算；
想收紧成全字段一致就只留需要的字段，例如 ``fields=("eff",)``。

判定时机：速度类规则**观测到就立刻置位**，回合边界再兜底复核一次。
"""

from __future__ import annotations

from functions.achievement.battle_achievements import SpeedValueAchievement

# ---- 业务常量（游戏数据；与偏移无关，驱动不认识它们）----
IDENTITY_FAUST_KUISHOU = 10212       # 黑兽 - 卯 魁首 浮士德
SPEED_TARGET = 9


class FaustKuiSpeedNineAchievement(SpeedValueAchievement):
    """战斗事件类成就：观测 SPD 事件（速度掷骰/被覆盖）。"""

    def __init__(self) -> None:
        super().__init__(
            ach_id="ach_faust_kui_speed9",
            name="呃啊，我脚崴了",
            description="浮士德-魁首速度为 9。\n我缺的重投谁给我补啊！",
            identity_ids=(IDENTITY_FAUST_KUISHOU,),
            value=SPEED_TARGET,
            fields=("os", "ow", "its", "eff"),
            label="黑兽-卯 魁首 浮士德",
            rarity="rare",
        )
