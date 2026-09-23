"""成就数据模块 - 所有成就类均位于此目录下。

每个成就文件都继承自 ``base_achievement.py`` 中的 ``BaseAchievement`` 类，
并在 ``achievements.py::_define_achievements()`` 里注册（显式 import，不靠目录扫描）。

按判定来源分三类：

- **函数式成就**：直接写在 ``achievements.py`` 里（战斗计数/Steam/物品/按键/点击），
  判定只依赖 ``GlobalState`` 或注入的输入统计。
- **内存成就**：``MemoryAchievement`` 子类（如 ``ach_enkephalin_100.py``），
  自己持有进程内存读取器；指针链来自云端笔记 ``FaustLauncher.hook_index``。
- **战斗事件成就**：``battle_driven = True`` 的 ``BaseAchievement`` 子类
  （``ach_yisang_lcb_s3.py`` / ``ach_faust_kui_speed9.py``）。判定状态由
  ``functions/achievement/battle_watch.py``（注入 ``hook_dll/battle_watch.dll`` 观测
  回合边界/技能使用/速度初始化）维护，``check()`` 只读状态，不自己碰内存。
"""
