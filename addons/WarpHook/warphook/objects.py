"""把游戏里的对象包成 Python 对象：一键读，不用记偏移、不用拼链。

底层那套（``hook(reads=...)`` / ``Host.read(slot, chain)`` / 字段表
``fields``）一个都没藏起来，想自己拼链随时可以；这里只是把最常用的几件事
做成一脚油门：

    from warphook import objects

    # 1) 抓单例：装一条钩子把 BattleObjectManager 存进对象槽 28
    bom = objects.bind_manager(host, timeout=120)

    # 2) 全场单位，一次拿齐
    for u in objects.units(host, bom):
        print(u.index, u.instance_id(), u.hp(), "/", u.max_hp(),
              "理智", u.mp(), "速度", u.speed())

    # 3) 全局场景
    print(objects.scene(host))     # {'scene': 1, 'time_scale': 1.0}

**为什么不用钩子读血**：``units()``/``snapshot()`` 走的是「命令通道代读」，
按需往返，不占钩子槽、不需要 DLL 重装、随时能调。真机一次往返约 20–40 ms，
3 个单位 × 4 个字段 ≈ 0.5 s，做低频采样完全够。要是需要「每帧变化的瞬间
值」（比如伤害弹出），那才该装 ``reads=`` 的钩子 —— 那是另一条路，底层接口
一直在。

对象槽是共享资源：0..31 里主段被成就观测占了几个，插件请用 24..31，
本项目自己的测试也用这一段。
"""

import time

from . import fields
from .host import HOST_OBJECT_COUNT

# 对象槽分配：24..31 留给插件/诊断（主段 0..23 是成就观测在用）
SLOT_MANAGER = 28   # BattleObjectManager 单例
SLOT_SCENE = 29     # GlobalGameManager 单例
SLOT_SCRATCH = 30   # 临时抓取

_MANAGER_DICT = fields.field("BattleObjectManager", "_allUnitDictionary")["off"]


class Unit:
    """一个战场单位的门面。

    背后是「对象槽 28 里的 manager → 字典第 index 个 value → 字段」，每次
    属性访问都是一次 DLL 代读（约 20–40 ms）。要一次拿很多字段用
    :func:`snapshot`，它把整场扫一遍给你字典列表。
    """

    __slots__ = ("host", "slot", "index", "_prefix")

    def __init__(self, host, slot, index):
        self.host = host
        self.slot = int(slot)
        self.index = int(index)
        # 前缀：manager +0x90 → Dictionary → 第 index 个活跃 value（BattleUnit）
        self._prefix = [{"off": _MANAGER_DICT, "deref": True},
                        {"dict": self.index}]

    def __repr__(self):
        return f"<Unit #{self.index} id={self.instance_id()}>"

    def _read(self, *path, **kwargs):
        spec = fields.unit_path(*path)
        chain = self._prefix + spec["off"]
        return self.host.read(self.slot, chain, kind=spec["kind"],
                              default=kwargs.get("default"),
                              timeout=kwargs.get("timeout", 2.0))

    def instance_id(self):
        """单位唯一 id（小整数，1/2/3…）。"""
        return self._read("_model", "_instanceID")

    def origin_id(self):
        return self._read("_model", "_originID")

    def hp(self):
        """当前血量（ObscuredInt，已解混淆）。"""
        return self._read("_model", "_state", "_hp")

    def max_hp(self):
        return self._read("_model", "_state", "_maxHp")

    def mp(self):
        """理智 SP，负数表示恐慌。"""
        return self._read("_model", "_state", "_mp")

    def speed(self):
        """原始速度（定点 ×1000，5 速读到 5000，这里除回 1000）。"""
        raw = self._read("_model", "_originSpeed")
        return None if raw is None else raw / 1000.0

    def alive(self):
        hp = self.hp()
        return None if hp is None else hp > 0

    def state(self):
        """一次拿齐常用字段，返回 dict（每个字段仍是一次往返）。"""
        return {
            "index": self.index,
            "instance_id": self.instance_id(),
            "hp": self.hp(),
            "max_hp": self.max_hp(),
            "mp": self.mp(),
            "speed": self.speed(),
        }


def count(host, slot=SLOT_MANAGER):
    """场上单位总数（字典 count - freeCount，已跳过 Remove 留下的死坑）。"""
    return host.read(slot, [{"off": _MANAGER_DICT, "deref": True}],
                     kind="dict_count", default=0)


def unit(host, index, slot=SLOT_MANAGER):
    """按序号取一个单位门面（序号是「活跃 value 的第几个」，不是它的 id）。"""
    return Unit(host, slot, index)


def units(host, slot=SLOT_MANAGER, limit=None):
    """全场单位列表。``limit`` 用来只取前几个（读得慢，先探路用）。"""
    total = count(host, slot=slot) or 0
    if limit is not None:
        total = min(total, int(limit))
    return [Unit(host, slot, i) for i in range(total)]


def snapshot(host, slot=SLOT_MANAGER, limit=None):
    """整场扫一遍，返回 ``[{'index','instance_id','hp','max_hp','mp','speed'}]``。

    适合「每 0.5–1 秒看一眼战况」这种用法。要「变化的一瞬间」请装钩子。
    """
    return [u.state() for u in units(host, slot=slot, limit=limit)]


def bind_manager(host, klass="BattleObjectManager", method="OnRoundStart_Model",
                 argc=1, slot=SLOT_MANAGER, timeout=180.0, extra_hooks=()):
    """装一条钩子，把 BattleObjectManager 单例抓进对象槽，返回槽号。

    回合级方法（OnRoundStart_Model）只在回合开始触发，所以**得先打一回合**
    才会有值；返回前一直等到槽里有指针或者超时（超时返回 None）。

    已有钩子把 manager 缓存好的话不用调这个，直接 ``objects.units(host, 那个槽)``。
    """
    hooks = list(extra_hooks)
    hooks.append({"klass": klass, "method": method, "argc": int(argc),
                  "cache": (0, int(slot)), "event": 0})
    _push_hooks(host, hooks)
    deadline = time.time() + float(timeout)
    while time.time() < deadline:
        if host.object_ptr(slot):
            return int(slot)
        time.sleep(0.05)
    return None


def bind_scene(host, klass="GlobalGameManager", method="FixedUpdate", argc=0,
               slot=SLOT_SCENE, timeout=180.0):
    """抓 GlobalGameManager 单例（它每帧 FixedUpdate，命中最快）。"""
    hooks = [{"klass": klass, "method": method, "argc": int(argc),
              "cache": (0, int(slot)), "event": 0}]
    _push_hooks(host, hooks)
    deadline = time.time() + float(timeout)
    while time.time() < deadline:
        if host.object_ptr(slot):
            return int(slot)
        time.sleep(0.05)
    return None


def _push_hooks(host, hooks):
    """把钩子表推给宿主：``configure`` 改内存里的表，``push`` 才写进共享内存。"""
    host.configure(hooks=hooks)
    host.push()
    return True


def scene(host, slot=SLOT_SCENE):
    """读全局状态：``{'scene': 1, 'time_scale': 1.0, 'scene_entries': N}``。"""
    spec_scene = fields.read_chain("GlobalGameManager", "sceneState")
    spec_scale = fields.read_chain("GlobalGameManager", "_currentTimeScale")
    spec_entries = fields.read_chain("GlobalGameManager", "_mainSceneEntryCount")
    return {
        "scene": host.read(slot, spec_scene["off"], kind=spec_scene["kind"]),
        "time_scale": host.read(slot, spec_scale["off"], kind=spec_scale["kind"]),
        "scene_entries": host.read(slot, spec_entries["off"],
                                   kind=spec_entries["kind"]),
    }


SCENES = {0: "登录", 1: "战斗", 2: "主界面", 3: "剧情", 4: "地牢",
          5: "镜像地牢", 6: "铁路", 7: "剧情镜像", 8: "ProjectGS", 9: "Rpg"}


def scene_name(value):
    """场景枚举 → 中文名（未知返回 ``?n``）。"""
    return SCENES.get(value, f"?{value}")
