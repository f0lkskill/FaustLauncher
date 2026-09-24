"""成就「将你李箱，也将我李箱。」—— LCB 罪人李箱 在回合中使用了三技能。

现在只是 ``SkillUseAchievement`` 的一行数据（判定逻辑在
``functions/achievement/battle_watch.py`` 的规则引擎里）：

    BattleRule(key="ach_yisang_lcb_s3", kind="skill",
               identity_ids=(10101,), skill_ids=(1010103,), tiers=(3,))

链路：

    battle_watch.dll（注入游戏进程）
        └─ hook BattleActionModel::DoneWithAction / GetTakeAttackDmgMultiplier → ACT skid=<技能ID>
    battle_watch.py
        └─ 本回合出现过 skid == 1010103 → 回合边界（或战斗结束）结算置位
    ← 本文件
        └─ check() 只读 battle_watch 的规则结果

为什么用技能 ID 判定：技能 ID 的编码是 ``<身份5位><槽位2位>``（游戏数据实测，见
``Lang/LLC_zh-CN/Skills.json``），所以 ``1010103`` 本身就同时锁定了
「LCB 罪人李箱（10101）」和「三技能（03）」，比"按实例 ID 反查身份"更硬。
"""

from __future__ import annotations

from functions.achievement.battle_achievements import SkillUseAchievement


class YisangLcbThirdSkillAchievement(SkillUseAchievement):
    """战斗事件类成就：由注入 DLL 观测，回合边界结算。"""

    def __init__(self) -> None:
        super().__init__(
            ach_id="ach_yisang_lcb_s3",
            name="将你李箱，也将我李箱。",
            description="让 LCB罪人-李箱 使用一次三技能。\n '将鸟字抹去一点，乌鸦俯瞰大地。'",
            identity_id=10101,
            skill_ids=(1010103,),
            tiers=(3,),
            label="LCB罪人-李箱 三技能",
            rarity="common",
        )
