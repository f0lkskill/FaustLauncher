"""成就系统模块。

该模块提供 Limbus Company 游戏的成就追踪功能。

主要功能:
- 实时监控 Player.log 游戏日志 (战斗/背包/退出)
- 反向检测物品拥有 (日志只打印"数量为0"的物品)
- 全局输入统计: P键(自动战斗) 与 鼠标左右键点击
- 成就稀有度: 白/绿/蓝/紫/金/红 (标题颜色随稀有度)
- 解锁时右下角 Steam 风格弹窗 (圆角/图标/堆叠)

使用方法:
    from functions.achievement import start_achievement_monitoring
    
    # 启动成就监测 (含 GUI 弹窗, 需在主线程 pump)
    hook = start_achievement_monitoring('C:/path/to/Player.log')
    
    # 或者在游戏启动流程中自动调用
    from functions.base.load_mod import launch_game_process
    launch_game_process()  # 会自动启动成就监测

独立进程模式:
    python main.py --achievement-hook --log <Player.log> --output <log.txt>
"""

from functions.achievement.base_achievement import (
    BaseAchievement,
    ItemAchievement,
    BattleAchievement,
    SteamAchievement,
    CollectionAchievement,
    HiddenAchievement,
)
from functions.achievement.achievements import (
    AchievementManager,
    get_manager,
    RARE_ITEM_IDS,
    TEN_PULL_IDS,
    GUARANTEED_IDS,
    SELF_SELECT_IDS,
    CHARACTER_ID_MAP,
    LOG_FILE,
    RARITY_COMMON,
    RARITY_UNCOMMON,
    RARITY_RARE,
    RARITY_EPIC,
    RARITY_LEGENDARY,
    RARITY_MYTHIC,
    RARITY_COLORS,
)
from functions.achievement.hook import (
    LogReader,
    LogProcessor,
    AchievementHook,
    get_hook,
    start_achievement_monitoring,
    stop_achievement_monitoring,
)
from functions.achievement.input_hook import (
    start_input_monitoring,
    stop_input_monitoring,
)

__all__ = [
    # 基础类
    "BaseAchievement",
    "ItemAchievement",
    "BattleAchievement",
    "SteamAchievement",
    "CollectionAchievement",
    "HiddenAchievement",
    # 管理器
    "AchievementManager",
    "get_manager",
    # 常量
    "RARE_ITEM_IDS",
    "TEN_PULL_IDS",
    "GUARANTEED_IDS",
    "SELF_SELECT_IDS",
    "CHARACTER_ID_MAP",
    "LOG_FILE",
    # 稀有度
    "RARITY_COMMON",
    "RARITY_UNCOMMON",
    "RARITY_RARE",
    "RARITY_EPIC",
    "RARITY_LEGENDARY",
    "RARITY_MYTHIC",
    "RARITY_COLORS",
    # Hook
    "LogReader",
    "LogProcessor",
    "AchievementHook",
    "get_hook",
    "start_achievement_monitoring",
    "stop_achievement_monitoring",
    # 输入统计
    "start_input_monitoring",
    "stop_input_monitoring",
]
