## 0.9.22 — GC 句柄回归（64 位）：三次「IsLoadedBank 崩溃」同根定案

**结论先行**：0.9.18 / 0.9.19 / 0.9.21 三次 `IsLoadedBank` 崩溃（同形栈
`runtime_invoke → AV`）真因**不是重载匹配**，而是 **`make_str` 造的字符串没有
GC 根**。0.9.15 拆掉句柄后，对象槽里是裸指针，而共享内存 MAP 不在 il2cpp GC
的扫描范围里 —— 下一次 GC 就把字符串回收，随后的 `call` 拿到悬空指针直接崩。
0.9.21 的「本机没有 `IsLoadedBank(string)`」结论**作废**：那是 LIST 输出缓冲
残留造成的误读，dump.cs:571721 明确有两个重载，`sig='S'` 的 typed 匹配一直
是对的。

- `warp_slot_put` 恢复句柄路径（`gchandle_new` / `gchandle_free`），句柄表
  `g_gc_handles[]` 从 `unsigned int[32]` 改为 **`uintptr_t[]`**：0.9.15 拆句柄时
  误判的「free 会崩」真因是 32 位截断 —— Unity 6（Boehm 64 位）的句柄是
  pointer-sized，截断后的值传回 `gchandle_free` 才 AV。现在 free 的是完整
  64 位、由我们自己 new 的句柄，恒安全。
- `warp_cmd_list` 输出缓冲改整块 `memset`（原来只清 `out[0]`，上一次 LIST 的
  残留行还在，py 侧按 `\0` 切分会切出 `m.Boolean)->S` 这类碎片行）。
- 事件 cache 落槽（`warp_action.c` 的 `warp_slot_put(...,0)`）行为不变；
  `MAKE` / `STR` / `CALL` 返回值落槽挂强句柄，`RELEASE` 走 put(NULL) 自动解句柄。

## 0.9.21 — LIST 标注签名匹配 + 沿基类链列方法

- `LIST` 命令支持 `"类名::方法名|签名串"`：除列出每个重载，还在**会被 `call(sig=...)`
  选中的那一个**后面标 ` [match]`。纯元数据遍历，不 invoke —— 用它就能在不动游戏
  的前提下回答「这个签名到底挑到了哪个重载」。
- `warp_cmd_list` 沿 `il2cpp_class_get_parent` 往上走最多 8 层：原来只列本类声明的
  方法，`SoundManager::get_Instance` 这类继承来的 getter 永远列不出来（`call` 能调到
  是因为 `class_get_method_from_name` 会查基类，两条路径的行为本来就不一致）。
- `il2cpp_class_get_parent` 早在 15 项导出时代就有（index 12），本次只是把 LIST 用上，
  导出表没有变动。
- 顺带记一条实测结论：**本机版本 `SoundManager` 没有 `IsLoadedBank(string)`**，
  只有 `IsLoadedBank(UnityEngine.AddressableAssets.AssetReference)`。所以「先查音库
  是否已加载」这个思路在本版本走不通，别再用它。

## 0.9.20 — 新增 LIST 诊断命令：只读方法签名，不再拿游戏试错

`IsLoadedBank` 经 `runtime_invoke` 必崩，而它有两个 1 参重载（`AssetReference` /
`string`）。v10 的类型匹配看起来对，但每次验证都以「游戏崩了」结束 —— 这种靠赔一次
重启来排除变量的方式不可接受，所以加了一条**只读**诊断通道。

- 新命令 `WARP_CMD_LIST`（8）：给 `"类名::方法名"`，宿主遍历 `class_get_methods`，
  把每个重载拼成 `Name(参数类型,参数类型)->返回类型` 写进 MAP 尾部的命令缓冲
  （`WARP_CMD_BUF_*`，4×64=256 字节），py 侧 `read_buf(0)` 取回。
- 只调元数据接口（`class_get_methods` / `method_get_name` / `method_get_param_count` /
  `method_get_param` / `method_get_return_type` / `type_get_name`），**绝不 invoke**。
- py 侧 `Host.list_methods(name, timeout)`。
- 附 `test/_v10_list.py`：一次列出 `IsLoadedBank` / `LoadBankFromLocal` /
  `TryCreateInstance` / `StartAddBGM` / `TryStartBattleBgmByName` / `ApplyBGMData` 的重载。

## 0.9.19 — 对象参数传槽号，修掉 64 位指针被截断

`WARP_HEADER.vars` 是 8 个 **32 位**整数槽，而 `call(..., args=(('slot', 27),))` 往里面塞的是
64 位对象指针 —— 高 32 位在写进共享内存时就丢了。游戏侧拿到的是截断后的野指针，
访问其字段即 AV。

真机表现：`IsLoadedBank` / `LoadBankFromLocal` 一调就「方法抛了异常」或直接超时，
随后进程崩，崩溃栈永远是 `hk_warp_pump → warp_pump_commands → warp_cmd_call →
warp_safe_invoke+0x22`（`call *0x30(%rax)` 即 `runtime_invoke`）。看起来像「调游戏方法
就会崩」，实际是参数根本没传对。

- C 侧 `warp_cmd_build_params` 的 `WARP_CMD_ARG_P` 分支：`vars[i]` 现在按**对象槽号**
  解释，指针由宿主侧 `warp_objects()[v]` 查表取出（越界返回 `BAD_ARGC`）。
- Python 侧 `Host._pack_args` 的 `('slot', n)` 改为传真槽号，不再传真指针。
- 教训：共享内存里跨进程传的东西，先问清楚「这个字段有多宽」，别假设 C 的 `int` 装得下指针。

## 0.9.18 — 协议 v10：按参数类型选重载

**这次是「防崩」而不是「加功能」**：0.9.16/0.9.17 三次把游戏打崩，根因
都是**同参数个数的重载选错**。

### 重载歧义是病根
`SoundManager.IsLoadedBank` 有 `IsLoadedBank(AssetReference)` 与
`IsLoadedBank(string)` 两个 1 参重载。宿主原来只按「名字 + 参数个数」找
方法（`il2cpp_class_get_method_from_name`），必然挑到第一个 —— 把 C 字符串
当对象指针传进去，崩在 GameAssembly 内部。

### v10 的做法（照旧插件 BattleBGMExtend 的 `method()`）
- 新增 7 个导出：`il2cpp_class_get_methods` / `method_get_name` /
  `method_get_param_count` / `method_get_param` /
  `method_get_return_type` / `type_get_name` / `il2cpp_free`
  （`WARP_EXPORT_COUNT 15 → 22`，MAP 178064 字节）。
- `warp_find_method_typed()` 遍历类的全部方法，名字、参数个数、每个参数的
  类型名三重比对才返回；`il2cpp_class_get_method_from_name` 退为兜底。
- `Host.call(..., sig=...)` 传类型串，写在命令文本的 `|` 之后：
  `S`=String `B`=bool `I`=int `F`=float `L`=long `D`=double `V`=void，
  `O`/`?` 不校验，末尾 `&` 表示 byref。
  例：`sig="S"`、`sig="S,B,B"`、`sig="S,FMOD.Studio.EventInstance&"`。

### 音库加载彻底关掉
`LoadBankFromLocal` 对已加载的 bank 重复调用会崩（连 `Master.strings.bank`
都崩）。白名单里**永久移除** `SoundManager::LoadBank` / `LoadBankFromLocal`；
`audio.ensure_bank()` 改成只查 `IsLoadedBank(string)`（`sig='S'`），
没加载就返回失败，交给调用方决定。

# WarpHook 更新记录

这里只记 WarpHook 自身的改动。启动器本体（`functions/`、`web/`）的改动不在这个文件里。

看完整历史：`git log --oneline -- addons/WarpHook/`

## 0.9.17

协议 **v9**：命令通道能接 out 参数了 —— 值类型返回值（FMOD 的
`EventInstance&`）终于能传出去。这一版把「换 BGM」补成跟旧插件一样的四步。

**一、命令的 out 参数缓冲（`('buf', n)`）。**

有些游戏方法要一个可写的值类型落点，`SoundManager.TryCreateInstance(string,
out EventInstance)` 就是。il2cpp 的 `runtime_invoke` 要求那个参数直接指向内存，
而插件进程没法往游戏堆里塞一块（也没法替它分配）。做法是把 MAP 尾部开 4 块
64 字节缓冲（`WARP_CMD_BUF_OFFSET`），参数类型多一个 `'m'`：C 侧把
「MAP 基址 + 块内偏移」当参数传进去 —— 共享内存在游戏进程里本来就是可写的，
游戏写进去，Python 侧 `read_buf(n)` 读同一块。

**二、`audio.try_create`：换曲前先验名字。**

旧插件的 `switch_rule` 在停原曲**之前**先调 `TryCreateInstance`，失败就报
「Cannot create BGM; original music retained.」直接返回。我们之前没这步，
于是曲名拼错时先停掉原曲、`StartAddBGM` 再静默失败，玩家只剩静音。
现在 `audio.play(..., check=True)` 默认走预检，名字无效就不动原曲。

**三、一个反直觉的取证结论。**

`Battle_Cp9_Boss_10` 这类名字**不是 FMOD 事件名**：遍历全部 `.bank`（867 个）
零命中，只在 `.assets.bank` 里以 `Battle_Cp9_Boss_10_AR` / `_MR` 的形式存在
（那是音频资源名）。`BGM_Default_S7_3.bank` 里真正的事件名是 `Battle_1_0`、
`Battle_2_S1` 这种。所以曲名要从 bank 里取，不能照抄规则表。

## 0.9.16

协议 **v8**：钩子能改参数了 —— 从「看着游戏做事」变成「改掉游戏要做的事」。
另外放开音频方法的直调白名单（0.9.15 已证明崩点是句柄不是 invoke）。

**一、钩子参数改写（`rewrite=`）。**

`Host.hook(..., rewrite=(参数序号, 槽号))`：命中时把第 N 个参数换成对象槽
里的指针，再照常调原函数。槽里通常先放一个 `make_str` 造好的 il2cpp String，
于是「游戏要放 A 曲」变成「游戏放 B 曲」，全程不调游戏方法。

C 侧只在 thunk 里替换一个形参，不构造任何对象；String 的归属仍在 Python 侧。
MAP 尾部追加 `WARP_REWRITE[32]`（8 字节/条），前面所有偏移不动。

**二、`audio.play` 解禁。**

白名单加入 `BattleSoundGenerator` 的 `StartAddBGM` / `StopBGM` /
`StopAddedBGM` / `StartBGM` / `PauseBGM` 与 `SoundManager::StopBGM`。
`allow_unsafe` 参数随之取消 —— 换曲走旧插件同一套三步顺序，不再需要逃生门。

## 0.9.15

0.9.14 的白名单拦住了「乱调游戏方法」，但白名单内第一条真机连调就崩了
—— 崩点不在游戏方法里，在我们自己写槽的句柄回收上。

**一、对象槽不再挂 GC 句柄（崩溃修复）。**

现象：`host.call("BattleObjectManager::get_Instance", ret="ref", out_slot=28)`
第一次成功，第二次起 `失败(-1)`，随后整条命令通道超时、游戏崩。

`Player-prev.log` 的栈把范围缩到 `warp_slot_put`：

```
warp_slot_put.part.0+0x3F   <- call il2cpp_gchandle_free
warp_cmd_call+0x31F
warp_pump_commands+0x164
hk_warp_pump+0x36
GameAssembly (gchandle_free 内部)
```

即「往同一个槽写第二次」时，先解掉上一次挂的强句柄，`gchandle_free`
在 GameAssembly 内部炸了。句柄本身不可信，这条路径整段关掉：对象槽
只存裸指针。槽里装的都是长命对象（场景单例、战斗单例）和当场用掉的
临时对象，不需要强引用保护。

**二、命令结果加 BUSY 哨兵。**

`warp_pump_commands()` 是先记 `cmd_ack` 再执行，而 `cmd_result` 要到执行
完才写。py 侧一看到 ack 到位就把上一条的旧值当结果读走 —— 这就是那次
第二次调用返回 `失败(-1)` 的直接原因。现在取走命令时先写
`WARP_CMD_RES_BUSY`(-2)，跑完再写 rc；py 侧遇到 BUSY 继续等。

## 0.9.14

`Host.call()` 这条路本身就是风险源 —— 这一版不再试图「保护」它，而是
默认不让它走。另外补掉 0.9.12 引入的一个重装回归。

**一、`Host.call` 改白名单。**
真机 18:08 / 18:21 / 18:44 三次崩溃全部源于「插件调了游戏自己的方法」。
现在 `call()` 只放 `SAFE_CALLS` 里的四条：

- `BattleObjectManager::get_Instance`
- `GlobalGameManager::get_Instance`
- `BattleSoundGenerator::IsBattleBgmPlaying`（只读 getter，实测 0.02s）
- `BattleSoundGenerator::get_CurrentBgmIndex`（同上）

其他方法一律返回 `未在安全白名单（...）`，要试必须显式 `unsafe=True`。
`audio.play()` / `stop()` / `pause()` 内部那几个换曲调用已标好 `unsafe=True`。

**二、VEH + `longjmp` 彻底废弃。**
0.9.12 的异常保护在真机上的表现是：接住第一击之后游戏还能活一分多钟，
然后崩在完全无关的地方 —— `Player.log` 里整条栈上一个 `warp_host` 帧
都没有。原因是 `longjmp` 跳过了 il2cpp 的托管栈展开，运行时状态变脏，
最后由游戏自己踩到。

托管异常本来就通过 `&exc` 正常返回，不需要插手；原生访问违例拦下来也
救不回来，只会把状态弄得更烂。所以 `warp_safe_invoke()` 里的 VEH 注册
改成 `if (0)` 关掉，只保留直调 + `exc` 检查。

**三、修 0.9.12 的重装回归：`s_mh_ready` 没复位。**
`warp_uninstall()` 里 `MH_Uninitialize()` 之后忘了清 `s_mh_ready`，于是
第二次重装时 `warp_mh_ensure()` 看见标志还是 TRUE 就直接返回，而 MinHook
其实已经反初始化 —— 结果 23 条钩子全部 `hook: create failed`，整张钩子表
死掉（含成就），只能重启游戏。真机 18:35 撞到。现在 `MH_Uninitialize()`
后面紧跟 `s_mh_ready = FALSE;`。

## 0.9.13

`Host.call()` 依然能弄死游戏 —— 0.9.12 的异常保护有个真 bug，而且
`StartAddBGM` 本身就不是能安全调用的方法。

**一、0.9.12 的 VEH 没认线程（真 bug）。**
`AddVectoredExceptionHandler` 是进程级的，`s_invoke_depth > 0` 时任何线程
的任何访问违例都会被 `longjmp` 到主线程的 `jmp_buf` 上 —— 拿别人的栈跳回
自己的帧，两层栈一起坏掉，于是第一击被接住了、几百毫秒后进程还是死
（`Player.log` 里栈是 `hk_warp_pump → warp_pump_commands → warp_slot_put`，
全是无辜的路过代码）。

- `warp_safe_invoke()` 记录 `s_invoke_tid`，VEH 里 `GetCurrentThreadId()`
  不一致就 `EXCEPTION_CONTINUE_SEARCH`。

**二、`StartAddBGM` 确认不能调。**
就算异常保护修好，它内部对 FMOD 实例状态的操作也会把进程带走。所以
`audio.play()` 现在**默认直接拒绝**（`ok=False`，不再发命令），要冒险得
显式传 `allow_unsafe=True`。

只读的 `audio.is_playing()` / `audio.current_index()` 是安全的，实测
`0.02s` 返回（`IsBattleBgmPlaying → 1`、`get_CurrentBgmIndex → 1`）。
真要做 BGM 替换，得走「钩住游戏自己的换曲调用、替换字符串参数」那条路，
需要协议支持字符串参数 —— 还没做。

## 0.9.12

修三件事，都是 BGM 真机验收时暴露的。

**一、`Host.call()` 能把游戏打崩 —— 现在打不动了。**
0.9.10 的 `audio.play` 直接 `runtime_invoke` 了 `StartAddBGM`，在非战斗场景下
它内部碰 FMOD 的句柄会访问违例，整个游戏进程直接消失（`Player.log` 栈顶三帧
全在 `warp_host`，反查到 `warp_cmd_call` 里 `call *0x30(%rax)`，即
`g_ic.runtime_invoke`）。插件一个调用就能崩掉用户的游戏，这是不能留的。

- `warp_cmd.c` 新增 `warp_safe_invoke()`：用 `AddVectoredExceptionHandler`
  只接管「我们正在 invoke」这个窗口里的异常，`longjmp` 回来变成一次失败返回；
  正常路径零开销。`warp_cmd_call` 与 `warp_probe_int` 都改走它。
- `audio.play()` 新增 `require_battle=True`：先确认 `sceneState == 1`（战斗）
  再放，不在战斗里返回 `{'ok': False, 'reason': '不在战斗场景'}`。

**二、装配阶段「类还没加载」的钩子槽现在会重试。**
il2cpp 的类是懒加载的，DLL 在 `engine ready` 就装配，那会儿
`BattleObjectManager` 还不存在 → `hook: class not found` → 该槽一辈子装不上，
插件表现成「逻辑不执行、也不报错」。BattleBGMExtend 的回合钩子就是这么丢的。

- 新增 `warp_retry_hooks()`，主循环每 2 秒补一次未装上的槽，装上打印
  `hook installed (late)`。
- MinHook 初始化提成 `warp_mh_ensure()`，重试路径也能确保它已就绪。

**三、`StartAddBGM` 只能点在战斗里这件事写进文档。**
`audio.py` 的模块注释与 `play()` 的 docstring 都写明时机约束。

## 0.9.11

修掉「重载插件时启动器整个消失」的崩溃（没有 traceback，日志停在
`载入插件 WarpHook...` 那一行）。

根因不在载入，而在**上一步的卸载**：`on_unload()` 会解除共享内存映射，可
`Live` / `Service` / `gacha` 起的后台线程只收到 `_stop.set()` 就没人等了。
线程下一轮 `host.beat()` / `host.read()` 访问的正是刚被解除映射的那块地址 ——
访问违规发生在后台线程，主线程日志已经往前走了几行，所以看起来像
「载入时崩」。没开游戏也会崩，因为 `Host.block()` 会自己建映射。

- **`Host.close()` 新增 `_closed` 标记**，关闭后 `block()` 一律返回 `None`。
  这样还在跑的线程拿到的是一次立刻返回的 `False` / `None`，不会再碰已释放的地址，
  也不会把映射重新建起来（只置 `_block=None` 是拦不住的，`block()` 是惰性打开的）。
- **`Live.close()` / `Service.stop()` 先 `host.close()` 再 join 线程**（5 秒）。
  顺序很关键：先关视图，线程里正在跑的 `scene()` 一次十几个字段本来每个都要等
  命令通道超时，关掉视图后立刻返回，join 才等得及。
- **`GachaWatcher.stop()` 也 join**。
- 新增复现脚本 `test/_reload_crash.py`：同一进程内模拟启动器
  `reload_addons()` 三轮（载入 WarpHook + BattleBGMExtend → 卸载 → 删
  `sys.modules` → 再来一轮），修复前稳定 `EXIT=139`，修复后三轮全过。

## 0.9.10

给插件「放一首 BGM」的能力，并把 `BattleBGMExtend` 从自带 DLL 的老插件移植成
纯 WarpHook 插件。

- **新增 `warphook/audio.py`**：`play(host, name)` / `stop(host, restore=True)` /
  `pause(host, value)` / `is_playing(host)` / `current_index(host)`。
  播放序列照抄老插件的成功路径 —— `BattleSoundGenerator.StopBGM(0, 0)` →
  `StartAddBGM(短名, STOP_MODE=1, 0)`，短名是 `event:/BGM/Battle/` 之后的部分
  （`StartAddBGM` 收的是短名，不是完整 event 路径）。
- **新增 `warp.audio` 命名空间**（给要自己拼序列的插件）与 **`game.bgm()` 门面**
  （`bgm/bgm_stop/bgm_playing/bgm_index`，默认等宿主就绪再发，和 `popup` 一致）。
  `Live.wait_ready()` 从 `popup` 里抽出来，两者共用。
- **`BattleBGMExtend` 移植版（2.0.0）**：删掉自带 `battlebgmextend.dll` 与
  `il2cpp-api-names.txt`，只留 `rules.json` + `icon.png`，靠 `requires: ["WarpHook"]`
  取能力。触发侧从「钩 `BuffDetail.RightAfterGetAnyBuff` + `TLS`」。改成
  `game.on_round_start` + `Unit.buff()`，9 条规则与四种条件原样保留，
  换战斗自动清状态，战斗结束 `bgm_stop`。
- 行为差别写在插件里：`has_buff()` 是「buff 在列表里」而不是
  `HasActivatedBuff` 的「已激活」，判定用 `stack > 0` 近似。
- **没有搬的部分**：老插件那套 30 多个音频方法的「锁定」（防止游戏把曲子切走）
  与 bank 预加载。附加曲会不会被游戏自己的换曲逻辑掐掉，要靠真机验证，
  如果会，走重放而不是拦截。

## 0.9.9

协议 **v7**：让插件能用「一行调用」读游戏对象。三件事——读链加宽、命令通道
代读、高层门面。

- **读链 4 跳 → 8 跳（`WARP_READ` 48B → 80B）**。「遍历 → 单位 → 模型 →
  状态 → 血量」刚好 4 跳，一步富余都没有；buff 名字那条要 6 跳，4 跳进不去。
  加宽后一条链能从头走到尾。`WARP_MAP_BYTES` 172928 → 177104（前面所有偏移
  不变，只在尾部追加），`HOST_VERSION`/`WARP_VERSION` = 7，`host_alive` 按
  `version≥7` 拒绝旧 DLL。
- **新增命令 `CMD_READ = 7`（代读）**。Python 把一条 `WARP_READ` 写到 MAP 尾部
  的 `代读链`（`WARP_CMD_READ_OFFSET`），连同对象槽号发命令，DLL 在游戏主线程
  跑 `warp_read_chain`，值写 `vars[6]`、遍历链活跃数写 `vars[7]`。
  `warp_read_chain` 去掉 `static` 供 `warp_cmd.c` 调用。**为什么必须代读**：
  插件在启动器进程，裸读游戏地址必崩（0.9.8 实测 exit 139）。
- **`Host.read(slot, chain, kind, detail=False)`**：一次同步往返读一个值，
  真机 20–40 ms，不占钩子槽、不用重装钩子表；`read_object()` 改走它
  （保留 `read_local()` 给同进程诊断）。
- **新增 `warphook/fields.py`（字段表）**。类名 + 字段名 → 读链，偏移只在这一处
  记；每条带 `verified`（真机验过没有）与 `note`（踩过的坑）。覆盖
  BattleObjectManager / BattleUnit / BattleUnitModel / CharacterState /
  GlobalGameManager / BuffDetail / BuffModel / BuffStaticData。
- **新增 `warphook/objects.py`（对象门面）**：
  `bind_manager()` / `units()` / `unit(i)` / `snapshot()` / `count()` /
  `scene()`，`Unit` 有 `instance_id()/hp()/max_hp()/mp()/speed()/alive()`。
  双轨设计：底层 `hook(reads=...)` / `Host.read(slot, chain)` 原样保留，
  门面与底层共用同一个 `_encode_read`，不存在两套翻译表。
- **`_encode_read` 抽成共用函数**。钩子表装配与命令代读原先各写一份读链编码，
  现在只有一份（dict 步缺省值漏改过一次，就是这么漏的）。
- **`env.py` 版本号改成读 `addon_info.json`**。原先硬写 `"0.9.6"`，
  `addon_info.json` 已经 0.9.8 了日志里还播 0.9.6 —— 又一个「同一常量抄两份」。
- **`warp_layout.h` 加编译期尺寸校验**：`sizeof(WARP_READ) == WARP_READ_SIZE`、
  `WARP_READ_STEPS == 8` 不符合直接编译失败，不让「布局漂移」跑到真机上变成
  「数不对但不报错」。
- **真机首次接线暴露的两个坑（都已修）**：
  - **`actions` 缺省值原本是 `WARP_ACT_POPUP`**。声明式 dict 路径没写
    `actions` 的钩子一律变成「弹窗动作」——真机实测：装了条每帧的
    `GlobalGameManager.FixedUpdate`，DLL 每帧刷 `fire actions (1)` 与
    `popup: empty text`（游戏里每帧弹一次空窗）。缺省改 **0**，要动作用显式
    写。既有插件（AutoBoom / gacha）本来就显式写 `'actions': 0`，未受影响。
  - **声明式 dict 路径不认 `cache=(arg, 槽)` 元组**，只认平铺的
    `cache_arg`/`cache_slot`，于是 `bind_manager()` 传的 cache 被静默丢掉，
    钩子装上了、对象槽永远空。现在两条路径同一套语义。
- **命令泵入口是保留位**：`GlobalGameManager.FixedUpdate` / `Update` 由宿主
  自己钩来跑命令泵。插件也钩它的话 `warp_target_taken` 会让泵找不到落点，
  日志是 `pump: no free entry point, cmd channel off`，`CMD_READ` 全线失效。
  现在装配时遇到这两个方法会打 warning；场景对象改由泵每帧缓存在
  **对象槽 29**（`WARP_SLOT_SCENE`），`bind_scene()` 只等不钩。
  对象槽 30/31 是每帧回调保留位（`"SKT1"` 魔法值 + 函数指针），别占用。
- **字段表扩到 8 类 62 字段**（`warphook/fields.py`）。原先只有十几个「够用就行」
  的字段，现在按 dump.cs 把 `BattleUnitModel`(37) / `CharacterState`(26) /
  `GlobalGameManager`(13) / `BattleObjectManager`(13) 的字段全收了；每条带
  `verified`，`fields.unverified_names(cls)` 一次列出「还只是照 dump 抄的」。
  抽取工具 `test/_dump_fields.py`（大文件必须用 bash grep，ops_grep 在 81 MB
  的 dump.cs 上匹配不到东西）。
- **`Unit` 门面扩了属性和扫描**：`is_panic()/is_break()/is_low_morale()/
  hp_ratio()/buff_count()/buff_id(i)/buff_ids()/scan()`，以及
  `objects.scan_class()` / `objects.scene_full()`。`scan()` 把一个单位的
  BattleUnitModel + CharacterState **全部 63 个字段**读一遍，是摸底工具
  （每字段一次往返，整场要十几秒），不是业务接口。
- **buff 名字只有指纹**：`buff_id(i)` 走 8 跳正好用满链长，落点 `kind='text'`
  给的是 il2cpp string 的数字换算而不是原文；要原文得等协议 v8 支持
  「读 UTF-16 到文本区」。
- **新增 `test/_v9_scan_all.py`**：一条命令扫出「当前场景全部对象与属性」
  （探协议/构建戳 → 抓 manager → 场景全字段 → 逐单位 63 字段 + buff 指纹，
  可 `--json` 落盘）；`test/_v9_fields_check.py` 离线校验字段表结构与链长
  （不超 8 跳）。

- **门面层（0.9.9 补）**：`objects.Access` / `Unit` / `Buff`。`game.access(host)`
  → `acc.get_obj(id=1)` → `u.hp` / `u.sp` / `u.identity` / `u.is_panic` /
  `u.buffs[i].name·stack·turn`；`u.get_pro("origin_id")` 走别名表，
  `u.props()` 一次拿 62 个字段。底层 `read()` / `fields.read_chain()` 不变。
- **ObscuredBool 解码**：`_isDead/_isPanic/_isBreak/_isLowMorale` 分两次读、
  按 byte 解（`hidden ^ key`），假码 `0xB5`、真码 `0xD5`；C 侧 `kind='obscured'`
  按 ObscuredInt 解会恒 181。
- **buff 明细**：`BuffInfo._stack@0x6C`（强度/层数）、`_turn@0x70`（次数）、
  `_maxStack@0x64`、`_maxTurn@0x68`；名字原文走一次跨进程读（`access.reader()`）。
- **buff 英文 ID（`Buff.key`）**：`BuffInfo._name` 只是本地化显示名（"呼吸法"），
  插件判断 buff 要用 `BuffStaticData.id@0x18` —— 真机值如
  `BurningWoundYisangMask` / `Breath` / `Combustion` / `Protection`。
  门面：`b.key` / `b.icon`(iconId) / `b.type_id`(BUFF_UNIQUE_KEYWORD) /
  `b.has("Breath")`、`u.has_buff("Breath")`、`u.buff("Breath")`（英文 ID 与
  中文名都认）。`BuffStaticData` 同时补了 `_id/iconId/buffClass/buffType/
  attributeType/totalStack/stackLimitPerTurn/maxStack/maxTurn`。
  `Unit.buff_id(i)` 的 8 跳末端从 `name` 改指英文 ID；要原文用 `Buff.key`。

## 0.9.8

0.9.7 上真机后必修的一轮：**il2cpp 的 Dictionary 字段序和 .NET 参考源码不一样**，
以及几处「只在真机才暴露」的装配/诊断问题。

- **字典字段序纠错（真机实测）**。0.9.7 按 .NET reference source 把 freeCount
  读在 `+0x2C`，il2cpp 实际是
  `buckets@+0x10 / entries@+0x18 / count@+0x20 / freeList@+0x24 / freeCount@+0x28 /
  version@+0x2C`（freeList=-1 表示无死坑）。读错一个字段的直接后果：
  `count - freeCount` 读到的是 `count - version`，负数 → `dict_count` 恒 0、
  遍历轮数也错。涉及 `src/warp_action.c`（`warp_dict_nth_value`、
  `warp_count_dict`）、`warphook/base.py`（三处）、`src/warp_layout.h` 注释、
  `DESIGN.md`。**教训：单元测试用同一份错误假设伪造内存，所以全绿也说明不了对
  ——「测试绿≠对」第二次应验。**
- **批去重真机验证通过**。连续三个回合不击杀、字典内容完全不变时，只有第一个
  回合投递 3 条事件，后两回合整批被吞（`head` 因成就钩子继续涨，
  hook 自己的批不再出现）。去重位 `HF_DEDUPE`（0x04）必须显式打开，
  没开时引擎只做单值去重、每回合全量重投——这是行为边界，写进 DESIGN。
- **新增 `warphook/remote.py`（跨进程读链）**。`base.read_chain` 走本进程
  `ctypes.from_address`，拿游戏地址去读必然段错误（实测 exit 139）；诊断脚本
  从外部进程验证读链时改用 `RemoteReader`（`OpenProcess`+`ReadProcessMemory`，
  支持 dict/dict_val/list/array 与 sum/count/dict_count/text/obscured 落点）。
- **`host_alive` 修 standalone 误判**。启动器退出后心跳没人写，age 动辄几十万
  毫秒，「心跳新鲜」判据把活着的宿主判成死的；现在心跳过期时若
  `standalone=1` 且 `hooked>0` 也算活。
- **构建戳**。`warp_host.c` 启动时写
  `build <__DATE__> <__TIME__> proto v<N>`，`host.py` 新增 `host_build()`
  从日志尾部读回来。此前编译产物落在 `test/`、注入路径却读
  `addons/WarpHook/warp_host.dll`，导致「源码已改、游戏里跑旧 DLL」，
  症状是读到垃圾值（新 kind 被旧 DLL 当默认 int 落点处理）。**只比 `version`
  区分不了同协议号的两次构建，必须比构建戳。**
- **字典步缺省值修正**。`host.py` 装配 `value_off`/`stride` 的缺省值原写成 0，
  落盘成 `0x80000000`，永远取 `entry[0]` 的 hashCode 当 value；改为文档写的
  16/24。
- 附带：`DESIGN.md` 编译命令改为直接输出到 `addons/WarpHook/warp_host.dll`
  并附 md5 核对；`README`/`addon_info.json` 版本随动。

## 0.9.7

读取链补上最后一块容器拼图：**Dictionary 遍历**（协议 v6，只改读链语义、
布局不变，`MAP_BYTES` 仍 172928）。

- **字典容器步 `6`/`7`（`'dict'`/`'dict_val'`）**。`Dictionary<K,V>` 布局
  固定（entries Array@+0x18、count@+0x20、freeCount@+0x2C，entry 形如
  `{hashCode@0, next@4, TKey@8, TValue}`），`Remove` 留死坑
  （hashCode<0）要跳过，活跃数 = count − freeCount。**注：freeCount 的偏移
  0.9.8 真机实测为 `+0x28`，`+0x2C` 是 version，见 0.9.8 条目。** entry 尺寸/ value 偏移
  由配置方从 dump.cs 算好写进步里（`value_off`/`stride`，缺省 16/24）。
  拿全场单位从此不用绕 List：`BattleObjectManager._allUnitDictionary`
  （+0x90）直接下脚。
- **遍历链（iter）**。字典步写 `'dict': 'iter'` 时一次命中按活跃 value
  逐轮装载、逐轮发事件（上限 `WARP_ITER_MAX=256`）；配套批去重
  （轮 0 快照哈希 + 轮数，只缓存一个 int）拦住每帧钩子的重复批。
- **`dict_count` 落点（kind 9）**。活跃 entry 数一步读出，与 List 的
  `count`（+0x18）偏移不同。
- **版本协商（A3 部分修复）**。`host_alive` 校验宿主 `version ≥ HOST_VERSION`：
  旧 DLL 不认识新步，直接拒绝装配而不是静默出错。
- 偏移依据：`docs/游戏内存探索.md`；单元测试以 ctypes 伪造 Dictionary
  内存全过（随机访问/死坑跳过/iter/dict_count/int→int 值直读/链后续跳）。

## 0.9.6

第七轮：BUF 事件转发上线 —— buff 类成就（"心脏，心脏！"的 eyebuff
条件）终于有了数据源。协议 v5。

- **buff 关注哈希表（共享内存尾部新段）**。共享内存 objects 之后追加
  32×8B：成就侧把规则里盯着的 buff 名做 fnv1a64 写进去（0 哨兵），
  C 侧新的 `buff_mask` 读法沿「单位→buff详情→List→模型→名字串」遍历，
  名字哈希命中关注表就置位，产出 32 位掩码。表为空时读法直接放弃，
  没有成就看 buff 就零开销。`WARP_VERSION`/`HOST_VERSION` 升 5，
  `WARP_MAP_BYTES` 172672→172928。
- **BUF 行**。unit 一帧（SPD+VAL）追加第三行
  `BUF tag=.. iid=.. oid=.. m=<掩码> n=<buff总数>`，格式与老链路
  `_apply_buffs` 的解析一字不差；`n=-1` 表示链没走到（读不到 ≠ 没 buff）。
  名单非空时才带这两格读链（`build_hooks(buffs=...)`），名单热变化
  每 5 秒查一次，开关翻转自动重挂钩子。
- **unit 钩子改 POST**（顺手修"呃啊，我脚崴了"浮士德 9 速成就的半个
  根因）：SetSpeed/SetRandomSpeed 是写速度的方法，PRE 读 self 拿到的
  是写入前的 -1；POST 无害且读的是终值。

## 0.9.5

真机第五轮：李箱成就触发（v0.9.4 钩点迁移生效）。本轮修「采光本被锁」
的根因——一个藏在所有 thunk 里的返回值覆盖 bug。

- **RAX 返回值被 warp_on_event_post 覆盖（真机反汇编实锤）**。thunk
  用 `void` cast 调 original，靠「寄存器透传」把 bool/int 返回值带回
  调用方——但 v0.9.1 引入的 `warp_on_event_post`（POST 事件发射）在
  original 之后调用，RAX 从此装着 post 的返回值。反汇编
  warp_thunk3_0（`IsNodeCleared` 用的形状）看到 `call *%rax` 之后
  紧跟 post 调用——所有未配置 ret_kind 的 bool/int/指针 getter 返回
  值全毁。表现：游戏把已通关的主线判成「通过 1-11 才能解锁」——
  采光本永久上锁（重启才恢复）；启用拦截插件必现（它带 BLOCK 钩子，
  拦截路径同样丢返回值）。
- **修法：一律接住 + 无条件写回**。original 全部按 64 位整数 cast 调
  用（int/bool/指针返回值都从 RAX 走，VOID 方法的 RAX 没人读、写回
  也无害），`ret_` 升为 64 位（`movq` 写回保住指针高 32 位）；尾部
  写回从「配置了 ret_kind 才写」改为无条件——float 写 XMM0，其余写
  RAX。BLOCK 拦截路径没调 original，写 0 = 「拦截未成功」。

## 0.9.4

真机第四轮排障：李箱链的钩点在当前游戏版本里换了地方，读法跟着重写。

- **事件钩点整体迁移**。当前版本 `BattleActionModel` 类里已经没有
  `OnEndTurn` / `DoneWithAction`（slot7/8 钩到 parent 链上的别的方法，
  timing 枚举读出 32 这种垃圾值）。真实钩点是
  `BattleSystemAbilityDetail::DoneWithAction(BattleActionModel)`（1 参）；
  `SkillAbility::DoneWithAction` 是 2 参虚方法、6 个子类 override 各自
  实现，MinHook 只认基类方法地址拦不到子类，弃用。damage 钩实际命中
  的是 `BattleUnitModel` 嵌套族的 4 参
  `GetTakeAttackDmgMultiplier(action,coin,attacker,isCritical)`（与
  BuffManager 的 6 参版是两套独立方法），签名按 4 参校正。
- **skill 读链重写（skid=2010341209 的根因）**。`SkillDataModel.id` 与
  `skillTier` 都是 `ObscuredInt`，旧读链按裸 int 读拿到的是混淆 key 分
  量。新链：actor = action→[0x18 解引用 `_model`]→[0x64 `origin_id`]，
  commander = [0xB4]，skid/tier = action→[0x20 `_skill`]→[0x10
  `_skillData`]→[0x10/0x40 按 obscured 异或]。
- **`action_actor_id` 偏移过时**。`BattleActionModel._model` 现在在
  0x18（旧配置 0xBC 是已删字段），且它是引用、必须显式解引用。
- **同 target 双钩防御**。`node_cleared_short` 与 `IsNodeCleared` 是同
  一个方法（MinHook 一方法只能一个 detour），从 FIRST_BATCH 删去；
  `node_state` 钩自带缓存（self 落对象槽 0）但照常占事件号。
- **类查找兜底**。`warp_find_class` 在精确命名空间查询全灭后按短名再扫
  全 assembly——铁路三类在第四轮真机上依旧 class not found，留这条
  退路。
- **注入重试**。成就观测先于游戏启动时，`inject_now(wait=False)` 直接
  放弃导致整轮无引擎；改为后台线程 `wait=True` 死等游戏进程出现。

## 0.9.3

真机第三轮排障：装钩失败的三大根因，逐条掀掉。

- **thunk 表截断（本轮最致命）**。v0.9.1 把钩子表从 16 槽扩到 32 槽
  时，`warp_hook.c` 的十个 thunk 数组声明改成了 32 槽，但初始化实例
  还停在 16 个——槽 16..31 的 thunk 全是 NULL，`warp_pick_thunk` 返
  回 NULL 后报 "unsupported argc"（而且日志打印的是 argc 值不是槽
  号，极具迷惑性）。真机上铁路五件套、伤害、两条抽卡钩全死在这。
  现在 160 个实例补齐，装钩前自检：任何一槽为 NULL 即拒绝装钩并打
  "thunk table truncated"。
- **argc 配错 5 条**。`ARGC_OVERRIDE` 一直是「老 thunk 取几格」而非
  真实参数个数，对着 dump.cs 逐条核过：`OnEndTurn`/`DoneWithAction`
  各 1 参（原配 3/2）、`UpdateData`/`GetData` 各 1 参（原配 0）、
  `IsNodeCleared` 选 3 参重载（原配 0）。argc 错 = 方法查不到，全
  数 "method not found"。
- **铁路三类 "class not found"**。`RailwayDungeonHistoryDataByCollection`
  和 `RailwayDungeonMapUpperUILine1002` 不在全局命名空间（分别在
  `LimbusCompany.RailwayDungeon.HistoryLibs` / `.UI`）。FALLBACK_HOOKS
  补全名，`warp_find_class` 的点分分割从「第一个点」改为「最后一个
  点」——命名空间自身可以带点，类名永远是末段。
- **李箱三技能成就链修复**。SKV 读链偏移 0x120 实为 `_targetDir`
  （float 0.0 → 位模式 0 → 全零事件），`_attackerInstanceID` 真身
  在 0x130。配合前两条修复，`OnEndTurn` 的 ACT 行恢复流动后
  `match_skill` 才有数据可比。
- **成就观测注入重试**。旧代码 `inject_now(wait=False)`：游戏还没开
  就直接放弃，之后没人再试（用户先开启动器后开游戏时引擎整轮不起
  来）。改为后台线程 `wait=True` 死等，游戏一起来就注入。

## 0.9.2

真机第二轮排障：钩子表不是不够大，是**多个插件进程在互踩**。

- **多作者分段协议（共享内存写规则）**。成就观测跑在独立子进程，
  NoGacha 在主进程——两个进程各自 push 同一段共享内存，而旧
  `_write_config` 是全表清写：后 push 的把先 push 的整表清掉。真机
  现场就是这样：子进程先写 25 条成就钩子，主进程 NoGacha 一 push，
  表里只剩 2 条抽卡钩子，C 侧「老老实实」只装 2 条——成就钩子全军
  覆没而两边日志都说自己成功了。现在按 owner 名字把表分段：名字含
  「成就/achievement」的进程占主段（钩子槽 0..26、读链 0..95、文案
  0..191），其余进辅段（27..31 / 96..127 / 192..255），每个作者只清、
  只写自己的段，`enabled` 也不再被别人的 push 关掉。谁先谁后、谁崩
  谁活，都不再互相覆盖。
- **ticks：battle_snark 的每帧驱动改走 WarpHost 的泵**。上一版为解
  崩溃删掉了 battle_snark 的 `FixedUpdate` 钩，气泡淡出就没了驱动——
  真机上立绘常驻不消失。直接钩 `Update`/`LateUpdate` 真机全失败
  （游戏类未必重载这两个方法）。改为函数指针共享：battle_snark 把
  `sk_ui_tick` 写进对象槽 30（magic `SKT1`）/31，WarpHost 泵每帧
  代跑——钩子装不装得上不再影响气泡生命周期。
- **battle_snark**：UI 加 `DontDestroyOnLoad`（崩溃根因：战斗场景
  卸载后缓存指针悬空，tick 对死对象 invoke）；`blind` 守卫（alpha
  调用失败即盲化，`show` 退回原版弹窗，绝不双重弹窗）。
- **诊断日志（`warphook/diag.py`）**：CFG/EVT/ST/DROP 四层，落
  `addons/WarpHook/warp_events.log`（2MB×3 轮转），`WARP_DIAG=0`
  关闭。真机上「配置写没写进去、C 装了几条、事件翻译成什么行」从此
  有账可查。
- 测试：warp_hook 64 项（新增 `test_dual_owner` 双实例互不覆盖）、
  warp_reads / warp_source / warp_cmd_smoke / nogacha_host 全绿；
  `test/shm_probe.py` 修 64 位指针截断与 `popup_ok` 偏移。

## 0.9.1

真机首航排障：一次上线暴露三个问题（成就不触发、NoGacha 拦了不弹窗、
游戏闪退），根因两个，都在协议与共存层面。

- **协议 v3 → v4：钩子表 16 → 32 槽**。成就 25 条 + NoGacha 2 条早就
  超过 16 槽，`_layout` 静默截断——真机上 NoGacha 的钩子整条消失，
  插件盯着 `hits()` 永远是 0，日志只说「工作中，命中 0 次」。截断现在
  会打日志点名被丢弃的钩子；映射总长 168064 → 172672。
- **同目标双钩防御（`warp_target_taken`）**：安装前读目标函数入口，
  已是 jmp（E9 / FF 25）或表内已有同方法就跳过并记日志。各 DLL 的
  MinHook 实例互不知情，双钩同一方法会形成嵌套跳板链——真机崩溃栈
  里 warp_host 与 battle_snark 在 `GlobalGameManager::FixedUpdate` 和
  `BattleActionModelManager::OnRoundStart_Before` 上各嵌一层，最内层
  游戏方法调 Unity API 时整个进程带走。命令泵也加了备胎：FixedUpdate
  被占用就退到 `Update`，再占用就放弃命令通道（事件钩子照常）。
  注意：这只防「别人先挂」；防不住别人在我们之后挂——多插件共存
  的礼仪靠这一条加文档约束。
- 配套的成就侧：`WarpSource.attach` 的 `int(h['event'])` 撞上只缓存
  钩子的 `event=None`（v0.9.0 子进程直连打通后才暴露），成就观测整条
  线炸成「仅日志成就生效」——现在跳过 `event is None` 的钩子。
- **battle_snark 同步**（独立插件，改动随本仓库）：删掉与 WarpHook 撞车
  的两条钩子（`GlobalGameManager::FixedUpdate` 气泡 tick、
  `BattleActionModelManager::OnRoundStart_Before` 触发候选 2）；气泡收起
  走回合兜底，触发候选还剩 BattleObjectManager 两个。

## 0.9.0

P6 对象构造落地：命令通道从「弹窗 / 杀进程」两条硬编码泛化成**可编程的
构造 / 调用通道**，插件不改 C 就能在游戏主线程造对象、调方法、造字符串。

- **协议 v2 → v3**：导出表 13 → 15（追加 `il2cpp_gchandle_new` / `free`，
  构造对象挂强句柄防 GC 收走；缺了退化裸指针）；`EV_CTRL` 起偏移 +128
  字节平移，映射总长 167936 → 168064。
- **命令扩展**：`cmd_type` 变打包字（code | argc | retkind | slot），新增
  MAKE（object_new + .ctor）/ CALL（runtime_invoke，实例 + 静态）/
  STR（string_new）/ RELEASE（解句柄清槽）四条；参数走 `vars[0..5]`
  （≤6 个，`#iif` 后缀标类型），int32/float 返回从 box +0x10 解包进
  `vars[6]`，引用返回落 `vars[7]` 指定槽；0xFF = 静态调用哨兵；结果码
  0..7 细分到「类没找到 / 方法没找到 / 槽越界 / 参数超六个 / 方法抛异常」。
- **GC 句柄生命周期**：对象槽写入口统一 `warp_slot_put`——写之前先解掉
  旧句柄，句柄表 `g_gc_handles[32]` 与槽同生命周期；探针读链照旧经
  `0x100+槽` 出发，构造出来的对象立刻就能当读链起点。
- **Python API**：`Host.make / make_str / call / release`；引用参数
  `('slot', n)` 打包时解析成真实指针；`ret='ref'` 返回输出槽号。
- **新增 `test/warp_cmd_smoke.py`**：假 GameAssembly（真桩、真 MinHook
  挂钩、真命令泵）26 项断言全绿；顺带 `warp_host_smoke.py` 的布局常量
  改为直接 import `warphook.host`，彻底告别手抄漂移。
- 防御性修复：`warp_cmd_build_params` 的 params 数组零初始化（真实
  il2cpp 只读前 argc 个，但桩和调试器会扫整段）。

## 0.8.0

三个新原语进宿主，成就桥老链路的**全部事件钩子**至此迁完（P5 收官的前一半）。

- **读返回值**：钩子槽加 `when` / `ret_kind` / `ret_slot` 三个字段。
  `ret_kind='int32'/'float'` 让 thunk 按类型调原函数（int 在 RAX、float 在 XMM0），
  返回值直出进事件的第 `ret_slot` 格，并在离开 thunk 前把值**写回寄存器**——
  原先 void thunk 靠 RAX/XMM0「没人碰就透传」碰巧正确，但后续任何 C 代码都会
  破坏 XMM0，带返回值的钩子必须显式写回。带 `ret_kind` 或 `when=1`（POST）时
  事件在原函数调用**之后**发，构造函数里「调用之后才填好」的字段读得到。
- **值类型容器遍历**：deref 位扩出 `list_val`(4) / `array_val`(5) 两种步，按
  4 字节元素取值（原先只有引用型的 8 字节指针步）；`sum` / `count` 两种落点
  直接对 `List<int>` 求和 / 计数。九参构造函数
  `RailwayDungeonHistoryDataByCollection::.ctor` 的 `clear_turns`（List<int>）
  一条配置就求出总回合。
- **字符串取数**：`text` 落点读 il2cpp string（len@+0x10、UTF-16 data@+0x14）
  取开头数字。`RailwayDungeonMapUpperUILine1002::UpdateUI` 之后 UI 文本 "86"
  → 86。
- **事件八格 → 十二格**（`a..l`，44 → 60 字节/格）：damage 钩子一条命中要同时
  还原 ACT + VAL 两行共十个数，八格装不下。配套 `WARP_READ_MAX` 64 → 128。
- **thunk 形状补齐 7/8/9 参**，且所有形状显式收发 il2cpp 的隐藏 `MethodInfo*`
  参数（原先直接丢掉——非泛型方法体不读它所以没炸，九参构造不敢赌）。
- 协议版本 1 → 2（钩子槽 272 → 288 字节、事件 44 → 60、读链 64 → 128 条，
  映射总长 131840 → **167936**）。
- 成就桥接上剩下六条钩子：`railway_total` / `railway_node` / `railway_hist` /
  `stage_node_id` / `railway_ui_text` / `take_attack_dmg_multiplier`，
  行格式与老 DLL 逐字一致（RWT / RWT node / RWT line+total+nodes / SNI / RUT /
  ACT+VAL），规则引擎零改动。damage 钩子的 BUF 行本轮不发（buff 链遍历 +
  FNV-1a 哈希仍无通用表达，buff 类成就继续走采样器路径，与 0.7 行为一致）。
- 踩坑两笔：`_write_config` 的 dict 路径原先只认整型 `ret_kind`，`'int32'`
  字符串 `int()` 失败后**静默回退 VOID**——返回值就丢了，现在与 `hook()`
  关键字路径共用 `HOST_RET_NAMES`；`out` 槽原先用 `& (SLOTS-1)` 掩码钳位，
  十二格不是 2 的幂，out=12 会被折到 8，改成显式钳制。

## 0.7.0

- **对象槽（object slot）**：钩子槽加两个字段 `cache_arg` / `cache_slot`，命中时
  把第 `cache_arg` 个参数（0 = self）的指针写进第 `cache_slot` 个对象槽。
  这是「先记住对象在哪儿，回头再摸」原语的第一次落地 —— 老链路里
  `cache_self` / `cache_arg1` 那两种读法只缓存指针、不当场发事件，之前在新引擎里
  没有对应物。映射里多了一片 `HOST_OBJECTS_OFFSET` 起的 32 × 8 字节区，
  总长 131456 → 131840。
- **读链可以拐道对象槽**：读链的 `arg` 写到 `0x100 + 槽号` 时表示「从那个对象槽
  里存着的对象出发」。这样一条链就能接在几秒前缓存下来的对象上，而不是只能挂在
  当次命中的参数上。
- **Python 侧也有了读取链解释器**（`warphook.base.read_chain` / `can_read`）：
  规则与 C 侧完全一致（加偏移 / 解引用 / List / Array / obscured），每一步都先问
  `VirtualQuery`。理由很实际 —— Python 读非法地址是直接段错误，没有异常可捕获，
  校验只能自己做。`Host.read_object(slot, chain, kind)` 是它的读端。
- 成就桥接上五种「只缓存不发事件」的钩子：`stage_clear_info` / `stage_clear_query` /
  `stage_clear_last` / `node_cleared_short`（缓存 self 到槽 0）、`stage_progress`
  （缓存第一个参数到槽 1）。它们不加事件号，只让对象槽里有值。
- 踩坑：`_write_config` 里读链的 `arg` 原来被钳在 `0..6`，`0x100 + 槽号` 会被截成
  0，链会莫名其妙从参数 0 开始读。现在 `arg >= 0x100` 原样落盘。

## 0.6.1

- **读取链支持「零跳」**：链长为 0 时不再把参数当指针解引用，而是把它本身的值
  当结果。关卡节点查询那类方法的签名是 `(self, int main, int sub, int node)`，
  三个参数全是值类型，直接躺在寄存器上，没有任何偏移可跟 —— 老链路为它们单独
  写了 thunk，现在一条空链就表达了。
- 顺带接上两种读法：`skv`（读表现层 `_attackerInstanceID`，发 `RND` 行）与
  `node_state`（三个 int 参数原样发 `NCL` 行）。成就桥挂的钩子从 8 条增加到 13 条。
- 记一笔之前踩过的坑：`KIND_SIGNATURES` 里的数只代表「老 thunk 从寄存器取几格」，
  不等于方法真实声明的参数个数（`Skill_Start()` 无参、`IsNodeCleared` 是 3 参），
  装钩子必须用 dump.cs 的真实签名，由 `warp_source.ARGC_OVERRIDE` 兜底。

## 0.6.0

- **事件环扩容 512 → 2048 格**（44 字节/格，约 90 KB），映射总长 63872 → **131456**
  字节。老容量在 `dedupe` 关掉的 60fps 钩子下 8.5 秒就翻一轮，读侧稍微慢一点
  就开始丢事件 —— 而丢了之后 Python 完全看不出来。
- **丢事件现在有准确的数字**：覆盖最旧槽时 `WARP_EV_CTRL` 的 `dropped` 累加，
  Python 侧读事件时把增量并进 `host.events_lost`，`WarpSource.stats()['lost']`
  也带出来了。「漏了 37 条」和「什么都没发生」不该长得一样。
- 钩子参数槽从 3 个扩到 6 个（112 个 thunk，`argc` 0..6）：读取链的 `arg` 可以写
  1..6，`GetTakeAttackDmgMultiplier(unit, action, coin, attacker, isCritical, info)`
  这类六参方法里的出手者终于读得到。
- `DESIGN.md` 补「事件队列与背压」一节（游标分工、为什么丢事件要计数、容量怎么选）。

## 0.5.0

- 事件从四格值（`a/b/c/d`）扩到**八格**（`a..h`），读链的 `out` 可以写 0..7。
  起因是成就那套读法：一条 `VAL` 要「实例号 + 模板号 + 血量 + 上限 + 理智」五个数，
  四条 `SPD` 要六个 —— 四格装不下只能把一条钩子拆成两条再在 Python 里按
  instanceID 配对，比加 16 字节难受得多。
- `WARP_EVENT` 28 → 44 字节，映射总长 63872 字节，`HOST_EVENT_SIZE` /
  `HOST_READ_OFFSET` / `HOST_MAP_BYTES` 跟着变，两侧测试已同步。
- 去重表 `g_last_vals` 从四列扩到八列，八格一起比。
- 修 `out` 落盘时被 `& 0x3` 掩掉高位的旧限制。

## 0.4.1

- 钩子新增 `dedupe=True`：**读链的值没变就不投递事件**。挂在
  `GlobalGameManager::FixedUpdate` 这类每帧调用的方法上时必开，否则 512 格的
  环形队列连一秒都撑不住（实测 8 秒翻一轮，消费者捞不到有用的东西）。
- 判断放在自增 `head` 之前，被吞掉的命中不会在队列里留空洞；
  拦截（`HF_BLOCK`）、一次性标记（`HF_ONCE`）、命中计数都不受去重影响。
- 「上次的值」放在 DLL 静态内存，不动共享内存布局 —— 少改一处就少一次两边对不上。

## 0.4.0

- 读取链新增**容器步**：`deref` 位可写 `'list'` / `'array'`，按下标取 `List<T>` /
  `Array<T>` 的元素。管理器身上的单位列表终于跳得进去了，
  `BattleObjectManager._deadUnitList[0] → _state → _hp` 一条配置写完。
- `deref` 位的四种取值（0 加偏移 / 1 解引用 / 2 List / 3 Array）在 `DESIGN.md` 里成表。

## 0.3.2

**读取链上线前的三个硬伤** —— 都是真机跑出来的，不是想出来的。

- **写错偏移不再崩游戏**：`warp_read_chain` 每跳与落点都先 `VirtualQuery`
  确认可读，读不到就当这一条没读到。实测中的崩法是插件把
  `sceneState`（0~15 的枚举）当对象指针解引用，`*(int*)0` 直接送游戏退出；
  读取链是插件写的东西，不能假设它一定对。
- **顶层 `deref` 数组生效**：`reads` 里 `off=[...]` 与 `deref=[...]` 并列写
  （跟 C 那张表一样）之前被忽略，一律按「解引用」处理。现在两种写法都收：
  元素级 `{'off':..,'deref':..}`，或者顶层并列数组；没写 `deref` 的一律默认解引用。
- **残留错误自清**：注入早期 `bind exports failed` 留下的
  「取不到 il2cpp 接口」现在会在绑定成功后清掉，不再一直挂在状态行上。

## 0.3.1

**混淆整数读法** —— 血量、理智这类数字在内存里不是明文 int，而是
`ObscuredInt { key, hidden, fake }`，真实值 = `hidden ^ key`。

- 读取链新增 `WARP_READ_OBSCURED`（`kind='obscured'`）：落点按 12 字节结构解，
  读 `[0]` 与 `[4]` 异或。老链路的 `read_unit_vitals()` 就是干这个的，
  现在不用再为它写 C 了。
- `Host.hook(reads=[...])` 的 `kind` 现在可以写名字：`'int' / 'float' / 'bool' /
  'ptr' / 'obscured'`，写数字仍然认。

## 0.3.0

**读取链** —— 钩子不再只能上报「第几个参数是个指针」，而是能直接给出「伤害多少、剩多少血」。

- 共享映射尾部新增读取链表：64 条 × 48 字节，`WARP_READ { arg, nsteps, kind, out, off[4], deref[4] }`。
  一条链 = 从某个参数出发，按偏移跳几跳（每跳可解引用），落点按 `int/float/bool/ptr` 解释。
- 钩子登记时写 `reads=[...]`，引擎命中时把读到的值直接填进事件槽 `a/b/c/d`；
  没配读链的钩子保持老行为（原始参数、`vars[0]` 快照）。
- `warp_on_event()` 现在带 `self` —— 成就那类钩子最常读的就是 `self` 上的单位状态。
  链上碰到空指针一律静默跳过，保留上一次的值，不打印也不抛。
- 钩子项 256 → **264** 字节（新增 `read_base` / `read_count`）；映射总长 52480 → **55680**。

## 0.2.0

**事件总线** —— 钩子从「只报次数」升级成「逐条报现场」。

- 共享映射尾部新增环形事件队列：512 条 × 28 字节，`WARP_EVENT { id, hook, tick, a, b, c, d }`，
  `d` 是 `vars[0]` 的快照，省得回调里再读一次。
- 钩子登记时写 `event=事件号`，引擎每命中一次就入队一条；队列满了丢最旧的。
  事件与行为位互相独立：`actions & WARP_ACT_EVENT` 的钩子可以同时什么都不做。
- Python 侧 `Host.events(limit=None)` 批量读走并推进 tail；`Service.on_event(callback)`
  在 Service 的轮询线程里逐条回调 `callback(host, event)`。
- 映射总长 38128 → **52480** 字节（新增 `WARP_EV_CTRL_OFFSET` 38128 / `WARP_EVENTS_OFFSET` 38144）。

## 0.1.0

**拆成独立组件**，从「一个 1241 行的 C 文件 + 一个 2310 行的 scr.py」变成可分发的包。

- C 侧：`src/` 下 9 个 `.c` + 2 个 `.h`（`warp_layout.h` 只放结构与宏、`warp_internal.h` 放内部声明）。
- Python 侧：`warphook/` 包 —— `env`（注入的上下文）、`base`（Win32/共享内存/il2cpp/注入）、
  `host`（Host 单例与钩子表）、`game`（抽卡语义层）、`service`（运行骨架）、`registry`（命名空间）。
  `scr.py` 只剩 40 行胶水，重载时会清掉 `sys.modules` 里的 `warphook*`。
- 新增 `README.md`（用法与编译）、`warp_stub.py`（给 IDE 的类型桩）、`DESIGN.md`（协议与设计约束）。

## 更早

WarpHook 最初是三个插件（NoGacha / AutoBoom / Yesod 监督器）共用的依赖库，
之前的演进（命名空间收编、多插件身份隔离、命令通道、文案池扩容）都在 git 历史里。
