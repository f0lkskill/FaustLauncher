"""已知 il2cpp 字段表：把「类名 + 字段名」翻译成读取链。

这里是**唯一**记偏移的地方。插件不该自己写 ``0x148``，那是 dump 期的数字，
游戏一版就可能变；写在这里的好处是变的时候只改一处，而且能一眼看出哪些
字段是真机验证过的、哪些只是照 dump 抄的。

三个入口：

``read_chain("BattleUnitModel", "_state", "_hp")``
    得到能直接塞进 ``reads=`` 或 ``Host.read()`` 的链元素列表，以及落点 kind::

        >>> spec = fields.read_chain("BattleUnitModel", "_state", "_hp")
        >>> spec["off"]
        [{'off': 336, 'deref': True}, {'off': 328, 'deref': False}]
        >>> spec["kind"]
        'obscured'

``kind_of("BattleUnitModel", "_state", "_hp")``
    只要落点 kind。

``field("CharacterState", "_hp")``
    原始记录（off / kind / ref / note / verified）。

**注意 Obscured 字段**：游戏用 ``ObscuredInt`` 把真值藏起来，布局是
``+0 key / +4 hidden / +8 fake``，真值 = ``hidden ^ key``。读的时候 kind 必须
写 ``obscured``，直接按 int 读会拿到 key 那一坨垃圾。血量、理智都在这类字段里。

「verified=False」的条目照 dump.cs 抄的、还没在真机上对过数，用之前先对一眼
（症状是「全 0」或者「数很大」，先怀疑偏移和尺寸）。
"""

# 落点 kind 与 C 侧 WARP_READ_* 同名，Host.read / reads= 直接用字符串。
INT = "int"
FLOAT = "float"
BOOL = "bool"
OBSCURED = "obscured"
LIST = "list"
ARRAY = "array"
DICT = "dict_count"

# ref 不为 None 表示这个字段是**对象引用**：中间步骤要 deref=True 跳过去；
# ref 为 None 表示是内嵌结构或标量，读到它就是值（或值类型容器）。

FIELD_TABLE = {
    # 单例，全局一份：拿全场单位从这里进。
    "BattleObjectManager": {
        "_currTeamPosition": {"off": 0x28, "ref": None, "kind": INT, "verified": False,
                              "note": "当前队伍的编号，不是坐标"},
        "_currEnemyTeamPosition": {"off": 0x30, "ref": None, "kind": INT, "verified": False},
        "_deadSceneList": {"off": 0x60, "ref": "List", "kind": LIST, "verified": True,
                           "note": "真机 count=0 时映证"},
        "_unitList": {"off": 0x78, "ref": "Dictionary", "kind": DICT, "verified": True,
                      "note": "Dictionary<UNIT_FACTION, List<BattleUnit>>，按阵营"},
        "_allUnitDictionary": {"off": 0x90, "ref": "Dictionary", "kind": DICT,
                               "verified": True,
                               "note": "Dictionary<int, BattleUnit>，全场单位；遍历主场"},
        "_deadUnitList": {"off": 0xB8, "ref": "List", "kind": LIST, "verified": False},
        "_roundDeathCount": {"off": 0xF4, "ref": None, "kind": INT, "verified": False},
    },
    # Dictionary 的 value 是 BattleUnit（壳），模型在 _model 里。
    "BattleUnit": {
        "_model": {"off": 0x10, "ref": "BattleUnitModel", "kind": INT, "verified": True},
        "_view": {"off": 0x18, "ref": None, "kind": INT, "verified": False},
        "_position": {"off": 0x20, "ref": None, "kind": FLOAT, "verified": False,
                      "note": "Vector3 内嵌，偏移和尺寸都得自己对"},
    },
    "BattleUnitModel": {
        "_instanceID": {"off": 0x60, "ref": None, "kind": INT, "verified": True,
                        "note": "1/2/3 这种小整数，真机对过"},
        "_originID": {"off": 0x64, "ref": None, "kind": INT, "verified": True},
        "_position": {"off": 0x70, "ref": None, "kind": FLOAT, "verified": False},
        "_originSpeed": {"off": 0xCC, "ref": None, "kind": INT, "verified": True,
                         "note": "×1000 定点，读到 5000 就是 5 速"},
        "_overwritedSpeed": {"off": 0xD0, "ref": None, "kind": INT, "verified": True},
        "_buffDetail": {"off": 0xE0, "ref": "BuffDetail", "kind": INT, "verified": True},
        "_state": {"off": 0x148, "ref": "CharacterState", "kind": INT, "verified": True},
        "_thisTurnIntSpeedOnCmdPhase": {"off": 0x184, "ref": None, "kind": INT,
                                        "verified": False},
    },
    # 血量、理智都藏在 ObscuredInt 里。
    "CharacterState": {
        "_maxHp": {"off": 0x11C, "ref": None, "kind": OBSCURED, "verified": True},
        "_hp": {"off": 0x148, "ref": None, "kind": OBSCURED, "verified": True,
                "note": "真机读到 148/1639，与血条一致"},
        "_mp": {"off": 0x158, "ref": None, "kind": OBSCURED, "verified": True,
                "note": "理智 SP，负数=恐慌"},
    },
    # 全局管理器：场景状态、时间缩放。
    "GlobalGameManager": {
        "_currentTimeScale": {"off": 0x50, "ref": None, "kind": FLOAT, "verified": True,
                              "note": "1.0 = 0x3F800000，暂停时是 0"},
        "sceneState": {"off": 0x64, "ref": None, "kind": INT, "verified": True,
                       "note": "0登录/1战斗/2主界面/3剧情/4地牢/5镜像地狱/"
                               "6铁路/7剧情镜像/8ProjectGS/9Rpg"},
        "_mainSceneEntryCount": {"off": 0xB8, "ref": None, "kind": INT, "verified": True},
    },
    "BuffDetail": {
        "list": {"off": 0x10, "ref": "List", "kind": LIST, "verified": True,
                 "note": "List<BuffModel>"},
    },
    "BuffModel": {
        "_staticData": {"off": 0x68, "ref": "BuffStaticData", "kind": INT, "verified": True},
    },
    "BuffStaticData": {
        "name": {"off": 0x18, "ref": None, "kind": "text", "verified": False,
                 "note": "il2cpp string，kind='text' 落点会换算成数字（不是原名）"},
    },
}


def field(cls, name):
    """取一条原始字段记录，找不到就抛 KeyError 并列出该类的已知字段。"""
    try:
        return FIELD_TABLE[cls][name]
    except KeyError:
        known = sorted(FIELD_TABLE.get(cls, {}))
        raise KeyError(f"{cls} 里没有字段 {name}；已知：{', '.join(known) or '(无这个类)'}")


def has(cls, name):
    return name in FIELD_TABLE.get(cls, {})


def kind_of(cls, *path):
    """路径末端的落点 kind（'int'/'float'/'obscured'/...）。"""
    if not path:
        raise ValueError("至少要给一个字段名")
    cur = cls
    record = None
    for name in path:
        record = field(cur, name)
        cur = record.get("ref") or cur
    return record["kind"]


def read_chain(cls, *path):
    """把「类 + 字段路径」翻成读链片段：``{'off': [...], 'kind': ...}``。

    中间每个引用字段都 deref=True（跳过去），最后一跳 deref=False（读值）。
    Container 字段（List / Dictionary）作为末端时，本函数只给 step 类型，
    取第几个元素要自己补 ``{'list': i}`` / ``{'dict': i}`` —— 那是调用方的
    语义，不是字段表的。
    """
    if not path:
        raise ValueError("至少要给一个字段名")
    steps = []
    cur = cls
    for i, name in enumerate(path):
        record = field(cur, name)
        last = (i == len(path) - 1)
        if record.get("ref") and not last:
            steps.append({"off": record["off"], "deref": True})
        else:
            steps.append({"off": record["off"], "deref": False})
        cur = record.get("ref") or cur
    return {"off": steps, "kind": record["kind"]}


def unit_path(*path):
    """从「一个 BattleUnit 对象」出发的常用路径。

    ``fields.unit_path("_model", "_state", "_hp")`` —— 注意起点不是
    BattleUnitModel 而是 BattleUnit（字典 value 的那个壳）。
    """
    return read_chain("BattleUnit", *path)


def units_chain(index=0):
    """从 BattleObjectManager 出发，取第 ``index`` 个单位的读链。

    返回的是**从 manager 开始**的链：``[+0x90] → dict[index] → ...
    自己再接字段``。要一次拿全场单位就用 ``{'dict': 'iter'}``。
    """
    return [{"off": field("BattleObjectManager", "_allUnitDictionary")["off"],
             "deref": True},
            {"dict": index}]


def units_iter():
    """从 BattleObjectManager 出发的**遍历**链：每个活跃单位各发一条事件。"""
    return [{"off": field("BattleObjectManager", "_allUnitDictionary")["off"],
             "deref": True},
            {"dict": "iter"}]
