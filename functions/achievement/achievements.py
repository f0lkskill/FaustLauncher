
import os
import json
import time as _time
from datetime import datetime
from functions.achievement.base_achievement import BaseAchievement

LOG_FILE = "Player.log"
CHECK_INTERVAL = 0.3
RETRY_COUNT = 3

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
    names = dict(_FALLBACK_ITEM_NAMES)
    try:
        from functions.web_update.translation_source import get_translation_dir_name
        lang_name = get_translation_dir_name()
    except Exception:
        lang_name = "LLC_zh-CN"
    try:
        from functions.base.common.path_utils import get_app_root
        root = get_app_root()
    except Exception:  # noqa: BLE001
        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    path = os.path.join(root, "lang", lang_name, "Items.json")
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

RARITY_COMMON = "common"
RARITY_UNCOMMON = "uncommon"
RARITY_RARE = "rare"
RARITY_EPIC = "epic"
RARITY_LEGENDARY = "legendary"
RARITY_MYTHIC = "mythic"

RARITY_ORDER = [
    RARITY_COMMON, RARITY_UNCOMMON, RARITY_RARE,
    RARITY_EPIC, RARITY_LEGENDARY, RARITY_MYTHIC,
]

RARITY_COLORS = {
    RARITY_COMMON:     (255, 255, 255),
    RARITY_UNCOMMON:   (96, 200, 110),
    RARITY_RARE:       (80, 150, 255),
    RARITY_EPIC:       (180, 110, 255),
    RARITY_LEGENDARY:  (255, 200, 60),
    RARITY_MYTHIC:     (255, 80, 70),
}

RARITY_NAMES_ZH = {
    RARITY_COMMON: "普通",
    RARITY_UNCOMMON: "精良",
    RARITY_RARE: "稀有",
    RARITY_EPIC: "史诗",
    RARITY_LEGENDARY: "传说",
    RARITY_MYTHIC: "神话",
}

ITEM_FAMILIES = [
    {101, 102},
    {103, 104, 105, 106, 107, 108, 109, 110},
    {501, 502, 601, 751},
]

class ItemFamily:

    @staticmethod
    def family_of(item_id: int) -> int:
        for idx, fam in enumerate(ITEM_FAMILIES):
            if item_id in fam:
                return idx
        return -1

class GlobalState:

    def __init__(self):
        self.reset()

    def reset(self):
        self.battle_count = 0
        self.steam_logged = False
        self.inventory_open_count = 0
        self.press_p_count: int = 0
        self.click_count: int = 0
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
        self.running_owned_ids = set(ids)
        self.owned_items = set(ids)

    def remember_family(self, fam_idx: int, zero_ids: set[int]):
        self.families[fam_idx] = set(zero_ids)

_state = GlobalState()

def get_state() -> GlobalState:
    return _state

class Achievement:

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
        self.rarity = rarity
        return self

    def check(self):
        ...

achievements: list[Achievement] = []

def _define_achievements():
    s = get_state

    achievements.append(Achievement(
        "ach_steam", "Steam玩家", "通过Steam登录游戏",
        lambda: s().steam_logged,
        rarity=RARITY_COMMON,
    ))

    achievements.append(Achievement(
        "ach_item_102", "十连券持有者", f"拥有1张{RARE_ITEM_IDS[102]}",
        lambda: 102 in s().owned_items,
    ))

    achievements.append(Achievement(
        "ach_inventory_1", "初次检视", "浏览1次背包/兑换页",
        lambda: s().inventory_open_count >= 1
    ))

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

    from functions.achievement.data.ach_battle_01 import AchBattle01
    from functions.achievement.data.ach_battle_02 import AchBattle02
    from functions.achievement.data.ach_battle_03 import AchBattle03
    for _cls, _rarity in ((AchBattle01, RARITY_COMMON),
                          (AchBattle02, RARITY_RARE),
                          (AchBattle03, RARITY_EPIC)):
        try:
            achievements.append(_cls().with_rarity(_rarity)) # type: ignore
        except Exception as _exc:  # noqa: BLE001
            print(f"[Achievement] {_cls.__name__} 注册失败: {_exc}")

    from functions.achievement.data.ach_enkephalin_100 import FullEnkephalinAchievement
    achievements.append(FullEnkephalinAchievement()) # type: ignore

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
                print(f"[Achievement] {_name}.{_cls.__name__} 注册失败（抽象基类可忽略）: {exc}")

    try:
        _plugins = load_addon_achievements()
        if _plugins:
            print(f"[Achievement] 插件自定义成就: {len(_plugins)} 个（{', '.join(_plugins)}）")
    except Exception as _exc:  # noqa: BLE001
        print(f"[Achievement] 插件成就加载失败: {_exc}")

    try:
        _marked = load_completed_state()
        if _marked:
            pass
            # print(f"[Achievement] 本地已完成 {_marked} 条，直接标记为已解锁（不再重复获取）")
    except Exception as _exc:  # noqa: BLE001
        print(f"[Achievement] 读取本地完成记录失败: {_exc}")

_completed_state_loaded = False

def load_completed_state(force: bool = False) -> int:
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

ADDON_ROOT_DIR = "addons"
ADDON_ENTRY_DEFAULT = "achievements.py"
ADDON_MANIFEST = "addon_info.json"

def _project_root() -> str:
    try:
        from functions.hook.paths import project_root as _pr  # type: ignore
        return _pr()
    except Exception:  # noqa: BLE001
        return os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))

def register_achievement(instance) -> bool:
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
    entry = ADDON_ENTRY_DEFAULT
    manifest = os.path.join(addon_dir, ADDON_MANIFEST)
    if os.path.isfile(manifest):
        try:
            with open(manifest, encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict) and str(data.get("achievements") or "").strip():
                entry = str(data["achievements"]).strip()
            settings = data.get("settings") if isinstance(data, dict) else None
            if isinstance(settings, dict) and settings.get("enable") is False:
                return ""
        except Exception:  # noqa: BLE001
            pass
    path = os.path.join(addon_dir, entry)
    return path if os.path.isfile(path) else ""

def sync_addon_icons(addon_dir: str) -> int:
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
    import importlib.util

    added: list[str] = []
    for addon_dir in _addon_dirs():
        try:
            sync_addon_icons(addon_dir)
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
            print(f"[Achievement] 插件 {name} 的成就模块导入失败: {exc}")
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
                continue
            _tag_plugin_achievement(inst, name)
            if register_achievement(inst):
                added.append(str(getattr(inst, "id", "")))
    return added

def _tag_plugin_achievement(instance, addon_name: str) -> None:
    try:
        instance.plugin = True
        instance.addon = addon_name
    except Exception:  # noqa: BLE001
        pass

def _classes_in_module(mod) -> list:
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

def check_achievements(log_callback) -> list[Achievement]:
    unlocked = []
    from functions.achievement.base_achievement import BattleAchievement
    for ach in achievements:
        if not ach.unlocked:
            matched = False
            try:
                if hasattr(ach, "check_func"):
                    matched = ach.check_func()
                    if matched:
                        ach.unlocked = True
                        ach.unlock_time = datetime.now()
                        ach.progress = ach.max_progress
                else:
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
    s = get_state()
    now = _time.time()
    if not s.zero_item_ids:
        s.round_active = True
    s.zero_item_ids.add(item_id)
    s.last_zero_time = now

def detect_owned_items(zero_ids: set[int]) -> list[tuple[int, str]]:
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
    s = get_state()
    s.inventory_open_count += 1
    return True

def poll_inventory_window(now=None):
    s = get_state()
    if not s.round_active or not s.zero_item_ids:
        return None
    if now is None:
        now = _time.time()
    if now - s.last_zero_time < 0.7:
        return None

    s.round_active = False
    collected = set(s.zero_item_ids)
    s.zero_item_ids.clear()
    return collected

def reset_achievements():
    get_state().reset()
    for ach in achievements:
        ach.unlocked = False
        ach.progress = 0
        ach.unlock_time = None

def get_manager() -> "AchievementManager":
    return AchievementManager()

class AchievementManager:

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
