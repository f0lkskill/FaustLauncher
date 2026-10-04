"""成就插件模板：一个文件里写多个自定义成就。

== 怎么用 ==

1. 把 ``addons/成就插件模板/`` 整个复制成 ``addons/我的成就/``；
2. 改 ``addon_info.json``：``name`` / ``desc`` / ``authors`` 换成你自己的；
3. 改本文件里的成就（下面每条都有注释说明怎么填）；
4. 把 ``addon_info.json`` 里的 ``"enable": false`` 改成 ``true``；
5. 重启启动器（或托盘菜单「重载插件」）→ 「成就」页就会出现。

== 注册规则 ==

- 本模块里所有 ``BaseAchievement`` 子类会**按定义顺序**自动实例化并注册；
- 想自己控制顺序/只注册一部分，就在文件末尾写
  ``ACHIEVEMENTS = (实例, 实例, ...)`` —— 有这个变量时以它为准；
- ``ach_id`` 必须**全局唯一**（和内置成就重名会被拒绝并跳过）；
- 每条成就解锁后会走和内置成就一样的弹窗（toast）+ 记进用户存档。

== 数据从哪来（怎么填 id） ==

- **身份 id**：5 位数字，``<罪人2位><人格2位>``。例：``10101`` = 李箱 LCB、
  ``10916`` = 罗佳 拇指 父辈。游戏目录 ``LimbusCompany_Data/Lang/LLC_zh-CN/`` 下
  配合人格名可以对照；游戏内看人格编号也行。
- **buff 名**：**字符串**，来自 ``Lang/LLC_zh-CN/Bufs.json`` 的 ``id`` 字段
  （例：``HanafudaTwo`` = 组札-芒上月、``Enhancement`` = 强壮）。**不是**中文名。
- **技能 id**：7 位数字，``<身份5位><槽位2位>``。例：``1010103`` = 李箱 LCB 三技能。
  槽位 ``01/02/03`` = 技能一/二/三，``04`` 常见于反击/防御。
- **速度 / 理智 / 血量**：直接给阈值。理智就是界面上的 SP（范围 ±45，负数=恐慌）。

== 想加图标 ==

在插件目录里放 ``assets/achievement/<成就id>.png``（也支持 webp/jpg/svg），
启动时会被同步到前端素材目录；没放就用默认占位图标。稀有度边框由前端按 rarity 自动着色，
**图片本身不要带边框**。
"""

from __future__ import annotations

from functions.achievement import battle_watch
from functions.achievement.battle_achievements import (
    BuffPresentAchievement,
    CompositeAchievement,
    Condition,
    DamageTakenAchievement,
    FieldPresenceAchievement,
    MentalThresholdAchievement,
    SkillUseAchievement,
    SpeedValueAchievement,
)

# ---------------------------------------------------------------------------
# 业务常量：把游戏数据集中放这里，方便改（驱动本身不认识这些值）
# ---------------------------------------------------------------------------
IDENTITY_YISANG_LCB = 10101             # 李箱 · LCB 罪人
IDENTITY_ISHMAEL_TING_REP = 10813       # 以实玛利 · 定事务所 代表
IDENTITY_RODION_THUMB_CAPO = 10916      # 罗佳 · 蜘蛛巢 拇指 父辈
IDENTITY_HEATHCLIFF_THUMB_PROXY = 10716  # 希斯克里夫 · 蜘蛛巢 拇指 子辈

BUFF_HANAFUDA_TWO = "HanafudaTwo"       # 组札-芒上月
BUFF_FUTURE_EYE = "FutureEyeOnRodion"   # 预知眼


# ---------------------------------------------------------------------------
# 1) 技能类：某个身份用了某个技能（可按回合窗口限制）
# ---------------------------------------------------------------------------
class DemoSingleSkillAchievement(SkillUseAchievement):
    """示例：李箱 LCB 用出三技能。"""

    def __init__(self) -> None:
        super().__init__(
            ach_id="ach_demo_skill_yisang_s3",   # 全局唯一
            name="示例·李箱三技能",
            description="李箱（LCB 罪人）使用三技能。",
            skill_ids=(1010103,),                # 精确技能 id（最硬）
            # 也可以只给 tiers=(3,) + identity_id=IDENTITY_YISANG_LCB 让驱动拼；
            # 或者 any_skill=True 表示"任意技能"。
            label="李箱 LCB",
            rarity="common",
        )


# ---------------------------------------------------------------------------
# 2) 速度类：结算时速度达到阈值
# ---------------------------------------------------------------------------
class DemoSpeedAchievement(SpeedValueAchievement):
    """示例：某身份速度 ≥ 9。"""

    def __init__(self) -> None:
        super().__init__(
            ach_id="ach_demo_speed_9",
            name="示例·速度九",
            description="以实玛利（定事务所 代表）速度值达到 9。",
            identity_ids=(IDENTITY_ISHMAEL_TING_REP,),
            value=9,
            label="定事务所代表 以实玛利",
            rarity="rare",
        )


# ---------------------------------------------------------------------------
# 3) 理智类：理智跌到阈值（负数 = 恐慌）
# ---------------------------------------------------------------------------
class DemoMentalAchievement(MentalThresholdAchievement):
    """示例：某身份理智 ≤ -20。"""

    def __init__(self) -> None:
        super().__init__(
            ach_id="ach_demo_mental_low",
            name="示例·濒临崩溃",
            description="以实玛利（定事务所 代表）理智降到 -20 或更低。",
            identity_ids=(IDENTITY_ISHMAEL_TING_REP,),
            threshold=-20,
            label="定事务所代表 以实玛利",
            rarity="legendary",
        )


# ---------------------------------------------------------------------------
# 4) 受伤类：单次受击掉到最大血量的某个比例
# ---------------------------------------------------------------------------
class DemoDamageAchievement(DamageTakenAchievement):
    """示例：一次挨打掉掉至少 50% 血量。"""

    def __init__(self) -> None:
        super().__init__(
            ach_id="ach_demo_half_dead",
            name="示例·一记半血",
            description="以实玛利（定事务所 代表）单次受击掉血达到自身最大血量的 50%。",
            identity_ids=(IDENTITY_ISHMAEL_TING_REP,),
            ratio=0.5,                           # 0.5 = 50%
            label="定事务所代表 以实玛利",
            rarity="uncommon",
        )


# ---------------------------------------------------------------------------
# 5) buff 类：身上带着某个 buff（可限定回合窗口）
# ---------------------------------------------------------------------------
class DemoBuffAchievement(BuffPresentAchievement):
    """示例：首个回合身上有「组札-芒上月」。"""

    def __init__(self) -> None:
        super().__init__(
            ach_id="ach_demo_first_turn_buff",
            name="示例·首回合芒上月",
            description="以实玛利（定事务所 代表）在首个回合身上带有「组札-芒上月」。",
            identity_ids=(IDENTITY_ISHMAEL_TING_REP,),
            buffs=(BUFF_HANAFUDA_TWO,),
            max_round=1,                         # 只在第 1 回合（及之前）算；0 = 不限
            label="定事务所代表 以实玛利",
            rarity="uncommon",
        )


# ---------------------------------------------------------------------------
# 6) 在场类：某身份在场上（可限定回合窗口）
# ---------------------------------------------------------------------------
class DemoPresenceAchievement(FieldPresenceAchievement):
    """示例：前 3 回合场上同时有这两个身份之一。"""

    def __init__(self) -> None:
        super().__init__(
            ach_id="ach_demo_presence_early",
            name="示例·开局登场",
            description="第 3 回合结束前，场上存在 拇指 子辈 希斯克里夫。",
            identity_ids=(IDENTITY_HEATHCLIFF_THUMB_PROXY,),
            max_round=3,
            label="拇指 子辈 希斯克里夫",
            rarity="common",
        )


# ---------------------------------------------------------------------------
# 7) 复合类：多个条件按顺序/逻辑组合（最灵活，也最常用来还原游戏内成就）
# ---------------------------------------------------------------------------
class DemoCompositeAchievement(CompositeAchievement):
    """示例：带着预知眼出手，且场上有拇指子辈希斯克里夫。"""

    def __init__(self) -> None:
        skill = Condition(
            key="skill",
            rule=battle_watch.BattleRule(
                key="ach_demo_combo.skill",      # 规则 key 也必须唯一
                label="拇指 父辈 罗佳 使用任意技能",
                kind=battle_watch.RULE_KIND_SKILL,
                identity_ids=(IDENTITY_RODION_THUMB_CAPO,),
                any_skill=True,
            ),
        )
        eyebuff = Condition(
            key="eyebuff",
            rule=battle_watch.BattleRule(
                key="ach_demo_combo.buff",
                label="拇指 父辈 罗佳 带有 预知眼",
                kind=battle_watch.RULE_KIND_BUFF,
                identity_ids=(IDENTITY_RODION_THUMB_CAPO,),
                buffs=(BUFF_FUTURE_EYE,),
            ),
        )
        ally = Condition(
            key="ally",
            rule=battle_watch.BattleRule(
                key="ach_demo_combo.ally",
                label="拇指 子辈 希斯克里夫 在场",
                kind=battle_watch.RULE_KIND_PRESENCE,
                identity_ids=(IDENTITY_HEATHCLIFF_THUMB_PROXY,),
            ),
            state_only=True,                     # "在场"是状态，不参与先后顺序判定
        )
        super().__init__(
            ach_id="ach_demo_combo",
            name="示例·复合条件",
            description="拇指父辈罗佳带着预知眼出手时，若场上存在拇指子辈希斯克里夫则触发。",
            conditions=(skill, eyebuff, ally),
            # ⚠ chain 写的是"必须成立的先后顺序"：这里是"先有预知眼，再出手"。
            #   常驻 buff 第一次被采样必然早于出手，写反了链就永远不成立。
            chain=("eyebuff", "skill"),
            require="skill and eyebuff and ally",   # and / or / not 都支持
            label="示例·复合条件",
            rarity="rare",
        )


# ---------------------------------------------------------------------------
# 想自己控制注册顺序/只启用一部分时，取消下面这段注释（有这个变量时以它为准）：
# ---------------------------------------------------------------------------
# ACHIEVEMENTS = (
#     DemoSingleSkillAchievement(),
#     DemoCompositeAchievement(),
# )
