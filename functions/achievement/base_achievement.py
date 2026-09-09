"""基础成就类 - 所有具体成就都从此类继承。"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Callable


class BaseAchievement(ABC):
    """所有成就定义的基类。
    
    子类应实现 `check()` 方法来定义
    解锁此成就的特定条件。
    """

    def __init__(self, ach_id: str, name: str, description: str):
        self.ach_id = ach_id
        self.id = ach_id  # 与函数式 Achievement 使用相同的标识字段
        self.name = name
        self.description = description
        self.rarity = "common"
        self.unlocked = False
        self.unlock_time: datetime | None = None
        self.progress = 0
        self.max_progress = 1

    @abstractmethod
    def check(self) -> bool:
        """检查此成就是否应该被解锁。
        
        返回:
            如果成就条件满足则返回True，否则返回False。
        """
        pass

    def mark_unlocked(self):
        """将此成就标记为已解锁并记录时间。"""
        if not self.unlocked:
            self.unlocked = True
            self.unlock_time = datetime.now()
            self.progress = self.max_progress

    def is_unlocked(self) -> bool:
        """检查此成就是否已被解锁。"""
        return self.unlocked

    def get_progress(self) -> int:
        """获取当前进度（0到max_progress）。"""
        return self.progress

    def get_status_text(self) -> str:
        """获取显示状态文本。"""
        if self.unlocked:
            return f"✅ {self.name}"
        else:
            return f"⬜ {self.name}"


class MemoryAchievement(BaseAchievement):
    """基于游戏进程内存状态的成就。"""

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

    def check(self) -> bool:
        """读取内存并检查条件。读取失败时保持未解锁。"""
        if self.unlocked:
            return True
        try:
            if self._reader is None:
                self._reader = self._reader_factory()
            value = self._reader.read_enkephalin()
            self.current_value = value
            if value is not None and self._predicate(value):
                self.mark_unlocked()
        except Exception:
            self.current_value = None
        return self.unlocked

    def detach(self) -> None:
        """释放进程句柄。"""
        if self._reader is not None:
            try:
                self._reader.detach()
            except Exception:
                pass
            self._reader = None


class ItemAchievement(BaseAchievement):
    """检查特定物品ID是否被拥有的成就。"""
    
    def __init__(self, ach_id: str, name: str, description: str, item_id: int):
        super().__init__(ach_id, name, description)
        self.item_id = item_id

    def check(self, owned_items: set[int]) -> bool:
        """检查所需物品是否被拥有。
        
        参数:
            owned_items: 玩家拥有的物品ID集合
            
        返回:
            如果物品被拥有则返回True
        """
        if self.item_id in owned_items and not self.unlocked:
            self.mark_unlocked()
        return self.unlocked


class BattleAchievement(BaseAchievement):
    """追踪战斗相关进度的成就。"""
    
    def __init__(self, ach_id: str, name: str, description: str, 
                 target_count: int = 1, track_deaths: bool = True):
        super().__init__(ach_id, name, description)
        self.target_count = target_count
        self.track_deaths = track_deaths
        self._battle_count = 0
        self._deaths_detected = False

    def reset_state(self):
        """重置战斗追踪状态（在开始新游戏时调用）。"""
        self._battle_count = 0
        self._deaths_detected = False
        self.progress = 0

    def record_battle_end(self):
        """记录一场战斗结束。"""
        self._battle_count += 1
        self.progress = min(self._battle_count, self.max_progress)

    def record_death(self):
        """记录一个角色死亡。"""
        if self.track_deaths:
            self._deaths_detected = True

    def check(self, battle_count: int = 0, deaths: bool = False) -> bool:
        """检查战斗相关成就条件是否满足。
        
        参数:
            battle_count: 当前总战斗次数
            deaths: 是否发生角色死亡
            
        返回:
            如果条件满足则返回True
        """
        if self._battle_count >= self.target_count and not self.unlocked:
            # 如果追踪死亡，还需要检查死亡条件
            if self.track_deaths and self._deaths_detected:
                # 追踪到死亡 - 如果发生死亡则无法获得成就
                return False
            self.mark_unlocked()
        elif not self.track_deaths and battle_count >= self.target_count and not self.unlocked:
            self.mark_unlocked()
        
        return self.unlocked


class SteamAchievement(BaseAchievement):
    """追踪Steam登录状态的成就。"""
    
    def __init__(self, ach_id: str, name: str, description: str):
        super().__init__(ach_id, name, description)

    def check(self, steam_logged: bool = False) -> bool:
        """检查Steam登录条件是否满足。
        
        参数:
            steam_logged: 是否成功登录Steam
            
        返回:
            如果Steam已登录则返回True
        """
        if steam_logged and not self.unlocked:
            self.mark_unlocked()
        return self.unlocked


class CollectionAchievement(BaseAchievement):
    """追踪收藏进度的成就（例如，物品数量）。"""
    
    def __init__(self, ach_id: str, name: str, description: str, 
                 required_count: int, item_ids: list[int] | None = None):
        super().__init__(ach_id, name, description)
        self.required_count = required_count
        self.item_ids = item_ids or []
        self._collected_ids: set[int] = set()

    def add_collected(self, item_id: int):
        """将物品ID添加到已收藏集合中。"""
        self._collected_ids.add(item_id)
        self.progress = len(self._collected_ids)

    def check(self, owned_items: set[int]) -> bool:
        """检查收藏条件是否满足。
        
        参数:
            owned_items: 当前拥有的物品ID集合
            
        返回:
            如果达到所需数量则返回True
        """
        # 从当前拥有的物品更新已收藏集合
        if self.item_ids:
            # 只计算指定的物品
            newly_owned = owned_items & set(self.item_ids)
            self._collected_ids.update(newly_owned)
        else:
            # 计算所有拥有的物品
            self._collected_ids.update(owned_items)
        
        self.progress = len(self._collected_ids)
        
        if self.progress >= self.required_count and not self.unlocked:
            self.mark_unlocked()
        return self.unlocked


class HiddenAchievement(BaseAchievement):
    """可以隐藏的成就（在解锁之前不在UI中显示）。"""
    
    def __init__(self, ach_id: str, name: str, description: str, 
                 check_func, hidden: bool = True):
        super().__init__(ach_id, name, description)
        self._check_func = check_func
        self.hidden = hidden

    def check(self, *args, **kwargs) -> bool:
        """使用提供的回调函数进行检查。"""
        if self._check_func(*args, **kwargs) and not self.unlocked:
            self.mark_unlocked()
        return self.unlocked