# 战斗观测 DLL（`battle_watch.dll`）—— 战斗类成就的观测端

只做一件事：**在游戏里读若干个点位，把事实写成文本事件**；判定全部交给 Python。

> 当前版本 **v4**（协议 FBW3）：
> - v3：`SPD` 补整数速度 `osi`/`owi`（速度字段是「×1000 定点数」，见第四节）；
> - v4：新增 `VAL` 事件（**血量 / 理智**，见第四节），结构体多了 4 个偏移，
>   所以魔数改为 **FBW3**、`log_ring` 偏移 **1060**、总大小 **132132**。

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

## 三、共享内存协议（v2，v4 起魔数 FBW3）

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

**架构**：成就只声明数据 → ``functions/achievement/battle_achievements.py`` 的基类把它
转成一条 ``battle_watch.BattleRule`` → 驱动（``battle_watch.py``）负责观测与判定。
加一个新成就基本只要写一个 ``__init__``。

| 成就 | 基类 | 数据（可改） |
|---|---|---|
| 将你李箱，也将我李箱。 | `SkillUseAchievement` | 身份 `10101` + 三技能 `1010103` |
| 仿造的一生 | `SkillUseAchievement` | 身份 `10115`（蜘蛛巢 食指 父辈 李箱）+ 三技能 `1011503`（层数9时转化为 Furioso-Replica），另加受控 ID `134711/138010/955110`（需 actor 身份 = 10115） |
| 呃啊，我腿瘸了 | （速度专用）`battle_watch` 的速度判定 | 身份 `10212` + 整数速度 == 9 |
| 魔法少女的悲剧 | `MentalThresholdAchievement` | 身份 `10913`（绝望骑士 罗佳）/`10312`（憎恶女王 堂吉诃德）+ `threshold=0`（理智 < 0） |
| 神也会受伤吗？ | `DamageTakenAchievement` | 身份 `10705`（狐雨 希斯克利夫）+ `ratio=1.0`（掉血即算） |

三类基类的语义：

- **技能类**（`SkillUseAchievement`）：`ACT` 里出现目标技能 → **回合边界结算**
  （与李箱成就同一套逻辑）。匹配支持三种写法：完整 `skill_ids`、
  `identity_id + tiers`（技能 ID = 身份×100 + 槽位）、`gated_skill_ids`（ID 不带身份的
  转化技能，需 actor 身份匹配）。
- **理智类**（`MentalThresholdAchievement`）：`VAL` 的 `mp < threshold` → **立刻**置位，
  回合边界再兜底复核一次。
- **血量类**（`DamageTakenAchievement`）：`VAL` 的 `hp < mhp * ratio` → 立刻置位。

### 自定义成就怎么写

```python
from functions.achievement.battle_achievements import (
    SkillUseAchievement, MentalThresholdAchievement, DamageTakenAchievement)

class MyAchievement(SkillUseAchievement):
    def __init__(self):
        super().__init__(ach_id="ach_my", name="我的成就", description="…",
                         identity_id=10115, tiers=(3,), rarity="legendary")
```

然后把它 append 到 ``functions/achievement/achievements.py`` 的 ``_battle_achievements`` 元组。
阈值、身份、技能、比例全是构造参数（数据），不用碰 DLL / 驱动。

---

## 七、怎么用 / 怎么看运行情况

```powershell
# 编译（MinGW-w64 gcc + MinHook；默认取 D:\LCTA_CheatingCore-main\vendor\minhook）
powershell -NoProfile -ExecutionPolicy Bypass -File functions\achievement\hook_dll\build.ps1

# 离线自查：打印将要下发的钩子表（含桩解引用结果）、DLL/日志/进程状态，不注入
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

成就解锁在成就日志里**一定有一行**：成就检查有好几条路径（Player.log 事件 / 输入计数 /
内存 / 战斗观测），它们跑在不同线程上、谁先跑到谁解锁，所以现在所有路径都走同一个
“已写过就不再写”的出口（`hook._report_unlocks`），并在监控循环里每轮兜底扫一次
——“成就不声不响就解锁了、日志里却找不到”的情况不会再出现。

启动器还会把子进程 PID 记在 `cache/achievement/hook.pid`，下次启动时如果那个子进程
还活着（上次没退干净）就先收掉它：否则新旧两个实例会抢共享内存，新实例只能静默
“不双钩”（旧的那份代码里就碰上了这个）。

设置项 **「启用成就监测与战斗观测」**（`enable_achievement_hook`）可整体关闭。

---

## 八、排障

| 现象 | 原因 / 处理 |
|---|---|
| 心跳里所有钩子命中数都是 0 | 这些函数当前没被调用（v1 就是这个）→ 把心跳那段日志发我，或跑 `--probe` 看钩子表 |
| 速度/理智/血量没反应 | 先看 `logs/battle_watch.log` 里有没有对应的 `SPD`/`VAL` 行：没有就是钩子没命中或字段偏移不对；有但 `mp=-1000`/`hp=-1000` 就是 `_state` 读失败（看第四节） |
| 成就日志里看不到战斗事件 | 正常：事件默认只进 `logs/battle_watch.log`；要一起看就打开设置项「成就日志记录全部战斗事件」 |
| `ERR prologue mismatch` / `last_error=3` | 游戏更新了而索引没重建：`python -m functions.hook.main update` 后重启游戏 |
| `打开游戏进程失败` | 游戏以更高权限启动过（例如 Steam 用管理员启动）；用管理员权限跑启动器 |
| `CreateRemoteThread 失败` | 杀软拦截注入；加白名单或关掉本功能 |
| `共享内存已存在…本次不注入以免双钩` | 上次成就子进程没退干净；关掉旧进程或重启游戏 |
| 速度界面显示 9 但没解锁 | 先看 `logs/battle_watch.log` 里 `SPD … os=14518 osi=14` —— `osi`/`owi` 才是整数速度（×1000 定点数，见第四节）；确认是整数速度后若仍不中，把日志发我或改 `battle_watch.SPEED_FIELDS` |
| 事件抽取丢行 | 轮询太慢（日志会写 `抽取过慢，丢弃了 N 行`）；调小 `BattleWatch.poll_interval` |

`RND seq=` 里的序号是共享内存会话计数，跨关卡继续累加（不归零）；它只当回合边界用。
