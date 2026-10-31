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
_BUFF_ID = fields.field("BuffStaticData", "id")["off"]
_BUFF_INFO = fields.field("BuffModel", "_buffInfo")["off"]

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


# ObscuredBool 解码出来的「假」码。
# 真机 11 个单位对照：_isDead/_isBreak/_isPanic 全是 0xB5（都没死/没混乱），
# _isActivated 全是 0xD5（都激活）→ 0xB5 是假、其余是真。
BOOL_FALSE = 0xB5

# 好记的名字 → dump 里的字段名（get_pro / get_obj 用得上）
_FIELD_ALIAS = {
    "id": "_instanceID", "instance_id": "_instanceID", "iid": "_instanceID",
    "origin_id": "_originID", "identity": "_originID", "personality": "_originID",
    "hp": "_hp", "max_hp": "_maxHp", "sp": "_mp", "mp": "_mp", "san": "_mp",
    "speed": "_originSpeed", "overwrite_speed": "_overwritedSpeed",
    "dead": "_isDead", "is_dead": "_isDead",
    "panic": "_isPanic", "is_panic": "_isPanic",
    "break": "_isBreak", "is_break": "_isBreak",
    "low_morale": "_isLowMorale", "is_low_morale": "_isLowMorale",
    "position": "_position", "state": "_state", "buff_detail": "_buffDetail",
}


def _utf16(rd, addr, limit=256):
    """读 il2cpp string 的原文：``+0x10`` 是长度，``+0x14`` 起是 UTF-16 字符。"""
    if not addr:
        return None
    n = rd.i32(addr + 0x10)
    if n is None or n < 0 or n > int(limit):
        return None
    raw = rd.read(addr + 0x14, n * 2)
    if not raw:
        return None
    return raw.decode("utf-16-le", "replace")


class Buff:
    """一个 buff 的门面：名字、层数（强度）、剩余次数。

    层数/次数走 ``CMD_READ`` 代读（``BuffInfo._stack@0x6C`` /
    ``_turn@0x70``）；**名字原文**是 il2cpp string，命令通道只回 32 位读不
    了，所以要走一次跨进程读（:class:`Access` 持有那个读句柄）。拿不到
    读句柄时 ``name`` 返回 ``None``，其余字段照常可用。
    """

    __slots__ = ("unit", "index")

    def __init__(self, unit, index):
        self.unit = unit
        self.index = int(index)

    def __repr__(self):
        return f"<Buff #{self.index} {self.key or self.name!r} stack={self.stack} turn={self.turn}>"

    def _read(self, off, default=None):
        return self.unit.host.read(self.unit.slot,
                                   self.unit._buff_chain(self.index, off),
                                   kind="int", default=default)

    def _static(self):
        """``(reader, BuffStaticData 指针)``；拿不到返回 ``(None, 0)``。"""
        acc = self.unit._acc
        if acc is None:
            return None, 0
        rd = acc.reader()
        if rd is None:
            return None, 0
        return rd, acc.buff_static_ptr(self.unit.index, self.index)

    @property
    def key(self):
        """**英文 ID**（``BuffStaticData.id``），如 ``"Breath"``/``"Combustion"``。

        这是插件里应该用来判断 buff 的稳定标识；``name`` 是给人看的中文。
        读不到读句柄时返回 ``None``。
        """
        rd, data = self._static()
        if not rd or not data:
            return None
        return _utf16(rd, rd.u64(data + 0x18))

    @property
    def icon(self):
        """图标资源 ID（如 ``"UnlockBuff_3"``），可能为 ``None``。"""
        rd, data = self._static()
        if not rd or not data:
            return None
        return _utf16(rd, rd.u64(data + 0x38))

    @property
    def type_id(self):
        """``BUFF_UNIQUE_KEYWORD`` 枚举值（``BuffStaticData._id@0x20``）。"""
        rd, data = self._static()
        if not rd or not data:
            return None
        return rd.i32(data + 0x20)

    @property
    def name(self):
        """buff 名字原文（中文），读不到返回 ``None``。"""
        acc = self.unit._acc
        if acc is None:
            return None
        rd = acc.reader()
        if rd is None:
            return None
        info = acc.buff_info_ptr(self.unit.index, self.index)
        if not info:
            return None
        return _utf16(rd, rd.u64(info + 0x28))

    @property
    def stack(self):
        """强度/层数（界面上那个大数字）。"""
        return self._read(0x6C)

    @property
    def turn(self):
        """剩余次数/回合。"""
        return self._read(0x70)

    @property
    def max_stack(self):
        return self._read(0x64)

    @property
    def max_turn(self):
        return self._read(0x68)

    @property
    def stack_ratio(self):
        """当前层数 / 上限（0..1）。"""
        s, mx = self.stack, self.max_stack
        if s is None or not mx:
            return None
        return s / float(mx)

    def raw(self):
        return {"index": self.index, "key": self.key, "name": self.name,
                "icon": self.icon, "type_id": self.type_id,
                "stack": self.stack, "turn": self.turn,
                "max_stack": self.max_stack, "max_turn": self.max_turn}

    def has(self, key):
        """按英文 ID（``"Breath"``）或中文名（``"呼吸法"``）判断是不是这个 buff。"""
        k = str(key)
        return k in (self.key, self.name)


class Access:
    """场景访问器：``acc.units()`` / ``acc.get_obj(id=1)`` / ``acc.count()``。

    用 ``acc = objects.access(host)`` 拿一个；它自动保证 manager 已进对象槽
    （空就调一次静态 ``BattleObjectManager::get_Instance``，不需要钩子）。

    ``reader()`` 是懒加载的跨进程读句柄，只给 buff 名字这类「命令通道读不了
    的 64 位/文本」用；同一台机器上插件进程有权限直接读游戏内存。
    """

    def __init__(self, host, slot=SLOT_MANAGER, exe="LimbusCompany.exe", pid=None):
        self.host = host
        self.slot = int(slot)
        self.exe = exe
        self.pid = pid
        self._rd = None
        self._rd_failed = False

    # ---- 基础 ----
    def manager(self, timeout=3.0, force=False):
        """保证对象槽里有 manager 指针，返回它（失败 ``None``）。"""
        ptr = self.host.object_ptr(self.slot)
        if ptr and not force:
            return ptr
        try:
            self.host.call("BattleObjectManager::get_Instance",
                           ret="ref", out_slot=self.slot, timeout=timeout)
        except Exception:  # noqa: BLE001
            return self.host.object_ptr(self.slot)
        return self.host.object_ptr(self.slot)

    def count(self):
        return count(self.host, self.slot)

    def units(self, limit=None):
        total = self.count() or 0
        if limit is not None:
            total = min(total, int(limit))
        return [Unit(self.host, self.slot, i, acc=self) for i in range(total)]

    def get_obj(self, id=None, index=None):
        """按战斗内编号（``id=1``）或序号（``index=0``）取一个单位。"""
        if index is not None:
            return Unit(self.host, self.slot, int(index), acc=self)
        if id is None:
            return None
        for u in self.units():
            if u.id == int(id):
                return u
        return None

    def scene(self, slot=SLOT_SCENE):
        return scene(self.host, slot=slot)

    # ---- 跨进程读（只给名字这种读不了的东西用）----
    def reader(self):
        if self._rd is not None or self._rd_failed:
            return self._rd
        try:
            from . import remote
            pid = self.pid or remote.RemoteReader.by_process(self.exe)
            self._rd = remote.RemoteReader(pid) if pid else None
        except Exception:  # noqa: BLE001
            self._rd = None
        if self._rd is None:
            self._rd_failed = True
        return self._rd

    def unit_ptr(self, index):
        """序号 → BattleUnit 指针（跨进程读字典，给 buff 名字用）。"""
        rd = self.reader()
        if rd is None:
            return 0
        bom = self.host.object_ptr(self.slot)
        if not bom:
            return 0
        return rd.dict_nth(rd.u64(bom + _MANAGER_DICT), int(index)) or 0

    def buff_model_ptr(self, index, buff_index, unit_ptr=None):
        """序号 + buff 序号 → ``BuffModel`` 指针。"""
        rd = self.reader()
        if rd is None:
            return 0
        unit = unit_ptr or self.unit_ptr(index)
        if not unit:
            return 0
        model = rd.u64(unit + _UNIT_MODEL)
        if not model:
            return 0
        detail = rd.u64(model + _MODEL_BUFF)
        if not detail:
            return 0
        lst = rd.u64(detail + _BUFF_LIST)
        if not lst:
            return 0
        items = rd.u64(lst + 0x10)
        n = rd.i32(lst + 0x18) or 0
        if not items or not (0 <= int(buff_index) < n):
            return 0
        return rd.u64(items + 0x20 + int(buff_index) * 8) or 0

    def buff_info_ptr(self, index, buff_index, unit_ptr=None):
        """序号 + buff 序号 → ``BuffInfo`` 指针（层数/次数/显示名）。"""
        rd = self.reader()
        if rd is None:
            return 0
        bm = self.buff_model_ptr(index, buff_index, unit_ptr=unit_ptr)
        if not bm:
            return 0
        return rd.u64(bm + _BUFF_INFO) or 0

    def buff_static_ptr(self, index, buff_index, unit_ptr=None):
        """序号 + buff 序号 → ``BuffStaticData`` 指针（英文 ID / 图标 / 上限）。"""
        rd = self.reader()
        if rd is None:
            return 0
        bm = self.buff_model_ptr(index, buff_index, unit_ptr=unit_ptr)
        if not bm:
            return 0
        return rd.u64(bm + _BUFF_STATIC) or 0

    def close(self):
        if self._rd is not None:
            self._rd.close()
            self._rd = None


def access(host, slot=SLOT_MANAGER, **kwargs):
    """拿一个场景访问器（二次开发的主入口）。"""
    return Access(host, slot=slot, **kwargs)


class Unit:
    """一个战场单位的门面。

    背后是「对象槽 28 里的 manager → 字典第 index 个 value → 字段」，每次
    属性访问都是一次 DLL 代读（约 20–40 ms）。要一次拿很多字段用
    :func:`snapshot`，它把整场扫一遍给你字典列表。
    """

    __slots__ = ("host", "slot", "index", "_prefix", "_acc")

    def __init__(self, host, slot, index, acc=None):
        self.host = host
        self.slot = int(slot)
        self.index = int(index)
        self._acc = acc
        # 前缀：manager +0x90 → Dictionary → 第 index 个活跃 value（BattleUnit）
        self._prefix = [{"off": _MANAGER_DICT, "deref": True},
                        {"dict": self.index}]

    def __repr__(self):
        return f"<Unit #{self.index} id={self.id}>"

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

    def _state_prefix(self):
        return self._model_prefix() + [{"off": _MODEL_STATE, "deref": True}]

    # ---- 通用取值（不动就用它，字段名见 fields.FIELD_TABLE）----
    def get_pro(self, key, default=None):
        """按字段名取值，``key`` 可以是简名或带类名前缀的点路径。

        ``u.get_pro("origin_id")`` / ``u.get_pro("_hp")`` /
        ``u.get_pro("CharacterState._isPanic")`` / ``u.get_pro("_state._hp")``

        优先在 BattleUnitModel 里找，找不到再去它的 ``_state``（CharacterState）
        里找 —— 也就是「角色自己的字段」和「角色状态里的字段」都能一句拿到。
        """
        if not key:
            return default
        key = str(key)
        if key in _FIELD_ALIAS:
            key = _FIELD_ALIAS[key]
        parts = [p for p in key.replace(".", " ").split() if p]
        if len(parts) >= 2:
            # "CharacterState._hp" / "_state._hp"：第一段当类名或引用字段
            head, rest = parts[0], parts[1:]
            if head in fields.FIELD_TABLE:
                return self._get_from(head, rest, default)
            if head in fields.FIELD_TABLE.get("BattleUnitModel", {}):
                return self._get_from("BattleUnitModel", parts, default)
        if fields.has("BattleUnitModel", parts[0]) and len(parts) == 1:
            return self._get_from("BattleUnitModel", parts, default)
        if fields.has("CharacterState", parts[0]) and len(parts) == 1:
            return self._get_from("CharacterState", parts, default)
        return self._get_from("BattleUnitModel", parts, default)

    def _get_from(self, cls, path, default=None):
        try:
            spec = fields.read_chain(cls, *path)
        except KeyError:
            return default
        if cls == "BattleUnit":
            base = self._prefix
        elif cls == "CharacterState":
            base = self._model_prefix() + [{"off": _MODEL_STATE, "deref": True}]
        else:
            base = self._model_prefix()
        return self.host.read(self.slot, base + list(spec["off"]),
                              kind=spec["kind"], default=default)

    def _bool_code(self, base, off):
        """读 ObscuredBool 的**解码码**（一个字节），读不到 ``None``。

        ``+0`` 是 1 字节 key、``+4`` 是 int hiddenValue，真码 = ``hidden ^ key``。
        真机 11 个单位对照出来的取值：``0xB5`` 一律是假（都没死/没混乱），
        ``0xD5`` 是真（``_isActivated`` 在所有单位上都是这个码）。
        """
        key = self.host.read(self.slot, base + [{"off": int(off), "deref": False}],
                             kind="int", default=None)
        hid = self.host.read(self.slot, base + [{"off": int(off) + 4, "deref": False}],
                             kind="int", default=None)
        if key is None or hid is None:
            return None
        return (hid ^ (key & 0xFF)) & 0xFF

    def _bool_field(self, base, off):
        """把 ObscuredBool 解成 bool（``0xB5`` 假，其余真）。"""
        code = self._bool_code(base, off)
        return None if code is None else code != BOOL_FALSE

    def props(self, timeout=1.0):
        """把这个单位能读的字段全读一遍（BattleUnitModel + CharacterState）。"""
        out = {}
        out.update(_scan_fields(self.host, self.slot, self._model_prefix(),
                                "BattleUnitModel", timeout=timeout))
        out.update(_scan_fields(self.host, self.slot, self._state_prefix(),
                                "CharacterState", timeout=timeout))
        return out

    # ---- 常用属性（每次访问 = 一次 DLL 代读，约 20–40 ms）----
    @property
    def id(self):
        """战斗内编号（1/2/3…，敌人也有）。"""
        return self._read("_model", "_instanceID")

    @property
    def identity(self):
        """人格 ID（角色静态 id，浮士德 = 101xx）。:.Unit 的 originID。"""
        return self._read("_model", "_originID")

    origin_id = identity

    @property
    def hp(self):
        """当前血量（ObscuredInt，已解混淆）。"""
        return self._read("_model", "_state", "_hp")

    @property
    def max_hp(self):
        return self._read("_model", "_state", "_maxHp")

    @property
    def sp(self):
        """理智（SP），负数表示恐慌计数。"""
        return self._read("_model", "_state", "_mp")

    @property
    def speed(self):
        """原始速度（定点 ×1000，5 速读到 5000，这里除回 1000）。"""
        raw = self._read("_model", "_originSpeed")
        return None if raw is None else raw / 1000.0

    @property
    def is_dead(self):
        return self._bool_field(self._state_prefix(), 0x10)

    @property
    def is_panic(self):
        """恐慌（理智归零后的失控）。"""
        return self._bool_field(self._state_prefix(), 0x64)

    @property
    def is_break(self):
        """混乱（崩溃条被打满）。"""
        return self._bool_field(self._state_prefix(), 0x58)

    @property
    def is_low_morale(self):
        return self._bool_field(self._state_prefix(), 0x70)

    @property
    def alive(self):
        """还活着吗：优先看 ``_isDead``，读不到就退回 ``hp > 0``。"""
        dead = self.is_dead
        if dead is not None:
            return dead == 0
        hp = self.hp
        return None if hp is None else hp > 0

    @property
    def hp_ratio(self):
        """血量比例（0..1），两个字段都读到才算得出来。"""
        hp, mx = self.hp, self.max_hp
        if hp is None or not mx:
            return None
        return hp / float(mx)

    # ---- buff ----
    @property
    def buffs(self):
        """身上全部 buff，返回 :class:`Buff` 列表（含名字、层数、次数）。"""
        return [Buff(self, i) for i in range(self.buff_count())]

    def buff(self, key, default=None):
        """按序号、英文 ID 或中文名找一个 buff。

        ``u.buff(0)`` / ``u.buff("Breath")`` / ``u.buff("呼吸法")``
        """
        items = self.buffs
        if isinstance(key, int):
            return items[key] if 0 <= key < len(items) else default
        want = str(key)
        for b in items:
            if want in (b.name, b.key):
                return b
        return default

    def has_buff(self, key):
        """身上有没有某个 buff（英文 ID 或中文名）。"""
        return self.buff(key) is not None

    def buff_count(self):
        """身上有几个 buff（BuffDetail.list 的元素数）。"""
        chain = self._prefix + [{"off": _UNIT_MODEL, "deref": True},
                                {"off": _MODEL_BUFF, "deref": True},
                                {"off": _BUFF_LIST, "deref": True}]
        return self.host.read(self.slot, chain, kind="count", default=0)

    def buff_id(self, i):
        """第 i 个 buff 的**英文 ID 指纹**（``BuffStaticData.id`` 的哈希，不是原文）。

        要原文用 ``Unit.buffs[i].key``（走跨进程读）。这条路是纯命令通道
        版本，适合「只比较有没有变」的场合。
        """
        chain = self._prefix + [{"off": _UNIT_MODEL, "deref": True},
                                {"off": _MODEL_BUFF, "deref": True},
                                {"off": _BUFF_LIST, "deref": True},
                                {"list": int(i)},
                                {"off": _BUFF_STATIC, "deref": True},
                                {"off": _BUFF_ID, "deref": False}]
        return self.host.read(self.slot, chain, kind="text")

    def buff_ids(self):
        """全部 buff 的英文 ID 指纹列表。"""
        return [self.buff_id(i) for i in range(self.buff_count() or 0)]

    def _buff_chain(self, i, field_off):
        """unit → model → buffDetail → list → [i] → buffInfo → 字段，正好 8 跳。"""
        return self._prefix + [{"off": _UNIT_MODEL, "deref": True},
                               {"off": _MODEL_BUFF, "deref": True},
                               {"off": _BUFF_LIST, "deref": True},
                               {"list": int(i)},
                               {"off": _BUFF_INFO, "deref": True},
                               {"off": int(field_off), "deref": False}]

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
            "instance_id": self.id,
            "origin_id": self.identity,
            "hp": self.hp,
            "max_hp": self.max_hp,
            "sp": self.sp,
            "speed": self.speed,
            "alive": self.alive,
            "panic": self.is_panic,
            "break": self.is_break,
            "buffs": self.buff_count(),
        }


def _scan_fields(host, slot, base, cls, timeout=1.0):
    """在 ``base`` 这个已经指到对象上的链前缀之后，把 ``cls`` 的字段全读一遍。

    容器字段（List/Array/Dictionary）与文本字段要**先解引用**再落点：字段里
    存的是对象指针，不解引用就会拿指针当容器头去读，得到的永远是 0 或垃圾
    （0.9.9 真机踩过：``_allUnitDictionary`` 扫出 0，而 ``count()`` 扫出 11）。
    """
    out = {}
    for name, record in fields.FIELD_TABLE.get(cls, {}).items():
        deref = bool(record.get("ref")) and record["kind"] in (
            fields.LIST, fields.ARRAY, fields.DICT, fields.TEXT)
        chain = list(base) + [{"off": record["off"], "deref": deref}]
        out[name] = host.read(slot, chain, kind=_end_kind(record),
                              default=None, timeout=timeout)
    return out


def scan_class(host, slot, cls, timeout=1.0):
    """对象槽里那个对象如果是 ``cls``，把它的字段全读一遍。"""
    return _scan_fields(host, slot, [], cls, timeout=timeout)


def scan_object(host, slot, cls, base=(), timeout=1.0):
    """从对象槽出发先走一段 ``base`` 链，再把 ``cls`` 的字段全读一遍。

    ``scan_object(host, 27, "CharacterState",
                  base=[{"off": 0x148, "deref": True}])`` —— 槽 27 里是
    BattleUnitModel，先跳 ``_state`` 再扫 CharacterState。
    """
    return _scan_fields(host, slot, list(base), cls, timeout=timeout)


def count(host, slot=SLOT_MANAGER):
    """场上单位总数（字典 count - freeCount，已跳过 Remove 留下的死坑）。"""
    return host.read(slot, [{"off": _MANAGER_DICT, "deref": True}],
                     kind="dict_count", default=0)


def unit(host, index, slot=SLOT_MANAGER, acc=None):
    """按序号取一个单位门面（序号是「活跃 value 的第几个」，不是它的 id）。"""
    return Unit(host, slot, index, acc=acc or Access(host, slot))


def units(host, slot=SLOT_MANAGER, limit=None, acc=None):
    """全场单位列表。``limit`` 用来只取前几个（读得慢，先探路用）。"""
    acc = acc or Access(host, slot)
    total = count(host, slot=slot) or 0
    if limit is not None:
        total = min(total, int(limit))
    return [Unit(host, slot, i, acc=acc) for i in range(total)]


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
