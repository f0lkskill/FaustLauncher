# 游戏内存探索

把「在真机里验证过的」和「从 dump.cs 推算但还没验证的」分开记，避免下次又把推算值当成事实。

dump 来源：`cache/hook/dump/E6312D92/out/dump.cs`。字段后面那行 `// 0xNN` 就是偏移，
**从对象指针算起**（已经含 il2cpp 的 0x10 header），可以直接当读取链的 `off` 用。

---

## 一、已验证可读（真机跑通）

钩子是 `GlobalGameManager::FixedUpdate`（60fps，主线程），读取链直接读 `self` 的字段。

| 类 | 字段 | 偏移 | 类型 | 实测值 |
| --- | --- | --- | --- | --- |
| `GlobalGameManager` | `sceneState` | `0x64` | `SCENE_STATE`（枚举，底层 int） | 主界面 `2`、战斗 `1` |
| `GlobalGameManager` | `_mainSceneEntryCount` | `0xB8` | int | `1` |
| `GlobalGameManager` | `_currentTimeScale` | `0x50` | float | `1.0`（位模式 `0x3f800000`） |

`currentTimeScale` 那次的原始事件行：

```
#1 hook=7 a=1 b=1 c=1065353216 d=0
```

`1065353216` = `0x3F800000` = float **1.0**；`a=1` 是 `sceneState`（战斗），`b=1` 是
`_mainSceneEntryCount`。三个值同时对上，说明偏移和类型都没错。

另外验证过 `GlobalGameManager::FixedUpdate` 的调用频率：**8 秒内命中 4693 次**，
512 格事件环大约 8.5 秒翻一轮 —— 采样类的钩子必须做去重（值没变就不投递），
不然环里全是重复行。

---

## 二、`SCENE_STATE` 枚举

`dump.cs:509404`：

```c
Login = 0
Battle = 1
Main = 2
Story = 3
Dungeon = 4
MirrorDungeon = 5
RailwayDungeon = 6
StoryMirrorDungeon = 7
ProjectGS = 8
Rpg = 9
```

`sceneState` 是最便宜的「现在在哪个场景」探针，用它决定要不要启用某批战斗钩子就够了，
不必去猜 UI 层级。

---

## 三、战斗单位与状态（2026-10-28 真机验证通过）

**已经用 WarpHook 的读取链在真机读到真实数据**，读到的是战斗中会变的值：
同一场战斗里 `hp` 从 233 掉到 222、`mp` 从 45 掉到 0（45 正好是理智上限）。

用的钩子是 **`BattleUnitModel::RefreshSpeed`**（dump: `public virtual void RefreshSpeed()`）：

```python
{'klass': 'BattleUnitModel', 'method': 'RefreshSpeed', 'argc': 0,
 'reads': [
   {'arg': 0, 'out': 0, 'kind': 'obscured',
    'off': [{'off': 0x148, 'deref': True}, {'off': 0x148, 'deref': False}]},  # 血
   {'arg': 0, 'out': 1, 'kind': 'obscured',
    'off': [{'off': 0x148, 'deref': True}, {'off': 0x158, 'deref': False}]},  # 理智
 ]}
```

### 选钩子比选偏移更重要（四次探针的教训）

同一批偏移，换一个钩子就全错。踩过的坑：

| 钩子 | 结果 |
| --- | --- |
| `CharacterState::get_Hp` / `BattleUnitModel::ChangeIntegerPartOfSpeed` | 命中 0 —— 一行 getter 被 AOT 内联，内存里没有调用指令 |
| `BattleObjectManager::OnRoundStart_Prepare` | 命中，但 `self+0xB8` 读出 `0x68695720`，不是 `List` 指针 —— 那个 `self` 不是管理器 |
| `BattleUnitModel::OnRoundStart_Before` | 命中，但 `self+0x60` 读出 `0x68695A10` —— 该方法定义在父类 `CombatUnitModel` 上，钩父类实现时 `self` 不是我们以为的对象 |
| **`BattleUnitModel::RefreshSpeed`** | 命中，`self+0x60=11`、`self+0x64=98002`、`self+0x148=0x28ad6731a80`（堆指针）—— 全部合理，血量理智都读对 |

判断 `self` 对不对，最便宜的办法是读对象头：`+0x00` 是 klass 指针、`+0x08` 是
monitor（无锁时恒为 0）。klass 落在堆区（`0x28xxxxxxxxxx`）或 `0x7FFx` 段就说明
`self` 是合法托管对象。**注意 `kind: 'int'` 只读 4 字节**，64 位指针要读 `+0x00`
和 `+0x04` 再拼起来，别学我第一次那样只看低半就下结论。

### 战斗单位

`BattleUnitModel`（`dump.cs:538827`，`public abstract class BattleUnitModel : CombatUnitModel`）：

| 字段 | 偏移 | 说明 |
| --- | --- | --- |
| `_instanceID` | `0x60` | int，场上唯一实例号 |
| `_originID` | `0x64` | int，角色/敌人模板 id |
| `_position` | `0x70` | 站位 |
| `_originSpeed` | `0xCC` | **速度 ×1000 的定点数** |
| `_overwritedSpeed` | `0xD0` | 同上 |
| `_thisTurnIntSpeedOnCmdPhase` | `0x184` | 整数，不缩放 |
| `_buffDetail` | `0xE0` | → `BuffDetail` |
| `_state` | `0x148` | → `CharacterState`（**引用，链上要 deref**） |

速度为什么是 ×1000：`BattleUnitModel::GetIntegerOfPureOriginalSpeed()` 就是拿 `_originSpeed / 1000`。

### 状态对象

`CharacterState`（`dump.cs:535296`）：

| 字段 | 偏移 | 说明 |
| --- | --- | --- |
| `_maxHp` | `0x11C` | `ObscuredInt` |
| `_hp` | `0x148` | `ObscuredInt` |
| `_mp` | `0x158` | `ObscuredInt`，**这就是界面上的理智(SP)**，负数 = 恐慌 |

注意 `_state` 和 `CharacterState._hp` 都是 `0x148` —— 一个在 `BattleUnitModel` 上，
一个在 `CharacterState` 上，别混。

### `ObscuredInt` 布局

游戏用 ACTk 的反作弊整数，三个 int 一组：

```
+0  key
+4  hidden
+8  fake      （伪装值，干扰用）
```

真值 = `hidden ^ key`。直接按 int 读会得到垃圾，读取链里必须用 `kind: 'obscured'`。

### buff 链（读取链表达不了，需要容器遍历）

```
BattleUnitModel +0xE0  → BuffDetail
BuffDetail      +0x10  → List<BuffModel>
BuffModel       +0x68  → BuffStaticData
BuffStaticData  +0x18  → string（如 "HanafudaTwo"）
```

il2cpp 容器布局固定：`List<T>` 的 items 在 `+0x10`、size 在 `+0x18`；
`Array` 的长度在 `+0x18`、元素从 `+0x20` 起；`string` 的长度在 `+0x10`、utf16 内容从 `+0x14` 起。

### 战场管理器

`BattleObjectManager`（`dump.cs:16882`）关键字段：

| 字段 | 偏移 | 类型 |
| --- | --- | --- |
| `_currTeamPosition` | `0x28` | `TeamPosition` |
| `_currEnemyTeamPosition` | `0x30` | `TeamPosition` |
| `_unitList` | `0x78` | `Dictionary<UNIT_FACTION, List<BattleUnit>>` |
| `_allUnitDictionary` | `0x90` | `Dictionary<int, BattleUnit>` |
| `_deadUnitList` | `0xB8` | `List<BattleUnitModel>` |
| `_roundDeathCount` | `0xF4` | int |

想从这里拿单位，必须有容器遍历能力（P3 的容器步）。

---

## 四、一个踩了两次的坑：小 getter 钩不住

`CharacterState::get_Hp`、`get_Mp`、`get_IsDead`、`get_IsPanic`、
`BattleUnitModel::IsAlly`、`get_Position` 这几条都**装上了但命中 0**，
同一轮里 `GlobalGameManager::FixedUpdate` 命中 22 次（对照组）。

原因：il2cpp 是 AOT 编译，这种「读字段 + 异或解密」的一行 getter 会被**内联**进每个调用点，
内存里不存在「call 这个函数」的指令，MinHook 改了入口也没人走到。

**结论：钩子要挑带参数、带循环、体积大的方法。** 判断办法不是看它在不在 dump.cs 里，
而是挂上去看命中计数 —— 命中 0 就是内联了。
