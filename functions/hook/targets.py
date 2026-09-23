"""hook 目标定义 —— "要盯住哪些东西"的声明式清单。

这里只放**跨版本稳定的描述**（符号名 / 类名 / 值域），不放易变的数字：
具体偏移由 dump 流水线每次重新解出来，写进云端笔记 ``FaustLauncher.hook_index``。
游戏更新后，只要这些名字还在（Project Moon 基本不会改类名），偏移就能自动复原。

目标分两类：

``HOOK_TARGETS``（代码偏移）
    要给 DLL detour 的函数。索引里给的是 ``rva`` + ``prologue``（目标函数前 16 字节），
    两者配对使用：DLL 装钩前先比对 prologue，与本机 DLL 不一致就不装钩 —— 这是
    防"旧偏移打到新版本"的最后一道闸。

``CHAIN_TARGETS``（数据偏移）
    外部进程读游戏数值用的多级指针链。首级是模块内的一个槽位（
    ``GameAssembly.dll + base_offset``，Cheat Engine 里看到的那个地址）；
    ``offsets`` 是随后的逐级偏移（最后一级是值的字段偏移）。

    这类链的**根槽位**（``base_offset``）会随构建变化，但它指向的是 IL2CPP 的
    ``Il2CppClass*`` —— 所以只要知道类名，就能在模块的数据节里重新把它扫出来
    （见 ``locator.py``）。类名一旦被自动发现就会写进索引的 ``root_class``，
    以后每次更新都是"按名字重定位"，不再需要人工找偏移。
"""

from __future__ import annotations

from dataclasses import dataclass, field


# --------------------------------------------------------------------------- 代码钩子


@dataclass(frozen=True)
class HookTarget:
    """一个要 detour 的函数。"""

    key: str                     # 索引里的键（英文小写下划线）
    symbol: str                  # dump.cs 里的方法名：``类::方法`` 或 ``类$$方法``
    description: str
    compat_field: str = ""       # 写进 cheat_damage 兼容块的字段名（空则不入兼容块）
    required: bool = True        # 解不出来时是否算失败


# 默认盯住的两个目标：与 test/damage_log.* 和 web.lcta.top/cheat_damage.json 完全对齐，
# 名字取自 Il2CppDumper 的 ``类$$方法`` 写法（BattleUnitModel 在空命名空间下）。
# 注意同名方法在多处重载（BattleUnitModel 是 4 参数版本、BuffAbility 是 6 参数版本），
# 索引按"名字精确匹配取第一处"，与官方 payload 的做法一致（已实测一致）。
HOOK_TARGETS: tuple[HookTarget, ...] = (
    HookTarget(
        key="take_attack_dmg_multiplier",
        symbol="BattleUnitModel$$GetTakeAttackDmgMultiplier",
        description="战斗单位受击伤害倍率（单点覆盖全部子类；伤害/减伤类插件的入口）",
        compat_field="rva_get_take_attack_dmg_multiplier",
    ),
    HookTarget(
        key="opponent_faction",
        symbol="BattleUnitModel$$GetOpponentFaction",
        description="战斗单位敌对阵营判定（判断敌我，配合上面的倍率做方向过滤）",
        compat_field="rva_get_opponent_faction",
    ),
)


# --------------------------------------------------------------------------- 数据链


@dataclass
class ChainTarget:
    """一条"模块槽 → 多级指针 → 值"的读取链。

    ``base_offset`` / ``offsets`` 是**上次已知**的数字，只作为回退默认值；
    每次更新都会尝试用 ``root_class`` / ``field_refs`` 重新解析一遍。
    """

    key: str
    description: str
    base_offset: int
    offsets: tuple[int, ...]
    module: str = "GameAssembly.dll"
    value_type: str = "int32"
    root_class: str = ""                       # 根槽位指向的 Il2CppClass 名（可自动发现）
    static_fields_offset: int = 0xB8           # Il2CppClass::static_fields 的成员偏移
    field_refs: tuple[tuple[str, str], ...] = ()   # ((类, 字段), ...) 用于按名字刷新 offsets
    value_range: tuple[int, int] | None = None  # 合理值域（用于校验/发现）
    step_classes: tuple[str, ...] = ()         # 每级目标对象的类名（发现后填充，便于排障）

    def as_dict(self, **extra) -> dict:
        data = {
            "description": self.description,
            "module": self.module,
            "base_offset": self.base_offset,
            "offsets": list(self.offsets),
            "value_type": self.value_type,
            "root_class": self.root_class,
            "static_fields_offset": self.static_fields_offset,
            "field_refs": [list(item) for item in self.field_refs],
            "value_range": list(self.value_range) if self.value_range else None,
            "step_classes": list(self.step_classes),
        }
        data.update(extra)
        return data


# 脑啡肽容量：链来自用户桌面 ok.py 的 CE 结果（首级 0x07BB4F90 + 0xB8/0x80/0x18/0x28）。
# root_class 留空 —— 第一次跑会由结构性扫描自动认出类名并回填。
ENKEPHALIN_CHAIN = ChainTarget(
    key="enkephalin",
    description="脑啡肽容量（不是狂气；成就「满分脑啡肽」用它）",
    base_offset=0x07BB4F90,
    offsets=(0xB8, 0x80, 0x18, 0x28),
    value_type="int32",
    value_range=(0, 1000),
)

CHAIN_TARGETS: tuple[ChainTarget, ...] = (ENKEPHALIN_CHAIN,)


# --------------------------------------------------------------------------- 符号保留范围

# 只有命中这些模式的类，其方法/字段才会进索引（否则索引会有几十 MB）。
# 这些是"钩子/读值最可能用到"的类；需要更多时在这里加即可，或临时用 CLI 的
# ``--focus`` 覆盖。
FOCUS_PATTERNS: tuple[str, ...] = (
    "BattleUnitModel",
    "BattleActionModel",
    "AttackDamage",
    "DamageInfo",
    "CoinModel",
    "BuffAbility",
    "BattleUnit",
    "BattleManager",
    "Enkephalin",
    "Achievement",
    "SaveManager",
    "PlayerData",
    "UserData",
    "UnitData",
    "PassiveAbility",
)

# 索引里最多保留多少符号（防止 focus 写太宽导致本地缓存过大；
# 发布到云端时还会再裁剪一次，见 index.MAX_PUBLISH_METHODS）
MAX_METHODS = 40000
MAX_FIELDS = 20000


def all_targets() -> tuple[tuple[HookTarget, ...], tuple[ChainTarget, ...]]:
    return HOOK_TARGETS, CHAIN_TARGETS


def required_symbols() -> list[str]:
    """所有必须在 dump.cs 里找到的符号名（用于 dump 时的白名单保留）。"""
    names = [t.symbol for t in HOOK_TARGETS]
    for chain in CHAIN_TARGETS:
        for cls, fld in chain.field_refs:
            names.append(f"{cls}::{fld}")
        if chain.root_class:
            names.append(chain.root_class)
    return names
