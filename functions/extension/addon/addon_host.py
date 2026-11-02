"""独立插件宿主进程。

所有插件的 Python 代码都跑在启动器进程里，而且是 daemon 线程 —— 启动器一关，
插件就全没了。对「命中即动作」的插件无所谓（这类逻辑已经下沉进 DLL，见
WarpHook 的 ``ACT_POPUP``），但像战斗 BGM 替换这种**判定逻辑必须在 Python 里
跑**的插件，启动器关掉就只能停摆。

本模块就是那个「不跟着退出的进程」::

    FaustLauncher.exe --addon-host

无窗口、无托盘、无 WebView，只把同一份 ``AddonManager`` 载起来，然后盯着游戏
进程：**游戏一退出就 ``unload_all_addons()`` 收摊退出**，不管启动器在不在。
这正是「插件的管理层」该有的生命周期 —— 插件服务于游戏，不是服务于启动器。

交接不能两边同时写钩子表，所以拿 ``cache/addon_host.lock`` 做单实例锁（以
"不许别人共享"的方式打开这个文件，进程一死锁就自动释放）：谁开着它谁就是
当前宿主。启动器活着的时候自己开着，退出前先让旧宿主退场（``stop_host``）、
再把活交出去（``handoff``）—— 任何时刻只有一个写方。
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import os
import subprocess
import sys
import time

GAME_IMAGE = "LimbusCompany.exe"
"""只服务这一个游戏：它退出，宿主就收摊。"""

HOST_ARG = "--addon-host"
"""命令行开关，由 ``LAUNCH_MODE`` 分发到 :func:`run_host`。"""

_POLL_SECONDS = 2.0
"""盯游戏进程的间隔（秒）。进程表快照本身很便宜，2 秒足够。"""

_IDLE_LIMIT = 1800.0
"""一直没等到游戏启动就自己退场的时限（秒）。防止用户只关启动器、游戏永远
没起来，留下一个谁也看不见的常驻进程。"""

_DETACHED_PROCESS = 0x00000008
_CREATE_NEW_PROCESS_GROUP = 0x00000200

_INVALID_HANDLE = ctypes.c_void_p(-1).value
"""``CreateFileW`` 失败时返回的句柄（64 位下是 0xFFFFFFFFFFFFFFFF）。"""


class _PROCESSENTRY32W(ctypes.Structure):
    """``Process32FirstW`` 用的结构（只要 pid 与 exe 名）。"""

    _fields_ = [
        ("dwSize", wt.DWORD),
        ("cntUsage", wt.DWORD),
        ("th32ProcessID", wt.DWORD),
        ("th32DefaultHeapID", ctypes.c_void_p),
        ("th32ModuleID", wt.DWORD),
        ("cntThreads", wt.DWORD),
        ("th32ParentProcessID", wt.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wt.DWORD),
        ("szExeFile", ctypes.c_wchar * 260),
    ]


def _kernel32():
    """声明用到的 kernel32 函数签名（64 位下指针必须显式声明）。"""

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateFileW.argtypes = [
        wt.LPCWSTR, wt.DWORD, wt.DWORD, ctypes.c_void_p, wt.DWORD, wt.DWORD, wt.HANDLE,
    ]
    k32.CreateFileW.restype = wt.HANDLE
    k32.CloseHandle.argtypes = [wt.HANDLE]
    k32.CloseHandle.restype = wt.BOOL
    k32.CreateToolhelp32Snapshot.argtypes = [wt.DWORD, wt.DWORD]
    k32.CreateToolhelp32Snapshot.restype = wt.HANDLE
    k32.Process32FirstW.argtypes = [wt.HANDLE, ctypes.POINTER(_PROCESSENTRY32W)]
    k32.Process32NextW.argtypes = [wt.HANDLE, ctypes.POINTER(_PROCESSENTRY32W)]
    return k32


def _root() -> str:
    """启动器根目录（源码版是仓库根，打包版是 exe 所在目录）。"""

    try:
        from functions.base.common.path_utils import get_app_root

        return get_app_root()
    except Exception:
        return os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        )


def _state_path(name: str) -> str:
    """``cache/`` 下的状态文件路径（目录不存在就建）。"""

    folder = os.path.join(_root(), "cache")
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, name)


def _stop_file() -> str:
    return _state_path("addon_host.stop")


def _pid_file() -> str:
    return _state_path("addon_host.pid")


def _log_file() -> str:
    folder = os.path.join(_root(), "logs")
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, "addon_host.log")


def _game_pids() -> list:
    """当前在跑的 ``LimbusCompany.exe`` 进程号（取不到就返回空列表）。"""

    try:
        k32 = _kernel32()
        snap = k32.CreateToolhelp32Snapshot(0x00000002, 0)
        if not snap:
            return []
        pids = []
        try:
            entry = _PROCESSENTRY32W()
            entry.dwSize = ctypes.sizeof(entry)
            ok = k32.Process32FirstW(snap, ctypes.byref(entry))
            target = GAME_IMAGE.lower()
            while ok:
                if entry.szExeFile.lower() == target:
                    pids.append(int(entry.th32ProcessID))
                ok = k32.Process32NextW(snap, ctypes.byref(entry))
        finally:
            k32.CloseHandle(snap)
        return pids
    except Exception:
        return []


_OWN_LOCK = {"handle": 0}
"""本进程自己持有的锁（0 表示没持有）。启动器活着的时候持锁，退出前放出。"""


def _lock_path() -> str:
    return _state_path("addon_host.lock")


def _try_lock() -> int:
    """独占打开锁文件；成功返回句柄，返回 0 表示别人正持着。

    用"不给别人共享的文件的句柄"当锁，而不是命名互斥体：进程无论怎么死
    （崩溃、被杀、断电），句柄都由内核回收，下一次启动立刻能拿到锁，不存在
    abandoned 状态需要判断。
    """

    k32 = _kernel32()
    os.makedirs(os.path.dirname(_lock_path()), exist_ok=True)
    handle = k32.CreateFileW(
        _lock_path(),
        0x80000000 | 0x40000000,  # GENERIC_READ | GENERIC_WRITE
        0,                        # 不共享 —— 别人就打不开了
        None,
        4,                        # OPEN_ALWAYS
        0x00000080,               # FILE_ATTRIBUTE_NORMAL
        None,
    )
    if not handle or int(handle) in (_INVALID_HANDLE, 0):
        return 0
    return int(handle)


def take_over() -> bool:
    """本进程当宿主：持锁直到退出（退出时由 :func:`release_own` 放出）。

    这样「启动器 + 独立宿主」任何时刻只有一个在写钩子表 —— 宿主还在启动
    过程中就被重新打开的启动器顶掉，也不会打架。
    """

    if _OWN_LOCK["handle"]:
        return True
    handle = _try_lock()
    if not handle:
        return False
    _OWN_LOCK["handle"] = handle
    return True


def release_own() -> None:
    """放出本进程持有的锁（交接前必须先放，否则宿主抢不到）。"""

    handle = int(_OWN_LOCK.get("handle") or 0)
    if not handle:
        return
    _OWN_LOCK["handle"] = 0
    try:
        _kernel32().CloseHandle(handle)
    except Exception:
        pass


def is_host_running() -> bool:
    """当前有没有活着的进程（启动器或独立宿主）持着插件专属锁。"""

    if _OWN_LOCK["handle"]:
        return True
    handle = _try_lock()
    if not handle:
        return True
    try:
        _kernel32().CloseHandle(handle)
    except Exception:
        pass
    return False


def host_pid() -> int:
    """读宿主自己写下的 pid（读不到返回 0）。"""

    try:
        with open(_pid_file(), "r", encoding="utf-8") as handle:
            return int(handle.read().strip() or 0)
    except Exception:
        return 0


def _clear(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


def request_stop() -> None:
    """给宿主留一个停止标记，它下一轮自己收摊退出。"""

    try:
        with open(_stop_file(), "w", encoding="utf-8") as handle:
            handle.write(str(int(time.time())))
    except OSError:
        pass


def stop_host(timeout: float = 8.0, force: bool = True) -> bool:
    """让旧宿主退场并等它释放钩子表。

    返回 ``True`` 表示现在没有宿主在跑（本来就没有，或者已经退干净了）。
    ``force`` 为真时，超时之后直接杀掉 —— 两个进程同时写钩子表比杀进程更糟。
    """

    if _OWN_LOCK["handle"]:
        return True
    if not is_host_running():
        _clear(_stop_file())
        return True
    print("[AddonHost] 检测到独立宿主在运行，先让它退场…")
    request_stop()
    deadline = time.time() + max(1.0, float(timeout))
    while time.time() < deadline:
        if not is_host_running():
            _clear(_stop_file())
            print("[AddonHost] 宿主已退场")
            return True
        time.sleep(0.25)
    if not force:
        return False
    pid = host_pid()
    print(f"[AddonHost] 宿主 {timeout:.0f}s 内没有退出，强制结束 (pid={pid})")
    if pid:
        try:
            subprocess.run(
                ["taskkill", "/F", "/PID", str(pid)],
                capture_output=True,
                creationflags=0x08000000,
            )
        except Exception:
            pass
    _clear(_stop_file())
    _clear(_pid_file())
    return not is_host_running()


def spawn_host() -> bool:
    """拉起一个独立宿主（已经有一个在跑时直接返回 True）。"""

    if is_host_running():
        return True
    exe = sys.executable
    argv = [exe]
    if not getattr(sys, "frozen", False):
        argv.append(os.path.join(_root(), "main.py"))
    argv.append(HOST_ARG)
    try:
        log = open(_log_file(), "ab", buffering=0)
    except OSError:
        log = subprocess.DEVNULL  # type: ignore[assignment]
    try:
        subprocess.Popen(
            argv,
            cwd=_root(),
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            creationflags=_DETACHED_PROCESS | _CREATE_NEW_PROCESS_GROUP,
            close_fds=True,
        )
    except Exception as exc:
        print(f"[AddonHost] 拉起宿主失败: {type(exc).__name__}: {exc}")
        return False
    finally:
        if log is not subprocess.DEVNULL:
            try:
                log.close()  # type: ignore[union-attr]
            except Exception:
                pass
    print(f"[AddonHost] 已拉起独立宿主，日志: {_log_file()}")
    return True


def _system_shutting_down() -> bool:
    """系统正在关机时不要再拉进程（会阻塞关机、留下半个宿主）。"""

    try:
        return bool(ctypes.windll.user32.GetSystemMetrics(0x2000))
    except Exception:
        return False


def handoff(manager=None) -> bool:
    """启动器退出前的交接：卸掉本地插件，把活交给独立宿主。

    ``manager`` 是启动器里的 ``AddonManager``：先 ``unload_all_addons()``
    停掉线程、收掉共享内存映射，再让宿主重新载入 —— 不然两边会同时往同一张
    钩子表里写。
    """

    if _system_shutting_down():
        print("[AddonHost] 系统正在关机，不做交接")
        return False
    if not _game_pids():
        # 游戏没在跑：插件本来就没有服务对象，没必要留一个后台进程。
        print("[AddonHost] 游戏未运行，不启动独立宿主")
        return False
    _clear(_stop_file())
    if manager is not None:
        try:
            manager.unload_all_addons()
        except Exception as exc:
            print(f"[AddonHost] 卸载插件时出错: {type(exc).__name__}: {exc}")
    release_own()
    return spawn_host()


def _watch(manager) -> None:
    """盯游戏进程：游戏退出就收摊，等不到游戏也不会永远常驻。"""

    started = False
    begin = time.time()
    while True:
        if os.path.exists(_stop_file()):
            print("[AddonHost] 收到停止信号，准备退场")
            return
        if _game_pids():
            started = True
        elif started:
            print("[AddonHost] 游戏已退出，回收插件线程")
            return
        elif time.time() - begin > _IDLE_LIMIT:
            print("[AddonHost] 一直没等到游戏启动，退场")
            return
        time.sleep(_POLL_SECONDS)


def run_host(debug: bool = False) -> None:
    """宿主进程入口（``--addon-host`` 分发到这里）。"""

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass

    try:
        from functions.base.headless_ui import install as _install_headless

        _install_headless()
    except Exception as exc:
        print(f"[AddonHost] 静默模式安装失败(继续): {exc}")

    if not take_over():
        print("[AddonHost] 已有进程在跑插件，本进程退出")
        return

    _clear(_stop_file())
    try:
        with open(_pid_file(), "w", encoding="utf-8") as pid_handle:
            pid_handle.write(str(os.getpid()))
    except OSError:
        pass

    print(f"[AddonHost] 启动 pid={os.getpid()} 游戏进程={_game_pids() or '未启动'}")
    manager = None
    try:
        from functions.extension.addon.addon_utils import AddonManager

        manager = AddonManager([], app=None)
        manager.run_all_addon()
        print(f"[AddonHost] 插件已载入 {len(manager.loaded_modules)} 个")
        _watch(manager)
    except KeyboardInterrupt:
        print("[AddonHost] 收到中断")
    except Exception as exc:
        import traceback

        print(f"[AddonHost] 宿主异常退出: {type(exc).__name__}: {exc}")
        traceback.print_exc()
    finally:
        if manager is not None:
            try:
                manager.unload_all_addons()
            except Exception as exc:
                print(f"[AddonHost] 卸载插件时出错: {type(exc).__name__}: {exc}")
        _clear(_pid_file())
        _clear(_stop_file())
        release_own()
        print("[AddonHost] 已退出")
