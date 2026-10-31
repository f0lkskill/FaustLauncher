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

    # 3) 一个单位的「全部属性」
    print(objects.unit(host, 0).scan())

    # 4) 全局场景
    print(objects.scene(host))     # {'scene': 1, 'time_scale': 1.0}

**为什么不用钩子读血**：``units()``/``snapshot()`` 走的是「命令通道代读」，
按需往返，不占钩子槽、不需要 DLL 重装、随时能调。真机一次往返约 20–40 ms，
3 个单位 × 4 个字段 ≈ 0.5 s，做低频采样完全够。要是需要「每帧变化的瞬间
值」（比如伤害弹出），那才该装 ``reads=`` 的钩子 —— 那是另一条路，底层接口
一直在。

**一键不等于只有一键**：``scan()`` 是「把字段表里这一类能读的全读一遍」，
一个单位 60 多个字段、每个字段一次往返，整场扫下来要十几秒 —— 调试和摸底
用它，真跑业务请只读你关心的那几个（``u.hp()`` 之类）。

对象槽是共享资源：0..31 里主段被成就观测占了几个，插件请用 24..31，
本项目自己的测试也用这一段。
"""

import time

from . import fields
from .host import HOST_OBJECT_COUNT

# 对象槽分配：24..31 留给插件/诊断（主段 0..23 是成就观测在用）
# 注意 29/30/31 是宿主保留位：
#   29 = 命令泵每帧顺手缓存的 GlobalGameManager 单例
#   30 = 每帧回调魔法值 "SKT1"、31 = 每帧回调函数指针
SLOT_MANAGER = 28   # BattleObjectManager 单例
SLOT_SCENE = 29     # GlobalGameManager 单例（宿主已缓存，别自己钩 FixedUpdate）
SLOT_SCRATCH = 27   # 临时抓取（避开 29/30/31 保留位）

_MANAGER_DICT = fields.field("BattleObjectManager", "_allUnitDictionary")["off"]
_UNIT_MODEL = fields.field("BattleUnit", "_model")["off"]
_MODEL_STATE = fields.field("BattleUnitModel", "_state")["off"]
_MODEL_BUFF = fields.field("BattleUnitModel", "_buffDetail")["off"]
_BUFF_LIST = fields.field("BuffDetail", "list")["off"]
_BUFF_STATIC = fields.field("BuffModel", "_staticData")["off"]
_BUFF_NAME = fields.field("BuffStaticData", "name")["off"]

# 容器字段当读链末端时，落点要换成「数/g个数」，而不是容器步本身。
_END_KIND = {
    fields.LIST: "count",
    fields.ARRAY: "count",
    fields.DICT: "dict_count",
    fields.TEXT: "text",
}


def _end_kind(record):
    """字段记录 → 落到链末端时该用的 kind。"""
    return _END_KIND.get(record["kind"], record["kind"])


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

    # ---- 底层：自己拼链 ----
    def read(self, *chain, kind="int", default=None, timeout=2.0):
        """从**这个单位对象**（BattleUnit）出发读，链自己拼。

        ``u.read({"off": 0x10, "deref": True}, {"off": 0x60, "deref": False})``
        """
        return self.host.read(self.slot, self._prefix + list(chain), kind=kind,
                              default=default, timeout=timeout)

    def _read(self, *path, **kwargs):
        spec = fields.unit_path(*path)
        return self.read(*spec["off"], kind=spec["kind"],
                         default=kwargs.get("default"),
                         timeout=kwargs.get("timeout", 2.0))

    def _model_prefix(self):
        return self._prefix + [{"off": _UNIT_MODEL, "deref": True}]

    # ---- 常用属性 ----
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
        """还活着吗：优先看 ``_isDead``（加密布尔），读不到就退回 ``hp > 0``。"""
        dead = self._read("_model", "_state", "_isDead", default=None)
        if dead is not None:
            return dead == 0
        hp = self.hp()
        return None if hp is None else hp > 0

    def is_panic(self):
        """恐慌（理智归零后的失控状态）。"""
        return self._read("_model", "_state", "_isPanic")

    def is_break(self):
        """混乱/崩溃。"""
        return self._read("_model", "_state", "_isBreak")

    def is_low_morale(self):
        return self._read("_model", "_state", "_isLowMorale")

    def hp_ratio(self):
        """血量比例（0..1），两个字段都读到才算得出来。"""
        hp, mx = self.hp(), self.max_hp()
        if hp is None or not mx:
            return None
        return hp / float(mx)

    def buff_count(self):
        """身上有几个 buff（BuffDetail.list 的元素数）。"""
        chain = self._prefix + [{"off": _UNIT_MODEL, "deref": True},
                                {"off": _MODEL_BUFF, "deref": True},
                                {"off": _BUFF_LIST, "deref": True}]
        return self.host.read(self.slot, chain, kind="count", default=0)

    def buff_id(self, i):
        """第 i 个 buff 的**名字指纹**（il2cpp string 的哈希，不是原文）。

        这条路已经用满 8 跳：unit → model → buffDetail → list → [i] →
        staticData → name。想要原文得等宿主支持「读 UTF-16 文本」。
        """
        chain = self._prefix + [{"off": _UNIT_MODEL, "deref": True},
                                {"off": _MODEL_BUFF, "deref": True},
                                {"off": _BUFF_LIST, "deref": True},
                                {"list": int(i)},
                                {"off": _BUFF_STATIC, "deref": True},
                                {"off": _BUFF_NAME, "deref": False}]
        return self.host.read(self.slot, chain, kind="text")

    def buff_ids(self):
        """全部 buff 的名字指纹列表。"""
        return [self.buff_id(i) for i in range(self.buff_count() or 0)]

    # ---- 全字段扫描 ----
    def scan(self, classes=("BattleUnitModel", "CharacterState"), timeout=1.0):
        """按字段表把这一类能读的**全部**字段读一遍，返回 ``{字段名: 值}``。

        每个字段一次往返，慢但全 —— 摸底/调试用。读不到的字段是 ``None``
        （通常是偏移不对，或者那是还没验证过的条目）。
        """
        out = {}
        base = self._model_prefix()
        out.update(_scan_fields(self.host, self.slot, base, "BattleUnitModel",
                                timeout=timeout))
        if "CharacterState" in classes:
            state_base = base + [{"off": _MODEL_STATE, "deref": True}]
            out.update(_scan_fields(self.host, self.slot, state_base,
                                    "CharacterState", timeout=timeout))
        return out

    def state(self):
        """一次拿齐常用字段，返回 dict（每个字段仍是一次往返）。"""
        return {
            "index": self.index,
            "instance_id": self.instance_id(),
            "origin_id": self.origin_id(),
            "hp": self.hp(),
            "max_hp": self.max_hp(),
            "mp": self.mp(),
            "speed": self.speed(),
            "alive": self.alive(),
            "panic": self.is_panic(),
            "break": self.is_break(),
            "buffs": self.buff_count(),
        }


def _scan_fields(host, slot, base, cls, timeout=1.0):
    """在 ``base`` 这个已经指到对象上的链前缀之后，把 ``cls`` 的字段全读一遍。"""
    out = {}
    for name, record in fields.FIELD_TABLE.get(cls, {}).items():
        chain = list(base) + [{"off": record["off"], "deref": False}]
        out[name] = host.read(slot, chain, kind=_end_kind(record),
                              default=None, timeout=timeout)
    return out


def scan_class(host, slot, cls, timeout=1.0):
    """对象槽里那个对象如果是 ``cls``，把它的字段全读一遍。"""
    return _scan_fields(host, slot, [], cls, timeout=timeout)


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
    """整场扫一遍，返回 ``[{'index','instance_id','hp',...}]``。

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
    # 只要 cache，不要事件：抓单例不需要往事件环里塞东西，塞了反而会跟
    # 真正关心命中的插件抢环位（事件环是单 tail，多消费者会互吃）。
    hooks.append({"klass": klass, "method": method, "argc": int(argc),
                  "cache": (0, int(slot))})
    _push_hooks(host, hooks)
    deadline = time.time() + float(timeout)
    while time.time() < deadline:
        if host.object_ptr(slot):
            return int(slot)
        time.sleep(0.05)
    return None


def bind_scene(host, klass="GlobalGameManager", method="FixedUpdate", argc=0,
               slot=SLOT_SCENE, timeout=10.0):
    """等宿主把 GlobalGameManager 单例缓存好，返回槽号。

    由 DLL 的命令泵在它自己那条 FixedUpdate 钩子里每帧顺手写槽 29，所以
    **不要**再自己装一条 ``GlobalGameManager.FixedUpdate`` 钩子：那是命令泵
    的入口，抢了它 pump 装不上，``CMD_READ``（也就是 ``host.read``）整个失效
    —— v0.9.9 真机实测日志 ``pump: no free entry point, cmd channel off``。
    这里只等，不装钩子。
    """
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


def scene_full(host, slot=SLOT_SCENE, timeout=1.0):
    """GlobalGameManager 的全部已知字段（含场景名、加载状态、平台）。"""
    return scan_class(host, slot, "GlobalGameManager", timeout=timeout)


SCENES = {0: "登录", 1: "战斗", 2: "主界面", 3: "剧情", 4: "地牢",
          5: "镜像地牢", 6: "铁路", 7: "剧情镜像", 8: "ProjectGS", 9: "Rpg"}


def scene_name(value):
    """场景枚举 → 中文名（未知返回 ``?n``）。"""
    return SCENES.get(value, f"?{value}")
