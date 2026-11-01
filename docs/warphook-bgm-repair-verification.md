# WarpHook / BattleBGMExtend 修复与真机验收

## 这是什么

一份按版本倒序记录的**真机验收台账**：每个版本卡在哪个真机现象、改了什么、
哪些结论有日志证据、哪些还只是「代码上成立但没验证出声」。它和 CHANGELOG 的
分工是——CHANGELOG 说「改了什么」，这里说「凭什么认为改对了，以及还差什么」。

阅读顺序：先看下面「先看这三节」，再按兴趣往下翻历史轮次。

!!! info "台账的硬规矩"
    里面每一句「未验证」都不是客套。BGM 链路上区分三件事——**命令提交完成**
    （`ok=True`）、**原生确实拦住**（`blocked` 增长）、**耳朵听到**。
    上一级不能拿来替代下一级。

## 先看这三节

| 想确认 | 看 | 判定依据 |
| --- | --- | --- |
| 曲子跨回合不被盖回去 | `0.9.38 主曲被拦但附加曲被停止` 与 `0.9.37 回合末抢曲：锁声明未进入原生配置` | 四个锁入口 `blocked` 是否增长 |
| 换曲没声音 / 卡顿 | `0.9.39 音库重复预载与潜在卡顿` 与 `0.9.34 音库加载后仍为 False 的跟进` | `stage=cache-hit`、`elapsed_ms` |
| 回合回调不响 | `0.9.36 回合可靠投递与无人工延时` | 真实 hits 增长，不是定时器在装活 |

验收动作本身见文末「真机验收顺序」，日志判读见
[入门 01](tutorial/01-hello.md#log-file)。

## 0.9.39 音库重复预载与潜在卡顿

- 用户 17:06:51 日志所示 .assets.bank 和 .bank 是不同文件的一对加载，不是写磁盘。单段日志不能证明重复加载或掉帧根因；但代码确实每次 ensure_bank 都查 IsLoadedBank，已知本地预载后该查询可一直 False，导致同进程后续换曲再次加载大音库。
- 新增按 PID + GetProcessTimes 创建时间区分进程实例的成功提交缓存，重复 bank 跳过查询和加载；并发音频链共用 RLock，防止共享临时槽交错。失败/会话不明不缓存，游戏中途重启不记成功，提供 invalidate_bank_cache 处理已知卸载/音频引擎重置。缓存不是驻留或出声验证，外部静默卸载仍属已知边界。
- 阶段日志记录 load-complete/complete/cache-hit、elapsed_ms/wait_ms，另记录 stop/start 与音频操作总耗时。包含 IPC 排队、游戏线程执行与轮询等待，不能等同一帧卡顿。首次双文件加载仍可能阻塞游戏线程，不擅改 LoadBankFromLocal 的未验证布尔参数，也未加入逐帧状态轮询。
- 离线验收：同进程查询永远 False 仍只提交一对、不同 bank/PID创建时间隔离、并发合并、失败重试、无会话不复用、显式失效、加载中进程重启；真机需比较同进程第二次换曲是否 stage=cache-hit，以及卡顿是否仍发生于无加载时。重启启动器后缓存重建，属于保守重新预载；本轮仅 Python，无 DLL 替换或注入。

## 0.9.38 主曲被拦但附加曲被停止

- PID 14688 在换曲后 StartBGM blocked=3→4，证明此前编码修复已拦截部分游戏换曲；临时曲仍静音，现有三入口不能覆盖全部停止路径。旧版 battlebgmextend.c:632 明确同时 hook StopAddedBGM(2)，当前却遗漏该附加曲配对停止入口。补为第四锁入口，不能仅凭日志就声称已证明真机静音必定由它引起。
- 四锁加回合恰好占辅助5槽，其他辅助插件可能竞争。Live.bgm_lock_install 现在检查实际 layout 中的必需入口，缺任何入口返回失败及 missing，避免明知保护缺失仍报告配置成功。共享协议不提供逐入口安装状态，仍需实际 hits/blocked 验证。
- 按用户本轮要求取代整场优先级地板：有效条件存在时保持，不每回合重播；活动规则失效可切换到当前有效低优先级规则；无有效条件时后台释放控制并尝试恢复默认曲。转换事件不能简单下一回合全失效，目标 buff 仍存在时延续，单位退出/目标消失后释放。
- 停止/恢复现在先调用 StopAddedBGM(IMMEDIATE, false)，再 StopBGM，最后恢复默认 StartBGM；附加层停止失败不会假报恢复成功。释放任务必须先解锁成功；失败保留 active 供后续重试。快照不可用或显式 buff 读取异常不触发释放，但底层已吞掉异常并返回空列表的情况仍无法区分。
- 本轮实际通过：tests 目录 44 项、BGM 独立回归 37 项、生命周期 15 项、命令通道 4 项及原生独立回归；compileall 与限定源码的 git diff --check 通过。覆盖四入口编码/缺槽拒绝、停止附加层顺序、条件消失释放、降级和平级保持、转换续期、失效任务取消与失败重试。
- 真机复验：重启启动器载入新 Python；换曲后看 StopAddedBGM 的 hits/blocked 是否增加且临时曲跨回合延续，再验证条件消失后锁放行及恢复曲目。若附加曲仍被杀，须继续定位 CurrentBGM/owned FMOD 路径，当前不宣称完整旧版保护。生产 DLL 未替换或注入。

## 0.9.37 回合末抢曲：锁声明未进入原生配置

- PID 18756 日志 hits=14→19 证明回合入口仍在命中；维持 active/优先级地板本身不证明原游戏已被锁住。确认 audio.guard_hook_defs 使用 block=True、guard=(4,1)，但 Host._write_config 未转换这两个键，实际写入 flags=0、guard_var=-1，因此纯计数而非拦截。现补齐与 Host.hook 相同编码。
- 保持不每回合重播的策略，不以重播掩盖锁失效。自动判定不再丢弃结果；自动/手动及提交后输出真实配置、每入口 hits/blocked、guard 值和缺失入口。只读已经打开的映射，不新增游戏命令或初始化。逐入口安装状态未在协议中提供，installed=None，不冒充验证成功；blocked 增长才是发生过实际拦截的证据。
- 旧版参考 battlebgmextend.c:619-637 除当前三入口，还覆盖 SoundGenerator.ApplyBGMData、SoundManager/CurrentBGM、ResetBGM/StopAddedBGM/Interlude 等；:654-656 另保护 owned FMOD 实例。不能断言其他方法只在场景切换调用。当前仍部分覆盖，辅助5槽由多个插件共享；未盲目加入bool方法（旧版被拦返回true，通用BLOCK返回0）或全局FMOD锁。
- 已知边界：vars[4] 会被五/六参数命令覆盖，零参数命令不会；全局解锁窗口不同于旧版线程局部 own_call。当前 BGM 播放链不使用五/六参，但其他插件可能使用。不能只换另一个 vars 槽或 save/restore 伪称解决在途窗口；后续如有对应实证需独立状态/TLS权限设计。
- 真机验证：完整退出启动器再载入新 Python（本轮未替换/注入生产 DLL）。触发换曲后跨回合观察三入口 hits/blocked：若 hits 增长但 blocked 不增，检查 flags/guard；若 blocked 已增长仍被抢回，则需定位未覆盖路径，不能继续声称锁已完整复刻。本地回归结果不等于真机出声/跨回合保护确认。

## 0.9.36 回合可靠投递与无人工延时

- 用户 PID 12532 日志仍有 hits=6->7->8，证明不是所有后续回合均未进原生入口；不能把无业务输出一概归为原生 hook 失效。发现 Python 首次非零忽略、先消费 hits 再取快照导致快照失败永久丢事件，以及配置重推清零 hits 的独立问题。
- Live 抽出 _poll_round：仅真实命中建立 pending，首次非零/计数回退可恢复，快照失败保留并退避，成功才消费，不以周期回调伪造 hook。同入口配置重推直接跳过 hits/blocked 内存，不用读回再写回覆盖原生新命中。
- BGM 移除 sleep(0.1)；手动检测立即日志受理，后台读取/扫描，每条维持、排队、失败路径均有日志。战斗身份改生命周期哨兵，不因单位名单变化反复清 active/预载；无命中维持旧版整场优先级地板，结束重置。
- 回合 fake IO 14 项、真实共享配置计数 1 项、BGM 27 项及现有相关测试通过。正常监听仍有轮询调度与跨进程调用耗时，“无延迟”指不再人为 sleep，不是零耗时保证。尚需真机复验多回合及离战事件完整性。

## 0.9.35 撤销额外自检硬门槛（取代下文旧轮次策略）

- 用户 PID 10040 再次确认 invoke 双 bank 调用完成但复查 False。此前增加的加载后 IsLoadedBank=True 硬门槛并非参考旧版的行为，且其登记语义没有证实，现撤销。
- 初始 IsLoadedBank=True 仍用于避免重复加载；False 时执行两次预载，调用正常完成就继续 StopBGM/StartAddBGM。调用异常/超时仍中止，verified=False 不宣称已出声。
- 不再发起加载后的额外查询。BGM 18 项回归通过，新增语义覆盖查询始终 False 仍尝试播放、真实加载失败保留原曲。本轮仅 Python，无需再次更换 DLL，但需沿用 0.9.34 已修复的原生版本。

## 0.9.34 音库加载后仍为 False 的跟进

- PID 27068 原生日志 14:05:24：seq348 查询 rc0，seq350/352 两次加载 rc0，seq354 复查 rc0，但 Python 得到 False。说明请求已执行；rc0 不能证明 FMOD 音库注册成功。磁盘目标 assets.bank（19264448 字节）与 bank（52448 字节）实际存在。
- 对照独立旧版 src/battlebgmextend.c:275-287：音库调用实际使用 runtime_invoke，而非现有注释所称旧版只走 methodPointer。当前音库默认 direct 的参数形态本身未证实错误，不能把失败全部归为引用多一层。
- 另确证 runtime_invoke 分支存在引用参数打包缺陷：普通 String 应传对象指针，值类型 bool 应传其地址；当前与 direct 共用打包导致 invoke 多一层引用。修复需保持 direct 原行为，并覆盖构造函数路径。音库查询与预载显式选 invoke，以对齐参考实现；仍保留加载后复查，失败不停止原曲。
- 增加 bank、阶段、via、绝对路径、文件大小及前后查询结果诊断。该方案不是实际出声保证；不通过删除复查把 False 当作成功。
- 已修复 invoke 与 ctor 参数转换，保留 direct 原行为；原生回归实际通过字符串/空引用、bool/int/float 地址、out-buffer、boxed 返回、构造函数及真实 direct 参数兼容测试，既有 MinHook/worker/static 回归也通过。BGM 18 项通过。
- 检查无游戏后备份并部署最终新 DLL，SHA256：fb6efe597397ee00e84311fb179b18572cfc5181139c7617c5190b4fc19fad5d；原始生产版备份 test/warp_host_before_0930_4a948d717e67.dll（中间候选另备份为 test/warp_host_before_0930_8eddfba44af1.dll）。必须使用新 DLL 与新 Python 配套，不能只热重载 Python 后在旧 DLL 上走 invoke。需完整重启游戏和启动器验证。

## 0.9.33 跟进（历史白名单与空闲轮询）

- 用户 PID 6236 日志显示 LoadBankFromLocal 在 Python 方法白名单处即被拒绝；本次失败并不是已经进入游戏的音库加载崩溃。删除该方法名准入策略及过时推断，unsafe 仅兼容旧调用。保留对象槽、参数、签名校验；不能据此声称任何游戏方法都安全。
- Live 每 0.25 秒 scene_full 全字段扫描会在主线程泵未工作时制造无效 READ。现在以 monitoring 阶段、非空场景对象槽及命令通道空闲为本地门禁，仅采样公开接口所需三个字段，失败立即停止，重试按 0.5 秒递增至 10 秒。未知场景不触发离战事件。
- 命令停顿首次日志仍保留，后续重复日志按 30 秒窗口合并数量；请求超时结果不改变，不取消或覆写在途命令。本次不证明所有真机命令停顿已根除。
- 新增方法准入与日志合并 3 项、空闲场景轮询 8 项回归；与非阻塞生命周期 7 项一起运行全部通过。另行重跑命令并发 4 项、BGM 17 项、旧生命周期 15 项通过。
- 本轮仍为 Python 修复，不更换 DLL、不启动游戏。需重启启动器后验证主界面日志与实际换曲，未确认出声。

## 0.9.32 跟进（查询超时与启动流程阻塞）

- PID 21292 在 13:32:27.596 已记录 `static: runtime API resolved reference`，静态读取修复已真机生效。seq=1931 STATIC 和 seq=1932 STR 均完成；随后两秒是持续 READ 领取，没有音库 CALL 被领取，证明不能将本次超时归为 FMOD 慢或单例为空。
- Host 的单槽命令此前没有 Python 端互斥，后台对象读取可覆盖 BGM 请求。现在提交/结果解码/代读链准备均受全局可重入锁保护；前请求未完成不覆写。新增并发、跨实例结果隔离、BUSY 保留与 bool 类型回归。
- 音库层用 is True / is False，但 Host.call 原返回 int 0/1；现在 ret=bool 返回真实 bool，防止解决竞态后仍误报查询失败。
- 初始化同步链 on_round_start -> _ensure_hooks -> _push -> Host.push -> ensure_exports 已移至后台；Service.inject_now 不再在启动事件里等待进程/模块。启动器先发事件再创建游戏进程，事件回调不能等待尚未创建的进程。
- 本轮只修改 Python，无需更新原生 DLL；重启启动器以加载新模块。实际播放与启动耗时仍需端到端复验。

## 0.9.31 跟进（实际回合命中后的音库失败）

- 用户 PID 6772 的原生日志记录 `static: manual off=0 sf=1ae44500e80 ok=1 val=0`：可读地址不代表硬编码 Class+0xB8 正确，不能据此认定单例未初始化。
- 对照旧版并编译验证发现 `fn_field_static_get_value` 错写为三个参数，实际 IL2CPP 导出是 `(field, out)`；已修正 ABI 并移除硬编码偏移读取，改回旧版运行时 API。新增原生继承静态字段读取/空值失败回归通过。仍须真机确认当前导出与实例状态。
- 日志分类零统计支持 `=`，`error=0` 正常为 INFO；真实失败不降级。6 项分类回归通过。
- 健康信息将 `global_installed` 与 `owner_requested` 分开，避免把全局 24 条与本插件 4 条错写成比例。
- 已检查无游戏进程后部署更新 DLL，SHA256：4a948d717e671ec160d29e1c560266e2abaa3bc3e76bac48d5dc8b5bec3f5fb1。上一轮 DLL 备份：test/warp_host_before_0930_f36509488978.dll。完整重启游戏和启动器后生效，不向运行中的游戏热注入。

## 已定位的独立缺陷

- 旧 Service 等待游戏或 GameAssembly 超时、注入失败后直接结束线程；现在持续探测并重试，跟踪 PID 改变。
- Live 另建空配置的 Service Host，会覆盖同插件的钩子定义；现在传入已有 Host。后台配置 owner 使用线程本地上下文，读取回合命中显式指定 owner。
- 单个插件关闭共享 Host，会影响其余插件；现在先停止自身线程，共享映射只在全局卸载且线程确已退出后关闭。超时宁可保留资源，不释放在途访问所需内存。
- Python 写入的共享心跳不能证明游戏进程已载入 DLL；现在在目标 PID 内检查实际 DLL 模块。
- 原生热重装可能释放在途 trampoline；现在禁用但保留跳板，并按目标地址复用稳定物理槽。模块固定到游戏进程退出，不支持原地卸载旧模块切换新构建。
- 命令 ack / BUSY 的发布顺序和多个泵线程领取存在竞态；现在原子领取并先发布 BUSY。
- GC handle 数组虽然已扩为 uintptr_t，但函数指针原型仍为 unsigned int；64 位句柄在返回阶段就被截断。现在原型也同步为 uintptr_t，原生回归使用高位非零句柄。
- audio.ensure_bank 重复定义，后面的旧弃用版本覆盖了实际实现，并返回不同类型；现在保留唯一的 tuple 实现。

## 与独立旧版的对照边界

参考源为用户提供的 BattleBGMExtend-main.zip。复用其短名 StartAddBGM 入口、音库绝对路径、assets.bank 与 bank 双文件预载、预载失败保留原曲的顺序。不得在未知 bank 上停止原曲后盲试。

旧版 FMOD TryCreateInstance 的安全事件预检和实际播放状态验证，不等同于当前共享命令桥接返回的 void 执行成功。当前结果中的 verified=False 明确表示未确认实际出声；不通过高风险的场景切换期自动 FMOD 查询假装已经验证。恢复完整 FMOD 预检仍需要单独验证 ABI 与对象生命周期。

## 离线验证

- `python -m unittest discover -s test -p test_warp_lifecycle_regression.py -v`：15 项通过，包含实际 worker 方法的 fake 时钟晚启动、GameAssembly 超时重试、注入失败重试和 PID 重连，以及线程 owner 隔离和注入超时资源保护。
- `python -m unittest discover -s test -p test_bgm_standalone.py -v`：17 项通过，包含双 bank 绝对路径预载、失败不停止原曲、字符串失败/异常释放、旧任务取消、重复排队及插件日志转交持久化 writer。
- 原生独立回归实际通过：真实 MinHook 20 次拆装与稳定跳板复用，整数/浮点/9 参数及隐藏 MethodInfo ABI，8 个并发命令泵且恰好执行一次，worker 阻塞停止保资源，64 位高位非零 GC handle 释放。测试使用完整 WARP_MAP_BYTES 内存，未载入游戏。
- 最终 DLL 已用 MinGW GCC -O2 -Wall 构建，无告警；检查游戏未运行后部署到 addons/WarpHook/warp_host.dll。SHA256：f3650948897841ad1a842914719b1cfce2681838d28f93620122d2f1015e2f21。旧版备份：test/warp_host_before_0930_7f09bb8869ce.dll。
- 原生日志新增毫秒时间、PID、线程和有界格式化；worker 完成记录 seq/type/rc，不打印命令文本。
- Python compileall 与 git diff --check 通过；测试是离线 fake/AST 回归，不是对当前游戏版本的端到端保证。
- BGM 优先级地板维持旧版 locked/priority 语义，本次不擅自改变低优先级回退策略。FMOD TryCreateInstance 预检尚未安全移植。
- BattleBGMExtend 与 test 目录受现有 .gitignore 规则忽略，本次文件已在工作区修改，但普通 git diff 不展示它们；打包或同步时须显式包含，不要仅打包已跟踪差异。

## 更新方式

先完整退出游戏和启动器，再替换/使用新的 warp_host.dll。已有游戏进程加载的旧模块不会因为磁盘文件变动而更新。不要重复注入不同路径的候选 DLL 到同一个游戏进程。

## 真机验收顺序

1. 游戏关闭时打开启动器并启用 BGM 插件；确认日志持续处于 waiting_game。等待超过原来的等待时限后，再启动游戏。
2. 核对 waiting_gameassembly、inject_result、monitoring 的同一 PID；核对安装数量和错误码，不能把 LoadLibrary 完成当作业务成功。
3. 进入战斗，连续触发多次回合开始或手动检测，观察 hits 增量、战斗快照、规则命中、曲目提交。确认后续仍能响应且游戏未退出。
4. 选择需要跨 bank 的规则，确认 bank 预载；故意配置不存在的 bank 时，应明确失败并保留原曲。
5. 快速触发检测后离开战斗/关闭插件，确认旧请求不会在新场景补播。随后重新启用，确认重新可检测。
6. 不退出启动器，退出并重开游戏；确认进程变化及重新注入，不需要重启启动器。
7. 一个依赖插件卸载时，其余插件仍工作；全局卸载若出现停止超时，日志明确保留共享映射，而非启动器直接消失。

## 应保留的日志

只有一个文件：`addons/WarpHook/warp.log`（整个 WarpHook 共用，启动即覆写、不轮转）。
两类行按前缀区分：

- 行内带 `[host]`：启动器 PID/线程、阶段、`waiting_game` / `waiting_gameassembly`、
  `inject_result`、Win32 错误及 traceback，以及游戏进程内的装配、命令与 worker 状态。
- 行内带 `[event]`：事件流水，用于对应命中与回调。

因为文件每次启动都被清空，**出问题的当轮必须当场拷贝走**；启动器退出后再拷就只剩下一轮了。

报告时保留问题发生前后的同一时间段，注明启动顺序、游戏 PID、曲目/音库和动作。离线测试与原生自测通过不代表实际游戏版本的音频 ABI、听感与长时间稳定性已验证。
