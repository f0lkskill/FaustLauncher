"""成就基类与几种常用判定实现。

所有成就共享 :class:`BaseAchievement` 的状态字段（unlocked/progress/unlock_time）；
子类只需实现 check，把外部事件（道具、战斗、内存值、Steam 登录、收集数量）
转成解锁判定。成就定义放在 `data/` 子模块，这里只提供可复用的骨架。
"""


from abc import ABC, abstractmethod
from datetime import datetime
from typing import Callable
import threading

class BaseAchievement(ABC):

    """成就基类：保存 id/名称/描述/稀有度与解锁状态，定义 check 接口。"""
    def __init__(self, ach_id: str, name: str, description: str, rarity: str = "common"):
        """初始化成就元数据与进度状态。"""
        self.ach_id = ach_id
        self.id = ach_id
        self.name = name
        self.description = description
        self.rarity = rarity
        self.unlocked = False
        self.unlock_time: datetime | None = None
        self.progress = 0
        self.max_progress = 1

    @abstractmethod
    def check(self) -> bool:
        """根据外部事件/当前状态判断是否解锁，返回是否已解锁。"""
        pass

    def with_rarity(self, rarity: str):
        """设置稀有度并返回 self，支持链式声明。"""
        self.rarity = str(rarity or "common")
        return self

    def mark_unlocked(self):
        """标记为已解锁并记录时间，把进度推到上限。"""
        if not self.unlocked:
            self.unlocked = True
            self.unlock_time = datetime.now()
            self.progress = self.max_progress

    def is_unlocked(self) -> bool:
        """是否已解锁。"""
        return self.unlocked

    def get_progress(self) -> int:
        """当前进度值。"""
        return self.progress

    def get_status_text(self) -> str:
        """供界面显示的状态文本（已解锁/未解锁）。"""
        if self.unlocked:
            return f"✅ {self.name}"
        else:
            return f"⬜ {self.name}"

class MemoryAchievement(BaseAchievement):

    """通过周期性读内存数值判定的成就。"""
    memory_driven = True

    def __init__(
        self,
        ach_id: str,
        name: str,
        description: str,
        reader_factory: Callable[[], object],
        predicate: Callable[[int], bool],
    ):
        """初始化成就元数据与进度状态。"""
        super().__init__(ach_id, name, description)
        self._reader_factory = reader_factory
        self._predicate = predicate
        self._reader = None
        self.current_value: int | None = None
        self._read_lock = threading.Lock()

    def check(self) -> bool:
        """根据外部事件/当前状态判断是否解锁，返回是否已解锁。"""
        if self.unlocked:
            return True
        with self._read_lock:
            try:
                if self._reader is None:
                    self._reader = self._reader_factory()
                value = self._reader.read_enkephalin() # type: ignore
                self.current_value = value
                if value is not None and self._predicate(value):
                    self.mark_unlocked()
            except Exception:
                self.current_value = None
        return self.unlocked

    def detach(self) -> None:
        """释放内存读取器，避免长时间占用进程。"""
        if self._reader is not None:
            try:
                self._reader.detach() # type: ignore
            except Exception:
                pass
            self._reader = None

class ItemAchievement(BaseAchievement):
    
    """根据已拥有道具集合判定的成就。"""
    def __init__(self, ach_id: str, name: str, description: str, item_id: int):
        """初始化成就元数据与进度状态。"""
        super().__init__(ach_id, name, description)
        self.item_id = item_id

    def check(self, owned_items: set[int]) -> bool:
        """根据外部事件/当前状态判断是否解锁，返回是否已解锁。"""
        if self.item_id in owned_items and not self.unlocked:
            self.mark_unlocked()
        return self.unlocked

class BattleAchievement(BaseAchievement):
    
    """统计战斗次数（可选死亡标记）判定的成就。"""
    def __init__(self, ach_id: str, name: str, description: str, 
                 target_count: int = 1, track_deaths: bool = True):
        """初始化成就元数据与进度状态。"""
        super().__init__(ach_id, name, description)
        self.target_count = target_count
        self.track_deaths = track_deaths
        self._battle_count = 0
        self._deaths_detected = False

    def reset_state(self):
        """重置本轮战斗计数与死亡标记。"""
        self._battle_count = 0
        self._deaths_detected = False
        self.progress = 0

    def record_battle_end(self):
        """记录一次战斗结束并更新进度。"""
        self._battle_count += 1
        self.progress = min(self._battle_count, self.max_progress)

    def record_death(self):
        """记录一次死亡（仅 track_deaths=True 时生效）。"""
        if self.track_deaths:
            self._deaths_detected = True

    def check(self, battle_count: int = 0, deaths: bool = False) -> bool:
        """根据外部事件/当前状态判断是否解锁，返回是否已解锁。"""
        if self._battle_count >= self.target_count and not self.unlocked:
            if self.track_deaths and self._deaths_detected:
                return False
            self.mark_unlocked()
        elif not self.track_deaths and battle_count >= self.target_count and not self.unlocked:
            self.mark_unlocked()
        
        return self.unlocked

class SteamAchievement(BaseAchievement):
    
    """Steam 登录类成就。"""
    def __init__(self, ach_id: str, name: str, description: str, rarity: str = "common"):
        """初始化成就元数据与进度状态。"""
        super().__init__(ach_id, name, description, rarity)

    def check(self, steam_logged: bool = False) -> bool:
        """根据外部事件/当前状态判断是否解锁，返回是否已解锁。"""
        if steam_logged and not self.unlocked:
            self.mark_unlocked()
        return self.unlocked

class CollectionAchievement(BaseAchievement):
    
    """收集指定数量道具类成就。"""
    def __init__(self, ach_id: str, name: str, description: str, 
                 required_count: int, item_ids: list[int] | None = None):
        """初始化成就元数据与进度状态。"""
        super().__init__(ach_id, name, description)
        self.required_count = required_count
        self.item_ids = item_ids or []
        self._collected_ids: set[int] = set()

    def add_collected(self, item_id: int):
        """记录一个已收集道具 id 并尝试解锁。"""
        self._collected_ids.add(item_id)
        self.progress = len(self._collected_ids)

    def check(self, owned_items: set[int]) -> bool:
        """根据外部事件/当前状态判断是否解锁，返回是否已解锁。"""
        if self.item_ids:
            newly_owned = owned_items & set(self.item_ids)
            self._collected_ids.update(newly_owned)
        else:
            self._collected_ids.update(owned_items)
        
        self.progress = len(self._collected_ids)
        
        if self.progress >= self.required_count and not self.unlocked:
            self.mark_unlocked()
        return self.unlocked

class HiddenAchievement(BaseAchievement):
    """隐藏成就：未解锁时隐藏描述，解锁条件由外部函数提供。"""

    def __init__(self, ach_id: str, name: str, description: str, 
                 check_func, hidden: bool = True):
        """初始化成就元数据与进度状态。"""
        super().__init__(ach_id, name, description)
        self._check_func = check_func
        self.hidden = hidden

    def check(self, *args, **kwargs) -> bool:
        """根据外部事件/当前状态判断是否解锁，返回是否已解锁。"""
        if self._check_func(*args, **kwargs) and not self.unlocked:
            self.mark_unlocked()
        return self.unlocked
