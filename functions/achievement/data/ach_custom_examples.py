"""示例：**一个文件里写多个成就派生类**（注册时按定义顺序自动全部实例化）。

这里的两个成就就是按需求做的实例，也顺带演示了三种“检测类型”的基类怎么用：

1. 「这他妈的烂牌！」—— ``BuffPresentAchievement``：
   以实玛利（定事务所 代表，``10813``）在**首个回合**身上是否带着 buff
   「组札-芒上月」（Bufs.json 的 id：``HanafudaTwo``）。
2. 「心脏，心脏！」—— 复合成就主类 ``CompositeAchievement``：
   拇指 父辈 罗佳（``10916``）使用**任意**技能 → 她身上有「预知眼」
   （``FutureEyeOnRodion``）→ 场上存在 拇指 子辈 希斯克里夫（``10716``）。

补充说明：

* buff 的名字来自游戏 ``Lang/LLC_zh-CN/Bufs.json`` 的 ``id``（字符串，不是数字）；
* 技能类条件在**技能动画结束**时结算（收尾事件或 1.5s 静默期），不是回合边界；
* 「场上是否存在某身份」用 ``state_only=True`` 的条件：他在场是**状态**，
  从第一回合就在场，不能因为“记录得早”而算顺序不对。
"""

from __future__ import annotations

from functions.achievement import battle_watch
from functions.achievement.battle_achievements import (
    BuffPresentAchievement,
    CompositeAchievement,
    Condition,
)

# ---- 业务常量（游戏数据；驱动不认识它们）----
IDENTITY_ISHMAEL_TING_REP = 10813       # 以实玛利 · 定事务所 代表
IDENTITY_RODION_THUMB_CAPO = 10916      # 罗佳 · 蜘蛛巢 拇指 父辈
IDENTITY_HEATHCLIFF_THUMB_PROXY = 10716  # 希斯克里夫 · 蜘蛛巢 拇指 子辈
BUFF_HANAFUDA_TWO = "HanafudaTwo"       # 组札-芒上月
BUFF_FUTURE_EYE = "FutureEyeOnRodion"   # 预知眼


class DeadHandAchievement(BuffPresentAchievement):
    """这他妈的烂牌！—— 定事务所代表以实玛利 首个回合带着「组札-芒上月」。"""

    def __init__(self) -> None:
        super().__init__(
            ach_id="ach_dead_hand",
            name="这他妈的烂牌！",
            description="定事务所代表-以实玛利 在首个回合身上带有「组札-芒上月」。",
            identity_ids=(IDENTITY_ISHMAEL_TING_REP,),
            buffs=(BUFF_HANAFUDA_TWO,),
            max_round=1,                     # 只在首个回合（及之前）出现才算
            label="定事务所代表 以实玛利",
            rarity="uncommon",
        )


class HeartHeartAchievement(CompositeAchievement):
    """心脏，心脏！—— 复合成就：用技能 → 带预知眼 → 场上有拇指子辈希斯克里夫。"""

    def __init__(self) -> None:
        skill = Condition(
            key="skill",
            rule=battle_watch.BattleRule(
                key="ach_heart_heart.skill",
                label="拇指 父辈 罗佳 使用任意技能",
                kind=battle_watch.RULE_KIND_SKILL,
                identity_ids=(IDENTITY_RODION_THUMB_CAPO,),
                any_skill=True,
            ),
        )
        eyebuff = Condition(
            key="eyebuff",
            rule=battle_watch.BattleRule(
                key="ach_heart_heart.buff",
                label="拇指 父辈 罗佳 带有 预知眼",
                kind=battle_watch.RULE_KIND_BUFF,
                identity_ids=(IDENTITY_RODION_THUMB_CAPO,),
                buffs=(BUFF_FUTURE_EYE,),
            ),
        )
        ally = Condition(
            key="ally",
            rule=battle_watch.BattleRule(
                key="ach_heart_heart.ally",
                label="拇指 子辈 希斯克里夫 在场",
                kind=battle_watch.RULE_KIND_PRESENCE,
                identity_ids=(IDENTITY_HEATHCLIFF_THUMB_PROXY,),
            ),
            state_only=True,                 # 在场是状态，不参与先后顺序
        )
        super().__init__(
            ach_id="ach_heart_heart",
            name="心脏，心脏！",
            description="拇指父辈罗佳 使用技能且带上预知眼时，若场上存在拇指子辈希斯克里夫，则触发。",
            conditions=(skill, eyebuff, ally),
            chain=("skill", "eyebuff"),      # 先看到她出手，再看到预知眼
            require="skill and eyebuff and ally",
            label="心脏，心脏！",
            rarity="rare",
        )
