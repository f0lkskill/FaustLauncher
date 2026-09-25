"""成就「仿造的一生」—— 蜘蛛巢 食指 父辈 李箱 使用 Furioso-Replica。

数据（``SkillUseAchievement`` 的构造参数，判定逻辑在 battle_watch 规则表）::

    identity_id = 10115                # 蜘蛛巢 食指 父辈 李箱
    skill_ids   = (1011505,)           # Furioso-Replica 本体（id 里自带身份）
    tiers       = (3,)                 # 另外兼容「三技能」（1011503，层数 9 时转化）
    gated_skill_ids = (134711, 138010, 955110)
                                       # 转化后/敌方侧同名技能：必须 actor 身份 == 10115 才认，
                                       # 免得故事里的敌方食指父辈用 Furioso 时误触发

为什么带 ``tiers=(3,)``：`Lang/LLC_zh-CN/BattleSpeechBubbleDlg.json` 里有
``battle_s3_10115_1_6`` → ``"“灼烧着的伤口”状态下使用 Furioso-Replica 后"``，
而 ``Skills_personality-01.json``（罪人 1 = 李箱）里那个三技能写着
「回合开始时，若自身的 [StackYisangSpecialSkill] 层数为 9 层，则使本技能转化为
“Furioso-Replica”(每回合最多 1 次)」—— 两种上报形式都盖住。

判定时机：技能类规则**回合边界结算**。
"""

from __future__ import annotations

from functions.achievement.battle_achievements import SkillUseAchievement

# ---- 业务常量（游戏数据；与偏移无关，驱动不认识它们）----
IDENTITY_YISANG_INDEX_PROXY = 10115    # 蜘蛛巢 食指 父辈 李箱
SKILL_YISANG_FURIOSO = 1011505         # Furioso-Replica 本体
FURIOSO_REPLICA_IDS = (134711, 138010, 955110)  # 同名但 id 不带身份的技能


class IndexFuriosoReplicaAchievement(SkillUseAchievement):
    """战斗事件类成就：观测 ACT 事件里的技能 ID。"""

    def __init__(self) -> None:
        super().__init__(
            ach_id="ach_index_furioso_replica",
            name="仿造的一生",
            description="使用 食指父辈-李箱 进行一次 Furioso-Replica。\n '我听到海浪的声音了。'",
            identity_id=IDENTITY_YISANG_INDEX_PROXY,
            skill_ids=(SKILL_YISANG_FURIOSO),
            tiers=(3,),
            gated_skill_ids=FURIOSO_REPLICA_IDS,
            label="食指父辈-李箱 Furioso-Replica",
            rarity="uncommon",
        )