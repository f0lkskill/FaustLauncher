# 04 warp.field —— 字段表

**唯一记偏移的地方。** 插件不该自己写 `0x148`——那是 dump 期的数字，游戏一版就可能变。
写在这里，变的时候只改一处，还能一眼看出哪些条目在真机对过数。

```python
fld = _NS.space('warp').field
```

## 核心：`FIELD_TABLE`

一个两层字典：`FIELD_TABLE[类名][字段名] = 记录`。共 **8 个类、62 个字段**。

| 类 | 字段数 | 是什么 |
| --- | --- | --- |
| `BattleObjectManager` | 13 | 全局战场管理器（单例） |
| `BattleUnit` | 3 | 字典 value 的壳（`_model` / `_view` / `_position`） |
| `BattleUnitModel` | 37 | 单位本体（编号、人格、速度、形态…） |
| `CharacterState` | 26 | 单位状态（血量、理智、生死/混乱/恐慌） |
| `GlobalGameManager` | 13 | 场景根对象（场景编号、时间缩放…） |
| `BuffDetail` | 1 | buff 容器（`list@0x10`） |
| `BuffModel` | 1 | 单个 buff 实例（`_buffInfo` / `_staticData`） |
| `BuffStaticData` | 12 | buff 静态数据（英文 ID、图标、上限） |
| `BuffInfo` | 5 | buff 动态数据（名字、层数、次数） |

### 记录结构

```python
fld.FIELD_TABLE['CharacterState']['_hp']
# {'off': 328,          # 偏移（从对象指针算起）
#  'ref': None,         # 非 None = 这是个对象引用（中间步要 deref）
#  'kind': 'obscured',  # 落点类型
#  'verified': True,    # 真机对过数
#  'note': '血量，ObscuredInt'}
```

`verified` 是关键：`True` 表示真机上读出过正确值；`False` 表示照 dump 抄的、
**逻辑上对但没验过**。用未验证字段之前先打印看一眼。

### 落点 `kind`

| 常量 | 值 | 含义 |
| --- | --- | --- |
| `INT` | `'int'` | 有符号 32 位 |
| `FLOAT` | `'float'` | 单精度浮点 |
| `BOOL` | `'bool'` | 普通布尔 |
| `OBSCURED` | `'obscured'` | 反作弊混淆值（`hidden ^ key`） |
| `LIST` | `'list'` | `List<T>`（末端取 count） |
| `ARRAY` | `'array'` | `T[]`（末端取 count） |
| `DICT` | `'dict'` | `Dictionary<K,V>`（末端取 dict_count） |
| `TEXT` | `'text'` | il2cpp string（末端给指纹） |

## 函数

| 函数 | 返回 | 说明 |
| --- | --- | --- |
| `field(cls, name)` | `dict` | 取一条原始记录；找不到抛 `KeyError` 并列出该类已知字段 |
| `has(cls, name)` | `bool` | 有没有这个字段 |
| `kind_of(cls, *path)` | `str` | 路径末端的落点 kind |
| `read_chain(cls, *path)` | `{'off': [...], 'kind': ...}` | 翻成能直接塞进 `reads=` 的链 |
| `unit_path(*path)` | 同上 | **从 `BattleUnit` 出发**的路径（跳过 `_model` 那层壳） |
| `units_chain(index=0)` | `list` | 从 manager 到第 i 个单位的链 |
| `units_iter()` | `list` | 从 manager 的全场遍历链 |
| `verified_names(cls)` | `list[str]` | 该类真机验证过的字段 |
| `unverified_names(cls)` | `list[str]` | 还没验证的字段 |

## 示例

### 查一个偏移

```python
rec = fld.field('BattleUnitModel', '_originSpeed')
print(hex(rec['off']), rec['kind'], rec['verified'])
# 0xcc int True
```

### 拼一条链

```python
spec = fld.read_chain('BattleUnitModel', '_state', '_hp')
# {'off': [{'off': 328, 'deref': True}, {'off': 328, 'deref': False}],
#  'kind': 'obscured'}

host.read(27, spec['off'], kind=spec['kind'])    # 槽 27 里放一个 BattleUnitModel
```

`read_chain` 的规则：**中间每个引用字段 `deref=True`（跳过去），最后一跳 `deref=False`（读值）**。

### 从单位出发

```python
fld.unit_path('_model', '_originID')
# 起点是 BattleUnit，不是 BattleUnitModel
# {'off': [{'off': 16, 'deref': True}, {'off': 96, 'deref': False}], 'kind': 'int'}
```

### 全场遍历链

```python
fld.units_iter()
# [{'off': 144, 'deref': True}, {'dict': 'iter'}]
```

这条链塞进钩子的 `reads=` 就是「一次命中展开全场每个单位各一条事件」。

### 看哪些字段还没验证

```python
print(fld.unverified_names('CharacterState'))
```

## 容器字段要自己补一步

`read_chain` 遇到 List / Dictionary **作为末端**时，只给 step 类型，不给「取第几个」：

```python
fld.read_chain('BattleObjectManager', '_unitList')
# {'off': [{'off': 120, 'deref': False}], 'kind': 'list'}   ← 只到容器本身

# 要第 0 个，自己补：
[...] + [{'list': 0}]
```

因为「取第几个」是调用方的语义，不是字段表的。

## 字段表怎么更新的

1. 游戏更新 → 重新 dump（Il2CppDumper）；
2. `test/_dump_fields.py` 从 dump.cs 抽字段（`--find 类名` 找行号）；
3. 把新偏移并入 `addons/WarpHook/warphook/fields.py`，`verified` 先写 `False`；
4. 真机读出来对数 → 改 `True` 并写上 `note`。

!!! warning "同一协议号的两次构建，偏移可能不同"
    0.9.7 发布时按 .NET reference source 写了 `Dictionary.freeCount@0x2C`，
    真机一读是 `version`（13），`count - freeCount` 变负数，`dict_count` 恒 0。
    **单元测试用的是同一个错误假设，所以全绿。** 教训：偏移只有真机能证明。
