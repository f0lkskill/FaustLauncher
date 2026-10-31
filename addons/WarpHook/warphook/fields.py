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
写 ``obscured``，直接按 int 读会拿到 key 那一坨垃圾。血量、理智、生死标记
都在这类字段里（``ObscuredBool`` 同理，真值是 0/1）。

「verified=False」的条目照 dump.cs 抄的、还没在真机上对过数，用之前先对一眼
（症状是「全 0」或者「数很大」，先怀疑偏移和尺寸）。

字段来源：``cache/hook/dump/E6312D92/out/dump.cs``（Il2CppDumper，10-24 生成），
抽取工具 ``test/_dump_fields.py``。
"""

# 落点 kind 与 C 侧 WARP_READ_* 同名，Host.read / reads= 直接用字符串。
INT = "int"
FLOAT = "float"
BOOL = "bool"
OBSCURED = "obscured"
LIST = "list"
ARRAY = "array"
DICT = "dict_count"
TEXT = "text"

# ref 不为 None 表示这个字段是**对象引用**：中间步骤要 deref=True 跳过去；
# ref 为 None 表示是内嵌结构或标量，读到它就是值（或值类型容器）。

FIELD_TABLE = {
    # 单例，全局一份：拿全场单位从这里进。
    "BattleObjectManager": {
        "_currTeamPosition": {"off": 0x28, "ref": None, "kind": INT, "verified": False,
                              "note": "TeamPosition 枚举，不是坐标"},
        "_currEnemyTeamPosition": {"off": 0x30, "ref": None, "kind": INT, "verified": False},
        "_deadSceneList": {"off": 0x60, "ref": "Dictionary", "kind": DICT, "verified": True,
                           "note": "Dictionary<int, CharacterAppearanceDeadScene>，真机 count=0 时映证"},
        "_unitList": {"off": 0x78, "ref": "Dictionary", "kind": DICT, "verified": True,
                      "note": "Dictionary<UNIT_FACTION, List<BattleUnit>>，按阵营分组"},
        "_nextBattleUnitInstanceID": {"off": 0x88, "ref": None, "kind": INT, "verified": False,
                                      "note": "下一个要分配的实例 id，等于「活过多少个」"},
        "_allUnitDictionary": {"off": 0x90, "ref": "Dictionary", "kind": DICT,
                               "verified": True,
                               "note": "Dictionary<int, BattleUnit>，全场单位；遍历主场"},
        "_deadUnitList": {"off": 0xB8, "ref": "List", "kind": LIST, "verified": False,
                          "note": "List<BattleUnitModel>，直接是模型不是壳"},
        "_exitAllyList": {"off": 0xC0, "ref": "List", "kind": LIST, "verified": False},
        "_exitEnemyList": {"off": 0xC8, "ref": "List", "kind": LIST, "verified": False},
        "_retreatList": {"off": 0xE0, "ref": "List", "kind": LIST, "verified": False},
        "isOnNextWave": {"off": 0xF0, "ref": None, "kind": BOOL, "verified": False},
        "_roundDeathCount": {"off": 0xF4, "ref": None, "kind": INT, "verified": False,
                             "note": "本回合死亡数"},
        "_isSetOverrideEndDelay": {"off": 0xF8, "ref": None, "kind": BOOL, "verified": False},
    },
    # Dictionary 的 value 是 BattleUnit（壳），模型在 _model 里。
    "BattleUnit": {
        "_model": {"off": 0x10, "ref": "BattleUnitModel", "kind": INT, "verified": True},
        "_view": {"off": 0x18, "ref": None, "kind": INT, "verified": False,
                  "note": "BattleUnitView，表现层，改不了数值"},
        "_position": {"off": 0x20, "ref": None, "kind": FLOAT, "verified": False,
                      "note": "Vector3 内嵌，偏移和尺寸都得自己对"},
    },
    "BattleUnitModel": {
        "_instanceID": {"off": 0x60, "ref": None, "kind": INT, "verified": True,
                        "note": "1/2/3 这种小整数，真机对过"},
        "_originID": {"off": 0x64, "ref": None, "kind": INT, "verified": True},
        "_defaultPhaseID": {"off": 0x68, "ref": None, "kind": INT, "verified": False},
        "_participateOrder": {"off": 0x6C, "ref": None, "kind": INT, "verified": False,
                              "note": "入场顺序"},
        "_position": {"off": 0x70, "ref": None, "kind": INT, "verified": False,
                      "note": "UNIT_POSITION 枚举（槽位），不是坐标"},
        "_passiveDetail": {"off": 0x78, "ref": "PassiveDetail", "kind": INT, "verified": False},
        "_systemAbilityDetail": {"off": 0x80, "ref": "BattleSystemAbilityDetail",
                                 "kind": INT, "verified": False},
        "_actionSlotDetail": {"off": 0x88, "ref": "ActionSlotDetail", "kind": INT,
                              "verified": False},
        "_doneDefenseAction": {"off": 0x90, "ref": None, "kind": BOOL, "verified": False},
        "_actionList": {"off": 0xA0, "ref": "List", "kind": LIST, "verified": False,
                        "note": "List<BattleActionModel>，本回合行动"},
        "_activatedAbilityDic": {"off": 0xC0, "ref": "Dictionary", "kind": DICT,
                                 "verified": False, "note": "Dictionary<string, int>"},
        "_deadAllyCount": {"off": 0xC8, "ref": None, "kind": INT, "verified": False},
        "_originSpeed": {"off": 0xCC, "ref": None, "kind": INT, "verified": True,
                         "note": "×1000 定点，读到 5000 就是 5 速"},
        "_overwritedSpeed": {"off": 0xD0, "ref": None, "kind": INT, "verified": True},
        "_firstTurnSeed": {"off": 0xD4, "ref": None, "kind": INT, "verified": False},
        "_duelRank": {"off": 0xDC, "ref": None, "kind": INT, "verified": False,
                      "note": "拼点排名"},
        "_buffDetail": {"off": 0xE0, "ref": "BuffDetail", "kind": INT, "verified": True},
        "_formationPos": {"off": 0xF0, "ref": None, "kind": FLOAT, "verified": False,
                          "note": "Vector3 内嵌（阵型坐标）"},
        "_overrideAppearanceID": {"off": 0x100, "ref": None, "kind": TEXT, "verified": False,
                                  "note": "il2cpp string，只给 ID 不给名字"},
        "_originViewID": {"off": 0x108, "ref": None, "kind": INT, "verified": False},
        "_erosionData": {"off": 0x110, "ref": "EgoAndErosionState", "kind": INT,
                         "verified": False},
        "_defaultPanicType": {"off": 0x118, "ref": None, "kind": INT, "verified": False,
                              "note": "PANIC_TYPE 枚举"},
        "_cachedPanicType": {"off": 0x11C, "ref": None, "kind": INT, "verified": False},
        "_lowMoraleCondition": {"off": 0x124, "ref": None, "kind": INT, "verified": False},
        "_panicCondition": {"off": 0x128, "ref": None, "kind": INT, "verified": False},
        "_state": {"off": 0x148, "ref": "CharacterState", "kind": INT, "verified": True},
        "_resistDetail": {"off": 0x150, "ref": "ResistDetail", "kind": INT, "verified": False},
        "_mentalDetail": {"off": 0x158, "ref": "MentalDetail", "kind": INT, "verified": False},
        "_changeStat": {"off": 0x160, "ref": "ChangeStat", "kind": INT, "verified": False},
        "_hpRetentionRatio": {"off": 0x168, "ref": None, "kind": FLOAT, "verified": False},
        "_prevTurnMpOnCmdPhase": {"off": 0x170, "ref": None, "kind": INT, "verified": False},
        "_thisTurnMpOnCmdPhase": {"off": 0x174, "ref": None, "kind": INT, "verified": False},
        "_prevTurnHpOnCmdPhase": {"off": 0x178, "ref": None, "kind": INT, "verified": False},
        "_thisTurnHpOnCmdPhase": {"off": 0x17C, "ref": None, "kind": INT, "verified": False},
        "_prevTurnIntSpeedOnCmdPhase": {"off": 0x180, "ref": None, "kind": INT,
                                        "verified": False},
        "_thisTurnIntSpeedOnCmdPhase": {"off": 0x184, "ref": None, "kind": INT,
                                        "verified": False},
    },
    # 血量、理智、生死都藏在 Obscured* 里；同一个对象上是一串 12 字节一个的
    # 加密字段，所以偏移看着很稀。
    "CharacterState": {
        "_isDead": {"off": 0x10, "ref": None, "kind": OBSCURED, "verified": False,
                    "note": "ObscuredBool，真值 0/1"},
        "_isFakeDead": {"off": 0x1C, "ref": None, "kind": OBSCURED, "verified": False},
        "_isRetreated": {"off": 0x28, "ref": None, "kind": OBSCURED, "verified": False},
        "_isDisappered": {"off": 0x34, "ref": None, "kind": OBSCURED, "verified": False},
        "_isReleaseStandBy": {"off": 0x40, "ref": None, "kind": OBSCURED, "verified": False},
        "_isActivated": {"off": 0x4C, "ref": None, "kind": OBSCURED, "verified": False},
        "_isBreak": {"off": 0x58, "ref": None, "kind": OBSCURED, "verified": False,
                     "note": "混乱/崩溃"},
        "_isPanic": {"off": 0x64, "ref": None, "kind": OBSCURED, "verified": False,
                     "note": "恐慌"},
        "_isLowMorale": {"off": 0x70, "ref": None, "kind": OBSCURED, "verified": False},
        "_isNextTurnBreak": {"off": 0x7C, "ref": None, "kind": OBSCURED, "verified": False},
        "_isPrevTurnBreak": {"off": 0x88, "ref": None, "kind": OBSCURED, "verified": False},
        "_hitDamageThisRound": {"off": 0xA0, "ref": None, "kind": INT, "verified": False,
                                "note": "RoundAllDmgInfo 内嵌结构，偏移要再对"},
        "_hitAttackDamageThisRound": {"off": 0xA8, "ref": None, "kind": OBSCURED,
                                      "verified": False},
        "_hitRealHpDamageThisRound": {"off": 0xB8, "ref": None, "kind": OBSCURED,
                                      "verified": False},
        "_totalTakeDamageInThisBattle": {"off": 0xF8, "ref": None, "kind": OBSCURED,
                                         "verified": False},
        "_tempShields": {"off": 0x108, "ref": "List", "kind": LIST, "verified": False,
                         "note": "List<CharacterState.Shield>，护盾"},
        "_isEvade": {"off": 0x110, "ref": None, "kind": OBSCURED, "verified": False},
        "_maxHp": {"off": 0x11C, "ref": None, "kind": OBSCURED, "verified": True},
        "_isForcelyBreak": {"off": 0x12C, "ref": None, "kind": OBSCURED, "verified": False},
        "_forcedBreakedAdder": {"off": 0x138, "ref": None, "kind": OBSCURED, "verified": False},
        "_hp": {"off": 0x148, "ref": None, "kind": OBSCURED, "verified": True,
                "note": "真机读到 148/1639，与血条一致"},
        "_mp": {"off": 0x158, "ref": None, "kind": OBSCURED, "verified": True,
                "note": "理智 SP，负数=恐慌"},
        "_hasFakeDead": {"off": 0x168, "ref": None, "kind": OBSCURED, "verified": False},
        "_isImmortal": {"off": 0x174, "ref": None, "kind": OBSCURED, "verified": False},
        "_breakSections": {"off": 0x180, "ref": "List", "kind": LIST, "verified": False,
                           "note": "List<BreakSection>，混乱阈值分段"},
        "_originBreakSections": {"off": 0x188, "ref": "List", "kind": LIST,
                                 "verified": False},
    },
    # 全局管理器：场景状态、时间缩放。
    "GlobalGameManager": {
        "_currentTimeScale": {"off": 0x50, "ref": None, "kind": FLOAT, "verified": True,
                              "note": "1.0 = 0x3F800000，暂停时是 0"},
        "_currentPlatform": {"off": 0x60, "ref": None, "kind": INT, "verified": False},
        "sceneState": {"off": 0x64, "ref": None, "kind": INT, "verified": True,
                       "note": "0登录/1战斗/2主界面/3剧情/4地牢/5镜像地狱/"
                               "6铁路/7剧情镜像/8ProjectGS/9Rpg"},
        "_prevSceneName": {"off": 0x70, "ref": None, "kind": TEXT, "verified": False},
        "_nextSceneName": {"off": 0x80, "ref": None, "kind": TEXT, "verified": False},
        "_stageResult": {"off": 0x90, "ref": "StageResultData", "kind": INT, "verified": False},
        "_battleDamageStatistics": {"off": 0x98, "ref": "DamageStatistics", "kind": INT,
                                    "verified": False},
        "_initByAwaken": {"off": 0xA0, "ref": None, "kind": BOOL, "verified": False},
        "_isProcessingGameStarting": {"off": 0xA1, "ref": None, "kind": BOOL,
                                      "verified": False},
        "_mainSceneEntryCount": {"off": 0xB8, "ref": None, "kind": INT, "verified": True},
        "_speedHackHandler": {"off": 0xF0, "ref": "SpeedHackHandler", "kind": INT,
                              "verified": False},
        "isRunningLoad": {"off": 0x108, "ref": None, "kind": BOOL, "verified": False},
        "isSynchronousDataFetchCompleted": {"off": 0x109, "ref": None, "kind": BOOL,
                                            "verified": False},
    },
    "BuffDetail": {
        "list": {"off": 0x10, "ref": "List", "kind": LIST, "verified": True,
                 "note": "List<BuffModel>"},
    },
    "BuffModel": {
        "_buffInfo": {"off": 0x58, "ref": "BuffInfo", "kind": INT, "verified": True,
                      "note": "当前层数/次数在这里（BuffStaticData 只有模板值）"},
        "_staticData": {"off": 0x68, "ref": "BuffStaticData", "kind": INT, "verified": True},
        "_buffName": {"off": 0xA0, "ref": None, "kind": TEXT, "verified": False,
                      "note": "il2cpp string，缓存的名字"},
    },
    "BuffInfo": {
        "_name": {"off": 0x28, "ref": None, "kind": TEXT, "verified": True,
                  "note": "il2cpp string；原名要跨进程读 UTF-16，见 remote.utf16"},
        "_maxStack": {"off": 0x64, "ref": None, "kind": INT, "verified": True},
        "_maxTurn": {"off": 0x68, "ref": None, "kind": INT, "verified": True},
        "_stack": {"off": 0x6C, "ref": None, "kind": INT, "verified": True,
                   "note": "强度/层数（界面上那个大字数字）"},
        "_turn": {"off": 0x70, "ref": None, "kind": INT, "verified": True,
                  "note": "剩余次数/回合"},
    },
    "BuffStaticData": {
        "name": {"off": 0x18, "ref": None, "kind": TEXT, "verified": False,
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


def verified_names(cls):
    """这个类里真机验证过的字段名（给诊断/文档用）。"""
    return sorted(n for n, r in FIELD_TABLE.get(cls, {}).items() if r.get("verified"))


def unverified_names(cls):
    """还没在真机上对过数的字段名 —— 用之前先对一眼。"""
    return sorted(n for n, r in FIELD_TABLE.get(cls, {}).items() if not r.get("verified"))
