# 战斗 UI 插件 GC 显式线程注册错误调查

用户报告部分机器出现 `Fatal error in GC` / `Threads explicit registering is not previously enabled`，禁用战斗 UI 开关后好转。用户本机没有复现，因此本机日志不能作为故障归因证据。本调查不运行游戏、不注入、不读取游戏 DLL，不修改生产插件。

## 已确认的实现

战斗 UI 开关的 Python 宿主 `addons/战斗UI开关/scr.py` 使用独立共享映射和 `BattleUINative-1.7.dll`，没有通过 WarpHook 注入。宿主发现 GameAssembly 模块且导出解析成功后即注入；这不能证明引擎 GC 已准备好接受外来线程。

对现有插件 DLL 的离线反汇编确认：DllMain 在 RVA 0x10c7 调用 CreateThread，线程入口 RVA 0x10d9。解析 API 表后，RVA 0x1310 取得 index 12 的 thread_attach 指针（存于 RVA 0x209a0），RVA 0x1317 调 domain_get，RVA 0x1320 调 thread_attach。随后才枚举程序集并在 RVA 0x1421 初始化 MinHook。domain_get 返回值直接传给 attach，没有非空检查；attach 返回值也没有非空检查。成功路径在 RVA 0x197a detach 后退出控制线程，因此不是“完全没有 attach”或“成功路径没有 detach”。所审计 DLL SHA256 为 `9ee3c982ae8fdc274c1dbc50e72fc6e7ea27dc13e42e51587a007c724a0dbf63`。此为插件代码路径事实，不是远端崩溃堆栈。详细汇编证据在 [静态审计报告](../cache/battleui_gc_static_report.txt)。

已检查的安装包 `C:/Users/folkskill/Downloads/BattleUI-1.7-install.zip` 也不含 C/C++ 源码，不能用改 Python 代替修改 DLL 内部线程模型。

## 错误条件

BDWGC 8.2.2 上游 Windows 实现 `GC_register_my_thread` 入口在 `GC_need_to_lock == FALSE` 时执行：

    ABORT("Threads explicit registering is not previously enabled");

这在查询线程表之前发生。该文字指向显式线程注册所需状态未启用，不能直接解释成内存不足、线程过多或少调用 detach。上游版本不能代替故障机器实际使用的 Unity 定制实现。

来源：
- https://sources.debian.org/data/main/libg/libgc/1%3A8.2.2-3/win32_threads.c
- https://sources.debian.org/data/main/libg/libgc/1%3A8.2.2-3/include/gc.h

`GC_allow_register_threads` 有调用线程与初始化顺序约束，并会启动 GC 标记线程，不应从任意注入线程盲调；也不能跳过 attach 后继续在未注册线程上 invoke。固定延时不能证明 GC 已就绪。

## WarpHook 的边界

当前 WarpHook 控制线程不 attach，但 `addons/WarpHook/src/warp_cmd.c` 的命令 worker 仍逐任务调用 thread_attach/thread_detach。域、程序集数量和稳定时间不等于 GC 显式注册已启用。此前配对 detach 的修改针对退出生命周期，不保证本错误不会发生，也不能据插件独立实现排除组合时序影响。

## 仍需故障现场确认

优先证据是报错对话框尚在时的进程转储与全部线程调用栈，确认 GC fatal 路径之前是否经过 IL2CPP attach 及哪一个插件帧。附故障机器实际插件 DLL 的版本/哈希、游戏版本、启用插件列表与启动顺序。转储可能包含用户数据，仅私下交给调试人员。

若进行启用组合对照，每次必须完整退出并重新启动游戏；在启动器中禁用插件不会卸载已经注入的 DLL。先区分“仅战斗 UI”与“与其他注入插件组合”是否都触发，正常本机对照不能替代故障机证据。

源码修复方向是让托管对象操作在合适的游戏线程回调中执行，减少外来控制线程进入 IL2CPP 的需求；需要对应原生源码与验证，不能在未知源码 DLL 上盲补、擅自启用全局 GC 状态或宣称已修复。
