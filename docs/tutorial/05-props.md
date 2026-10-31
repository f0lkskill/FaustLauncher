# 05 把属性都拿出来

上一篇读的是「常用那几个」。真实需求经常是「我还想知道它身上别的数」——
本场承伤、行动顺序、崩溃条、士气、形态编号……这些也都能读。

## 三种读法，按需要选

| 想要 | 写法 | 成本 |
| --- | --- | --- |
| 一两个字段 | `u.hp` / `u.get_pro("_totalTakeDamageInThisBattle")` | 1 次往返 |
| 一批字段 | `u.props()` | 60 多次往返，约 2 秒 |
| 整场简表 | `game.snapshot()` | 单位数 × 11 次往返 |

先说最重要的规矩：**`props()` 很贵，不要在回合回调里对 11 个单位都调一遍**
（11 × 60 ≈ 660 次往返 ≈ 20 多秒）。它是摸底、调试、导出用的工具，不是业务接口。

## `get_pro`：按字段名取任意一个

```python
u.get_pro('hp')                        # 别名，和 u.hp 一样
u.get_pro('_hp')                       # 游戏里的真名
u.get_pro('CharacterState._hp')        # 带类名
u.get_pro('_state._hp')                # 带引用路径
```

三种写法等价，随便用你顺手的。名字从哪来？游戏自己的字段名——所以你会看到
`_` 开头的私有命名，这很正常，照着写就行。

字段名写错不会报错，只会返回 `None`（默认值可以自己给：`u.get_pro('xx', 0)`）。

## `props()`：一次全读

```python
props = u.props()
props['_maxHp'], props['_mp'], props['_isBreak']
```

返回一个字典，键是游戏里的字段名。实测一个人格 10115 的单位，里面长这样（节选）：

```text
_instanceID                          1
_originID                            10115
_hp                                  245
_maxHp                               248
_mp                                  45
_originSpeed                         5661
_hpRetentionRatio                    1.0
_totalTakeDamageInThisBattle         9
_isActivated                         213
_cachedPanicType                     9999
```

几个值得解释的：

| 字段 | 怎么理解 |
| --- | --- |
| `_originSpeed = 5661` | 定点数，×1000。`u.speed` 已经替你除好了 |
| `_isActivated = 213` | 混淆布尔原始码，**213 表示真**、181 表示假。`u.alive` 这类属性已经解好，别自己拿这个字段判断 |
| `_hpRetentionRatio = 1.0` | 血量保留比例，某些机制会按它折算伤害 |
| `_cachedPanicType = 9999` | 恐慌类型，9999 是「无」 |
| `_totalTakeDamageInThisBattle = 9` | 本场累计承伤——这类累计值特别适合做统计插件 |

## `scan()`：可以挑类

`props()` 是「单位本体 + 它的状态」两段合起来的。想只要一段：

```python
u.scan(classes=("CharacterState",))    # 只要状态（血量、理智、各种标志）
u.scan(classes=("BattleUnitModel",))   # 只要本体（编号、速度、形态）
```

## 字段表是唯一真相

所有字段名和偏移都在 `warp.field` 里：

```python
fields = _W.field
fields.FIELD_TABLE['BattleUnitModel']['_hp']
# {'off': 328, 'ref': None, 'kind': 'obscured', 'verified': True, 'note': '...'}

fields.verified_names('CharacterState')     # 真机核对过的字段
fields.unverified_names('CharacterState')   # 从 dump 抄来、还没核对的
```

`verified` 标记很重要：`True` 表示这个字段在真机上读出过正确的值；
`False` 表示名字和偏移来自游戏 dump，**逻辑上对，但还没验证过**。
用未验证字段时先打印出来看一眼再依赖它。

`warp.field` 也能直接拼链给你：

```python
fields.read_chain('BattleUnit', '_model', '_state', '_hp')
# {'off': [{'off': 16, 'deref': True},
#          {'off': 328, 'deref': True},
#          {'off': 328, 'deref': False}],
#  'kind': 'obscured'}
```

想自己走链读（底层）：`u.read({'off': 0x10, 'deref': True}, {'off': 0x60, 'deref': False})`。

## 示例

```json
--8<-- "docs/examples/read-props/addon_info.json"
```

```python
--8<-- "docs/examples/read-props/scr.py"
```

## 这一篇你该记住的

- 少数字段 → `u.hp` / `u.get_pro("真名")`；一批字段 → `u.props()`；整场 → `game.snapshot()`
- `props()` 很贵（单位 × 60 次往返），只在调试/导出时用
- 字段名就是游戏里的名字，写错返回 `None` 不报错
- `_originSpeed` 是 ×1000 的定点数，`_is*` 是混淆布尔原始码——用门面属性，别手算
- `warp.field` 是字段表的唯一真相，`verified=False` 的条目先验证再用

下一篇专讲 buff——它是唯一需要读到「文本」的东西，也是门面里封装得最多的一块。
