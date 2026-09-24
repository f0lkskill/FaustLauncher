"""成就「神也会受伤吗？」—— 希斯克利夫（脑叶公司E.G.O::狐雨）在战斗中受伤。

数据（``DamageTakenAchievement`` 的构造参数）::

    identity_ids = (10705,)      # 脑叶公司E.G.O:: 狐雨 希斯克利夫
    ratio        = 1.0           # hp < 最大血量 × 1.0 = 只要掉过血就算受伤

链路（血量读法与理智同一条，见 ``battle_watch``）::

    BattleUnitModel._state(0x148) → CharacterState._hp(0x148) / _maxHp(0x11C)   ← ObscuredInt
    battle_watch.dll 在读单位（回合开始 / 设置速度 / 受击）时捎带读一次，值变化才发 VAL
    battle_watch.py  → 规则命中即置位（立刻）；回合边界再兜底复核一次

所以「立刻检测」是支持的：他挨打的那一瞬间就会上报新的 hp。想收紧成「残血」就把
``ratio`` 改成 0.5 之类的数据即可。
"""

from __future__ import annotations

from functions.achievement.battle_achievements import DamageTakenAchievement


class HeathcliffSunshowerHurtAchievement(DamageTakenAchievement):
    """战斗事件类成就：观测单位血量（VAL 事件的 hp / mhp 字段）。"""

    def __init__(self) -> None:
        super().__init__(
            ach_id="ach_heathcliff_sunshower_hurt",
            name="神也会受伤吗？",
            description="脑叶公司E.G.O::狐雨-希斯克里夫 在战斗中受到一次伤害。",
            identity_ids=(10705,),
            ratio=1.0,
            label="狐雨 希斯克里夫",
            rarity="uncommon",
        )
