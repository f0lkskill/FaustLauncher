
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Callable
import threading

class BaseAchievement(ABC):

    def __init__(self, ach_id: str, name: str, description: str, rarity: str = "common"):
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
        pass

    def with_rarity(self, rarity: str):
        self.rarity = str(rarity or "common")
        return self

    def mark_unlocked(self):
        if not self.unlocked:
            self.unlocked = True
            self.unlock_time = datetime.now()
            self.progress = self.max_progress

    def is_unlocked(self) -> bool:
        return self.unlocked

    def get_progress(self) -> int:
        return self.progress

    def get_status_text(self) -> str:
        if self.unlocked:
            return f"✅ {self.name}"
        else:
            return f"⬜ {self.name}"

class MemoryAchievement(BaseAchievement):

    memory_driven = True

    def __init__(
        self,
        ach_id: str,
        name: str,
        description: str,
        reader_factory: Callable[[], object],
        predicate: Callable[[int], bool],
    ):
        super().__init__(ach_id, name, description)
        self._reader_factory = reader_factory
        self._predicate = predicate
        self._reader = None
        self.current_value: int | None = None
        self._read_lock = threading.Lock()

    def check(self) -> bool:
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
        if self._reader is not None:
            try:
                self._reader.detach() # type: ignore
            except Exception:
                pass
            self._reader = None

class ItemAchievement(BaseAchievement):
    
    def __init__(self, ach_id: str, name: str, description: str, item_id: int):
        super().__init__(ach_id, name, description)
        self.item_id = item_id

    def check(self, owned_items: set[int]) -> bool:
        if self.item_id in owned_items and not self.unlocked:
            self.mark_unlocked()
        return self.unlocked

class BattleAchievement(BaseAchievement):
    
    def __init__(self, ach_id: str, name: str, description: str, 
                 target_count: int = 1, track_deaths: bool = True):
        super().__init__(ach_id, name, description)
        self.target_count = target_count
        self.track_deaths = track_deaths
        self._battle_count = 0
        self._deaths_detected = False

    def reset_state(self):
        self._battle_count = 0
        self._deaths_detected = False
        self.progress = 0

    def record_battle_end(self):
        self._battle_count += 1
        self.progress = min(self._battle_count, self.max_progress)

    def record_death(self):
        if self.track_deaths:
            self._deaths_detected = True

    def check(self, battle_count: int = 0, deaths: bool = False) -> bool:
        if self._battle_count >= self.target_count and not self.unlocked:
            if self.track_deaths and self._deaths_detected:
                return False
            self.mark_unlocked()
        elif not self.track_deaths and battle_count >= self.target_count and not self.unlocked:
            self.mark_unlocked()
        
        return self.unlocked

class SteamAchievement(BaseAchievement):
    
    def __init__(self, ach_id: str, name: str, description: str, rarity: str = "common"):
        super().__init__(ach_id, name, description, rarity)

    def check(self, steam_logged: bool = False) -> bool:
        if steam_logged and not self.unlocked:
            self.mark_unlocked()
        return self.unlocked

class CollectionAchievement(BaseAchievement):
    
    def __init__(self, ach_id: str, name: str, description: str, 
                 required_count: int, item_ids: list[int] | None = None):
        super().__init__(ach_id, name, description)
        self.required_count = required_count
        self.item_ids = item_ids or []
        self._collected_ids: set[int] = set()

    def add_collected(self, item_id: int):
        self._collected_ids.add(item_id)
        self.progress = len(self._collected_ids)

    def check(self, owned_items: set[int]) -> bool:
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
    
    def __init__(self, ach_id: str, name: str, description: str, 
                 check_func, hidden: bool = True):
        super().__init__(ach_id, name, description)
        self._check_func = check_func
        self.hidden = hidden

    def check(self, *args, **kwargs) -> bool:
        if self._check_func(*args, **kwargs) and not self.unlocked:
            self.mark_unlocked()
        return self.unlocked
