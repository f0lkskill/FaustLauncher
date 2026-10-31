# 05 warp.plugin —— 宿主与后台骨架

这一层是「自己掌控」的地方：`Host` 是共享内存宿主的 Python 句柄（写钩子、代读、发命令），
`Service` 是插件后台流程的骨架，`Runtime` 是自带 DLL 的老式插件骨架。

```python
plugin = _NS.space('warp').plugin
```

## `Host` —— 共享宿主句柄

```python
host = plugin.Host(ADDON_NAME)                 # 按插件名分段（多插件共用一块映射）
host = plugin.Host(ADDON_NAME, hooks=[...])    # 顺手登记钩子
host = plugin.Host(ADDON_NAME, enabled=True)   # 默认启用
```

| 方法 | 返回 | 说明 |
| --- | --- | --- |
| `hook(klass, method, ...)` | `dict` | 登记一条钩子，返回那条 dict（见下） |
| `clear_hooks()` | — | 清空本插件的钩子（重新声明前调） |
| `hooks()` | `list` | 当前登记的钩子 |
| `configure(hooks=None, texts=None, dedupe_ms=None)` | — | 批量设置（改完要 `push()`） |
| `push(enabled=None)` | `str` | 把配置写进共享内存，返回 `共享内存不可用` 之类表示失败 |
| `status(owner=None)` | `dict` | 状态字典（键见 `warp.game.status()`） |
| `status_line(st=None)` | `str` | 一行状态文本 |
| `beat()` | — | 写心跳（自己写循环时**必须**每轮调） |
| `poll()` | `dict` | 读一次状态并更新内部缓存 |
| `hits(method=None, blocked=False, owner=None)` | `int` | 某方法累计命中数 |
| `events(limit=None)` | `list[HostEvent]` | 取事件（**消费语义**：取走就推进 tail） |
| `object_ptr(slot)` | `int\|None` | 对象槽里的指针 |
| `read(slot, chain, kind="int", timeout=2.0, default=None, detail=False)` | 值 | **让游戏主线程代读**（v7 起读对象一律走这里） |
| `read_local(slot, chain, kind="int")` | 值 | 本进程裸读，跨进程必崩，仅诊断用 |
| `read_object(...)` | 值 | `read()` 的旧名字 |
| `object_slot(slot, out=0, kind="int")` | 值 | 读事件的输出格 |
| `write_buff_watch(hashes)` | — | 设置 buff 关注列表（bitmask 用） |
| `make(klass, args=(), slot=24, timeout=2.0)` | 槽号 | 在游戏里构造一个对象 |
| `make_str(text, slot=24, timeout=2.0)` | 槽号 | 构造一个 il2cpp string |
| `call(method, slot=None, args=(), ret="int32", out_slot=-1, timeout=2.0)` | 值/槽号 | 调游戏方法 |
| `release(slot, timeout=2.0)` | — | 释放对象槽上的 GC 句柄 |
| `popup(text, timeout=2.0)` | `str` | 让游戏弹窗 |
| `kill_game(timeout=2.0)` | `str` | 让游戏退出进程 |
| `set_enabled(on)` | `str` | 启用 / 停用整套钩子 |
| `arm()` / `disarm()` | — | 同一件事的旧写法 |
| `inject_now(wait=False, stop_event=None)` | — | 手动注入 DLL |
| `dll_path()` | `str` | `warp_host.dll` 的完整路径 |
| `block()` | 映射对象 | 共享内存块（**方法，不是属性**） |
| `read_mapped()` / `mapped_texts()` | — | 读映射 / 读文案区 |
| `log(message, owner=None)` | — | 写一行日志 |
| `close()` | — | 关映射 |

### `hook()` 的全部参数

```python
host.hook(
    'BattleUnitModel', 'OnCreateUnitModel',
    argc=0,                # 参数个数（不含 self）
    block=False,           # True = 拦下，不执行原方法
    actions=None,          # 动作位；默认 0 = 只看不碰
    probe=None,            # (类, 方法, 参数序号, vars 槽号) 顺手把参数对象的属性读进 vars
    guard=None,            # (vars 槽号, 值) 那个槽等于该值时才放行
    event=1,               # 每次命中往事件环塞一条
    reads=None,            # 读取链列表，命中时读值写进事件格
    dedupe=False,          # 读出的值跟上次一样就不投递（挂 FixedUpdate 必开）
    cache=(0, 27),         # (参数序号, 槽号) 命中时把那个参数的指针存进对象槽
    when=None,             # 1 = 原方法调用**之后**才处理
    ret_kind=None,         # 'int32' / 'float'：取原方法返回值（自动转 POST）
    ret_slot=None,         # 返回值直出到事件的某一格
)
```

| 参数 | 缺省 | 说明 |
| --- | --- | --- |
| `klass` / `method` | — | 类名 / 方法名（必填） |
| `argc` | `0` | 参数个数，**不含 `this`** |
| `block` | `False` | 拦下原方法 |
| `actions` | `0` | 动作位（`ACT_POPUP` 等），默认什么也不做 |
| `probe` | `None` | `(类, 方法, 参数序号, vars 槽)`，把参数对象的属性读进 `vars[]` |
| `guard` | `None` | `(vars 槽, 值)`，等于才放行（拿来做开关） |
| `event` | `None` | 事件号，非 `None` 就往事件环投递 |
| `reads` | `None` | 读取链列表 |
| `dedupe` | `False` | 去重（值不变不投递） |
| `cache` | `None` | `(参数序号, 槽号)`，留住参数指针 |
| `when` | `None` | `1` = POST（原方法之后） |
| `ret_kind` | `None` | `'int32'` / `'float'` |
| `ret_slot` | `None` | 返回值落哪一格 |

### 调用示例

**只看不看、抓住对象**

```python
host.hook('BattleUnitModel', 'OnCreateUnitModel', argc=0, cache=(0, 27))
host.push(True)
```

**拦下抽卡**

```python
host.hook('MainUI.GachaUIPresenter', 'OnGachaSelected', argc=2, block=True,
          guard=(0, 1))
host.push(True)
```

**读一个值（代读）**

```python
hp = host.read(28, [{'off': 0x90, 'deref': True}, {'dict': 0},
                    {'off': 0x10, 'deref': True},
                    {'off': 0x148, 'deref': True},
                    {'off': 0x148, 'deref': False}], kind='obscured')
```

**调一个静态方法**

```python
slot = host.call('BattleObjectManager::get_Instance', ret='ref', out_slot=28)
print(host.object_ptr(28))       # 管理器地址
```

`call` 的 `ret` 三种形状：

| `ret` | 返回 | 说明 |
| --- | --- | --- |
| `'int32'` | `int` | 返回值当 32 位整数（RAX） |
| `'float'` | `float` | 返回值当浮点（XMM0） |
| `'ref'` | 槽号 | 返回的对象落进 `out_slot` 那个槽 |

## `Service` —— 插件后台骨架

不用它也能写插件（`game.*` 自己管线程），但要做「等游戏 → 注入 → 心跳 → 状态播报 →
托盘菜单」这一整套，用它最省事。

```python
service = plugin.Service(
    addon_name=ADDON_NAME,
    name='我的插件',
    sync=_push,                                        # 把设置写进共享内存
    auto=lambda: True,                                  # 游戏启动时自动注入
    menu=(('注入', lambda: service.inject_now(wait=True)),
          ('解除', lambda: service.set_enabled(False)),
          ('应用设置', lambda: service.sync())),
)
service.start()
```

| 参数 | 缺省 | 说明 |
| --- | --- | --- |
| `addon_name` | 调用方模块名 | 记账用的键 |
| `name` | 同 `addon_name` | 日志前缀 / 菜单标题 |
| `sync` | `None` | `() -> 任意`：把当前设置写进共享内存 |
| `auto` | `None` | `() -> bool`：游戏启动时要不要自动注入 |
| `menu` | `()` | `((标题, 回调), ...)` 托盘菜单项 |
| `interval` | `0.25` | 心跳间隔（秒，最小 0.05） |
| `host` | `None` | 复用已有 `Host` |
| `shared` | `True` | `True` = 共享宿主 `warp_host.dll`；`False` = 插件自带 DLL |

| 方法 | 说明 |
| --- | --- |
| `start()` | 起后台线程 |
| `stop()` | 停线程（`on_unload` 里调） |
| `host()` | 拿 `Host` |
| `sync()` | 立刻把设置推一次 |
| `on_hit(callback, *, method=None, once=False, delay=0.0, thread=True)` | 钩子命中后调 `callback(host)`；`thread=True` 跑独立线程（可 `sleep`） |
| `on_event(callback)` | 事件环有新事件时调 |
| `inject_now(wait=False)` | 手动注入 |
| `set_enabled(enabled=True)` | 启用 / 停用 |
| `status()` | 状态字典 |
| `describe(st)` | 一行状态文本 |
| `register_menu()` | 手动注册菜单 |
| `Service.stop_all()` | 类方法，停掉全部 |

`on_hit` 的 `once=True` 表示同一个方法只回调一次（自爆插件用）。

## `Runtime` —— 自带 DLL 的老式骨架

v0.4 时代的写法，插件自己带一个 DLL、自己一块共享内存。现在的插件基本不用，
但 `COMMON_FIELDS` 这个常量还在用：

| 参数 | 说明 |
| --- | --- |
| `addon_name` | 插件名 |
| `map_name` | 共享内存名 |
| `struct_cls` | 配置结构体类型 |
| `magic` | 结构体 `magic` 字段的期望值 |
| `dll_name` | 插件目录下的 DLL 文件名 |
| `exports` | il2cpp 导出名序列（顺序要与 C 侧一致） |
| `apply` / `read` | `(block, enabled) -> (ok, msg)` / `(block) -> dict` |
| `format_line` | `(status) -> str` |
| `menu_labels` | 三个菜单文案 |
| `auto_key` | settings 里控制自动注入的键名 |

方法：`log` `settings` `block` `cfg` `read_mapped` `push` `set_enabled` `arm` `disarm`
`status` `dll_path` `beat` `poll` `close` `inject_now`。

## 常量

### 钩子 flags

| 常量 | 值 | 含义 |
| --- | --- | --- |
| `HF_BLOCK` | `0x01` | 拦下原方法 |
| `HF_ONCE` | `0x02` | 只触发一次 |
| `HF_DEDUPE` | `0x04` | 读值不变就不投递 |

### 动作位

| 常量 | 说明 |
| --- | --- |
| `ACT_POPUP` | 弹窗 |
| `ACT_PANEL` | 面板 |
| `ACT_KILL` | 退出游戏 |

**默认是 `0`（什么都不做）**——要弹窗自己调 `host.popup()`。

### 命令

| 常量 | 值 | 含义 |
| --- | --- | --- |
| `CMD_NONE` | `0` | 空 |
| `CMD_POPUP` | `1` | 弹窗 |
| `CMD_KILL` | `2` | 退出游戏 |
| `CMD_MAKE` | `3` | 构造对象 |
| `CMD_CALL` | `4` | 调方法 |
| `CMD_STR` | `5` | 构造字符串 |
| `CMD_RELEASE` | `6` | 释放句柄 |
| `CMD_READ` | `7` | 代读（v7 新增） |

### 读链与事件

| 常量 | 值 | 含义 |
| --- | --- | --- |
| `HOST_STEP_PLAIN` | `0` | 只加偏移（+ 可选解引用） |
| `HOST_STEP_DEREF` | `1` | 解引用 |
| `HOST_STEP_LIST` | `2` | List 约定偏移 |
| `HOST_STEP_ARRAY` | `3` | Array 约定偏移 |
| `HOST_STEP_LIST_VAL` | `4` | List 取第 i 个值 |
| `HOST_STEP_ARRAY_VAL` | `5` | Array 取第 i 个值 |
| `HOST_STEP_DICT_VALUE` | `6` | Dictionary 取第 k 个活跃 value |
| `HOST_STEP_DICT_VALUE32` | `7` | 同上，值直出 |
| `HOST_READ_STEPS` | `8` | 一条链最多几步 |
| `HOST_READ_SIZE` | `80` | 一条读链占多少字节 |
| `HOST_READ_MAX` | `128` | 最多几条读链 |
| `HOST_EVENT_SLOTS` | `12` | 一条事件带几格数据（a..l） |
| `HOST_EVENT_COUNT` | `2048` | 事件环容量 |
| `HOST_EVENT_SIZE` | `60` | 一条事件多少字节 |
| `HOST_EVENT_SLOTS` | `12` | 事件数据格数 |

### 落点 kind

| 常量 | 值 | 含义 |
| --- | --- | --- |
| `HOST_READ_INT` | `0` | int32 |
| `HOST_READ_FLOAT` | `1` | float |
| `HOST_READ_BOOL` | `2` | bool |
| `HOST_READ_PTR` | `3` | 指针 |
| `HOST_READ_OBSCURED` | `4` | 解混淆 int |
| `HOST_READ_SUM_LIST` | `5` | 容器求和 |
| `HOST_READ_COUNT_LIST` | `6` | List/Array 元素数 |
| `HOST_READ_TEXT_NUM` | `7` | 字符串指纹 |
| `HOST_READ_BUFF_MASK` | `8` | buff 位掩码 |
| `HOST_READ_COUNT_DICT` | `9` | Dictionary 活跃数 |

### 布局

| 常量 | 值 | 说明 |
| --- | --- | --- |
| `HOST_MAP_BYTES` | `177104` | 整块共享内存大小（v7） |
| `HOST_HEADER_SIZE` | `432` | 头部 |
| `HOST_HOOK_OFFSET` / `HOST_HOOK_SIZE` | `432` / `288` | 钩子表起点 / 每条大小 |
| `HOST_MAX_HOOKS` | `32` | 钩子槽总数 |
| `HOST_HOOKS_PRIMARY` | `27` | 成就主段占的钩子数（0..26） |
| `HOST_READS_PRIMARY` | `96` | 主段读链数 |
| `HOST_TEXTS_PRIMARY` | `192` | 主段文案数 |
| `HOST_TEXT_SIZE` / `HOST_MAX_TEXTS` | `128` / `256` | 文案格 |
| `HOST_OBJECT_COUNT` / `HOST_OBJECT_SIZE` | `32` / `8` | 对象槽 |
| `HOST_OBJ_ARG_BASE` | `0x100` | 读链里 `arg=0x100+n` 表示对象槽 n |
| `HOST_VAR_COUNT` | `16` | `vars[]` 槽数 |
| `HOST_CMD_TEXT_LEN` | `256` | 命令文本长度 |
| `HOST_DLL_NAME` | `warp_host.dll` | 宿主 DLL 文件名 |

### 结构体

| 类 | 说明 |
| --- | --- |
| `HostHeader` | 共享内存头部（`magic` `version` `enabled` `hooked` `evt_count` `vars[]` …） |
| `HostHook` | 一条钩子的磁盘布局（写 `configure` 时不必自己碰） |
| `HostRead` | 一条读链的磁盘布局 |
| `HostEvent` | 一条事件（`id` `hook` `tick` `a`..`l`） |

### 其他函数

| 函数 | 说明 |
| --- | --- |
| `host_alive(block)` | 映射是否指向一个活的宿主（校验 magic + version + 心跳/钩子状态） |
| `host_build(log_path=None)` | 读宿主日志尾部的构建戳，如 `Oct 31 2026 14:51:57 proto v7` |
| `COMMON_FIELDS` | 老式插件共享内存的约定字段名 |
| `ensure_exports(block, names, offset, name_max)` | 填 il2cpp 导出名表 |

!!! danger "`host.block` 是方法"
    `host.block` 返回的是**绑定方法**，不是映射对象。要用 `host.block()`。
    这个坑踩过一次：`host_alive(host.block)` 会静默返回 `False`。
