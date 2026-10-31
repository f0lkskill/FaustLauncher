# 06 解析 buff

buff 是这套接口里封装得最多的一块——因为它要读**文字**，比读数字麻烦得多。
你只需要记住三个入口：

```python
u.buff_count()          # 有几个
u.buffs                 # 全部，列表
u.buff("Breath")        # 找一个（英文 ID / 中文名 / 序号都行）
u.has_buff("呼吸法")     # 有没有
```

## `Buff` 能读什么

| 属性 | 含义 | 例子 |
| --- | --- | --- |
| `b.name` | 中文名（游戏里显示的那个） | `呼吸法` |
| `b.key` | 英文 ID（数据里真正的标识） | `Breath` |
| `b.stack` | 当前层数 / 强度（界面上那个大字） | `85` |
| `b.turn` | 剩余次数 / 回合 | `28` |
| `b.max_stack` | 层数上限 | `99` |
| `b.max_turn` | 次数上限 | `99` |
| `b.stack_ratio` | 层数比例 0..1 | `0.858` |
| `b.icon` | 图标 ID | `Buff_Breath` |
| `b.raw()` | 九个字段的字典 | — |

```python
for b in u.buffs:
    print(b.key, b.stack, b.turn)
```

## `key` 和 `name` 的区别（重要）

同一个 buff 有两个名字：

- **`name`** 是**中文显示名**（`呼吸法`），跟着游戏语言走。玩家切成英文，它就变成别的。
- **`key`** 是**英文 ID**（`Breath`），是数据里的真实标识，**任何语言都一样**。

所以：给玩家看用 `name`，**写逻辑一律用 `key`**。

```python
if u.has_buff("Breath"):        # ✅ 换语言也不会坏
    ...

if u.has_buff("呼吸法"):         # ⚠️ 游戏换语言就失效
    ...
```

## 一只手数完的实例

我方人格 10115（浮士德·魁首）身上的 9 个 buff，实测值：

| 中文名 | key | 层数/上限 | 次数/上限 |
| --- | --- | --- | --- |
| 呼吸法 | `Breath` | 85 / 99 | 28 / 99 |
| 指令加护 | `BlessingOfIndexPrescriptAlly` | 9 / 9 | 0 / — |
| 代行[赫尔墨斯] | `StackYisangSpecialSkill` | 9 / 9 | 0 / — |
| 烧伤 | `Combustion` | 3 / 99 | 1 / 99 |
| 守护 | `Protection` | 1 / 10 | 0 / — |
| 遮盖伤口的假面 | `BurningWoundYisangMask` | 1 / 1 | 0 / — |

`key` 是从游戏的数据表里直接读出来的字符串，所以它们看起来像英文变量名——那就是原样。

## 示例

```json
--8<-- "docs/examples/buffs/addon_info.json"
```

```python
--8<-- "docs/examples/buffs/scr.py"
```

点「列出我方 buff」：

```text
[buff 观察] 编号 1（人格 10115）身上 9 个 buff：
[buff 观察]   遮盖伤口的假面  1/1 层  0/0 次   [BurningWoundYisangMask]
[buff 观察]   呼吸法  85/99 层  28/99 次   [Breath]
[buff 观察]   烧伤  3/99 层  1/99 次   [Combustion]
...
```

## 文字是怎么读出来的

数字走的是「DLL 代读」，一次往返 20–40ms。但**文字不行**——那条通道只能回一个
32 位的数。所以 `b.name` / `b.key` 走的是另一条路：WarpHook 拿到字符串对象的地
址，再由插件进程直接从游戏内存里读出来（只读，安全）。

这条路的代价是要先找到游戏进程（第一次调用会慢一点），之后每次读一个 buff 名
大约几十毫秒。所以：

- `u.buff_count()` 很快（一次往返）
- `u.buffs` 里的 `b.stack` / `b.turn` 也快（每项往返一次）
- `b.name` / `b.key` 慢一点（每个字符串单独读）

想在回合回调里报「全场每人的 buff 名单」，11 个单位 × 几个 buff × 每个字符串，
一秒以上是正常的。**只在需要时读名字**，或者只读你关心的那几个。

## 只要「变了没变」的快速写法

如果目的只是「这个 buff 出现了 / 消失了」，不需要文字：

```python
u.buff_ids()      # 每个 buff 的英文 ID 指纹（数字），比读字符串快
```

它是 `BuffStaticData.id` 的哈希，同一个 buff 永远同一个数，换个 buff 就变。
想放到事件里做 diff 就够用了。

## 这一篇你该记住的

- `u.buff_count()` / `u.buffs` / `u.buff(key)` / `u.has_buff(key)`
- `Buff` 给：`name` `key` `stack` `turn` `max_stack` `max_turn` `icon`
- 写逻辑用 `key`（英文 ID），给玩家看用 `name`（中文名）
- 读名字比读数字慢，别在循环里无脑读全场
- 只要判断有无/变化，用 `u.buff_ids()`（数字指纹）

下一篇收尾：插件的生命周期——什么时候启动、什么时候该收手、怎么不把游戏搞崩。
