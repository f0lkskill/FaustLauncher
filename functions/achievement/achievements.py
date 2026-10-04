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
    # 汉化目录名跟随当前平台 (零协会 LLC_zh-CN / OurPlay OurPlayHanHua / 插件自定义)
    try:
        from functions.web_update.translation_source import get_translation_dir_name
        lang_name = get_translation_dir_name()
    except Exception:
        lang_name = "LLC_zh-CN"
    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "lang", lang_name, "Items.json",
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
        rarity: str = RARITY_COMMON,
    ):
        self.id = ach_id
        self.name = name
        self.description = description
        self.check_func = check_func
        self.unlocked = False
        self.progress = 0
        self.max_progress = max_progress
        self.hidden = hidden
        self.rarity: str = rarity
        self.unlock_time: datetime | None = None

    def with_rarity(self, rarity: str):
        """链式设置稀有度。"""
        self.rarity = rarity
        return self

    def check(self):
        ...


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

    # === Steam 成就 ===
    achievements.append(Achievement(
        "ach_steam", "Steam玩家", "通过Steam登录游戏",
        lambda: s().steam_logged,
        rarity=RARITY_COMMON,
    ))

    # === 物品反向检测成就 ===
    # 物品状态来自当前背包检查批次，不使用跨会话缓存。
    achievements.append(Achievement(
        "ach_item_102", "十连券持有者", f"拥有1张{RARE_ITEM_IDS[102]}",
        lambda: 102 in s().owned_items,
    ))

    # === 背包/兑换页浏览系列 ===
    achievements.append(Achievement(
        "ach_inventory_1", "初次检视", "浏览1次背包/兑换页",
        lambda: s().inventory_open_count >= 1
    ))

    # === P 键 (自动战斗) 系列成就 ===
    # 6 阶段: 1 / 10 / 100 / 1000 / 10000 / 100000 次按 P
    _p_stages = [
        (1, "首脑的智慧", "使用 P 键进行首次自动战斗"),
        (10, "越用越上瘾。", "累计按 P 键自动战斗 10 次"),
        (100, "IQ -100", "累计按 P 键自动战斗 100 次"),
        (1000, "放弃大脑。", "累计按 P 键自动战斗 1000 次"),
        (10000, "思考已经和呼吸一样简单。", "累计按 P 键自动战斗 10000 次"),
        (100000, "超级无敌霹雳屌炸天的懈怠罪种", "累计按 P 键自动战斗 100000 次"),
    ]
    for idx, (threshold, nm, ds) in enumerate(_p_stages):
        achievements.append(Achievement(
            f"ach_press_p_{idx + 1}", nm, ds,
            (lambda n=threshold: lambda: s().press_p_count >= n)(),  # noqa: E731
            hidden=False,
        ).with_rarity(RARITY_ORDER[idx]))

    # === 点击系列成就 ===
    _click_stages = [
        (1, "哇，你点击了一次！", "点击 1 次"),
        (10, "已经点了十次喽。", "累计点击 10 次"),
        (100, "点了一百次！好厉害！", "累计点击 100 次"),
        (1000, "闲的没事..?", "累计点击 1000 次"),
        (10000, "我去，一万次点击？", "累计点击 10000 次"),
        (100000, "哇，你点击了 100000 次鼠标！", "累计点击 100000 次"),
    ]
    for idx, (threshold, nm, ds) in enumerate(_click_stages):
        achievements.append(Achievement(
            f"ach_click_{idx + 1}", nm, ds,
            (lambda n=threshold: lambda: s().click_count >= n)(),  # noqa: E731
            hidden=False,
        ).with_rarity(RARITY_ORDER[idx]))

    # === 战斗次数系列 ===
    # 这三个模块一直存在（data/ach_battle_01|02|03.py），但**从没进过任何注册列表** ——
    # 结果就是：成就页看不到、没有徽标、也从来不判定。这里显式收进来。
    # 稀有度按目标场次往上走：1 场=普通 / 10 场=稀有 / 100 场=史诗。
    from functions.achievement.data.ach_battle_01 import AchBattle01
    from functions.achievement.data.ach_battle_02 import AchBattle02
    from functions.achievement.data.ach_battle_03 import AchBattle03
    for _cls, _rarity in ((AchBattle01, RARITY_COMMON),
                          (AchBattle02, RARITY_RARE),
                          (AchBattle03, RARITY_EPIC)):
        try:
            achievements.append(_cls().with_rarity(_rarity)) # type: ignore
        except Exception as _exc:  # noqa: BLE001
            print(f"[成就] {_cls.__name__} 注册失败: {_exc}")

    # === 内存成就 ===
    # 该成就自身维护内存读取器，不使用成就状态缓存。
    from functions.achievement.data.ach_enkephalin_100 import FullEnkephalinAchievement
    achievements.append(FullEnkephalinAchievement()) # type: ignore

    # === 战斗事件类成就（注入 battle_watch.dll 观测：技能 / 速度 / 血量 / 理智 / buff / 在场）===
    # 都只读 battle_watch 的规则结果；未注入/未观测到时保持未解锁。
    #
    # **一个文件可以写多个成就派生类**：下面只列模块，注册时会把该模块里所有
    # ``BaseAchievement`` 子类**按定义顺序全部实例化**（想控制顺序/选择性注册，可在
    # 模块里写 ``ACHIEVEMENTS = (实例, ...)``，那就以它为准）。
    _battle_achievement_modules = (
        "data.ach_yisang_lcb_s3",
        "data.ach_faust_kui_speed9",
        "data.ach_index_furioso",
        "data.ach_magical_girl_tragedy",
        "data.ach_heathcliff_sunshower_hurt",
        "data.ach_custom_examples",
        "data.ach_railway6_100t",
        "data.ach_story_10_4",
    )
    # ⚠ 打包（PyInstaller）**只收集静态可见的导入**：动态 ``import_module`` 的模块不会进包，
    # 冻结后就是 "[成就] 模块 data.ach_xxx 导入失败: No module named ..."（实测踩过）。
    # 所以这里显式 import 一遍，下面的遍历只处理这些已经导入进来的模块对象 —— 与打包配置无关，
    # 以后新增成就模块时**只要加到这个 import 列表里**（别再只往字符串元组里加）。
    from functions.achievement.data import (            # noqa: F401
        ach_custom_examples,
        ach_faust_kui_speed9,
        ach_heathcliff_sunshower_hurt,
        ach_index_furioso,
        ach_magical_girl_tragedy,
        ach_railway6_100t,
        ach_story_10_4,
        ach_yisang_lcb_s3,
    )
    _battle_achievement_mods = (
        ach_yisang_lcb_s3,
        ach_faust_kui_speed9,
        ach_index_furioso,
        ach_magical_girl_tragedy,
        ach_heathcliff_sunshower_hurt,
        ach_custom_examples,
        ach_railway6_100t,
        ach_story_10_4,
    )
    for _mod in _battle_achievement_mods:
        _name = getattr(_mod, "__name__", "?")
        explicit = getattr(_mod, "ACHIEVEMENTS", None)
        if explicit:
            for _inst in explicit:
                achievements.append(_inst)
            continue
        for _cls in _classes_in_module(_mod):
            try:
                achievements.append(_cls())
            except Exception as exc:  # noqa: BLE001
                print(f"[成就] {_name}.{_cls.__name__} 注册失败（抽象基类可忽略）: {exc}")

    # === 插件（addon）自定义成就 ===
    # 扫描 addons/*/ 里插件声明的成就模块，登记到同一张表 —— 与内置成就完全同权。
    # 详见 addons/成就插件模板/README.md。
    try:
        _plugins = load_addon_achievements()
        if _plugins:
            print(f"[成就] 插件自定义成就: {len(_plugins)} 个（{', '.join(_plugins)}）")
    except Exception as _exc:  # noqa: BLE001
        print(f"[成就] 插件成就加载失败: {_exc}")

    # 把本地**已完成**的成就直接标记成已解锁（见函数注释：不同步这一步，重启后会重复获取）
    try:
        _marked = load_completed_state()
        if _marked:
            print(f"[成就] 本地已完成 {_marked} 条，直接标记为已解锁（不再重复获取）")
    except Exception as _exc:  # noqa: BLE001
        print(f"[成就] 读取本地完成记录失败: {_exc}")


# ============ 已完成状态（防止重复获取）============

_completed_state_loaded = False


def load_completed_state(force: bool = False) -> int:
    """把本地**已完成**的成就标记为 ``unlocked``，返回标记条数（幂等）。

    为什么必须有这一步：完成记录是**落盘**的（内置在 ``settings.json``，插件在
    ``plugin_achievements.json``），而 ``unlocked`` 只是**内存态**。不补这一步的话，
    每次重启后同一条成就还会再“解锁”一次 —— 重复弹窗、重复写日志、成就页看起来
    像刚拿到。这里读盘一次直接置位，判定循环会跳过已解锁的成就。

    ``force=True`` 可强制重读（比如刚写完记录想立刻对齐）。
    """
    global _completed_state_loaded
    if _completed_state_loaded and not force:
        return 0
    _completed_state_loaded = True
    done: set[str] = set()
    try:
        from functions.base.user_system import (completed_achievements,
                                                completed_plugin_achievements)
        done |= {str(x) for x in completed_achievements()}
        done |= {str(x) for x in completed_plugin_achievements()}
    except Exception:  # noqa: BLE001
        return 0
    if not done:
        return 0
    marked = 0
    for ach in achievements:
        aid = str(getattr(ach, "id", "") or "")
        if not aid or aid not in done:
            continue
        if getattr(ach, "unlocked", False):
            continue
        try:
            ach.unlocked = True
            marked += 1
        except Exception:  # noqa: BLE001
            continue
    return marked


# ============ 插件（addon）自定义成就 API ============

ADDON_ROOT_DIR = "addons"                  # 插件根目录（相对项目根）
ADDON_ENTRY_DEFAULT = "achievements.py"    # 插件成就模块的默认文件名
ADDON_MANIFEST = "addon_info.json"         # 插件清单（可在里面用 achievements 字段改名）


def _project_root() -> str:
    """项目根目录（``addons/`` 就在它下面）。

    优先复用项目里已有的实现（打包后也能定位），拿不到再按文件位置往上推两级。
    """
    try:
        from functions.hook.paths import project_root as _pr  # type: ignore
        return _pr()
    except Exception:  # noqa: BLE001
        return os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))


def register_achievement(instance) -> bool:
    """把一个成就实例登记进全局表（**插件专用公开接口**）。返回是否登记成功。

    规则（故意严格，避免插件把内置成就顶掉）：
      - 只接受 :class:`BaseAchievement` 子类**实例**；
      - ``id`` 必须是非空字符串，且**不能与已有成就重复**（重复直接拒绝）；
      - 登记后与内置成就完全同权：进成就页、参与判定、解锁弹 toast。
    """
    from functions.achievement.base_achievement import BaseAchievement
    if not isinstance(instance, BaseAchievement):
        return False
    aid = str(getattr(instance, "id", "") or "").strip()
    if not aid:
        return False
    if any(str(getattr(a, "id", "") or "") == aid for a in achievements):
        return False
    achievements.append(instance) # type: ignore
    return True


def register_achievements(items) -> int:
    """批量登记，返回成功条数。"""
    return sum(1 for item in (items or ()) if register_achievement(item))


def _addon_dirs() -> list[str]:
    root = os.path.join(_project_root(), ADDON_ROOT_DIR)
    if not os.path.isdir(root):
        return []
    return sorted(
        os.path.join(root, name) for name in os.listdir(root)
        if os.path.isdir(os.path.join(root, name))
    )


def _addon_entry_file(addon_dir: str) -> str:
    """插件里成就模块的路径：清单里有 achievements 字段就用它，否则用默认文件名。"""
    entry = ADDON_ENTRY_DEFAULT
    manifest = os.path.join(addon_dir, ADDON_MANIFEST)
    if os.path.isfile(manifest):
        try:
            with open(manifest, encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict) and str(data.get("achievements") or "").strip():
                entry = str(data["achievements"]).strip()
            # 清单里 settings.enable 为 false 的插件直接跳过
            settings = data.get("settings") if isinstance(data, dict) else None
            if isinstance(settings, dict) and settings.get("enable") is False:
                return ""
        except Exception:  # noqa: BLE001
            pass
    path = os.path.join(addon_dir, entry)
    return path if os.path.isfile(path) else ""


def sync_addon_icons(addon_dir: str) -> int:
    """把插件自带的成就图标同步到前端素材目录，返回拷贝数量。

    插件放 ``addons/<插件名>/assets/achievement/<成就id>.png``（也支持 webp/jpg/svg），
    启动时拷到 ``web/app/assets/achievement/`` —— 前端本来按成就 id 找图，**不用改前端**。
    已存在的同名文件不会被覆盖（内置成就素材优先）。
    """
    import shutil

    src_dir = os.path.join(addon_dir, "assets", "achievement")
    if not os.path.isdir(src_dir):
        return 0
    try:
        from functions.base.common.path_utils import get_web_root
        dst_dir = get_web_root("app", "assets", "achievement")
    except Exception:  # noqa: BLE001
        return 0
    if not dst_dir:
        return 0
    try:
        os.makedirs(dst_dir, exist_ok=True)
    except Exception:  # noqa: BLE001
        return 0
    copied = 0
    for fname in sorted(os.listdir(src_dir)):
        if os.path.splitext(fname)[1].lower() not in (".png", ".webp", ".jpg", ".svg"):
            continue
        dst = os.path.join(dst_dir, fname)
        if os.path.isfile(dst):
            continue
        try:
            shutil.copyfile(os.path.join(src_dir, fname), dst)
            copied += 1
        except Exception:  # noqa: BLE001
            continue
    return copied


def load_addon_achievements() -> list[str]:
    """扫描 ``addons/*/``，把插件声明的自定义成就登记进来，返回新登记的 id 列表。

    插件约定（只认这一种，简单可预期）：

    - 目录：``addons/<插件名>/``
    - 清单：``addon_info.json``（与现有插件一致；``settings.enable=false`` 会被跳过）
    - 成就模块：``achievements.py``（或在清单里写 ``"achievements": "别的名字.py"``）

    成就模块里可以：
      1. 导出 ``ACHIEVEMENTS = (实例, ...)`` —— 推荐，顺序明确；或
      2. 只定义 :class:`BaseAchievement` 子类，按**定义顺序**自动实例化。

    模块里可以直接 ``from functions.achievement.battle_achievements import ...``
    使用内置的各类成就基类（技能 / 速度 / 理智 / 受伤 / buff / 在场 / 复合）。
    """
    import importlib.util

    added: list[str] = []
    for addon_dir in _addon_dirs():
        try:
            sync_addon_icons(addon_dir)       # 插件自带图标先同步过去
        except Exception:  # noqa: BLE001
            pass
        entry = _addon_entry_file(addon_dir)
        if not entry:
            continue
        name = os.path.basename(addon_dir) or "addon"
        mod_name = f"faustlauncher_addon_{abs(hash(entry)):x}"
        try:
            spec = importlib.util.spec_from_file_location(mod_name, entry)
            if spec is None or spec.loader is None:
                continue
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        except Exception as exc:  # noqa: BLE001
            print(f"[成就] 插件 {name} 的成就模块导入失败: {exc}")
            continue
        explicit = getattr(module, "ACHIEVEMENTS", None)
        if explicit:
            for inst in explicit:
                _tag_plugin_achievement(inst, name)
                if register_achievement(inst):
                    added.append(str(getattr(inst, "id", "")))
            continue
        for cls in _classes_in_module(module):
            try:
                inst = cls()
            except Exception:  # noqa: BLE001
                continue          # 抽象/中间基类实例化失败属正常
            _tag_plugin_achievement(inst, name)
            if register_achievement(inst):
                added.append(str(getattr(inst, "id", "")))
    return added


def _tag_plugin_achievement(instance, addon_name: str) -> None:
    """给插件成就打标记：``plugin=True`` + ``addon=<插件目录名>``。

    成就页据此显示「插件」角标；判定/落盘据此走**插件独立存档**、不进云端。
    """
    try:
        instance.plugin = True
        instance.addon = addon_name
    except Exception:  # noqa: BLE001
        pass


def _classes_in_module(mod) -> list:
    """列出某模块里**自己定义**的成就派生类（按定义顺序）。

    - 只收 ``BaseAchievement`` 子类（含类式与战斗类基类的孙子类）；
    - 只收 ``__module__`` 就是本模块的（避免把 import 进来的基类/别处类重复注册）；
    - 实例化失败（比如只是个中间抽象基类）时由调用方跳过并打日志。
    """
    from functions.achievement.base_achievement import BaseAchievement
    out = []
    for _name, obj in vars(mod).items():
        if not isinstance(obj, type):
            continue
        if obj is BaseAchievement or not issubclass(obj, BaseAchievement):
            continue
        if getattr(obj, "__module__", "") != getattr(mod, "__name__", ""):
            continue
        if getattr(obj, "abstract_battle_base", False):
            continue
        out.append(obj)
    return out


_define_achievements()


# ============ 成就检查函数 ============
def check_achievements(log_callback) -> list[Achievement]:
    """检查所有成就，解锁满足条件的成就。

    参数:
        log_callback: 日志回调函数，用于输出成就解锁信息

    返回:
        新解锁的成就列表
    """
    unlocked = []
    from functions.achievement.base_achievement import BattleAchievement
    for ach in achievements:
        if not ach.unlocked:
            matched = False          # 必须初始化：check() 抛异常时才不会沿用上一轮的值
            try:
                # 函数式 Achievement 使用 check_func；类式成就自行实现 check。
                if hasattr(ach, "check_func"):
                    matched = ach.check_func()
                    if matched:
                        ach.unlocked = True
                        ach.unlock_time = datetime.now()
                        ach.progress = ach.max_progress
                else:
                    # 战斗次数类成就的 check 需要"当前完成场次"这个入参
                    # （它们的内部计数器不会自己涨，全局计数在状态里）。
                    if isinstance(ach, BattleAchievement):
                        matched = ach.check(
                            battle_count=int(get_state().battle_count or 0), deaths=False) # type: ignore
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
        return check_achievements(lambda msg: print(msg))  # type: ignore # noqa

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