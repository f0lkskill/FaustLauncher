"""成就「呃啊，我脚崴了」—— 浮士德-魁首 速度为 9。

判定链路（全部只读）：

    battle_watch.dll（注入游戏进程）
        └─ hook BattleUnitModel::SetRandomSpeed/RefreshSpeed  →  SPD iid=.. oid=10212 os=.. osi=.. ow=.. owi=.. its=..
    battle_watch.py
        └─ os/ow 按 SPEED_SCALE 归一成整数速度，若身份 == 10212（黑兽 - 卯 魁首 浮士德）
           且速度命中 9 即置位
    ← 本文件
        └─ check() 只读 battle_watch 的置位结果

身份 10212 与技能 ID 编码同样是游戏数据实测（``Lang/LLC_zh-CN/Personalities.json``：
``{"id": 10212, "title": "黑兽 - 卯 魁首", "name": "浮士德"}``）。

速度取哪个字段（值都是**整数速度**）：``_originSpeed``（本回合掷出的速度）/``_overwritedSpeed``
（被技能覆盖后的速度）/``_thisTurnIntSpeedOnCmdPhase``（命令阶段快照，回合开始那一刻还是
上一回合的值，只能当参考）/``eff``（有效速度）任一等于 9 即命中，命中时成就会在描述与
日志里写明是哪个字段（见 ``battle_watch.SPEED_FIELDS``）。

⚠️ 速度字段的坑：``_originSpeed``(0xCC) / ``_overwritedSpeed``(0xD0) 存的是
「速度 ×1000」的**定点数**（小数部分是隐藏的同速排序值），直接当速度看会得到 ``14518``
这种怪值；换算见 ``battle_watch.SPEED_SCALE`` / ``speed_int()``（游戏
``GetIntegerOf*Speed`` 就是 /1000）。日志里 ``os=14518 osi=14`` 的 ``osi`` 才是速度 14。
"""

from __future__ import annotations

from functions.achievement.base_achievement import BaseAchievement


class FaustKuiSpeedNineAchievement(BaseAchievement):
    """战斗事件类成就（``battle_driven``）：速度初始化时校验。"""

    battle_driven = True

    def __init__(self) -> None:
        super().__init__(
            ach_id="ach_faust_kui_speed9",
            name="呃啊，我脚崴了",
            description="浮士德-魁首速度为 9。\n我缺的重投谁给我补啊！",
        )
        self.rarity = "rare"

    def check(self) -> bool:
        if self.unlocked:
            return True
        try:
            from functions.achievement import battle_watch
            if battle_watch.faust_kui_speed_nine():
                self.mark_unlocked()
        except Exception:
            return False
        return self.unlocked
