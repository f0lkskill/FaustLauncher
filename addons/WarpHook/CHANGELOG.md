# WarpHook 更新记录

这里只记 WarpHook 自身的改动。启动器本体（`functions/`、`web/`）的改动不在这个文件里。

看完整历史：`git log --oneline -- addons/WarpHook/`

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
