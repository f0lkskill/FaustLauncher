# WarpHook 开发笔记

零散的判断、边界和还没做的事。协议细节在 `addons/WarpHook/DESIGN.md`，
用法示例在 `addons/WarpHook/README.md`，这份只记「为什么这么做」和「下一步」。

---

## 一、这个组件到底是什么

一句话：**插件 Python 与游戏 C++ 之间的中间包装**。

不是「钩子管理器」，也不是「成就引擎」。它只提供四类原语，别的什么都别往里塞：

| 原语 | 干什么 |
| --- | --- |
| 钩子 | 声明「哪个类的哪个方法被调用时通知我」，可拦可放 |
| 事件 | 命中后把「谁、哪个钩子、几个读出来的值」写进环形队列，Python 逐条取 |
| 读取链 | 告诉引擎「从这个对象的这个偏移、跳几下、读几个字节」 |
| 命令通道 | 反过来：Python 想让它弹窗 / 崩游戏，写一条命令，游戏主线程执行 |

判断标准：**如果一件事能用这四样之一组合出来，就不该加新接口**。
之前 Service 长出 `watch` / `auto_inject` / `register_menu` 一大堆，就是违反这条被推翻重做的。

---

## 二、几条已经确定下来的规则

### 线程归属

插件只提供**函数**，线程由 WarpHook 起（用户原话：「让插件提供函数，然后 wh 负责统一起线程」）。
插件要是自己起线程，重载时旧线程没收住，就会出现「两份日志」「两个实例互相覆盖」。

### 重载要清 `sys.modules`

启动器用 `exec(compile(...), module_globals)` 载入插件，`warphook.*` 会留在 `sys.modules` 里。
不清掉的话，插件重载后子模块不重新执行，模块级单例还是旧的 —— `scr.py` 开头那段
`for _stale in ...` 就是干这个的，不能删。

### 结构尺寸以 `sizeof` / `ctypes.sizeof` 为准

给 `WARP_HOOK` 加字段后，我按公式手算 `272`，实际 `ctypes` 报 `264`。
手算会漏 padding，两边不一致的后果是**整块映射错位**，症状是「钩子装上了但读出来全是 0」。

### 顶层 `deref` 数组要显式写

读取链的「跳」有两层含义：加偏移（内嵌 struct）和解引用（class 引用）。
默认是**解引用**，所以读内嵌字段必须显式 `deref: [false]`。
忘了写的后果不是读错数，是**把枚举当指针解引用 → 游戏直接崩**（`*(int*)0`）。
C 侧现在有 `warp_can_read` 兜底（`VirtualQuery` 查 `MEM_COMMIT` + 可读保护位），
但那是保险，不是许可证。

### 钩子表变更 = 重装

DLL 装过一次钩子后原来就 `continue` 了，导致「游戏运行中改配置必须重启游戏」。
现在控制线程每 250ms 算一次钩子表的 FNV-1a 指纹，变了之后**等 400ms 稳定**再卸了重装。
400ms 是给 Python 写表留的时间，别调小。

---

## 三、边界：读取链能做什么、不能做什么

能：**内存里的数字**。int / float / bool / 指针 / `ObscuredInt`，沿偏移链跳最多 4 跳；
容器也能进 —— `List`（0.4.0 / 0.7.0）、`Dictionary`（0.9.7 协议 v6，0.9.8 真机纠错），
按下标取 or 整批遍历（一条链一次命中枚举出全场单位）。

不能：

- **函数返回值** —— 值在 `xmm0` / `eax` 里，不在对象里
- **容器的 TKey** —— 遍历吐出来的是 TValue，要键就在配置里另算 key 偏移
- **字符串** —— il2cpp string 是变长结构，要读长度再读 utf16
- **小 getter 的调用点** —— 见下一节

### il2cpp 内联

AOT 编译会把一行的 getter 内联进所有调用点，内存里没有调用指令，钩子命中 0。
`CharacterState::get_Hp` 就是这样。**选钩子要看体积，不是看名字好不好听。**

---

## 四、下一步（按优先级）

### 1. 容器步（已完成）

`List<T>` 遍历 0.4.0 / 0.7.0；`Dictionary<K,V>` 0.9.7（协议 v6），0.9.8 真机纠错。
新增两种步类型 `dict` / `dict_val`（deref 6/7）和 `iter` 位：普通用法按下标取第 k 个活跃值，
带 iter 位则一次命中枚举全部活跃值、每轮推一条事件。

真机踩了两个边界，都写进 DESIGN 了：遍历范围用 `count`（+0x20）不是 entries 容量；
「从未用过」的槽 hashCode 是 0，只有 `Remove` 留下的死坑才是 -1。

`BattleObjectManager._allUnitDictionary → 每个单元 → _model → _instanceID`
一条四跳链就能拿到全场单位 id，正是成就需要的「遍历全场单位」。

### 2. 去重开关（已完成）

单值去重 0.4.1（`flags & WARP_HF_DEDUPE`）；批去重 0.9.7 随容器步一起做 ——
遍历批按「轮 0 快照的 12 格 FNV 哈希 + 轮数」比对，整批不变就不投。
`FixedUpdate` 60fps + 512 格环 8.5 秒翻一轮的压力测试通过（连打三回合字典不变只投 1 批）。
**注意：开关必须显式打开（`flags=0x04` / Python 侧 `dedupe=True`），不开位则每回合全量重投。**

### 3. 采样率（未做）

用户提过「允许自己配自己的采样率，同时兼容低访问的普通插件」。
方向：钩子项加 `sample_every`（每 N 次命中才投递一次），C 侧计数取模，不用 Python 参与。

### 4. 中间层（未做）

用户原话：「如果那些其他映射真翻译不了，那我们可以做中间层，反正包装到极致最好。」
比如 `BattleUnitModel.hp` 这种「链 + 解密 + 容器」组合，可以做成语义层：
配置写 `{'unit': 'self', 'field': 'hp'}`，底层展开成若干步。位置应该在 WarpHook 里，
不是插件里 —— 否则每个插件都要重复一遍。

---

## 五、留给后来者的几条教训

1. **症状是「全是 0」时，先怀疑偏移和尺寸，别怀疑逻辑。** 三次全部 0，三次都是偏移/尺寸错。
2. **测试绿不等于对。** `warp_host_smoke` 曾经一直绿，因为测试和 DLL 用的是同一份旧布局，
   自洽但都不对；换了新 DLL 立刻变成 `bind exports ok (11)`。
   布局变更时，测试里的常量必须手动同步，而且要拿 DLL 真实 `sizeof` 对一遍。
3. **void thunk 的「寄存器透传」是运气不是机制。** thunk 声明成 `void` 时，
   RAX/XMM0 里 original 留下的返回值只要没人碰就会透传回调用方——但「没人碰」
   保持不住：发事件、fire 动作，任何后续 C 代码都可能用掉 XMM0。带返回值的钩子
   （`ret_kind`）必须在 thunk 的**最后一步**把值显式写回（int→`movl %0,%%eax`、
   float→`movd %0,%%xmm0`），写在函数末尾保证后面没有代码再碰这两个寄存器。
4. **thunk 形状要完整收发 il2cpp 的隐藏 `MethodInfo*`。** 形状写成
   `(self, a1..aN, mi)` 而不是 `(self, a1..aN)`：非泛型方法体一般不读 mi，
   丢了也没事，但九参构造（railway_hist 的 `.ctor`）不敢赌——多声明一个形参
   就能完整转发，成本为零。
5. **宏参数带逗号要整体加括号。** `WARP_THUNK_DEF(N, n, DECL, EVT, CALL)` 的
   `EVT` 摊平后是六个实参，宏只看到十个参数直接炸（`passed 10 arguments, but
   takes just 5`）。实参处写 `(NULL, a1, …, a6)`，配合 `WARP_EVT6 EVT` 摊平。
6. **同一件事的两条配置路径必须共用一张翻译表。** `ret_kind='int32'` 在
   `hook()` 关键字路径有名字翻译，`_write_config` 的 dict 路径却直接 `int(value)`
   ——失败后**静默回退 VOID**，返回值悄悄丢了，还不报错。修法是抽
   `HOST_RET_NAMES` 常量两边共用。
7. **`& (N-1)` 掩码钳位只对 2 的幂成立。** 事件八格时 `out & 7` 是对的，
   扩成十二格后 `out & 11` 会把 12 折成 8——非 2 的幂一律用显式
   `max(0, min(x, N-1))`。
8. **删一整段代码前，先把区间里的 `def` 清单列全再动手。** P5 删老链路时按
   首尾锚点整段删除，把夹在中间的 574 行规则引擎应用层（`handle_line` 到
   `_apply_buffs`）一起吞了；靠 `git show HEAD:` 把区间原样提回来才救回。
   锚点删除必须先断言「区间内 def 列表 == 预期要删的列表」。
9. **这个仓库不要用 `git stash`，对照基线一律 `git worktree add`。** 工作区里
   常驻忽略文件和别的会话留下的脏改动，stash push/pop 一冲突就出 DU 混沌态；
   worktree 挂提交号是只读对照，永远干净。
10. **il2cpp 的 `Dictionary` 字段序不等于 .NET reference source。** 照文档把
   `freeCount` 读在 `+0x2C`，真机读到的是 `version`（13），`count - freeCount`
   变负数 → `dict_count` 恒 0。实测是 `count@0x20 / freeList@0x24 / freeCount@0x28 /
   version@0x2C`。最阴的是**单元测试用伪造内存 + 同一个错误假设，全绿**；
   「测试绿 ≠ 对」这次又应验了一遍。
11. **只比 `version` 区分不了同协议号的两次构建。** 改完源码编到 `test/` 忘了拷
   到 `addons/WarpHook/`，游戏跑的还是旧 DLL：`hdr.version` 照样是 6，症状却是
   「`dict_count` 读出 1682595280 = buckets 指针低 32 位、iter 批只出 1 条」。
   现在 DLL 启动打一行 `build <DATE> <TIME> proto vN`，Python 侧 `host_build()`
   对得上才算同版。
