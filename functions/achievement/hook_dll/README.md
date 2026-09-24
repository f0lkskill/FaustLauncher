# 战斗观测 DLL（`battle_watch.dll`）—— 战斗类成就的观测端

只做一件事：**在游戏里读若干个点位，把事实写成文本事件**；判定全部交给 Python。

> 当前版本 **v5**（协议 FBW4）：
> - v3：`SPD` 补整数速度 `osi`/`owi`（速度字段是「×1000 定点数」，见第四节）；
> - v4：新增 `VAL` 事件（**血量 / 理智**，见第四节），结构体多了 4 个偏移；
> - v5：新增 `BUF` 事件（**buff**）+ 配置末尾的 **关注 buff 表**，又多了 4 个偏移
>   → 魔数 **FBW4**、`log_ring` 偏移 **1076**、总大小 **132408**。

```
游戏进程                                      成就监测进程（Python）
┌──────────────────────────────┐            ┌────────────────────────────────────┐
│ battle_watch.dll (MinHook)   │  共享内存   │ functions/achievement/             │
│  ├ 单位速度类钩子（SPD）      │ ─────────▶ │  battle_watch.py                   │
│  ├ 血量/理智类钩子（VAL）     │  事件行     │   ├ 静态解析钩子表（尾调用桩解引用）  │
│  ├ 行动类钩子（ACT）          │  命中计数   │   ├ 注入 + 抽事件 + 规则引擎         │
│  └ 边界类钩子（RND）          │             │   ├ 心跳/状态文件/独立事件日志        │
│                              │             │   └ 战斗类成就只读判定结果            │
└──────────────────────────────┘            └────────────────────────────────────┘
```

设计骨架与 `test/damage_log.c` + `test/damage_log.py` 同一套（共享内存配置、环形日志、
prologue 自检、watcher 线程重试、`LoadLibraryW` 远程线程注入），两份工具互不干扰。

> ⚠️ 边界：本 DLL **只读**（读取一律经 `ReadProcessMemory(GetCurrentProcess())` 带边界校验，
> 不裸解引用、不写游戏内存、不调用游戏函数）。注入行为本身有封号风险，请自行判断。

---

## 一、v1 的教训（很重要）

v1 按 dump.cs 给的 RVA 钩了三个点，**装钩成功、整场战斗却 0 事件**。原因：

```
BattleUnitModel::RefreshSpeed              0x11C89D0  = 33 D2 E9 B9 FA FF FF CC
   → xor edx,edx; jmp 0x11C8490            （尾调用桩，真实实现是 SetRandomSpeed）
BattleActionModelManager::OnRoundStart_Before 0xB63FA0 = 33 D2 E9 19 FE FF FF CC
   → xor edx,edx; jmp 0xB63DC0             （尾调用桩，真实实现是 Init）
BattleActionModel::DoneWithAction          0x11AD140  = 48 89 5C 24 08 ...（真实函数体）
   → 普通战斗里根本没被调用
```

调用方直接调真实实现，所以钩在桩上等于没钩。于是 v2 做了三件事：

1. **静态尾调用桩解引用**：驱动读本机 `GameAssembly.dll` 的字节，遇到
   `33 D2 E9 rel32` / `E9 rel32` 就顺着跳，钩真实实现，并在日志里写明
   `0x11C89D0 (RefreshSpeed) 是尾调用桩 → 改钩 0x11C8490 (SetRandomSpeed)`；
2. **同一地址自动合并**：解引用后撞到同一地址的候选合并成一个钩子（日志记录被合并的键）；
3. **命中计数可观测**：DLL 为每个钩子累加调用次数，驱动轮询后报出
   `观测点开始命中: unit_refresh_speed ×12`，另有每 20 秒一条心跳：
   `心跳: 阶段=观测中（已装钩） PID=3920 | 事件: RND 3 / SPD 36 / ACT 12 | 钩子命中: ...`
   ——"装钩成功但 0 次调用"一眼可见。

---

## 二、观测点（候选池）

| 键 | 符号 | RVA（build 2026-09-17） | kind | 用途 |
|---|---|---|---|---|
| `unit_refresh_speed` | `BattleUnitModel::RefreshSpeed` | `0x11C89D0` → **`0x11C8490`** | unit | 速度初始化公开入口（桩→SetRandomSpeed） |
| `unit_set_random_speed` | `BattleUnitModel::SetRandomSpeed` | `0x11C8490` | unit | 速度掷骰（每回合每单位） |
| `unit_set_speed` | `BattleUnitModel::SetSpeed` | `0x11C7970` | unit_int_bool | 速度被设置/覆盖（带 value 参数） |
| `unit_get_origin_speed` | `BattleUnitModel::GetIntegerOfOriginSpeed` | `0x11C7B50` | unit_get_int | 读有效速度（含覆盖），UI/排序热路径，去重后上报 |
| `unit_round_start` | `BattleUnitModel::OnRoundStart_Before` | `0x11E7380` | unit | 单位回合开始（边界兜底 + 速度） |
| `manager_on_round_start_before` | `BattleActionModelManager::OnRoundStart_Before` | `0xB63FA0` → **`0xB63DC0`** | plain | 回合边界（桩→Init） |
| `manager_init` | `BattleActionModelManager::Init` | `0xB63DC0` | plain | 回合边界（真实实现） |
| `action_on_end_turn` | `BattleActionModel::OnEndTurn` | `0x11ACBA0` | action_int | 行动在回合结束时（技能） |
| `action_done_with_action` | `BattleActionModel::DoneWithAction` | `0x11AD140` | action_int | 行动完成（v1 实测不触发，留作对照） |
| `take_attack_dmg_multiplier` | `BattleUnitModel::GetTakeAttackDmgMultiplier` | `0x11E1D10` | damage_action | **已证实会被调用**：拿 attacker 身份 + action 技能 |

RVA / prologue / 字段偏移都不写死在 DLL 里：驱动从云端笔记 `FaustLauncher.hook_index`
（`functions/hook` 自动生成，含这 11 个钩子与 15 个字段）读出后写进共享内存配置。
拿不到索引时才用 `battle_watch.py` 里的内置回退值（此时 prologue 为空 → 跳过版本自检，
DLL 会写 `WARN prologue check skipped`）。

---

## 三、共享内存协议（v5，魔数 FBW4）

- 名字 `Local\FaustLauncher_BattleWatch`，魔数 `0x33574246`（"FBW3"；v2 是 FBW2）
- 结构体 `BW_CONFIG` ↔ `battle_watch.py` 的 `BWConfig`：`log_ring` 偏移 **1060**、
  总大小 **132132**（C 端 `_Static_assert` + Python 断言 + DLL 回写 `ring_offset`
  /`struct_size` 三重校验）
- 钩子表（Python 写入）：`hook_count` / `hook_rva[12]` / `hook_kind[12]` /
  `hook_prologue[12][16]` / `hook_name[12][40]`；DLL 回写 `hook_hits[12]`
- 事件行（环形缓冲，按 `log_head` 单调递增增量抽取）::

    RND tag=manager_on_round_start_before
    SPD tag=unit_refresh_speed iid=1234 oid=10101 os=7000 osi=7 ow=-1 owi=-1 its=7   （或 eff=..）
    VAL tag=take_attack_dmg_multiplier iid=1234 oid=10705 hp=41 mhp=58 mp=-3        （血量/理智）
    ACT tag=take_attack_dmg_multiplier actor=1234 cmd=1234 skid=1010103 slot=3 tier=3 aoid=10101
    INFO/WARN/ERR ...   （DLL 自己的提示）

- 状态回写：`gameassembly_found` / `verified` / `installed` / `last_error` /
  `event_count` / `round_seq` / `last_log`
- 错误码：`0` 正常、`1` 共享内存不可用、`2` GameAssembly.dll 60 秒未加载、
  `3` prologue 不符（版本不匹配）、`4/5/6` MinHook 初始化/创建/启用失败

---

## 四、字段偏移与混淆类型

> ⚠️ **速度字段的单位（v3 修正，别再踩）**：`_originSpeed`(0xCC) / `_overwritedSpeed`(0xD0)
> 存的是「速度 ×1000」的**定点数**，小数部分是隐藏的同速排序值（同速单位靠它决定先后），
> 不是精度垃圾。直接把字段当速度看会得到 `14518` 这种怪值。
>
> 证据（反汇编本机 `GameAssembly.dll`）：
>
> | 函数 / 常量 | 说明 |
> |---|---|
> | `BattleUnitModel::GetIntegerOfPureOriginalSpeed` | 就是「带符号 /1000」（魔数 `0x10624DD3`） |
> | `BattleUnitModel::GetIntegerOfOverwritedSpeed` | 同上（`<= 0` 原样返回） |
> | `BattleUnitModel::ChangeIntegerPartOfSpeed` | 只改整数部分、保留小数（差值 ×1000 加回 `_originSpeed`） |
> | `BattleUnitModel::SetRandomSpeed` | `Random.Range(lower*1000, upper*1000 + 1000)` 后写 0xCC |
> | `BattleUnitModel::GetSpeedLowerLimit/UpperLimit` | 返回**整数**速度（内部 `Math.Round`，下限 1） |
> | 常量 `_CORRECTION_FOR_SPEED = 1000`、`_MIN_SPEED = 1000` | |
>
> 所以 **界面上看到的速度 = `trunc(字段 / 1000)`**。DLL v3 起 `SPD` 行同时给原始值与换算值
> （`os=`/`osi=`、`ow=`/`owi=`，`osi/owi = trunc(raw/1000)`，负值 `-1` = 本回合还没掷速度，原样保留）；
> `its`(0x184 `_thisTurnIntSpeedOnCmdPhase`) 本来就是整数，不缩放。Python 端两种都认，
> 装了旧 DLL（只有 `os=`/`ow=`）时会自己换算（`battle_watch.SPEED_SCALE`）。

| key | 类::字段 | 偏移 |
|---|---|---|
| `unit_instance_id` | `BattleUnitModel::_instanceID` | `0x60` |
| `unit_origin_id` | `BattleUnitModel::_originID`（身份 ID） | `0x64` |
| `unit_origin_speed` | `BattleUnitModel::_originSpeed` | `0xCC` |
| `unit_overwrited_speed` | `BattleUnitModel::_overwritedSpeed` | `0xD0` |
| `unit_int_speed_turn` | `BattleUnitModel::_thisTurnIntSpeedOnCmdPhase` | `0x184` |
| `unit_state` | `BattleUnitModel::_state`（→ `CharacterState*`） | `0x148` |
| `state_hp` | `CharacterState::_hp`（ObscuredInt） | `0x148` |
| `state_max_hp` | `CharacterState::_maxHp`（ObscuredInt） | `0x11C` |
| `state_mp` | `CharacterState::_mp`（ObscuredInt，**理智/SP**） | `0x158` |
| `unit_buff_detail` | `BattleUnitModel::_buffDetail`（→ `BuffDetail*`） | `0xE0` |
| `buff_detail_list` | `BuffDetail::_grantedBuffList`（`List<BuffModel>`） | `0x10` |
| `buff_model_data` | `BuffModel::_buffData`（→ `BuffStaticData*`） | `0x68` |
| `buff_static_id` | `BuffStaticData::id`（**string**） | `0x18` |
| `action_skill` | `BattleActionModel::_skill`（→ SkillModel） | `0x20` |
| `action_commander_id` | `BattleActionModel::_commanderInstanceID` | `0xB4` |
| `action_actor_id` | `BattleActionModel::_orderedActionActorInstanceId` | `0xBC` |
| `skill_data` | `SkillModel::_skillData`（→ SkillDataModel） | `0x10` |
| `skill_id` | `SkillDataModel::id` | `0x10` |
| `skill_tier` | `SkillDataModel::skillTier` | `0x40` |

> **血量 / 理智（v4）**：`BattleUnitModel::get_Hp()` 的反汇编就是
> `_state[0x148]` → `_hp`（带 null 检查），所以链子是
> `unit[0x148] → CharacterState{ _maxHp@0x11C, _hp@0x148, _mp@0x158 }`，三个值都是
> ACTk `ObscuredInt`。`_mp` 就是界面上的**理智(SP)** —— 同类的常量
> `_maxMp = 45` / `_minMp = -45` 正好就是它的上下限，负数 = 陷入恐慌。
> 读不出来一律发 `BW_VITAL_UNREAD(-1000)`，绝不会被误当成“真的负数理智”。
> DLL 内按 `(单位指针, hp, mp)` 去重，只在上报值变化时发 `VAL`（否则一枚硬币一行）。

> **buff（v5）**：链子是
> `unit[0xE0] → BuffDetail[0x10] → List<BuffModel>`，每个
> `BuffModel[0x68] → BuffStaticData[0x18]` 是一个 **字符串 id**
> （如 `HanafudaTwo` = 组札-芒上月、`FutureEyeOnRodion` = 预知眼，与
> `Lang/LLC_zh-CN/Bufs.json` 的 `id` 一致）。
> il2cpp 容器布局是固定的（不放配置）：`List<T>` → items@0x10 / size@0x18；
> 数组元素从 `+0x20` 开始（每个 8 字节）；`string` → 长度@0x10、utf16 字符@0x14。
>
> 跨进程传名字太占地方，所以配置里带一张**关注 buff 表**
> （`buff_watch_count` + `buff_watch_hashes[32]`，Python 写入名字的 **FNV-1a 64**）；
> DLL 只上报“命中了关注表第几位”的位掩码 `m`，而且**没配关注表时连 buff 链都不读**。
> 两边必须用同一个哈希（自检里有专门的 C 编译对照项）。

`SkillDataModel` 的这两个字段是 **ACTk（Anti-Cheat Toolkit）混淆类型 `ObscuredInt`**：

```c
struct ObscuredInt { int currentCryptoKey; int hiddenValue; int fakeValue;
                     bool fakeValueActive; bool inited; };   // +0/+4/+8/+12/+13
value = hiddenValue ^ currentCryptoKey;
```

DLL 按这个布局解密，并把 `fakeValue` 一起上报（`tf=`）做交叉校验。

---

## 五、业务常量（游戏数据，不是偏移）

| 常量 | 值 | 来源 |
|---|---|---|
| LCB 罪人 李箱 | `10101` | `Lang/LLC_zh-CN/Personalities.json` |
| 黑兽 - 卯 魁首 浮士德 | `10212` | 同上 |
| 李箱 LCB 三技能 | `1010103` | `Skills.json`；技能 ID 编码 = `<身份5位><槽位2位>` |

技能 ID 自带身份与槽位，所以「李箱用了三技能」用 `skid == 1010103` 判定最硬。

---

## 六、战斗类成就怎么判定

**架构（重要：驱动不认识任何具体成就）**

```
成就模块（functions/achievement/data/*.py）
  └─ 业务常量（身份 ID / 技能 ID / 阈值）+ 基类构造 → 登记一条 BattleRule
battle_achievements.py
  └─ 四类数据基类：Skill / Speed / MentalThreshold / DamageTaken
battle_watch.py（驱动）
  └─ 只管事件字段解释 + 一张规则表：按 kind 统一求值，没有 if 成就名的分支
```

规则类型是**统一清单**（``battle_watch.RULE_KINDS``），加新类型 = 在 ``BattleRule`` 里
加一个 ``match_*`` + 一个 ``RULE_KIND_*``，调用处不用改：

| kind | 看的事件 | 命中条件 | 何时置位 |
|---|---|---|---|
| ``skill`` | ``ACT`` | ``skill_ids``，或（``identity_ids``+``tiers``）拼出的技能 ID，或（``gated_skill_ids`` 且 actor 身份匹配），或 ``any_skill``（只看身份） | **技能动画结束**（收尾事件 ``action_done_with_action``/``action_on_end_turn``，或 1.5s 静默期；回合边界兼着兜底） |
| ``speed`` | ``SPD`` | 身份命中且 ``fields``（默认全部速度字段）里任一 == ``threshold`` | 立刻（边界兜底） |
| ``mental`` | ``VAL`` | 身份命中且 ``mp < threshold`` | 立刻（边界兜底） |
| ``hp`` | ``VAL`` | 身份命中且 ``hp < mhp * ratio`` | 立刻（边界兜底） |
| ``buff`` | ``BUF`` | 身份命中且身上有目标 buff（名字哈希对关注表） | 立刻（边界兜底） |
| ``presence`` | ``VAL``/``SPD``/``BUF`` | 目标身份出现在单位表里（“在场上”） | 立刻（边界兜底） |

部分类型还支持 **回合窗口** ``max_round`` / ``min_round``（0 = 不限）：例如
「首个回合身上带着某 buff」就用 ``max_round=1``。

“立刻”类全走同一个求值器（``BattleWatch._eval_immediate_locked``）；技能类走
``settle_turn()``，调用时机是**技能动画结束**（收尾事件 / 静默期），不再是回合边界 ——
否则一个技能要等到整回合结束才报，玩家已经看不到因果关系了。

复合成就主类 ``CompositeAchievement`` 把多条规则按任意组合拼起来：
``require``（``and/or/not`` 表达式）、``chain``（顺序约束）、``implied``（“完成 1 也算完成 2”），
并且支持 ``state_only=True`` 的**状态条件**（如“场上是否存在某身份”——他在场是状态，
不该当成事件先后）。

当前七个战斗类成就的数据（全部写在各自模块里，驱动只是“照数办事”）：

| 成就 | 文件 | 基类 | 数据 |
|---|---|---|---|
| 将你李箱，也将我李箱。 | `data/ach_yisang_lcb_s3.py` | `SkillUseAchievement` | 身份 `10101` + 技能 `1010103` / `tiers=(3,)` |
| 呃啊，我脚崴了 | `data/ach_faust_kui_speed9.py` | `SpeedValueAchievement` | 身份 `10212` + `value=9` + 四个速度字段 |
| 仿造的一生 | `data/ach_index_furioso.py` | `SkillUseAchievement` | 身份 `10115` + 技能 `1011505/1011503` + 受控 ID `134711/138010/955110` |
| 魔法少女的悲剧 | `data/ach_magical_girl_tragedy.py` | `MentalThresholdAchievement` | 身份 `10913`/`10312` + `threshold=0` |
| 神也会受伤吗？ | `data/ach_heathcliff_sunshower_hurt.py` | `DamageTakenAchievement` | 身份 `10705` + `ratio=1.0` |
| 这他妈的烂牌！ | `data/ach_custom_examples.py` | `BuffPresentAchievement` | 身份 `10813` + buff `HanafudaTwo` + `max_round=1` |
| 心脏，心脏！ | `data/ach_custom_examples.py` | `CompositeAchievement` | 10916 用技能 → 10916 带 `FutureEyeOnRodion` → 场上存在 `10716`（带顺序约束） |

> 最后两个在**同一个文件**里 —— 注册时会把模块里所有 ``BaseAchievement`` 子类
> 按定义顺序自动实例化，所以一个文件写多个人格/系列成就不用逐个去登记。

### 自定义成就怎么写

```python
from functions.achievement.battle_achievements import (
    SkillUseAchievement, SpeedValueAchievement, BuffPresentAchievement,
    FieldPresenceAchievement, CompositeAchievement, Condition,
    MentalThresholdAchievement, DamageTakenAchievement)

# 1) 单条件：身份 10115 用了三技能
class MyAchievement(SkillUseAchievement):
    def __init__(self):
        super().__init__(ach_id="ach_my", name="我的成就", description="…",
                         identity_id=10115, tiers=(3,), rarity="legendary")

# 2) 复合：先 A 再 B，且场上要有 C（C 是状态条件）
class MyCombo(CompositeAchievement):
    def __init__(self):
        a = Condition("a", battle_watch.BattleRule(key="ach_my.a", kind="skill",
                                                   identity_ids=(10916,), any_skill=True))
        b = Condition("b", battle_watch.BattleRule(key="ach_my.b", kind="buff",
                                                   identity_ids=(10916,),
                                                   buffs=("FutureEyeOnRodion",)))
        c = Condition("c", battle_watch.BattleRule(key="ach_my.c", kind="presence",
                                                   identity_ids=(10716,)), state_only=True)
        super().__init__(ach_id="ach_my_combo", name="…", description="…",
                         conditions=(a, b, c), chain=("a", "b"),
                         require="a and b and c")
```

同一个文件里可以写多个派生类；然后只需把**模块名**加到
``functions/achievement/achievements.py`` 的 ``_battle_achievement_modules``
元组（一行）。身份/技能/阈值/比例全是构造参数，**不需要碰 DLL，也不可能需要碰驱动**。

---

## 七、注入流程（身份校验 / 挂起窗口 / DLL 版本）

`battle_watch.py` 侧（`BattleWatch._run` → `_inject`）在“进程一出现就注入”之上加了四道闸 ——
“钩子没装上 / 事件全 0”历史上多半不是 DLL 写错了，而是**注错了进程 / 注错了时机 /
注的是旧文件 / 游戏 DLL 已经更新**：

| 闸 | 做什么 | 关键日志 |
|---|---|---|
| ① 身份校验 | 按 PID 取映像路径（`QueryFullProcessImageNameW`），必须等于配置的 `game_path\LimbusCompany.exe`；同名多进程时取**创建时间最新**那个 | `跳过 PID …：映像是 …，与配置的游戏（…）不一致` |
| ② 稳定性 | 找到的进程必须连续存活 1s（`GAME_STABLE_SECONDS`，与 mod loader 的判定约定一致），排除 Steam 拉起的短命引导进程 | `PID … 存活不足 1s（疑似 Steam 引导进程/闪退）` |
| ③ 挂起窗口 | 注入期间让进程**不执行游戏代码**：进程本来就挂着（全部线程挂起）就直接借用；否则临时挂起它全部线程（`SuspendThread`，用返回值区分“本来就挂起”，退出时**只恢复自己加的那一次**），注入完立刻恢复 | `检测到游戏进程已处于挂起态（N/N 个线程挂起）→ 直接在这个挂起窗口内注入` / `已建立注入窗口：挂起 N 个线程` |
| ④ 落点回读 | 注入后枚举目标进程模块，确认 `battle_watch.dll` 已加载、且路径 == 刚注入的那份文件；进程里本来就有同名模块（`LoadLibraryW` 只会返回旧句柄）会直接告警 | `已确认目标进程加载 battle_watch.dll @0x…` / `来自 …，不是刚注入的 …` |

> 为什么不是“等进程自己挂起”：LimbusCompany.exe 是 **Steam 拉起的**
> （`steam://rungameid/1973530`），我们既不是 `CreateProcess` 的调用方，也看不到
> `CREATE_SUSPENDED` 那个窗口，而正常游戏进程不会静止挂起 —— 所以 ③ 的做法是
> **自己建立挂起窗口**（如果碰巧它真的处于挂起态，就顺手借用）。

### 注入的是哪份 DLL（“确保 DLL 是最新版本”）

- 运行时**只注入编译好的文件，绝不现编译**；发布包（`build.py`）只把 `battle_watch.dll`
  复制进 `_internal/hook_dll/`，`.c` / `.ps1` / README 不进分发产物。
- 候选路径可能同时存在多份（打包副本 `_MEIPASS/hook_dll/`、开发目录
  `functions/achievement/hook_dll/`、部署目录 `_internal/hook_dll/`），`dll_path()` 取
  **mtime 最新**的一份，并把被忽略的旧份写进日志
  （`发现 N 份 battle_watch.dll，选用最新的一份 …`）—— 否则开发目录里重新编译之后，
  打包版会一直注入包里那份旧 DLL。注入时还会把该文件的**大小 / mtime / sha256 前 12 位**
  打进日志与状态文件。
- `build.py` 额外防一手：`battle_watch.c` 比 DLL 新时会直接报
  “发布包里的是旧构建，请先跑 build.ps1”。

### 游戏的 DLL（GameAssembly.dll）是不是最新

| 检查 | 时机 | 判定 |
|---|---|---|
| 索引 vs 磁盘 | 建完钩子表（`_check_index_freshness`） | `index.game.gameassembly_size` / `pe_timestamp` vs 磁盘文件；不一致 → `⚠ 偏移索引与磁盘上的 GameAssembly.dll 不匹配 …（跑 python -m functions.hook.main update）` |
| 进程内 vs 磁盘 | DLL 报 `GameAssembly 已加载` 之后（`_verify_gameassembly`） | 读远端模块 PE 头（时间戳 / 映像大小 / 入口 RVA）与磁盘文件比对 → `游戏 DLL 校验通过` 或 `⚠ 游戏 DLL 不一致` |

⚠ **判据不能用头部哈希**：加载器会往头部写几个字节（实测 `python.exe` 偏移 `0x13A`
处存的是模块基址），磁盘文件与内存映像的头部并不逐字节相等；所以用
`时间戳 + 映像大小 + 入口 RVA`（`pe_identity_same()`）作为判据。

状态文件 `cache/achievement/battle_watch_status.json` 因此多了三段：`injection`
（注入的映像 / DLL + 文件信息）、`index_game`（索引记录的游戏构建）、
`gameassembly_check`（远端 vs 磁盘 + `same` 布尔）。

---

## 八、怎么用 / 怎么看运行情况

```powershell
# 编译（MinGW-w64 gcc + MinHook；默认取 D:\LCTA_CheatingCore-main\vendor\minhook）
powershell -NoProfile -ExecutionPolicy Bypass -File functions\achievement\hook_dll\build.ps1

# 离线自查：钩子表（含桩解引用）+ 要注入的 DLL（大小/mtime/sha256）+ 游戏 DLL 新鲜度 + 同名进程映像，不注入
python -m functions.achievement.battle_watch --probe

# 看观测状态 + 事件日志末尾（游戏通过启动器跑过之后才有）
python -m functions.achievement.battle_watch --status

# 独立调试（注入 + 实时打印事件与状态）
python -m functions.achievement.battle_watch

# 离线自检（不需要游戏）：布局 / 桩解引用 / 真注入 / 状态机 / 状态文件 / 成就
python test\battle_watch_test.py
```

正常流程不用手动跑：启动器启动游戏时会拉起 `main.py --achievement-hook`，
其中 `AchievementHook.start_monitoring()` 里 `start_battle_watch()`。**看运行情况的三处**：

| 看什么 | 位置 | 关键行 |
|---|---|---|
| 成就日志（**只留成就相关**） | `logs/achievement_hook.log` | `已注入 …` / `prologue 自检通过` / `已装钩 N 个观测点` / `观测点开始命中: …` / `心跳: …` / `★ …判定…` / `[成就] 解锁: …`；每行都带 `[HH:MM:SS]` 时间轴 |
| 事件流（全量） | `logs/battle_watch.log` | 每一行 `RND/SPD/VAL/ACT`，带时间戳 |
| 机器可读状态 | `cache/achievement/battle_watch_status.json` | 阶段/注入 PID/每个钩子的 rva+命中数/`rule_hits`（每条判定）/`watched_vitals`（目标身份的血量理智） |

两个日志都在**每次实例启动时清空重写**（只留本次运行）。事件行默认**不**进成就日志；
想看就把设置项 **「成就日志记录全部战斗事件」**（`achievement_log_verbose`）打开，
或直接用 `logs/battle_watch.log`。

成就日志的写入方式（修「日志损坏」时改的）：启动时清空一次，之后用
**`O_APPEND` + 每行一次 `os.write` + 线程锁**（`hook._LogSink`）。
以前是 `open(path,'w')` + `write`：句柄带固定偏移，一旦有第二个/残留实例也在写，
或文件中途被清空，就会按旧偏移覆写 → 错位、中间夹 NUL 空洞的“损坏”文件。
启动器现在会**先收掉上次的子进程（`cache/achievement/hook.pid`，校验进程映像才是自己人）
再清空日志**；子进程发现另一个实例在跑时会**跳过清空并告警**。

成就解锁在成就日志里**一定有一行**：成就检查有好几条路径（Player.log 事件 / 输入计数 /
内存 / 战斗观测），它们跑在不同线程上、谁先跑到谁解锁，所以现在所有路径都走同一个
“已写过就不再写”的出口（`hook._report_unlocks`），并在监控循环里每轮兜底扫一次
——“成就不声不响就解锁了、日志里却找不到”的情况不会再出现。

启动器还会把子进程 PID 记在 `cache/achievement/hook.pid`，下次启动时如果那个子进程
还活着（上次没退干净）就先收掉它：否则新旧两个实例会抢共享内存，新实例只能静默
“不双钩”（旧的那份代码里就碰上了这个）。

设置项 **「启用成就监测与战斗观测」**（`enable_achievement_hook`）可整体关闭。

---

## 九、排障

| 现象 | 原因 / 处理 |
|---|---|
| 心跳里所有钩子命中数都是 0 | 这些函数当前没被调用（v1 就是这个）→ 把心跳那段日志发我，或跑 `--probe` 看钩子表 |
| 日志里没有“已注入” | 看同段日志的前几行：`跳过 PID … 映像不一致`（注错进程）/ `存活不足 1s`（Steam 引导进程）/ `CreateRemoteThread 失败`（杀软）/ `打开游戏进程失败`（权限）|
| 改了 DLL 代码但没生效 | 看 `发现 N 份 battle_watch.dll，选用最新的一份 …`：说明注的是另一份（旧）副本；`发现 N 份` 那句后面列的就是被忽略的路径 |
| `⚠ 偏移索引与磁盘上的 GameAssembly.dll 不匹配` | 游戏更新过： `python -m functions.hook.main update` 重建索引 |
| `⚠ 游戏 DLL 不一致`（进程内 vs 磁盘） | 进程加载的 GameAssembly.dll 不是磁盘上那份（游戏正在更新/加载了旧版本）→ 重启游戏；若目录里的文件已更新过就先 `update` |
| 游戏内模块已有同名 battle_watch.dll | `LoadLibraryW` 不会重新加载同名模块 → 重启游戏（旧模块随进程退出消失）|
| 速度/理智/血量没反应 | 先看 `logs/battle_watch.log` 里有没有对应的 `SPD`/`VAL` 行：没有就是钩子没命中或字段偏移不对；有但 `mp=-1000`/`hp=-1000` 就是 `_state` 读失败（看第四节） |
| buff 成就没反应 | 1) `logs/achievement_hook.log` 启动时应有一行「关注 buff N 个: …」——没有就说明 `battle_watch.watched_buff_names()` 是空的（成就没登记 / 没在模块列表里）；2) `logs/battle_watch.log` 里搜 `BUF`：有行但掩码 `m=0` 就是哈希对不上（改过 C 或 Python 的 fnv1a64？自检里有 C/Python 对照项）；根本没 `BUF` 行就是 buff 链偏移不对（链见第四节） |
| 启动后整台机器卡顿 | 一般是**游戏更新后的索引重建**（capstone 解密 + Il2CppDumper，满核 1~2 分钟），不是观测本身。启动器已把 hook 子进程改成 `BELOW_NORMAL_PRIORITY_CLASS`（不再抢桌面），弹窗空闲时也不 60fps 空转 |
| 成就日志里看不到战斗事件 | 正常：事件默认只进 `logs/battle_watch.log`；要一起看就打开设置项「成就日志记录全部战斗事件」 |
| `ERR prologue mismatch` / `last_error=3` | 游戏更新了而索引没重建：`python -m functions.hook.main update` 后重启游戏 |
| `打开游戏进程失败` | 游戏以更高权限启动过（例如 Steam 用管理员启动）；用管理员权限跑启动器 |
| `CreateRemoteThread 失败` | 杀软拦截注入；加白名单或关掉本功能 |
| `共享内存已存在…本次不注入以免双钩` | 上次成就子进程没退干净；关掉旧进程或重启游戏 |
| 速度界面显示 9 但没解锁 | 先看 `logs/battle_watch.log` 里 `SPD … os=14518 osi=14` —— `osi`/`owi` 才是整数速度（×1000 定点数，见第四节）；确认是整数速度后仍不中，就改那个**成就模块**里的 `fields`/`value`（例：`data/ach_faust_kui_speed9.py`）——驱动没有可调的"速度阈值" |
| 成就日志出现空洞 / 乱码 / 被杀断 | 两个实例在写同一个文件（旧实现是固定偏移覆写）。现在：启动器先收残留子进程再清空；写入改成 `O_APPEND` 单行原子写；发现有别的实例时会跳过清空并写一行告警 |
| 弹窗动画末尾卡顿 / 像卡死 | 旧版把成就轮询（含一次 ~400ms 的读内存）跑在**驱动动画的主线程**上。现在：轮询在独立线程（`ACHIEVEMENT_POLL_SEC`）；内存读取从 ~400ms 降到 ~7ms（不再 `spawn tasklist`，改 ctypes 枚举）；卡片背景改 C 级合成 + 缓存；每帧最多新建 1 张卡；启动时预热 Toplevel/图片 |
| 弹窗描述被截断 | 现在按**像素宽度自动换行**（显式 `\n` 也认；最多 `MAX_DESC_LINES` 行，超出用省略号），卡片高度随行数自适应 |
| 事件抽取丢行 | 轮询太慢（日志会写 `抽取过慢，丢弃了 N 行`）；调小 `BattleWatch.poll_interval` |

`RND seq=` 里的序号是共享内存会话计数，跨关卡继续累加（不归零）；它只当回合边界用。
