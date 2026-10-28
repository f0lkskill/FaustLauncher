# WarpHook 更新记录

这里只记 WarpHook 自身的改动。启动器本体（`functions/`、`web/`）的改动不在这个文件里。

看完整历史：`git log --oneline -- addons/WarpHook/`

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
