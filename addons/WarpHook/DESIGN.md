# WarpHook v2 设计：宿主化 + 配置驱动 + 线程自持

> 目标形态：依赖 WarpHook 的插件**一行 C 都不用写**，`scr.py` 只负责声明配置。
> 本文是实现前的设计稿，先说清楚为什么、怎么做、代价在哪。

---

## 1. 当前问题清单

| 编号 | 问题 | 证据 |
| --- | --- | --- |
| P1 | 游戏刚启动就闪退 | `Player.log` 第 6 行 `Crash!!!`，栈为 `auto_boom` → `BaseThreadInitThunk` |
| P2 | 每个插件都带一份 C 源码与 DLL | AutoBoom 486 / NoGacha 623 / BattleSnark 1483 行，公共部分占 77% / 82% / 32% |
| P3 | 插件 `scr.py` 仍有底层兼容 | 结构体布局、类型宽度、`assert sizeof(...)` 散落各插件 |
| P4 | 启动器一退出，插件行为退化 | NoGacha 的换词逻辑跑在 Python 轮询里，启动器死掉就只弹固定一句 |
| P5 | 加钩子要改 C、重编译、重新部署 | 用户自己无法扩展 |

## 2. P1 崩溃根因（必须先修，与架构改造同源）

`addons/AutoBoom/auto_boom.c` 的 `watcher_thread()`：

```c
if (GetModuleHandleW(L"GameAssembly.dll")) {
    if (g_cfg) g_cfg->ga_found = TRUE;
    try_install();          /* ← 这里从工作线程直接调 il2cpp */
}
```

`GetModuleHandleW` 非空只代表 **DLL 被映射**，不代表 il2cpp 运行时初始化完成。
`try_install()` 里虽然有 `if (!domain) return;`，但域指针可能已非空、程序集数组却还在填充中，
此时 `domain_get_assemblies` / `assembly_get_image` / `class_get_method_from_name` 会读到未完成状态的内存，
崩在 `auto_boom.dll` 自己的工作线程上 —— 与栈完全吻合（`BaseThreadInitThunk` 起点）。

**以前不崩的原因**：注入发生在游戏跑起来之后，watcher 抢跑时域早已就绪。
现在 `register_start` 把注入挂在 gamestart 上，游戏一启动就注入，抢跑成功。

**结论**：il2cpp 调用不能由「我自己的时间表」决定，必须由「游戏的就绪状态」决定。

## 3. 设计原则

1. **所有 il2cpp 调用只在游戏主线程**，且只在确认就绪之后。
2. **工作线程只碰 Win32 与共享内存**，永不调用 il2cpp。
3. **插件零 C**：行为原语由 WarpHook 的宿主 DLL 提供，插件用配置声明「何时做什么」。
4. **注入后自持**：启动器退出不影响已注入的行为，DLL 用内存快照继续跑。
5. **配置向后兼容**：`warp` 段缺失的插件按旧路径（自带 DLL）处理，不强制迁移。

## 4. 三层架构

```
┌──────────────────────────────────────────────────────────────┐
│ 插件层（纯 Python，~60 行）                                    │
│   addon_info.json: { "warp": { hooks, texts, rules, panel } } │
│   scr.py: 读设置 → 组装配置 → PLUGIN.push() → 注入 → 状态转发   │
└───────────────────────────┬──────────────────────────────────┘
                            │ 共享内存（Local\WarpHost_<插件名>）
┌───────────────────────────▼──────────────────────────────────┐
│ 宿主层 warp_host.dll（WarpHook 自带，唯一 C 代码）              │
│   ├─ Bootstrap：等就绪 → 解析导出映射 → 逐个装配钩子            │
│   ├─ HookTable：由配置生成的「类/方法/argc → 事件」表            │
│   ├─ RuleEngine：事件 → every/chance → 行为原语序列            │
│   ├─ Primitives：popup / panel / block / kill / counter        │
│   └─ Reporter：命中数、最后触发、健康状态回写共享内存            │
└───────────────────────────┬──────────────────────────────────┘
                            │ MinHook（游戏主线程回调）
┌───────────────────────────▼──────────────────────────────────┐
│ 游戏进程（GameAssembly / UnityPlayer）                         │
└──────────────────────────────────────────────────────────────┘
```

### 4.1 Bootstrap 就绪判定（修 P1 的核心）

```
阶段 0  等 GameAssembly.dll 被映射          （GetModuleHandleW，纯 Win32）
阶段 1  等 il2cpp_domain_get() 返回非空      （只调这一个函数，未初始化时返回 NULL，安全）
阶段 2  等 domain_get_assemblies 返回非空 且 count >= 8
阶段 3  等首个 assembly_get_image 返回非空
阶段 4  再过 N 毫秒稳定窗（默认 1500ms）后装配钩子
```

任何一步不满足就 `WaitForSingleObject(stop, 250)` 重来，**不重试解析、不提交任何状态改变**。
阶段 1~4 全部通过才 `MinHook` 挂钩；此前 `status` 一律是「等待游戏加载」。

补充保险：装配失败不会崩（全部判空），失败原因写入 `last_error`，由 Python 侧显示。

### 4.2 线程隔离与 standalone 模式（修 P4）

- DLL 在 `DllMain` 里打开并**长期持有**共享内存句柄；启动器进程退出后，只要 DLL 还持着，
  `Local\` 命名映射就继续有效，最后一份配置留在内存里。
- 文案池、随机数、计数、计时器**全部下沉到 DLL**：Python 只负责一次性灌入文本，
  之后每次触发由 DLL 自己选一句 —— 启动器死掉也照常换词。
- 心跳字段：Python 每 2 秒写 `heartbeat = GetTickCount64()`；DLL 发现超过 10 秒没更新，
  切到 `standalone` 模式（继续跑，只不再接受新配置）。这个状态会体现在状态行里。

## 5. 配置协议（`addon_info.json` 的 `warp` 段）

```json
"warp": {
  "host": "warp_host.dll",
  "hooks": [
    { "class": "BattleObjectManager", "method": "OnRoundStart_Prepare", "argc": 1, "event": "round" },
    { "class": "BattleObjectManager", "method": "OnRoundStart_Model_Before", "argc": 1, "event": "round" }
  ],
  "texts": ["记录完毕。你的每一个选择，都已被我归档。", "..."],
  "rules": [
    {
      "event": "round",
      "every": 3,
      "chance": 30,
      "dedupe_ms": 800,
      "do": [
        { "act": "panel", "text": "$random", "hold_ms": 9000 }
      ]
    }
  ],
  "panel": {
    "portrait": "yesod.rgba",
    "bubble": "bubble.rgba",
    "anchor": "bottom-left",
    "portrait_h": 560,
    "bubble_box": [340, 242],
    "bubble_pos": [224, 271],
    "font_size": [21, 19, 17, 16, 14],
    "text_color": [0.17, 0.12, 0.24, 1.0]
  }
}
```

### 5.1 行为原语

| act | 参数 | 语义 | 对应旧实现 |
| --- | --- | --- | --- |
| `popup` | `text`, `title` | 调 `GlobalGameManager.OpenGlobalPopup` 弹原版窗 | NoGacha |
| `panel` | `text`, `hold_ms` | 自建 Canvas：立绘 + 气泡 + 文字 | BattleSnark |
| `block` | `ret` | 拦下原方法（返回指定值），配合 `hooks.block = true` | NoGacha 拦截 |
| `kill` | `delay_ms` | 起独立线程 → Sleep → `TerminateProcess` | AutoBoom |
| `count` | `field` | 计数器自增（也可直接读 DLL 内部状态） | 通用 |
| `log` | `text` | 写 `warp_host.log` | 通用 |

`$random` 在 `texts` 池里随机取一句，由 DLL 内部 xorshift32 完成。

### 5.2 钩子能力

- `event`：自定义事件名，多条规则可挂同一事件。
- `argc`：参数个数（`il2cpp_class_get_method_from_name` 按名字+参数个数匹配）。
- `block`：`true` 时拦截（挂 `void` 返回的方法无效，宿主会自动忽略并记日志）。
- 父类方法自动沿 `il2cpp_class_get_parent` 链查找；虚方法只挂声明处一份（与现在一致）。

## 6. 迁移映射

| 插件 | 现在 | 迁移后 |
| --- | --- | --- |
| AutoBoom | 486 行 C + 177 行 py | **0 行 C** + ~45 行 py；`warp.hooks` 挂 `GlobalGameManager::FixedUpdate`? → 改用 `BattleObjectManager::OnRoundStart_Prepare` + `delay` 原语 |
| NoGacha | 623 行 C + 246 行 py | **0 行 C** + ~50 行 py；`hooks` 挂 `GachaUIPresenter::OnGachaSelected` + `block: true` |
| BattleSnark | 1483 行 C + 399 行 py | **0 行 C** + ~70 行 py；`hooks` 挂两个回合方法 + `panel` 原语 |

WarpHook 自身：`warp_host.dll` 约 1200~1500 行 C（现成代码可复用 80%：`bind_il2cpp`、`find_class`、
`method_pointer`、`resolve_popup_methods`、`show_vanilla_popup`、整套 UI 构建栈）。
`scr.py` 从 982 行缩到 ~300 行（`Runtime` 只剩「发配置 / 注入 / 收状态」）。

**合计 C 代码 2592 行 → ~1400 行；插件侧 Python 822 行 → ~165 行。**

## 7. 分阶段落地

| 阶段 | 内容 | 可验证结果 |
| --- | --- | --- |
| S0 | 宿主 DLL 骨架 + Bootstrap 就绪判定 | 冷启动注入不再崩，状态能到「已挂钩」 |
| S1 | HookTable + RuleEngine + `popup` / `log` | NoGacha 用配置跑通 |
| S2 | `kill` + `block` + 心跳/standalone | AutoBoom 用配置跑通 |
| S3 | `panel` + 资源加载 | BattleSnark 用配置跑通 |
| S4 | 删旧 C 源码，`scr.py` 收敛 | 三个插件目录只剩 py + json + 资源 |

每个阶段都保持「旧插件仍可跑」，不做一次性切换。

## 8. 风险与代价

| 风险 | 说明 | 对策 |
| --- | --- | --- |
| 规则引擎表达力不足 | 以后插件想要「看图说话」之类复杂逻辑 | `hooks` 之外预留 `on_event` 的 Python 回调（启动器在线时生效），DLL 只做离线兜底 |
| `warp_host.dll` 单点 | 一处崩，所有依赖插件一起崩 | 所有 il2cpp 调用判空 + 就绪门闩；装配失败只降级不崩 |
| 配置格式演进 | 加字段要兼容旧版 | `warp.version` 显式版本号，未知字段忽略 |
| 打包体积 | 一个 DLL 服务所有插件 | 约 100KB，远小于各插件各带一份 |
| 资源文件体积 | `yesod.rgba` 998KB、`bubble.rgba` 1.4MB | 已在插件目录，迁移时不动 |

## 9. 待拍板

1. `warp_host.dll` 是否放在 `addons/WarpHook/` 内、由 WarpHook 自己注入（推荐），
   还是由启动器统一注入？
2. AutoBoom 的「延迟 N 秒后弹窗」是否用 `FixedUpdate` 计帧实现，还是用独立线程 Sleep？
   （独立线程更符合你说的「不依赖主线程节奏」，但要保证弹窗仍在主线程）
3. 迁移期间是否需要保留旧 DLL 路径作为回退开关（`warp.host: "legacy"`）？

---

## 10. 落地结果（已实现）

S0–S2 已完成并验证，S3/S4 按用户要求保留 BattleSnark 的自建 UI 栈。

| 插件 | 迁移前 | 迁移后 | C 代码 |
| --- | --- | --- | --- |
| WarpHook | — | `scr.py` + `warp_host.c/.dll`（43520 字节） | 宿主本体 |
| AutoBoom | 486 行 C + 714 行 py | **177 行 py**，声明 1 条钩子 | **零** |
| NoGacha | 623 行 C + 580 行 py | **212 行 py**，声明 2 条钩子 | **零** |
| BattleSnark | 1483 行 C + 942 行 py | 保留自有 DLL（UI 栈扩展性证明） | 保留 |

协议（`warp_host.c` ↔ `scr.py` 的 `Host`）：

```
WARP_HEADER 432B   magic version enabled hooked status last_error heartbeat standalone
                   evt_count hook_installed hook_total panel_step last_event fired
                   ga_found popup_ok boot_at(u64) dedupe_ms reserved0 log_tail[48] vars[8]
                   cmd_seq cmd_ack cmd_type cmd_result cmd_text[256]   ← 命令槽
WARP_HOOK   264B×16 klass[48] method[48] argc event_id every chance actions flags
                   hold_ms delay_ms guard_index guard_value
                   probe_class[48] probe_method[48] probe_index probe_slot guard_var
                   text_base read_base read_count reserved[2]
文案池      128B×256 随机挑一句弹出去（按插件分段，段尾空串当界标）
导出表      64B×13   标准名按固定顺序映射成混淆名
事件 ctrl   16B      head / tail / dropped / pad（环形队列游标）
事件队列    44B×2048 WARP_EVENT { id, hook, tick, a, b, c, d, e, f, g, h }
读取链      48B×64   WARP_READ { arg, nsteps, kind, out, off[4], deref[4] }
总长        131456B
```

钩子表 → 行为的三段式表达力：

1. **探针**（`probe_*`）：调参数对象的 0 参 getter，把整数写进 `vars[]`。
2. **参数门**（`guard_var` / `guard_value`）：命中就彻底放行，既不拦也不弹。
   NoGacha 用它实现「放行付费单抽」——探针读 `GachaPayment.GachaType` 到 `vars[0]`，
   `guard_var=0, guard_value=1` 时直接 `return 0`。
3. **动作**（`actions`）：`ACT_POPUP` 弹原版窗、`ACT_KILL` 结束进程；`flags=HF_BLOCK`
   让原方法不执行。`every` / `chance` / `delay_ms` / `dedupe_ms` / `HF_ONCE` 决定何时触发。

读取链（`reads=`）是第 1 条的通用版：探针只能「调一个 0 参 getter 拿 int」，
读取链能「从任意参数出发，按偏移跳最多 4 跳，落点按 int/float/bool/ptr/obscured
解释」，结果直接写进事件槽 `a/b/c/d`。每跳的动作由 `deref` 位决定：

| `deref` 值 | 动作 |
| --- | --- |
| `0` / `false` | 只加偏移（读内嵌 struct 的字段） |
| `1` / `true`（没写时的默认） | 加偏移后解引用（字段存的是对象引用） |
| `2` / `'list'` | 把当前指针当 `List<T>`，取第 `off` 个元素 |
| `3` / `'array'` | 把当前指针当 `Array<T>`，取第 `off` 个元素 |

链长为 **0** 是另一种意思：不往前走，把参数本身的值当结果。这专给「参数是
值类型」的钩子用 —— `IsNodeCleared(int main, int sub, int node)` 的三个参数
就躺在寄存器上，没有任何偏移可跟。

il2cpp 取字段只有「加偏移 / 先解引用」两种动作，所以前两种就够；后两种是为了
**进容器** —— 管理器身上的单位列表是 `List<BattleUnitModel>`，不遍历就够不着单位。
`List<T>` 的布局固定（`_items` 在 +0x10、`_size` 在 +0x18），`Array` 的 `max_length`
在 +0x18、元素从 +0x20 起，所以按下标取元素不需要类型信息。容器步取的是**引用**
元素，值类型容器暂不支持。

成就那十六种 `BWK_*` 读法全都是「参数形状 × 读路径 × 输出方式」的组合，
有了读取链和容器步，它们退化成十六行配置。

> 边界：读取链读不到**函数返回值**（值在 xmm0/eax）、**字符串**（变长结构）；
> 容器要显式写容器步。另外**一行的 getter 会被 AOT 内联**，内存里没有调用指令，
> 钩子命中 0 —— 选钩子要看方法体积，不是看名字好不好听。

### 事件队列与背压

事件环 2048 格 × 44 字节（约 90 KB）。游标放在 `WARP_EV_CTRL` 的
`head / tail / dropped / pad` 四个 int 里：生产者只碰 `head`，消费者只碰 `tail`，
两边都不加锁（64 位对齐的 int 读写本身是原子的，槽内容在 head 前进之前就写完了）。

读侧跟不上时**不阻塞游戏**，直接把 `tail` 往前推、覆盖最旧的，同时
`dropped` 累加。这个数字会经 `host.events_lost` 暴露出来：

```python
host.events()               # 读一批，读的同时把 dropped 的增量并进 events_lost
host.events_lost            # 引擎侧累计丢了多少条（只增不减）
```

`WarpSource.stats()` 里的 `lost` 就是它。**丢掉的和「没发生」必须能区分** ——
否则成就那边会把「这条内存读晚了」当成「这件事没发生」，规则静默错判。

容量选取：2048 格在 `dedupe` 关掉的 60fps 钩子下能缓冲约 34 秒，开了 `dedupe`
（值不变不投递）后一般几小时都用不完。真要观察长期高频采样，用 `every=N` 降频
比继续扩环更划算 —— 环越大，`GetTickCount()` 取模命中同一槽的概率越低，但
Python 一次性要读的条数也越多，反而更容易把单次 `pump()` 拖长。

### 事件去重（`dedupe=True`）

`FixedUpdate` 这类每帧调用的方法一秒能命中 60 次，一小时就是二十万条事件，
环形队列（2048 格）也撑不了几分钟，消费者只能在垃圾里捞针。所以钩子可以带
`dedupe=True`：**DLL 每次命中照样跑读链，但读出来的值跟上次全一样就不入队**。

```python
host.hook('GlobalGameManager', 'FixedUpdate', argc=0, event=1,
          reads=[{'arg': 0, 'out': 0, 'kind': 'int', 'off': [0x64]}],
          dedupe=True)          # 场景没变就一条都不投
```

三条设计约束：

1. **只有配了 `reads=` 才有意义**。没读链时 `a/b/c` 装的是参数指针，每次都不一样，
   去重等于没做 —— DLL 里也就直接跳过判断。
2. **判断放在自增 `head` 之前**。先占槽位再判断的话，被吞掉那条会在环形队列里
   留个空洞（Python 读到一条 `id=0` 的空事件），所以必须先跑完读链。
3. **只吞事件，不吞动作**。`HF_BLOCK` 的拦截、`HF_ONCE` 的「已经打过」标记、
   命中计数（`reserved[0]`）全都不受去重影响 —— 去重管的是「要不要告诉 Python」，
   不是「要不要做事」。

「上次的值」存在 DLL 进程的静态内存（`g_last_vals[16][8]` + `g_last_valid[16]`），
不进共享内存：布局少改一处就少一次两边对不上的机会，而且插件本来也不需要读它。

命令通道（P5）：除了「挂钩子等游戏自己触发」，py 还能主动命令游戏做事。
`Host.popup(text)` / `Host.kill_game()` 只是往命令槽写 `cmd_type` + `cmd_text` 并递增
`cmd_seq`，然后等 `cmd_ack` 追上；真正的执行发生在游戏主线程——泵点有两个：任何
用户钩子命中时顺带泵一次，以及宿主自己在 `GlobalGameManager::FixedUpdate` 上补的
一条内部钩子（用户钩子已占该地址时自动跳过）。所以 `host.popup("...")` 一行就能让
游戏弹窗，不用关心线程，也不用等战斗回合。

`warp_on_event()` 返回位掩码：bit0 = 拦原函数、bit1 = 执行动作，由 112 个独立 thunk
按 `argc`(0..6) 分派——`GetTakeAttackDmgMultiplier(unit, action, coin, attacker,
isCritical, info)` 这类方法有 6 个参数，出手者（attacker）在第 4 个上，只转发
`a1..a3` 的话「谁打的我」永远读不到。读取链的 `arg` 也是 0..6（0=this，1..6=参数）。

崩溃修复（P1）：`warp_wait_ready()` 五阶段门闩，**不调用 `il2cpp_thread_attach`**；
工作线程只做只读元数据查询，一切 `new` 对象/弹窗都在主线程钩子回调里。
`ga_found` 语义：0 未就绪 / 1 DLL 已映射 / 2 域在加载程序集 / 3 完全就绪。

线程自持（P4）：`warp_host.dll` 自己持有共享内存句柄，心跳超 10s 未更新即置
`standalone=1`，此时仍按最后一次配置继续工作；启动器退出不影响弹窗与计时。

## 11. 命名空间契约（`ADDON_ARG['Namespaces']`）

一个插件提供的能力必须收在**自己的名字**之下，不能占用通用名字。否则根上就是
「谁先注册谁占坑」，整个生态只能存在一套 `il2cpp` / `inject`，第二个想提供同样
能力的插件只能覆盖别人。

WarpHook 注册的是 `warp` 一个顶级 space 加五个子分区：

```
warp              顶级，提供方 WarpHook，带 name / version / description
warp.il2cpp       导出名解析：resolve / names_table / export_mapped
warp.inject       找进程、等引擎、远程线程注入
warp.shm          共享内存：open / SharedMap / ensure_exports
warp.plugin       共享宿主：Host / Runtime / 常量
warp.log          日志：write
```

子分区同时支持两种取法（第二个是子 space 本身，不是别名）：

```python
NS = ADDON_ARG['Namespaces']
WARP = NS['warp']                 # 依赖方只拿 warp 这一层
WARP.il2cpp.resolve()             # 嵌套访问
NS['warp.plugin'].Host            # 扁平访问，等价
```

**依赖方不要写** `ADDON_ARG['Namespaces'].il2cpp` —— 那是把整个容器当自己的
命名空间用了。`NS.space('warp')` 在依赖库没装时返回 `None`，依赖方据此降级。

## 12. 多插件共存的身份规则

`Host` 是全进程单例（挂在启动器的 `AddonManager` 上，跨插件重载共享），因为它
对应唯一一块共享映射、唯一一份 `warp_host.dll`。因此**任何「属于谁」的判断都不能
用实例字段**，`self.addon_name` 只会是第一个创建者的名字。

| 场景 | 规则 |
| --- | --- |
| `Host(...)` 构造 | `addon_name` 是显式参数，直接作为 owner 登记进 `_owners` |
| 钩子 / 文案 | 按 owner 分区存储，`_layout()` 拼成总表时给每段打 `owner` 标 |
| 日志前缀 | `log(msg, owner=...)` 现算，不用实例上的 `log_prefix` |
| 状态 | `status(owner=...)` / `_own_hits(cfg, owner)`，命中数与 `hook_total` 都按 owner |
| 监视线程 | **每插件一条**（`_watch_threads[owner]`），共用一条会让第二个插件永远不播报 |
| 文案池 | 全局 256 条，按开启的插件数均分（还要留一个空串当段尾界标）；台词多的插件不会再被截成一两条 |
| 注入 | 先查心跳与 `ga_found`，宿主已在跑就只 `push` 配置，绝不重复 `LoadLibrary` |
| 托盘菜单 | `_act(owner, fn)` 显式带上身份，菜单回调里没有插件调用栈 |

线程里没有调用栈，`_current_owner()` 认不出是谁——所以 owner 必须在**入口**取一次，
再一路显式传下去。这条规则适用于以后新增的任何按插件区分的行为。


## 13. 代码结构（分文件）

### C 侧（`warp_host.dll`）

原来是一个 1241 行的 `warp_host.c`，按职责拆成 9 个 `.c` + 2 个 `.h`。
`static` 全部去掉（跨翻译单元需要），能揭示的只有 `WarpHostState` /
`WarpHostVersion` 两个导出，和拆之前完全一致。

| 文件 | 职责 |
| --- | --- |
| `warp_layout.h` | 协议层：`WARP_HEADER`(432B)、`WARP_HOOK`(264B)、13 个函数指针类型 |
| `warp_internal.h` | 内部契约：`WARP_IC` / `WARP_SLOT`、全部 `extern` 全局与函数原型 |
| `warp_state.c` | 全局状态、日志、状态码、随机数 |
| `warp_shm.c` | 打开 / 创建共享映射 |
| `warp_il2cpp.c` | 混淆导出名绑定、类与方法解析 |
| `warp_ready.c` | 引擎就绪门闩（等程序集、稳定期、域初始化） |
| `warp_popup.c` | 原版弹窗、杀进程 |
| `warp_action.c` | 挑台词、执行动作、参数探针、单次事件入口 |
| `warp_hook.c` | thunk 表、装配 / 卸载钩子 |
| `warp_cmd.c` | 命令泵（`popup` / `kill_game` 主动调用） |
| `warp_host.c` | 控制线程、`DllMain`（只剩入口） |

编译（`MH` 是 MinHook 目录）：

```bash
gcc -shared -O2 -Wall -s -static-libgcc -o test/warp_host.dll \
  addons/WarpHook/src/warp_*.c \
  "$MH/src/hook.c" "$MH/src/buffer.c" "$MH/src/trampoline.c" "$MH/src/hde/hde64.c" \
  -I addons/WarpHook/src -I "$MH/include" -I "$MH/src/hde"
```

### Python 侧（`warphook/` 包）

`scr.py` 从 2310 行缩到 40 行，只做三件事：把插件目录放进 `sys.path`、
把 `ADDON_ARG` 交给包、注册命名空间。实现按「一层只依赖下一层」拆开：

| 模块 | 行数 | 职责 |
| --- | --- | --- |
| `env.py` | 19 | 插件作用域：`ADDON_ARG` / `ADDON_NAME` / `ADDON_MANAGER` |
| `base.py` | 509 | Win32、共享内存、il2cpp 导出名解析、注入 |
| `host.py` | 823 | `Host`：钩子表与文案池的配置端 |
| `game.py` | 197 | `Gacha` / `GachaBill`：抽卡语义层 |
| `service.py` | 690 | `Runtime` / `Service`：等游戏、注入、心跳、状态播报 |
| `registry.py` | 171 | 组装 `warp` 命名空间、卸载收尾 |

**两条必须知道的规则**：

1. 包里的模块读不到 `exec` 那份 globals，所以 `scr.py` 必须先调
   `warphook.bind(...)`，包内一律用 `env.ADDON_NAME` 这类写法。
2. 插件重载时启动器会重新 `exec` `scr.py`，但 `warphook.*` 已在
   `sys.modules` 里 —— 不清掉的话子模块不会重新执行，模块级单例还是旧的。
   `scr.py` 开头那段 `for _stale in ...` 就是干这个的。

`_owner_of_caller()` / `_caller_dir()` 都改成了「沿调用栈往上找」而不是固定
几层，正是为了让拆包以后不管中间多套几层仍然认得出真正的调用方。
