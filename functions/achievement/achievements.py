"""成就管理器 - 统一管理所有成就定义和全局状态。

此模块负责：
- 从 data/ 目录自动加载所有成就模块
- 维护全局游戏状态（战斗、物品、死亡等）
- 提供成就检查和状态更新功能
"""

import os
import json
import time as _time
import importlib
from datetime import datetime
from functions.achievement.base_achievement import BaseAchievement

# ============ 配置 ============
LOG_FILE = "Player.log"
CHECK_INTERVAL = 0.3
RETRY_COUNT = 3

# ============ 物品映射 ============
# Items.json 是名称来源；这些 ID 是日志中需要反向检测的目标物品。
# 只纳入 Items.json 中实际存在、且原成就追踪的物品。
# 107-110 不存在于当前语言包，不能参与任何拥有判定。
_ITEM_IDS = (101, 102, 103, 104, 105, 106, 501, 502, 601, 751)
_FALLBACK_ITEM_NAMES = {
    101: "提取券",
    102: "十连提取券",
    103: "3★人格必得十连提取券",
    104: "[第1赛季]3★人格必得十连提取券",
    105: "[第2赛季]3★人格必得十连提取券",
    106: "[第3赛季]3★人格必得十连提取券",
    107: "[第4赛季]3★人格必得十连提取券",
    108: "[第5赛季]3★人格必得十连提取券",
    109: "[第6赛季]3★人格必得十连提取券",
    110: "[第7赛季]3★人格必得十连提取券",
    501: "第1赛季人格自选券",
    502: "第2赛季人格自选券",
    601: "第1赛季通行证E.G.O自选券",
    751: "播报员自选券",
}


def _load_item_names() -> dict[int, str]:
    """从项目语言包加载物品名称，缺失时使用内置名称。"""
    names = dict(_FALLBACK_ITEM_NAMES)
    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "lang", "LLC_zh-CN", "Items.json",
    )
    try:
        with open(path, "r", encoding="utf-8") as f:
            for item in json.load(f).get("dataList", []):
                item_id = int(item.get("id", -1))
                if item_id in _ITEM_IDS and item.get("name"):
                    names[item_id] = str(item["name"])
    except (OSError, ValueError, TypeError):
        pass
    return names


RARE_ITEM_IDS = _load_item_names()
ITEM_IDS = tuple(_ITEM_IDS)

TEN_PULL_IDS = [102, 103, 104, 105, 106]
GUARANTEED_IDS = [103, 104, 105, 106]
SELF_SELECT_IDS = [501, 502, 601, 751]

# ============ 成就稀有度 ============
# 由低到高: 白 → 绿 → 蓝 → 紫 → 金 → 红
RARITY_COMMON = "common"      # 白
RARITY_UNCOMMON = "uncommon"  # 绿
RARITY_RARE = "rare"          # 蓝
RARITY_EPIC = "epic"          # 紫
RARITY_LEGENDARY = "legendary"  # 金
RARITY_MYTHIC = "mythic"      # 红

RARITY_ORDER = [
    RARITY_COMMON, RARITY_UNCOMMON, RARITY_RARE,
    RARITY_EPIC, RARITY_LEGENDARY, RARITY_MYTHIC,
]

# 稀有度 → (标题/边框颜色, 名称颜色)
RARITY_COLORS = {
    RARITY_COMMON:     (255, 255, 255),        # 白
    RARITY_UNCOMMON:   (96, 200, 110),         # 绿
    RARITY_RARE:       (80, 150, 255),         # 蓝
    RARITY_EPIC:       (180, 110, 255),        # 紫
    RARITY_LEGENDARY:  (255, 200, 60),         # 金
    RARITY_MYTHIC:     (255, 80, 70),          # 红
}

RARITY_NAMES_ZH = {
    RARITY_COMMON: "普通",
    RARITY_UNCOMMON: "精良",
    RARITY_RARE: "稀有",
    RARITY_EPIC: "史诗",
    RARITY_LEGENDARY: "传说",
    RARITY_MYTHIC: "神话",
}

# ============ 物品族 (同族物品在背包同一分类页, 日志会一并打印缺货项) ============
ITEM_FAMILIES = [
    {101, 102},            # 提取券族: 普通提取券 / 十连提取券
    {103, 104, 105, 106, 107, 108, 109, 110},  # 必得券族: 3★必得十连(含赛季)
    {501, 502, 601, 751},  # 自选券族: 人格/通行证EGO/播报员 自选券
]


class ItemFamily:
    """物品族分组助手。"""

    @staticmethod
    def family_of(item_id: int) -> int:
        """返回物品所属族的索引, 不在任何族时返回 -1。"""
        for idx, fam in enumerate(ITEM_FAMILIES):
            if item_id in fam:
                return idx
        return -1

# ============ 角色映射 ============
CHARACTER_ID_MAP = {
    "10110": "李箱",
    "11114": "奥提斯",
    "10209": "浮士德",
    "10715": "希斯克利夫",
    "11115": "奥提斯",
    "10116": "李箱",
}


# ============ 全局状态 ============
class GlobalState:
    """全局游戏状态 - 所有成就检查共享这些状态。"""

    def __init__(self):
        self.reset()

    def reset(self):
        """重置所有状态（完全清空, 测试用）。"""
        self.battle_count = 0
        self.steam_logged = False
        self.inventory_open_count = 0     # 背包/兑换页浏览次数
        # ── 按键/点击统计 (仅当前游戏会话, 不写缓存) ──
        self.press_p_count: int = 0
        self.click_count: int = 0
        # ── 兼容旧字段 (不再用于成就判定) ──
        self.death_detected = False
        self.death_occurred = False
        self.last_battle_clean = False
        self.is_in_battle = False
        self.owned_items: set[int] = set()
        self.zero_items_in_last_inventory: set[int] = set()
        self.has_inventory_opened = False
        self.inventory_check_done = False
        self.zero_item_ids: set[int] = set()
        self.last_zero_time: float = 0.0
        self.round_active: bool = False
        self.families: list[set[int]] = [set() for _ in ITEM_FAMILIES]
        self.session_zero_seen: set[int] = set()
        self.running_owned_ids: set[int] = set()

    def load_owned(self, ids: set[int]):
        """从持久化文件加载已拥有的物品 ID。"""
        self.running_owned_ids = set(ids)
        self.owned_items = set(ids)

    def remember_family(self, fam_idx: int, zero_ids: set[int]):
        """记录某族最近一次缺货快照 (用于跨会话推断同族其他未打印物品)。"""
        self.families[fam_idx] = set(zero_ids)


# 全局单例
_state = GlobalState()


def get_state() -> GlobalState:
    """获取全局状态实例。"""
    return _state


# ============ 成就类 ============
class Achievement:
    """单个成就定义。

    每个成就包含：
    - id: 唯一标识符
    - name: 显示名称
    - description: 描述
    - check_func: 检查函数（无参数，返回 True 表示满足条件）
    - unlocked: 是否已解锁
    - progress: 当前进度
    - max_progress: 最大进度
    - hidden: 是否隐藏
    - unlock_time: 解锁时间
    """

    def __init__(
        self,
        ach_id: str,
        name: str,
        description: str,
        check_func,
        max_progress: int = 1,
        hidden: bool = False,
    ):
        self.id = ach_id
        self.name = name
        self.description = description
        self.check_func = check_func
        self.unlocked = False
        self.progress = 0
        self.max_progress = max_progress
        self.hidden = hidden
        self.rarity: str = RARITY_COMMON
        self.unlock_time: datetime | None = None

    def with_rarity(self, rarity: str):
        """链式设置稀有度。"""
        self.rarity = rarity
        return self


# ============ 成就定义列表 ============
achievements: list[Achievement] = []


def _define_achievements():
    """定义所有成就。

    仅保留 Player.log + 输入钩子能**可靠验证**的成就:
    - 战斗完成 (StageController:EndStage, 每场唯一)
    - Steam 登录 (SetLoginInfo : STEAM)
    - 背包/兑换页浏览 (InventoryUIPopup:SetItemPool)
    - P 键 / 鼠标点击 (Windows 输入钩子)

    说明:
    - 物品拥有成就使用当前背包检查批次的反向检测，不读取跨会话缓存。
    - 脑啡肽成就使用进程内存读取器，不读取跨会话缓存。
    - 无伤通关已移除，因为 Player.log 没有可靠的角色死亡信号。
    """
    s = get_state

    # === 战斗成就 ===
    achievements.append(Achievement(
        "ach_battle_01", "初次战斗", "完成1场战斗",
        lambda: s().battle_count >= 1
    ))
    achievements.append(Achievement(
        "ach_battle_02", "战斗达人", "完成10场战斗",
        lambda: s().battle_count >= 10
    ))
    achievements.append(Achievement(
        "ach_battle_03", "战斗大师", "完成100场战斗",
        lambda: s().battle_count >= 100
    ))
    achievements.append(Achievement(
        "ach_battle_04", "通关百战", "累计完成100场战斗后继续征战",
        lambda: s().battle_count >= 500
    ))

    # === Steam 成就 ===
    achievements.append(Achievement(
        "ach_steam", "Steam玩家", "通过Steam登录游戏",
        lambda: s().steam_logged
    ))

    # === 物品反向检测成就 ===
    # 物品状态来自当前背包检查批次，不使用跨会话缓存。
    achievements.append(Achievement(
        "ach_item_101", "提取券持有者", f"拥有1张{RARE_ITEM_IDS[101]}",
        lambda: 101 in s().owned_items,
    ))
    achievements.append(Achievement(
        "ach_item_102", "十连券持有者", f"拥有1张{RARE_ITEM_IDS[102]}",
        lambda: 102 in s().owned_items,
    ))
    achievements.append(Achievement(
        "ach_guaranteed_general", "必得券持有者", f"拥有1张{RARE_ITEM_IDS[103]}",
        lambda: 103 in s().owned_items,
    ))
    for season, item_id in ((1, 104), (2, 105), (3, 106)):
        achievements.append(Achievement(
            f"ach_season_{season}_guaranteed",
            f"第{season}赛季必得券持有者",
            f"拥有1张{RARE_ITEM_IDS[item_id]}",
            lambda i=item_id: i in s().owned_items,
        ))
    achievements.append(Achievement(
        "ach_ten_pull_1", "十连券收集者 I", "拥有1种以上的十连券",
        lambda: any(i in s().owned_items for i in TEN_PULL_IDS),
    ))
    achievements.append(Achievement(
        "ach_ten_pull_3", "十连券收集者 II", "拥有3种以上的十连券",
        lambda: sum(i in s().owned_items for i in TEN_PULL_IDS) >= 3,
    ))
    achievements.append(Achievement(
        "ach_ten_pull_5", "十连券大师", "拥有5种以上的十连券",
        lambda: sum(i in s().owned_items for i in TEN_PULL_IDS) >= 5,
    ))
    achievements.append(Achievement(
        "ach_guaranteed_2", "必得券收集者", "拥有2种以上的必得券",
        lambda: sum(i in s().owned_items for i in GUARANTEED_IDS) >= 2,
    ))
    achievements.append(Achievement(
        "ach_guaranteed_4", "必得券大师", "拥有4种以上的必得券",
        lambda: sum(i in s().owned_items for i in GUARANTEED_IDS) >= 4,
    ))
    achievements.append(Achievement(
        "ach_self_select", "自选券收藏家", "拥有1张赛季人格自选券",
        lambda: any(i in s().owned_items for i in SELF_SELECT_IDS),
    ))
    achievements.append(Achievement(
        "ach_total_5", "物品收集者", "拥有5种不同的稀有物品",
        lambda: len(s().owned_items) >= 5,
    ))
    achievements.append(Achievement(
        "ach_total_10", "物品收藏家", "拥有10种不同的稀有物品",
        lambda: len(s().owned_items) >= 10,
    ))

    # === 背包/兑换页浏览系列 ===
    achievements.append(Achievement(
        "ach_inventory_1", "初次检视", "浏览1次背包/兑换页",
        lambda: s().inventory_open_count >= 1
    ))
    achievements.append(Achievement(
        "ach_inventory_10", "检视达人", "累计浏览背包/兑换页10次",
        lambda: s().inventory_open_count >= 10
    ))
    achievements.append(Achievement(
        "ach_inventory_100", "检视大师", "累计浏览背包/兑换页100次",
        lambda: s().inventory_open_count >= 100
    ))

    # === P 键 (自动战斗) 系列成就 ===
    # 6 阶段: 1 / 10 / 100 / 1000 / 10000 / 100000 次按 P
    _p_stages = [
        (1, "首脑的智慧", "使用 P 键进行首次自动战斗"),
        (10, "战术家", "累计按 P 键 10 次"),
        (100, "自动战斗大师", "累计按 P 键 100 次"),
        (1000, "全自动指挥官", "累计按 P 键 1000 次"),
        (10000, "战场自动化之神", "累计按 P 键 10000 次"),
        (100000, "不需要双手之人", "累计按 P 键 100000 次"),
    ]
    for idx, (threshold, nm, ds) in enumerate(_p_stages):
        achievements.append(Achievement(
            f"ach_press_p_{idx + 1}", nm, ds,
            (lambda n=threshold: lambda: s().press_p_count >= n)(),  # noqa: E731
            hidden=False,
        ).with_rarity(RARITY_ORDER[idx]))

    # === 点击系列成就 ===
    _click_stages = [
        (1, "初次点击", "点击 1 次"),
        (10, "点击新手", "累计点击 10 次"),
        (100, "双击狂魔", "累计点击 100 次"),
        (1000, "鼠标艺术家", "累计点击 1000 次"),
        (10000, "连点传说", "累计点击 10000 次"),
        (100000, "天选之手", "累计点击 100000 次"),
    ]
    for idx, (threshold, nm, ds) in enumerate(_click_stages):
        achievements.append(Achievement(
            f"ach_click_{idx + 1}", nm, ds,
            (lambda n=threshold: lambda: s().click_count >= n)(),  # noqa: E731
            hidden=False,
        ).with_rarity(RARITY_ORDER[idx]))

    # === 内存成就 ===
    # 该成就自身维护内存读取器，不使用成就状态缓存。
    from functions.achievement.data.ach_enkephalin_100 import FullEnkephalinAchievement
    achievements.append(FullEnkephalinAchievement())


_define_achievements()


def _assign_legacy_rarities():
    """为既有成就按类别标注稀有度 (系列成就已在定义处标注)。"""
    rarity_map = {
        "ach_battle_01": RARITY_COMMON,
        "ach_battle_02": RARITY_UNCOMMON,
        "ach_battle_03": RARITY_RARE,
        "ach_battle_04": RARITY_LEGENDARY,
        "ach_steam": RARITY_COMMON,
        "ach_inventory_1": RARITY_COMMON,
        "ach_inventory_10": RARITY_UNCOMMON,
        "ach_inventory_100": RARITY_RARE,
    }
    for ach in achievements:
        if ach.id in rarity_map:
            ach.rarity = rarity_map[ach.id]


_assign_legacy_rarities()


# ============ 成就检查函数 ============
def check_achievements(log_callback) -> list[Achievement]:
    """检查所有成就，解锁满足条件的成就。

    参数:
        log_callback: 日志回调函数，用于输出成就解锁信息

    返回:
        新解锁的成就列表
    """
    unlocked = []
    for ach in achievements:
        if not ach.unlocked:
            try:
                # 函数式 Achievement 使用 check_func；类式成就自行实现 check。
                if hasattr(ach, "check_func"):
                    matched = ach.check_func()
                    if matched:
                        ach.unlocked = True
                        ach.unlock_time = datetime.now()
                        ach.progress = ach.max_progress
                else:
                    matched = ach.check()
                if matched:
                    unlocked.append(ach)
            except Exception:
                pass
    return unlocked


def record_zero_item(item_id: int):
    """记录一个 0 数量物品 (加入浏览归并窗口)。

    参数:
        item_id: 数量为 0 的物品 ID
    """
    s = get_state()
    now = _time.time()
    if not s.zero_item_ids:
        s.round_active = True
    s.zero_item_ids.add(item_id)
    s.last_zero_time = now


def detect_owned_items(zero_ids: set[int]) -> list[tuple[int, str]]:
    """根据当前一次背包检查批次反向推断拥有的目标物品。

    日志只记录数量为 0 的物品。批次中出现 0 的 ID 明确视为未拥有，
    其余目标 ID 视为拥有。该函数只接收当前批次，不读取任何缓存。
    """
    s = get_state()
    zero_ids = set(zero_ids)
    new_owned = []
    for item_id in ITEM_IDS:
        if item_id in zero_ids:
            s.owned_items.discard(item_id)
            continue
        if item_id not in s.owned_items:
            s.owned_items.add(item_id)
            new_owned.append((item_id, RARE_ITEM_IDS[item_id]))
    s.running_owned_ids = set(s.owned_items)
    return new_owned


def register_inventory_open() -> bool:
    """记录一次背包/兑换页浏览结束 (0 记录簇空闲)。

    返回:
        True 表示本次浏览计数变化 (供调用方检查成就)
    """
    s = get_state()
    s.inventory_open_count += 1
    return True


def poll_inventory_window(now=None):
    """浏览归并: 0 物品记录簇空闲(>0.7s)视为一次页面浏览。

    需在主循环中周期性调用。

    返回:
        - None  : 无活动窗口或窗口仍在收集
        - 非 None: 已归并一次浏览 (调用方应 register_inventory_open + 查成就)
    """
    s = get_state()
    if not s.round_active or not s.zero_item_ids:
        return None
    if now is None:
        now = _time.time()
    if now - s.last_zero_time < 0.7:
        return None

    # 一簇结束: 固化本批次 0 集合，交给 hook 做反向检测
    s.round_active = False
    collected = set(s.zero_item_ids)
    s.zero_item_ids.clear()
    return collected


def reset_achievements():
    """重置所有成就状态（开始新游戏时调用）。"""
    get_state().reset()
    for ach in achievements:
        ach.unlocked = False
        ach.progress = 0
        ach.unlock_time = None


def get_manager() -> "AchievementManager":
    """兼容旧接口：返回 AchievementManager 代理对象。"""
    return AchievementManager()


class AchievementManager:
    """成就管理器 - 兼容旧接口代理到全局函数和状态。"""

    def __init__(self):
        self.achievements = achievements

    @property
    def battle_count(self) -> int:
        return get_state().battle_count

    @property
    def death_detected(self) -> bool:
        return get_state().death_detected

    @property
    def owned_items(self) -> set[int]:
        return get_state().owned_items

    @property
    def steam_logged(self) -> bool:
        return get_state().steam_logged

    def check_all(self) -> list[BaseAchievement]:
        """检查所有成就并返回新解锁的列表（兼容接口）。"""
        return check_achievements(lambda msg: print(msg))  # noqa

    def reset(self):
        reset_achievements()

    def get_unlocked_count(self) -> int:
        return sum(1 for ach in achievements if ach.unlocked)

    def get_achievements_info(self) -> list[dict]:
        return [
            {
                "id": ach.id,
                "name": ach.name,
                "description": ach.description,
                "unlocked": ach.unlocked,
                "progress": ach.progress,
                "max_progress": ach.max_progress,
                "rarity": ach.rarity,
            }
            for ach in achievements
        ]

    def get_achievement(self, ach_id: str) -> Achievement | None:
        for ach in achievements:
            if ach.id == ach_id:
                return ach
        return None