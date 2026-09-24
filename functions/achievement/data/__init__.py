"""成就数据模块 - 所有成就类均位于此目录下。

每个成就文件都继承自 ``base_achievement.py`` 中的 ``BaseAchievement`` 类，
并在 ``achievements.py::_define_achievements()`` 里注册（显式 import，不靠目录扫描）。

按判定来源分三类：

- **函数式成就**：直接写在 ``achievements.py`` 里（战斗计数/Steam/物品/按键/点击），
  判定只依赖 ``GlobalState`` 或注入的输入统计。
- **内存成就**：``MemoryAchievement`` 子类（如 ``ach_enkephalin_100.py``，
  带 ``memory_driven = True`` 标记），自己持有进程内存读取器；
  指针链来自云端笔记 ``FaustLauncher.hook_index``。
- **战斗事件成就**（``battle_driven = True``）：只声明**数据**，
  继承 ``functions/achievement/battle_achievements.py`` 的四个数据基类之一：

  | 基类 | 规则 kind | 数据（构造参数） |
  |---|---|---|
  | ``SkillUseAchievement`` | ``skill`` | ``identity_id`` / ``skill_ids`` / ``tiers`` / ``gated_skill_ids`` |
  | ``SpeedValueAchievement`` | ``speed`` | ``identity_ids`` / ``value`` / ``fields`` |
  | ``MentalThresholdAchievement`` | ``mental`` | ``identity_ids`` / ``threshold`` |
  | ``DamageTakenAchievement`` | ``hp`` | ``identity_ids`` / ``ratio`` |

  构造时会把数据登记成一条 ``battle_watch.BattleRule``；观测与判定在
  ``functions/achievement/battle_watch.py``（注入 ``hook_dll/battle_watch.dll``，
  观测回合边界 / 技能 / 速度 / 血量 / 理智）里按 kind 统一求值，
  ``check()`` 只读结果（``battle_watch.rule_hit(规则名)``）。

  ⚠️ **业务常量（身份 ID、技能 ID、阈值）写在各成就模块里**，不要在驱动里加常量或特判：
  驱动只认识事件字段与规则类型，加新成就 = 写一个 ``__init__`` + 在 ``achievements.py``
  的 ``_battle_achievements`` 元组里加一行。
"""
