# 06 底层四个命名空间

`warp.shm` / `warp.il2cpp` / `warp.inject` / `warp.log`。

这四个是给 `plugin` 层打地基的：找进程、把 DLL 塞进去、等 il2cpp 导出表就绪、
拿一块共享内存开始读写、打日志。**日常插件开发几乎不直接碰它们** —— `Host` 已经把
「共享内存 + 命令通道 + 事件环」全包了。要看它们只有三种情况：

1. 你要写一个**自带 DLL** 的老式插件（不走 `warp_host.dll`）；
2. 你在排查「DLL 没注入 / 名字表没就绪」这类底层故障；
3. 你想看懂 `Host` 底下到底在做什么。

```python
w = _NS.space('warp')
shm, il2cpp, inject, log = w.shm, w.il2cpp, w.inject, w.log
```

## warp.inject —— 找进程、塞 DLL {#warp-inject}

```mermaid
flowchart LR
    A[find_pid<br/>找游戏进程] --> B[wait_for_gameassembly<br/>等 GameAssembly.dll]
    B --> C[inject<br/>远程线程加载 warp_host.dll]
    C --> D[DLL 自己在游戏里<br/>hook / 建线程]
```

| 函数 | 返回 | 说明 |
| --- | --- | --- |
| `find_pid(process='LimbusCompany.exe')` | `int\|None` | 按可执行文件名找进程 ID（不区分大小写） |
| `has_gameassembly(pid, module='GameAssembly.dll')` | `bool` | 目标进程有没有加载 il2cpp 运行时 |
| `wait_for_game(timeout=600, stop_event=None, process=...)` | `int\|None` | 阻塞等游戏启动，返回 pid；`stop_event` 可中断 |
| `wait_for_gameassembly(pid, timeout=60, stop_event=None, ...)` | `bool` | 等运行时就绪（**必须在它加载完之后才能读导出表**） |
| `inject(pid, dll_path)` | `bool` | 远程线程加载 DLL |
| `game_process` | 属性 | 当前记录的游戏进程（名称） |
| `game_module` | 属性 | 运行时模块名（`GameAssembly.dll`） |

**为什么必须等 `GameAssembly.dll`**：宿主要解析混淆后的 il2cpp 导出名来拿对象构造、
字符串、方法调用能力。运行时没加载完，导出表是空的，`Host` 会一直报「游戏未就绪」。

## warp.shm —— 共享内存 {#warp-shm}

宿主和插件之间唯一的通道。一块**定长**映射，按固定偏移切段：头部 → 钩子表 → 文案表 →
导出名表 → 事件环 → 读链表 → 对象槽 → buff 关注表 → 代读链。

```python
block = shm.open('Local\\WarpHost_Default', 177104, plugin.HostHeader,
                 magic_field='magic', magic_value=0x54534857)
```

| 参数 | 说明 |
| --- | --- |
| `name` | 映射名（`Local\` 前缀 = 当前会话；跨用户要用 `Global\`） |
| `size` | 映射字节数，必须和宿主编译时一致（v7 = `177104`） |
| `struct_cls` | 头部 `ctypes.Structure` 类型 |
| `magic_field` / `magic_value` | 校验字段名与期望值（对不上说明不是我们的映射） |
| `wait` / `timeout` | 映射不存在时要不要等 |

返回 `SharedMap`：

| 成员 | 说明 |
| --- | --- |
| `address()` | 映射基址（`.cfg` 是头部结构体视图） |
| `write_text(field, value, size)` | 往头部某字符串字段写（定长、自动补 `\0`） |
| `write_table(offset, names, name_max=64)` | 往指定偏移写一串名字（导出名表） |
| `read_table(offset, count, name_max=64)` | 读回来 |
| `read_text(field, size)` | 读头部某字符串字段 |
| `close()` | 解除映射 |

`shm.ensure_exports(block, names, offset, name_max=64)`：把导出名**补进**映射里的名字表，
已经有的不重复写。

!!! warning "映射名不要自己编"
    默认是 `Local\\WarpHost_Default`。自己起一个名字 = 开了一块空映射，
    里面没有宿主 —— `host_alive()` 会返回 `False`，`push()` 返回「共享内存不可用」。
    插件不需要自己调 `shm.open`，`plugin.Host` 已经做了。

## warp.il2cpp —— 导出名解析 {#warp-il2cpp}

il2cpp 打包后，C# 方法名被混淆成 `il2cpp_codegen_...` 之类。宿主需要「类名 + 方法名 →
函数地址」的对应关系，这一层负责查表。

| 函数 | 返回 | 说明 |
| --- | --- | --- |
| `resolve(refresh=False)` | `dict` | 解析并返回名字表（`refresh=True` 重新扫） |
| `names_table()` | `dict` | 当前缓存的名字表（不触发扫描） |
| `export_mapped(names, block, offset, count=None, name_max=64)` | 写入条数 | 把名字表写进映射的指定偏移 |
| `version` | 属性 | il2cpp 运行时版本 |

日常用法就一句：`plugin.ensure_exports(block, names, offset)` —— 它内部走 `il2cpp.export_mapped`。

## warp.log —— 统一前缀日志 {#warp-log}

```python
log.write('插件开始工作', prefix='[我的插件]')
# 控制台输出：[我的插件] 插件开始工作
```

| 参数 | 缺省 | 说明 |
| --- | --- | --- |
| `message` | — | 日志正文 |
| `prefix` | `'[WarpHook]'` | 前缀 |

和直接 `print` 的区别只有一个：它**强制 flush**。你 `print` 不打 `flush=True`，
在启动器被重定向输出时可能一行都看不到 —— 这是新手最常踩的一个坑。

## 什么时候真的需要看这些

| 症状 | 看哪一层 |
| --- | --- |
| `push()` 返回「共享内存不可用」 | `shm` —— 映射名 / 大小 / DLL 有没有注入 |
| `status()` 里 `ready=False` 一直不变 | `inject` + `il2cpp` —— 游戏没开或运行时没加载完 |
| 自己写的老式插件读不到导出名 | `il2cpp` —— 导出名序列顺序必须和 C 侧一致 |
| 日志一行都没有 | `log` —— 用 `log.write` 或 `print(..., flush=True)` |

!!! tip "别绕过 Host 直接 open 映射"
    `Host` 已经处理了多插件分段（每个插件名占一段钩子槽 / 读链 / 文案）、
    版本协商（协议版本对不上会拒连）、心跳与 `standalone` 判定。
    手工 `shm.open` 会绕过这些，写错偏移还可能让宿主读到半截配置。
