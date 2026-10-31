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

0.9.9（协议 v7）起，读对象不用自己拼链、不用装钩子：

```python
from warphook import objects

host = service.host()

bom = objects.bind_manager(host)        # 抓 BattleObjectManager（等一个回合）
for u in objects.units(host, bom):      # 全场单位
    print(u.instance_id(), u.hp(), '/', u.max_hp(), '理智', u.mp())

print(objects.scene(host))              # {'scene': 1, 'time_scale': 1.0}
```

想看「一个单位身上到底有什么」，直接扫：

```python
u = objects.unit(host, bom, 0)
u.scan()            # BattleUnitModel + CharacterState 全部 63 个字段
u.buff_count()      # 身上几个 buff
u.buff_ids()        # 每个 buff 名字的指纹（原文要等协议 v8）
objects.scene_full(host)                        # 场景对象全字段
objects.scan_class(host, objects.SLOT_SCENE, 'GlobalGameManager')
```

`scan()` 每个字段一次代读往返，整场扫下来十几秒 —— 摸底用它，业务只读你关心的。

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
