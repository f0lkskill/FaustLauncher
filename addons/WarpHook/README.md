# WarpHook

> 本目录是 [FaustLauncher](https://github.com/f0lkskill/FaustLauncher) 仓库内的**独立组件**，
> 不是独立仓库。它有自己的 `README.md` 与 `CHANGELOG.md`，版本号单独演进
> （`warphook/vX.Y.Z` 标签），但代码与启动器一起在 `main` 上维护。
> 看它的完整提交历史：`git log --oneline -- addons/WarpHook/`
> 只看它的提交信息：`git log --oneline --grep "warphook"`

插件底层依赖库。别的插件只写 Python，**不写任何 C 代码**：等游戏、注入、
挂钩、读参数、弹窗、杀进程全部由这里的 `warp_host.dll` 完成，插件通过一块
共享内存给它下配置。

```
Warphook/
├── addon_info.json          插件声明（permanent：作为依赖库常驻，不可关闭）
├── scr.py                   入口（40 行）：bind 作用域 + 注册 warp 命名空间
├── warphook/                运行时实现（Python）
│   ├── env.py               插件作用域（ADDON_ARG / ADDON_NAME）
│   ├── base.py              Win32、共享内存、il2cpp 导出名解析、注入
│   ├── host.py              Host：钩子表与文案池的配置端
│   ├── game.py              Gacha / GachaBill：抽卡语义层
│   ├── service.py           Runtime / Service：等游戏、注入、心跳、状态播报
│   └── registry.py          组装 warp 命名空间、卸载收尾
├── src/                     C 侧（编译成 warp_host.dll）
│   ├── warp_layout.h        协议结构：WARP_HEADER / WARP_HOOK / 函数指针类型
│   ├── warp_internal.h      内部契约：extern 全局与函数原型
│   ├── warp_state.c         全局状态、日志、状态码
│   ├── warp_shm.c           共享映射
│   ├── warp_il2cpp.c        混淆导出名绑定、类与方法解析
│   ├── warp_ready.c         引擎就绪门闩
│   ├── warp_popup.c         原版弹窗、杀进程
│   ├── warp_action.c        挑台词、执行动作、参数探针
│   ├── warp_hook.c          thunk 表、装配 / 卸载钩子
│   ├── warp_cmd.c           命令泵（主动 popup / kill_game）
│   └── warp_host.c          控制线程与 DllMain
├── warp_stub.py             类型桩（给插件的 IDE / pyright 用，无运行时逻辑）
├── DESIGN.md                设计文档、协议表、命名空间契约、代码结构
└── il2cpp-api-names.txt     il2cpp 导出名的期望表
```

## 调试模式（0.9.50）

在启动器的 WarpHook 插件设置中开启「调试模式」，无需为切换日志开关重启游戏。
默认关闭：保留连接、实际状态变化、换曲和错误；不再周期输出健康状态、无命中扫描、音库阶段和锁计数。
开启后，代理插件的注入结果（PID、DLL 路径）、周期宿主状态及 native tail、回合命中和音频阶段进入详细日志。
插件可使用 `warp.log.debug(message, prefix=...)`，昂贵的诊断读取应先检查 `warp.log.is_debug_enabled()`。
同一 BGM 自动错误按内容合并，手动恢复等操作始终反馈。

## 导出解析（0.9.51）

出现「引用 0 个，基准表 234 项」表示表已读取，失败在 DLL 名字/指令解析链路。解析器现在兼容不同长度混淆名及高寄存器 LEA，标准导出按名字直接映射；错误包含各阶段计数及两 DLL 摘要，避免误导用户反复放置基准表。

缓存绑定 GameAssembly、UnityPlayer、基准表有序内容和解析器版本，旧缓存自动失效。宿主失败短暂退避后重试，重复错误节流。混淆映射仍依赖注册顺序与基准表一致，不能仅凭数量相等证明任意重排安全。本轮用临时合成文件离线验证，没有读取本机游戏；远端故障机器需更新后反馈新诊断。

## 故障排查

- **只有一个日志：`addons/WarpHook/warp.log`。** 宿主 DLL 与 Python 侧写同一个文件，凭行内
  标签区分：`[host]` 是启动器/宿主侧流程（`waiting_game` 持续等待进程、
  `waiting_gameassembly` 等待模块、`inject_result` 仅为 LoadLibrary 阶段结果、`monitoring`
  之后还要核对钩子安装数量和错误码、30 秒健康日志没停表示后台仍在等待/监听），
  `[event]` 是钩子命中的事件流水。
- **启动即覆写**：每次运行启动器，文件先被清空再重写，所以它只描述当前这一轮，不会
  让你看到上一轮的残留；也意味着要留档必须在启动器退出前拷走。曾经的
  `warp_host.log` / `warp_events.log` / `warp_python.log` 及 2 MiB × 3 轮转备份已取消。
- 回合日志区分「钩子命中」「战斗快照不可用」「业务回调异常」。BGM 的 `ok=True, verified=False`
  只代表命令提交完成，不代表已经听到声音；指定 bank 的预载失败不会停掉原曲。
- 后台异常包含 traceback；注入失败包含 API 阶段及 Win32 错误码。停止超时会明确报告并保留在途
  资源，而不是冒险释放共享映射。
- 更新原生 DLL 后必须完整退出游戏和启动器再重新运行。DLL 会为在途 Hook 保留跳板并固定模块
  生命周期，旧游戏进程不能热切换到磁盘上的新 DLL。目录里**只保留最新的 `warp_host.dll`**，
  不要攒 `*_old.dll`（`.gitignore` 已排除）。

## 插件怎么用

```python
NS = ADDON_ARG['Namespaces']
WARP = NS.space('warp') if NS else None

service = WARP.plugin.Service(
    addon_name=ADDON_NAME, name='MyAddon',
    sync=_push,                              # 把设置写进共享内存
    auto=lambda: _settings()['enable'],      # 游戏启动时自动注入？
    menu=(('注入', lambda: service.inject_now(wait=True)),
          ('解除', lambda: service.set_enabled(False)),
          ('应用设置', lambda: service.sync())),
)
service.start()
```

拿到底层句柄就能直接开火：

```python
service.host().popup('这行字是 Python 下发的')   # 游戏里立刻弹原版系统窗
service.host().kill_game()                     # 结束游戏进程
```

## 读游戏里的东西

0.9.9（协议 v7）起，一行就能读到一个单位的血量、人格、buff：

```python
from warphook import game

acc = game.access(host)          # 自动把 BattleObjectManager 抓进对象槽
u = acc.get_obj(id=1)            # 按战斗内编号找

u.hp, u.max_hp                   # 245, 248
u.sp                             # 45   理智
u.identity                       # 10115  人格 ID
u.alive, u.is_panic, u.is_break  # True, False, False

for b in u.buffs:                # 身上的 buff
    print(b.key, b.name, b.stack, b.turn)   # Breath 呼吸法 85 28
u.buff("Breath").stack           # 按英文 ID 找 buff
u.has_buff("Combustion")         # True / False
```

buff 有两个名字，别混：`b.key` 是 `BuffStaticData.id`（英文 ID，如 `"Breath"`），
跨语言不变、**插件判断用这个**；`b.name` 是本地化显示名（`"呼吸法"`）。

全场：

```python
for u in acc.units():            # 场上每个单位
    print(u.id, u.identity, u.hp, '/', u.max_hp)
acc.count()                      # 场上单位数
acc.scene()                      # {'scene': 1, 'time_scale': 1.0, ...}
```

通用取值（好记的名字或 dump 原名都行）：

```python
u.get_pro("origin_id")                    # 人格 ID
u.get_pro("CharacterState._maxHp")        # 带类名前缀
u.props()                                 # 62 个字段的字典（摸底用，慢）
```

底层一直开着 —— 门面只是便利，不是遮罩：

```python
u.read({"off": 0x10, "deref": True}, {"off": 0x60, "deref": False})
host.read(slot, [{"off": 0x90, "deref": True}], kind="dict_count")
from warphook import fields
fields.read_chain("BattleUnit", "_model", "_state", "_hp")
```

想读别的字段就查字段表，或者自己拼链 —— 底层一直开着：

```python
from warphook import fields

spec = fields.read_chain('BattleUnitModel', '_state', '_mp')
host.read(slot, spec['off'], kind=spec['kind'])          # 一次代读往返

host.read(slot, [{'off': 0x90, 'deref': True}, {'dict': 'iter'}],
          kind='dict_count')                            # 遍历链只回报活跃数
```

要「变化的一瞬间」而不是「现在是多少」，就用钩子 + `reads=`：

```python
host.configure(hooks=[{
    'klass': 'BattleObjectManager', 'method': 'OnRoundStart_Model', 'argc': 1,
    'cache': (0, 28), 'flags': 0x04,                     # HF_DEDUPE
    'reads': [{'arg': 0, 'kind': 'dict_count', 'off': [0x90], 'out': 0},
              {'arg': 0, 'kind': 'int', 'off': [0x90, {'dict': 'iter'},
                                                {'off': 0x10}, {'off': 0x60}],
               'out': 1}],
}])
host.push()
```

三个容易踩的地方：

- **不要钩 `GlobalGameManager.FixedUpdate` / `Update`**。那是宿主命令泵的入口，
  钩了它 `host.read` 会全线失效（日志：`pump: no free entry point`）。
  场景状态宿主每帧缓存在对象槽 29，`objects.scene(host)` 直接读。
- **对象槽 30/31 是保留位**（每帧回调的魔法值 + 函数指针），插件用 24..29。
- **钩子 dict 不写 `actions` 就是「只看不动」**。老版本缺省是 `ACT_POPUP`——
  忘了写就会每帧弹空窗，这条真机踩过。

对象槽 24..31 留给插件，0..23 主段是成就观测在用。

## 放一首 BGM

```python
game = _W.game

game.bgm('Battle_Cp9_Boss_10')      # 战斗里换曲，前缀可以不写
game.bgm_playing()                  # True / False
game.bgm_index()                    # 当前曲目编号
game.bgm_stop()                     # 停掉附加曲，游戏原曲回来
```

`game.bgm` 默认等宿主就绪（游戏没开最多等 120 秒），传 `wait=False` 就立刻发。

要自己拼序列（比如先 `PauseBGM` 再播）走 `warp.audio`：

```python
audio = _W.audio
audio.play(host, 'event:/BGM/Battle/Battle_Cp9_Boss_10')
audio.pause(host, True)
```

两个必须知道的点：

- **`StartAddBGM` 收短名**。`audio.short_name()` 帮你截掉
  `event:/BGM/Battle/`，传全长路径会静默不播。
- **游戏会自己掐附加曲**。回合切换/战斗结束时游戏调 `StopAddedBGM` / `StartBGM`。
  保持这首用**换曲锁**：`game.bgm_lock_install()` 装钩子，`game.bgm_lock(False)`
  锁死，`game.bgm_lock(True)` 放行（放曲前必须先解锁）。别再每回合重放。
  详见 `BattleBGMExtend` 移植版。

## 生成 / 移除敌人

```python
game = _W.game

game.create_enemy(1110, level=47, sync_level=4)  # 主线程 wave 流程，创建即 PickSkills
game.create_enemy(1110, immediate=True)          # 主线程直接 CreateEnemyInStage + PickSkills
game.create_enemy(1110, main=False)              # 旧 worker 队列（不保证 PickSkills）
game.remove_enemy(15)                            # 单个入队移除
game.remove_enemies([15, 16])                    # 批量
game.clear_enemies(keep=[17, 18])                # 清空敌方，保留 17/18
```

- v0.9.58 起 `create_enemy` 默认 `main=True`：主线程 `EnqueueCreateUnit` +
  `ForceCreateUnitsInQueue(ON_START_WAVE)`，创建时跑 `PickSkills`，Abnormality
  也能出招；需要重编译 `warp_host.dll`（协议 v16）。
- `level` / `sync_level` 必须使用当前关卡正常敌人的等级（例如 47/4），传
  `-1/-1` 会让 Abnormality 的技能列表缺项，变成不出招的空壳。
- `immediate=True` 主线程直接 `CreateEnemyInStage` 并补 `PickSkills`；
  `main=False` 只入队、等下一回合，不保证 `PickSkills`。
- 移除仍走 `EnqueueRemoveUnitInstanceID`，只改队列，下一回合或生成时机生效。
- 场景切换前先把自制单位清掉，避免不完整的 View / DOTween 留到清场景阶段。

### 观察 / 改写敌人生成

```python
game.watch_enemy_spawn()       # 只读观察，事件号 31/32
game.hook_enemy_spawn(100101)  # 改写 CreateEnemyUnit 的 id
game.clear_enemy_spawn()
```

`watch_enemy_spawn` 用 `host.events()` 读：

- `id=31`（CreateEnemyUnit）：`a=id / b=level / c=syncLevel`
- `id=32`（CreateEnemyInStage）：`a=GenerationData.id / b=level / c=syncLevel / d=faction`

`hook_enemy_spawn` 只改普通敌人入口；Abnormality（嫉妒罪种）如果走
`CreateEnemyInStage`，先观察事件再决定，不要直接假设 int 改写生效。

### 替换 Abnormality part

```python
game.replace_abnormality_part(100101)  # 默认改嫉妒罪种 1110..1115
```

直接改 `AbnormalityStaticData.abnormalityPartList`，下一次游戏正常生成
嫉妒罪种时使用目标 part 的静态数据（技能 / 人格内容）。只改静态数据，
当前场上已生成的敌人不变，需要重进场景。协议 v17，需重编译 DLL。

## 原生退出排查（协议 v14 candidate）

原生命令 worker 曾在启动时调用一次 `il2cpp_thread_attach`，随后在事件等待中
一直保持注册，且没有绑定 `il2cpp_thread_detach`。Unity 退出期间可能等待外来
注册线程，而宿主停止信号直到 `DLL_PROCESS_DETACH` 才到达，存在退出顺序环。
这项源码证据不能代替现场线程栈，不能仅据此认定某次游戏卡死已被确诊。

v14 改为每条 worker 命令执行前 attach、命令成功或 AV 恢复后 detach，先释放
注册再发布 ack；空闲 worker 不注册。缺少 attach/detach 导出或 attach 失败时
命令明确失败。`thread_detach` 的混淆导出名追加在映射尾部独立 64 字节槽中，
原先 24 项导出表以及事件、对象槽等所有偏移保持不变。

`DllMain` 退出仍只置标志、发事件，不等待线程、不调用 IL2CPP、不运行 MinHook
卸钩。进程退出时由操作系统回收固定模块与映射。在途命令若已卡在 IL2CPP 内部，
本修复无法强制中断，也不保证解决所有游戏关闭问题。

独立回归（不加载游戏，不注入，不覆盖生产 DLL）：

```bash
bash addons/WarpHook/tools/test_worker_lifecycle.sh
python addons/WarpHook/tools/test_protocol_layout.py
```

原生桩测试使用实际 worker、Win32 事件与 VEH，覆盖空闲不 attach、成功命令、
AV 恢复后 detach、缺失 detach、attach 失败与停止资源回收。协议测试静态比对
C/Python 偏移。它们不验证真实 GameAssembly 的 shutdown/GC 行为。

## 编译

需要 MinGW-w64 与 MinHook 源码：

```bash
MH=/path/to/minhook
gcc -shared -O2 -Wall -s -static-libgcc -o warp_host.dll \
  src/warp_*.c \
  "$MH/src/hook.c" "$MH/src/buffer.c" "$MH/src/trampoline.c" "$MH/src/hde/hde64.c" \
  -I src -I "$MH/include" -I "$MH/src/hde"
```

编完把 `warp_host.dll` 放到本目录（与 `scr.py` 同级）即可，插件侧会按
`插件目录 / warp_host.dll` 找它。

## 版本与目录

- 代码在 `main` 上，跟着仓库一起演进；`.gitignore` 对 `addons/WarpHook/**` 开了白名单，
  但 `warp_host.dll`、`__pycache__`、运行日志不入库。
- 版本号唯一来源是 `addon_info.json`（`warphook/env.py` 启动时读它，不再各写一份），
  发布时打 `warphook/vX.Y.Z` 标签（不要和启动器本体的版本混在一起）。
- 改动写进本目录的 `CHANGELOG.md`；提交信息用 `feat(warphook): ...` 这种 scope，
  这样 `git log --grep warphook` 就能把它的历史单独筛出来。
