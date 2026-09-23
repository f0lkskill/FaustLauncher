# functions/hook —— 边狱巴士偏移索引（`FaustLauncher.hook_index`）

自动把「游戏更新 → 偏移全变」这件事变成「跑一条命令 / 什么都不用做」。

```
GameAssembly.dll + 加密的 global-metadata.dat
        │  ① 拿明文 metadata：静态解密（离线）或运行时内存 dump（游戏在跑）
        ▼
   标准明文 global-metadata.dat
        │  ② Il2CppDumper
        ▼
   dump.cs（78 MB / 198 万行，含每个方法的 RVA 与每个字段的偏移）
        │  ③ 解析 + 运行时校验（必要时内存里重定位）
        ▼
   偏移索引 ──④──▶ 云端笔记 FaustLauncher.hook_index
        │
        ├─ 注入 DLL：取 rva + prologue，prologue 不符就不装钩（防旧偏移打新版本）
        ├─ 成就模块：取 targets.enkephalin 的指针链（云端 → 本地缓存 → 内置默认）
        └─ test/damage_log.py：`--api-url <笔记地址>` 直接切过来（cheat_damage 兼容块）
```

实测（2026-09-23，游戏 build `2026-09-17`）本流水线复现出的值，与官方
`web.lcta.top/cheat_damage.json` **完全一致**：

| 目标 | RVA | prologue（前 16 字节） |
|---|---|---|
| `BattleUnitModel::GetTakeAttackDmgMultiplier` | `0x11E1D10` | `48 8B C4 53 55 56 57 41 54 41 55 41 56 41 57 48` |
| `BattleUnitModel::GetOpponentFaction` | `0x11C3750` | `48 83 EC 28 48 8B 01 48 8B 90 90 01 00 00 FF 90` |

---

## 一、快速开始

```powershell
# 看现状（本地索引 vs 游戏文件是否匹配，不联网不 dump）
python -m functions.hook.main status

# 完整更新：解密 → dump → 解析 → 写本地缓存 → 上传云端笔记
python -m functions.hook.main update

# 只生成不上传 / 忽略缓存强制重建
python -m functions.hook.main update --dry-run
python -m functions.hook.main update --force

# 看索引 / 只解 metadata / 只跑 dumper
python -m functions.hook.main show
python -m functions.hook.main decrypt
python -m functions.hook.main decrypt --memory        # 改成从运行中的游戏内存 dump
python -m functions.hook.main dump

# 生成 C 头文件（给自编译的注入 DLL 用）
python -m functions.hook.main gen-header --out hook_index.h

# 运行时校验/重定位数据链（需要游戏在跑）
python -m functions.hook.main locate --key enkephalin
python -m functions.hook.main locate --class BattleUnitModel    # 按类名找模块槽位

# 离线自检（不需要游戏/网络）
python test/hook_index_test.py
```

依赖：`capstone`（静态解密用，`pip install capstone`；仓库 `requirements.txt` 已加）。
Il2CppDumper 本地没有时会自动从 GitHub Release 下载到 `cache/hook/tools/il2cppdumper/`，
若你机子上已有（如 `Desktop\win-x64-net8`），会直接复用。

---

## 二、metadata 解密（这一步是整条链路的前提）

Il2CppDumper 自己**不做解密**，拿到被保护过的 metadata 会直接报
`ERROR: Metadata file supplied is not valid metadata file`。边狱巴士就是这种情况：

```
global-metadata.dat 头 4 字节实测 = A0 EF A3 ED（不是标准的 AF 1B B1 FA）
前 17 MB 熵 ≈ 8.0（加密/置乱），尾部 ~2 MB 是明文（能搜到 mscorlib / Assembly-CSharp）
```

所以本模块准备了两条路，按代价从低到高自动选择：

### 1) 静态解密（离线、不需要游戏运行）

`metadata_recovery/` 是一条**无参考文件**的还原流水线（移植自 LCTA 项目）：

| 阶段 | 做什么 |
|---|---|
| locate | 在 GameAssembly.dll 里扫 xorshift 字节模板 + 反汇编特征评分，定位解密入口函数 |
| extract | 指令级提取参数（header 大小/种子/表地址/各节 seed） |
| verify | 解密 header 后自动判定布局（`count_offset_size` 等）+ 节段结构门 |
| solve | 31 个节的锚点间隙链拼装（无参考文件） |
| rebuild | 重建标准 metadata + 四重自验证（sanity/version、无缝拼接、dataIndex 单调、结构门） |

命令行：`python -m functions.hook.main decrypt`（约 40 秒，产物落在
`cache/hook/dump/<指纹8位>/standard-rebuilt.dat`）。它会打印 `run-report.md`，
里面每个阶段的裁决都能查。

> 版本表在 `metadata_recovery/universal/versions.py`。当前游戏是 **IL2CPP v39**
> （31 节）。如果哪天游戏跳版本（例如 v40），`verify` 会 REVIEW、`solve`
> 需要新版本的节名/记录大小表 —— 那时往 `versions.py` 加一张表即可。

### 2) 运行时内存 dump（游戏在跑时优先，几秒钟）

原理：**磁盘上加密，但运行时一定在内存里解密成标准布局** —— 因为 IL2CPP 运行时
是把 metadata 当结构体直接用的（`Il2CppGlobalMetadataHeader* header = s_GlobalMetadata`），
不还原成标准布局它自己都跑不起来。

`metadata_source.dump_from_memory()` 的做法（纯 ctypes，不需要 Frida、不需要管理员，
读同用户进程即可）：

1. 优先扫"尺寸 ≥ 32 MB 的私有区域"，搜标准魔数 `AF 1B B1 FA`，命中后校验头部
   （版本、节表、偏移范围），算出 metadata 长度 = `max(offset+size)`；
2. 万一魔数没搜到，用**磁盘文件的明文尾部字节**当锚点：在内存里搜到这段字节后，
   按"锚点在文件里的偏移"反推头部地址，再核对那里的魔数；
3. 整段读出来，写 `memory-global-metadata.dat`，再做一次完整校验
   （魔数 + 节范围 + `mscorlib` 出现在 string 节附近）。

顺带说：这也是 Windows 上"动态 dump metadata"最省事的路子 ——
比 Frida 方案少装一轮工具链（Frida 方案参考 `frida-il2cpp-bridge` /
Zygisk-Il2CppDumper，Android 上更常见）。本模块只需要 `ReadProcessMemory`。

---

## 三、Il2CppDumper 怎么用

```powershell
Il2CppDumper.exe <GameAssembly.dll> <global-metadata.dat> <输出目录>
```

- 第三个参数是**输出目录**，别给路径加引号（它不会剥引号，会当成相对目录把产物
  写到工具目录里去）；
- 无人值守必须把 `config.json` 的 `RequireAnyKey` 设成 `false`，否则 dump 完会
  等按键卡住 —— 本模块自己写了一份 `config.json`（同时关掉 `GenerateDummyDll` /
  `GenerateStruct` 省时间与体积）；
- 输出里最有用的就是 `dump.cs`：C# 伪代码，**方法上方是
  `// RVA: 0x11E1D10 Offset: 0x11E1CA0 VA: 0x181E1D10 Slot: 168`，
  字段行尾是 `; // 0x28`**（静态字段的偏移是"静态区内的偏移"，实例字段是"对象内偏移"）。

所以"从 dump.cs 里取偏移"就是两步：搜类名 → 读注释。`dump_cs.py` 把 198 万行
流式扫一遍只要 **2~3 秒**，且只保留 focus 范围内的符号（否则 JSON 会有几十 MB）。

---

## 四、怎么"明确指定要 hook 的函数"

三种粒度，按需要选：

1. **只改 `targets.py` 里的 `HOOK_TARGETS`**（推荐）
   ```python
   HookTarget(
       key="take_attack_dmg_multiplier",
       symbol="BattleUnitModel$$GetTakeAttackDmgMultiplier",   # dump.cs 里的 "类::方法"
       description="战斗单位受击伤害倍率",
       compat_field="rva_get_take_attack_dmg_multiplier",       # 写进 cheat_damage 兼容块的字段名
   )
   ```
   名字就写 dump.cs 里的（`类::方法` 或 Il2CppDumper script.json 的 `类$$方法` 都认）。
   **同名重载会取第一处**（与官方 payload 的做法一致：`BattleUnitModel` 是 4 参数版、
   `BuffAbility` 是 6 参数版，我们要的是前者），想区分就把类名写全。

2. **临时查一个符号**（不写代码）
   ```powershell
   python -m functions.hook.main symbols --name BattleUnitModel::GetOpponentFaction --focus BattleUnitModel
   ```
   输出 RVA / 字段偏移；要 hook 别人的函数就用它查出来，然后加进 `targets.py` 固化。

3. **直接用 dump.cs 自己搜**（`grep GetTakeAttackDmgMultiplier dump.cs`）——
   最灵活，但每次更新都要重来，所以才有了第 1 种。

索引里每个 hook 长这样（`show` 可以看到）：

```json
"hooks": {
  "take_attack_dmg_multiplier": {
    "symbol": "BattleUnitModel::GetTakeAttackDmgMultiplier",
    "alias": "BattleUnitModel$$GetTakeAttackDmgMultiplier",
    "rva": 18750736, "rva_hex": "0x11E1D10", "va": 6461201680,
    "slot": 168, "overloads": 1,
    "prologue": "48 8B C4 53 55 56 57 41 54 41 55 41 56 41 57 48"
  }
}
```

---

## 五、C 语言注入 DLL 怎么用这些偏移

### 5.1 取基址 + 算真实地址

```c
uintptr_t base = (uintptr_t)GetModuleHandleW(L"GameAssembly.dll");
void *target = (void *)(base + LIMBUS_TAKE_ATTACK_DMG_MULTIPLIER_RVA);
```

注意 `GetModuleHandle` 的时机：**必须在游戏加载完 GameAssembly.dll 之后**再取，
`DllMain(DLL_PROCESS_ATTACH)` 里 GameAssembly.dll 往往还没加载（返回 NULL）。
稳妥做法是起一个线程轮询，或等模块列表里出现它再装钩。

### 5.2 装钩前用 prologue 自检（务必保留这一步）

```c
static BOOL prologue_matches(void *p, const unsigned char *expect, size_t n)
{
    return memcmp(p, expect, n) == 0;
}

if (!prologue_matches(target, LIMBUS_TAKE_ATTACK_DMG_MULTIPLIER_PROLOGUE, 16)) {
    /* 本机 DLL 与索引不是同一个版本 → 拒绝装钩，避免把游戏打崩 */
    return FALSE;
}
```

### 5.3 MinHook 示例（只读观测，不改数值）

```c
#include "MinHook.h"

/* 签名要对上 dump.cs：BattleUnitModel::GetTakeAttackDmgMultiplier(
 *     BattleActionModel action, CoinModel coin, BattleUnitModel attacker, bool isCritical)
 * IL2CPP 成员函数在 Windows 上是 __fastcall：this, 参数..., methodInfo */
typedef float (__fastcall *fn_take_dmg)(void *self, void *action, void *coin,
                                        void *attacker, int8_t isCritical, const void *mi);
static fn_take_dmg original = NULL;

static float __fastcall hook_take_dmg(void *self, void *action, void *coin,
                                      void *attacker, int8_t isCritical, const void *mi)
{
    float value = original(self, action, coin, attacker, isCritical, mi);
    /* 你的逻辑：例如按阵营过滤（attacker 的 faction）后记录/改值 */
    return value;
}

BOOL install(void)
{
    uintptr_t base = (uintptr_t)GetModuleHandleW(L"GameAssembly.dll");
    void *target = (void *)(base + LIMBUS_TAKE_ATTACK_DMG_MULTIPLIER_RVA);
    if (!prologue_matches(target, LIMBUS_TAKE_ATTACK_DMG_MULTIPLIER_PROLOGUE, 16))
        return FALSE;
    if (MH_Initialize() != MH_OK) return FALSE;
    if (MH_CreateHook(target, (LPVOID)hook_take_dmg, (LPVOID *)&original) != MH_OK) return FALSE;
    return MH_EnableHook(target) == MH_OK;
}
```

本仓库 `test/damage_log.c` 就是这套模式的完整实现（只读观测版，含共享内存日志环形缓冲、
prologue 自检、错误码回写），可以直接对照。

### 5.4 生成头文件

```powershell
python -m functions.hook.main gen-header --out hook_index.h
```

产物形如：

```c
#define LIMBUS_GA_SHA256        "E893CE93…"
#define LIMBUS_GA_SIZE          156323328ULL
#define LIMBUS_TAKE_ATTACK_DMG_MULTIPLIER_RVA      18750736ULL
#define LIMBUS_TAKE_ATTACK_DMG_MULTIPLIER_RVA_HEX  0x11E1D10ULL
static const unsigned char LIMBUS_TAKE_ATTACK_DMG_MULTIPLIER_PROLOGUE[16] = { 0x48, … };
#define LIMBUS_ENKEPHALIN_BASE_OFFSET  0x7BB4F90ULL
#define LIMBUS_ENKEPHALIN_OFFSETS      { 0xB8, 0x80, 0x18, 0x28 }
```

---

## 六、数据链（读游戏数值的指针链）与"自动重定位"

外面读游戏数值靠多级指针链（Cheat Engine 那种）：

```
GameAssembly.dll + base_offset → +0xB8 → +0x80 → +0x18 → +0x28 → int32
```

`base_offset` 就是模块数据节里的一个**静态槽位**，它**每次更新都会变**，但它指向的
东西有稳定特征：

- 槽位里的指针 `P` 指向堆上的 `Il2CppClass`：`*(P+0x00)` 是 `Il2CppImage*`（落在模块内）、
  `*(P+0x10)` 是**类名字符串**；
- 所以：**知道类名 → 就能把槽位重新扫出来**。

`locator.py` 的三级策略：

1. 旧偏移先直测（游戏没更新时 0.1 秒出结果，读出来的值落在合理区间即认定有效）；
2. 旧偏移失效 → 按 `root_class` 类名扫模块可写数据节，找"指向该类 Il2CppClass 的槽位"，
   再用值域二次校验；
3. 连类名都不知道（首次）→ **结构性发现**：扫所有候选槽位、沿链读值、值在合理区间
   且类名可读的才算命中，命中后把类名/字段名回填进索引 —— 以后就永远走第 2 条快路。

回填还能更进一步：`attribute_chain()` 用 dump.cs 里"偏移 == 链上该级偏移"的字段反查
字段名，于是链会变成 `类::字段` 的形式，下次更新先用名字从新 dump 里解析偏移、
再按类名重定位槽位 —— 整条链自愈，不再需要人工 CE。

> 首次运行前建议先跑一次 `python -m functions.hook.main locate --key enkephalin`（游戏在跑），
> 让它把类名认出来并写进笔记；之后每次游戏更新都是全自动。

---

## 七、成就模块怎么用（`functions/achievement/memory_reader.py`）

### 7.1 索引里的 battle 钩子与 `fields` 段

索引除了上面两类目标，还带两组给**战斗事件观测**用的内容（细节见
[`functions/achievement/hook_dll/README.md`](../achievement/hook_dll/README.md)）：

```json
"hooks": {
  "unit_refresh_speed":            { "rva": 18629584, "prologue": "33 D2 E9 B9 FA FF FF CC …" },
  "action_done_with_action":       { "rva": 18182464, "prologue": "48 89 5C 24 08 57 48 83 …" },
  "manager_on_round_start_before": { "rva": 11943840, "prologue": "33 D2 E9 19 FE FF FF CC …" }
},
"fields": {
  "unit_origin_id":  { "symbol": "BattleUnitModel::_originID",  "offset": 100 },
  "skill_id":        { "symbol": "SkillDataModel::id",          "offset": 16 },
  "skill_tier":      { "symbol": "SkillDataModel::skillTier",   "offset": 64 }
  // …共 11 个字段，全部由 dump.cs 现算
}
```

- 这三个 hook 的语义在 `targets.py` 的 `HOOK_TARGETS`（`group="battle"`）里声明，
  要加观测点就加一条；字段清单在 `targets.BATTLE_FIELDS`；
- 消费方：`functions/achievement/battle_watch.py`（读 RVA / prologue / 字段偏移后写进
  注入 DLL 的共享内存配置）与 `test/damage_log.py --api-url <笔记地址>`（读 `cheat_damage` 兼容块）。

### 7.2 读指针链

```python
from functions.achievement.memory_reader import memory_target, refresh_chain_from_cloud

refresh_chain_from_cloud(background=True)     # 启动时后台拉一次云端笔记
target = memory_target("enkephalin")          # 索引 → 本地缓存 → 内置默认
reader = LimbusMemoryReader()
value = reader.read_enkephalin()
```

- 拿索引**不联网**（进程内记忆 → `cache/hook/hook_index.json`），所以不会卡读取；
  云端刷新由后台线程做一次，拿到新链后下次读取自动生效；
- 索引里的 `gameassembly_size` 与本机 GameAssembly.dll 不一致时**拒绝使用**该链
  （那是别的游戏版本的偏移，用了只会读出垃圾），并打印原因；
- 拿不到索引就回退到代码里的内置常量（`ENKEPHALIN_TARGET`）。

---

## 八、文件一览

| 文件 | 作用 |
|---|---|
| `paths.py` | 游戏路径解析（设置 → Steam VDF）、缓存布局、GameAssembly 指纹（size+sha256） |
| `memory.py` | 进程内存读写/扫描（ctypes）：区域枚举、多级指针链、模式扫描、指针收集 |
| `metadata_source.py` | 明文 metadata 三条路（磁盘 / 静态解密 / 内存 dump）+ 头部布局自动识别 |
| `metadata_recovery/` | 离线解密流水线（定位→提取→验证→求解→重建，移植自 LCTA 项目） |
| `dumper.py` | Il2CppDumper 的获取（复用/自动下载）、config、执行、产物定位 |
| `dump_cs.py` | dump.cs 流式解析（类型/方法 RVA/字段偏移，支持 `类::方法` 与 `类$$方法` 查法） |
| `locator.py` | 运行时重定位：走链校验、按类名找槽位、结构性发现、字段名回填 |
| `targets.py` | **要盯住什么**（钩子符号 + 数据链的稳定描述），改这里就能加目标 |
| `index.py` | 索引模型 / 本地缓存 / 云端笔记读写 / 发布体积预算 / C 头文件渲染 |
| `updater.py` | 编排（指纹快路径 → 解密 → dump → 解析 → 校验 → 落盘 → 上传）+ 后台自动更新 |
| `main.py` | 命令行（status/update/pull/push/show/gen-header/decrypt/dump/locate/symbols） |
| `test/hook_index_test.py` | 离线自检（头部布局 / dump.cs 解析 / 索引体积 / locator / 内存 dump）|
| `test/battle_watch_test.py` | 战斗观测离线自检（共享内存布局 / 真注入 DLL / 事件状态机 / 成就判定）|

缓存（都可以随时删）：

```
cache/hook/
├── hook_index.json            # 本地索引（完整版，成就模块读它）
├── published.json             # 已发布版本标记（避免重复上传）
├── tools/il2cppdumper/        # Il2CppDumper + 我们的 config.json
└── dump/<指纹8位>/
    ├── standard-rebuilt.dat   # 解密后的明文 metadata（复用，省 40 秒）
    ├── memory-global-metadata.dat  # 若走的是内存 dump
    ├── run-report.md          # 解密流水线报告
    └── out/dump.cs            # Il2CppDumper 产物
```

---

## 九、何时会自动更新

- 成就监测进程在游戏启动时（`functions/achievement/hook.py` → `_start_hook_index_refresh`）
  会：① 后台拉一次云端笔记里的指针链；② 调 `updater.auto_update_async()` 检查索引，
  **指纹没变就直接返回**（0.2 秒），变了才真的跑解密+dump（游戏在跑时优先内存 dump，几秒）。
- 想关掉自动更新：设置项 **「自动刷新游戏偏移索引」**（`config/settings.json`
  → `auto_update_hook_index`）设为 false，之后只有手动跑 CLI 才会更新。

---

## 十、排障

| 现象 | 原因 / 处理 |
|---|---|
| `Metadata file supplied is not valid metadata file` | 拿的还是加密的磁盘文件；用本模块的 `decrypt` / `update`，别直接喂 Il2CppDumper |
| 成就战斗观测报 `prologue 自检失败`（DLL `last_error=3`） | 游戏更新了而索引没重建：`python -m functions.hook.main update` 后重启游戏 |
| 静态解密报 `缺少 capstone` | `pip install capstone`（或 `main.py decrypt --install-capstone`） |
| 静态解密 `solve` 阶段 REVIEW | 游戏的 metadata 版本表变了，往 `metadata_recovery/universal/versions.py` 加新版本节表 |
| `没有可用的 Il2CppDumper` | 手动下载 Release 解压到 `cache/hook/tools/il2cppdumper/`，或放开 `--no-download` |
| 写回云端报 `413 Content Too Large` | 笔记服务对 body 有硬限制；索引已按 48 KB 预算逐级裁剪符号表（`index.NOTE_BUDGET_BYTES`），要更多符号就调大它并确认服务端放行 |
| 数据链 `verified: false` | 更新时游戏没在跑；下次游戏运行时会自动校验/重定位 |
| 结构性发现有多个候选 | 看日志里的候选列表，用 `locate --class <类名>` 确认后把它填进 `targets.py` 的 `root_class` |
| 读出来的值明显不对 | 索引与本机 GameAssembly.dll 不是同一个版本（看 `status` 的 `index_matches`），跑一次 `update` |

---

## 十一、边界与风险

- 本模块只做**只读**分析（读文件、读内存）与**写云端笔记**；不注入、不改游戏内存、
  不修改游戏文件。注入/改值是 `test/damage_log.c` 那类工具的事，风险自负。
- 反作弊：`dump.cs` 里能看到 `ACTk.Runtime.dll`（Anti-Cheat Toolkit）。本模块不碰游戏
  进程的写权限，也不挂钩运行时函数，但**注入类工具无论如何都有封号风险**，请自行判断。
- 笔记是公开可读的（同一服务上的其它笔记同样如此），别把个人信息放进去 —— 索引里只有
  偏移/符号/哈希。
