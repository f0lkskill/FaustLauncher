
import os
import re
import sys
import time
import threading
import argparse
from datetime import datetime

from functions.achievement.achievements import (
    LOG_FILE, CHECK_INTERVAL, RETRY_COUNT,
    RARE_ITEM_IDS, TEN_PULL_IDS,
    get_state, check_achievements,
    record_zero_item, poll_inventory_window, detect_owned_items,
    register_inventory_open, achievements,
)
from functions.achievement import log_sink

def _writable_root() -> str:
    try:
        from functions.base.common.path_utils import get_app_root
        return get_app_root()
    except Exception:  # noqa: BLE001
        return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ACHIEVEMENT_POLL_SEC = 1.0

class LogReader:

    def __init__(self, log_path: str):
        self.log_path = log_path
        self.last_position = 0
        self.lock = threading.Lock()
        self.last_size = 0

    def _get_file_size(self) -> int:
        for _ in range(RETRY_COUNT):
            try:
                return os.path.getsize(self.log_path)
            except (PermissionError, OSError):
                time.sleep(0.1)
        return self.last_size

    def read_new_lines(self) -> list[str]:
        with self.lock:
            current_size = self._get_file_size()
            if current_size == self.last_size:
                return []

            if current_size < self.last_position:
                self.last_position = 0

            try:
                with open(self.log_path, 'rb') as f:
                    f.seek(self.last_position)
                    data = f.read()
            except (PermissionError, OSError):
                return []

            if not data:
                self.last_size = current_size
                return []

            text = data.decode('utf-8', errors='replace')
            text = text.replace('\r\n', '\n').replace('\r', '\n')
            lines = text.split('\n')
            last_size = current_size

            if text.endswith('\n'):
                self.last_position = self.last_position + len(data)
                self.last_size = last_size
                if lines and lines[-1] == '':
                    lines.pop()
                return lines

            if len(lines) > 1:
                complete = lines[:-1]
                partial_len = len(lines[-1].encode('utf-8'))
                self.last_position = self.last_position + len(data) - partial_len
                self.last_size = last_size
                return complete
            self.last_size = last_size
            return []

    def sync_to_end(self):
        size = self._get_file_size()
        self.last_position = size
        self.last_size = size

def with_timestamp(message: str) -> str:
    return log_sink.format_line(message)

_logged_unlocks: set[str] = set()
_unlock_log_lock = threading.Lock()

def _report_unlocks(log_callback, unlocked, header: str = "") -> list:
    if not unlocked:
        return []
    fresh = []
    with _unlock_log_lock:
        for ach in unlocked:
            key = getattr(ach, "id", None) or getattr(ach, "name", "")
            if key and key not in _logged_unlocks:
                _logged_unlocks.add(key)
                fresh.append(ach)
    if not fresh:
        return []
    try:
        from functions.base.user_system import (record_achievements,
                                                record_plugin_achievements)
        builtin = [getattr(a, "id", "") or "" for a in fresh
                   if not getattr(a, "plugin", False)]
        if builtin:
            record_achievements(builtin)
        for ach in fresh:
            if not getattr(ach, "plugin", False):
                continue
            record_plugin_achievements([getattr(ach, "id", "") or ""],
                                       addon=str(getattr(ach, "addon", "") or ""))
    except Exception as exc:  # noqa: BLE001
        log_callback(f"  [Achievement] 本地记录写入失败（不影响解锁）: {type(exc).__name__}: {exc}")

    _builtin_ids = [i for i in
                    ([getattr(a, "id", "") or "" for a in fresh
                      if not getattr(a, "plugin", False)]) if i]
    if _builtin_ids:
        try:
            import threading as _threading
            from functions.base import user_system as _us

            def _push() -> None:
                for _aid in _builtin_ids:
                    try:
                        _us.push_achievement(_aid)
                    except Exception:  # noqa: BLE001
                        pass

            _threading.Thread(target=_push, name="faust-ach-push", daemon=True).start()
        except Exception:  # noqa: BLE001
            pass
    if header:
        log_callback(header)
    for ach in fresh:
        detail = getattr(ach, "detail", "")
        log_callback(f"  [Achievement] 解锁: {ach.name}"
                     + (f"\n     判定依据: {detail}" if detail else ""))
    return fresh

class _LogSink:

    _BOM = b"\xef\xbb\xbf"

    def __init__(self, path: str, truncate: bool = True) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._fd: int | None = None
        self.failures = 0
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        if truncate:
            try:
                with open(path, "wb") as fh:
                    fh.write(self._BOM)
            except OSError:
                pass
        self._open()

    def _report_failure(self, message: str) -> None:
        self.failures += 1
        if self.failures <= 3 or self.failures % 100 == 0:
            try:
                print(f"[AchLog] {message}（第 {self.failures} 次；path={self.path}）",
                      file=sys.stderr, flush=True)
            except Exception:  # noqa: BLE001
                pass

    def _open(self) -> None:
        flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
        if hasattr(os, "O_BINARY"):
            flags |= os.O_BINARY
        try:
            self._fd = os.open(self.path, flags, 0o666)
            if self._fd is not None and os.fstat(self._fd).st_size == 0:
                os.write(self._fd, self._BOM)
        except OSError as exc:
            self._fd = None
            self._report_failure(f"打开失败: {exc}")

    def write_line(self, message: str, area: str | None = None) -> None:
        text = log_sink.format_line(message, area=area)
        data = b"\n" if not text else (text + "\n").encode("utf-8", "replace")
        with self._lock:
            if self._fd is None:
                self._open()
            if self._fd is None:
                return
            try:
                os.write(self._fd, data)
            except OSError as exc:
                try:
                    os.close(self._fd)
                except OSError:
                    pass
                self._fd = None
                self._open()
                if self._fd is not None:
                    try:
                        os.write(self._fd, data)
                    except OSError as exc2:
                        self._fd = None
                        self._report_failure(f"写入失败: {exc2}")
                else:
                    self._report_failure(f"重开仍失败: {exc}")

    def close(self) -> None:
        with self._lock:
            if self._fd is not None:
                try:
                    os.close(self._fd)
                except OSError:
                    pass
                self._fd = None

def _self_image_paths() -> set[str]:
    import sys as _sys
    cand = {getattr(_sys, "executable", "") or "",
            getattr(_sys, "_base_executable", "") or ""}
    try:
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetModuleFileNameW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p,
                                                wintypes.DWORD]
        kernel32.GetModuleFileNameW.restype = wintypes.DWORD
        buf = ctypes.create_unicode_buffer(1024)
        if kernel32.GetModuleFileNameW(None, buf, wintypes.DWORD(len(buf))):
            cand.add(buf.value)
    except Exception:  # noqa: BLE001
        pass
    out: set[str] = set()
    for path in cand:
        if path:
            try:
                out.add(os.path.normcase(os.path.abspath(path)))
            except OSError:
                continue
    return out

def _self_and_ancestors() -> set[int]:
    pids = {os.getpid()}
    try:
        ppid = os.getppid()
    except OSError:
        ppid = 0
    if ppid > 0:
        pids.add(ppid)
    return pids

def _is_self_image(image: str) -> bool:
    if not image:
        return False
    try:
        image = os.path.normcase(os.path.abspath(image))
    except OSError:
        return False
    return image in _self_image_paths()

def _other_hook_running(pid_file: str = "") -> int:
    import ctypes
    try:
        with open(pid_file or _default_pid_file(), "r", encoding="utf-8") as fh:
            pid = int(fh.read().strip() or 0)
    except (OSError, ValueError):
        return 0
    if pid <= 0 or pid == os.getpid():
        return 0
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return 0
        try:
            buf = ctypes.create_unicode_buffer(1024)
            size = ctypes.c_ulong(len(buf))
            if not kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                return 0
            image = buf.value
        finally:
            kernel32.CloseHandle(handle)
    except Exception:
        return 0
    if pid in _self_and_ancestors():
        return 0
    if not _is_self_image(image):
        return 0
    return pid

def _default_pid_file() -> str:
    return os.path.join(_writable_root(), "cache", "achievement", "hook.pid")

HOOK_MUTEX_NAME = "Local\\FaustLauncher_AchievementHook"
WAIT_OBJECT_0 = 0x00000000
WAIT_ABANDONED = 0x00000080
WAIT_TIMEOUT = 0x00000102
ERROR_ALREADY_EXISTS = 183

def _write_own_pid(pid_file: str = "") -> None:
    try:
        path = pid_file or _default_pid_file()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(str(os.getpid()))
    except OSError:
        pass

def _terminate_pid(pid: int, on_log=None) -> bool:
    import ctypes
    from ctypes import wintypes
    log = on_log or (lambda _m: None)
    guard = _self_and_ancestors()
    if pid <= 0 or pid in guard:
        if pid in guard and pid != os.getpid():
            log(f"[AchMonitor] PID {pid} 是本进程的父进程（解释器 launcher）→ 绝不动它")
        return False
    PROCESS_TERMINATE = 0x0001
    PROCESS_QUERY_LIMITED = 0x1000
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                                    ctypes.c_wchar_p,
                                                    ctypes.POINTER(wintypes.DWORD)]
    handle = kernel32.OpenProcess(PROCESS_TERMINATE | PROCESS_QUERY_LIMITED, False, pid)
    if not handle:
        log(f"[AchMonitor] 打不开旧实例 PID {pid}（可能已经退出了）")
        return False
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(len(buf))
        if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            image = buf.value
            if not _is_self_image(image):
                log(f"[AchMonitor] PID {pid} 的映像是 {image}，不是我们拉起的监测进程 → 不动它")
                return False
        ok = bool(kernel32.TerminateProcess(handle, 0))
        log(f"[AchMonitor] 已收掉旧实例 PID {pid}" if ok
            else f"[AchMonitor] 终止 PID {pid} 失败")
        return ok
    except Exception as exc:  # noqa: BLE001
        log(f"[AchMonitor] 终止 PID {pid} 异常: {type(exc).__name__}: {exc}")
        return False
    finally:
        kernel32.CloseHandle(handle)

def _acquire_single_instance(pid_file: str = "", on_log=None,
                             timeout: float = 8.0) -> tuple[bool, str]:
    import ctypes
    from ctypes import wintypes
    log = on_log or (lambda _m: None)
    pid_file = pid_file or _default_pid_file()
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, ctypes.c_wchar_p]
    handle = kernel32.CreateMutexW(None, False, HOOK_MUTEX_NAME)
    if not handle:
        log("[AchMonitor] 创建单实例互斥体失败 → 按老行为继续（可能并存）")
        return True, "互斥体不可用"
    globals()["_hook_mutex"] = handle

    def _try_take(seconds: float) -> bool:
        rc = kernel32.WaitForSingleObject(handle, int(seconds * 1000))
        return rc in (WAIT_OBJECT_0, WAIT_ABANDONED)

    if _try_take(0):
        stale = _other_hook_running(pid_file)
        if stale:
            log(f"[AchMonitor] 互斥体给了本进程，但 pid 文件里还有一个活着的监测进程 "
                f"PID {stale} → 先收掉它（新实例接管）")
            _terminate_pid(stale, log)
            deadline = time.time() + 3.0
            while time.time() < deadline and _other_hook_running(pid_file):
                time.sleep(0.1)
        _write_own_pid(pid_file)
        return True, (f"本进程是唯一实例（已收掉旧实例 PID {stale}）" if stale
                      else "本进程是唯一实例")

    other = _other_hook_running(pid_file)
    if not other:
        log("[AchMonitor] 互斥体被占用，但 pid 文件里没有可用的 PID"
            "（手工启动 / 记录坏了）→ 等它放开互斥体…")
        deadline = time.time() + max(1.0, timeout)
        while time.time() < deadline:
            if _try_take(1.0):
                _write_own_pid(pid_file)
                return True, "本进程是唯一实例（上一个实例刚好退出）"
        log("[AchMonitor] 等不到互斥体（认不出持有者）→ 本次直接退出，避免两个实例并存")
        return False, "已有实例且拿不到它的 PID"
    log(f"[AchMonitor] 检测到已有监测实例在跑（PID {other}）→ 按“新的接管”策略收掉它")
    if not _terminate_pid(other, log):
        log("[AchMonitor] 收不掉旧实例 → 本次直接退出（避免两个实例并存）")
        return False, f"无法收掉旧实例 PID {other}"
    deadline = time.time() + max(1.0, timeout)
    while time.time() < deadline:
        if _try_take(1.0):
            _write_own_pid(pid_file)
            return True, f"已接管（收掉旧实例 PID {other}）"
    log(f"[AchMonitor] 旧实例 PID {other} 没收干净（{int(timeout)}s 内没放开互斥体）"
        "→ 本次直接退出")
    return False, f"旧实例 PID {other} 未退出"

def _notify_toast(unlocked):
    if not unlocked:
        return
    try:
        from functions.achievement.sound import play_achievement_sound
        play_achievement_sound()
    except Exception:
        pass
    try:
        from functions.achievement.toast import show_toast_async
        for ach in unlocked:
            show_toast_async(ach.name, ach.description,
                             getattr(ach, 'rarity', 'common'),
                             getattr(ach, 'id', '') or '')
    except Exception:
        pass

class LogProcessor:

    def __init__(self, log_callback):
        self.log_callback = log_callback
        self._battle_end_marker = "StageController:EndStage()"
        self._game_quit_patterns = [
            "Quit Local Save...",
            "[Physics::Module] Cleanup",
            "Input System module state changed to: Shutdown",
            "OnApplicationQuit",
        ]

    @staticmethod
    def _ts() -> str:
        return datetime.now().strftime('%H:%M:%S')

    def process_log_line(self, line: str) -> bool:
        s = get_state()
        quit_seen = False

        if "SetLoginInfo : STEAM" in line and not s.steam_logged:
            s.steam_logged = True
            self.log_callback(f"[{self._ts()}] [Login] Steam 登录成功")
            unlocked = check_achievements(self.log_callback)
            if unlocked:
                _report_unlocks(self.log_callback, unlocked)
                _notify_toast(unlocked)

        if "아이템 ID:" in line and "갯수가 0입니다." in line:
            match = re.search(r'아이템 ID:\s*(\d+)', line)
            if match:
                item_id = int(match.group(1))
                if item_id in RARE_ITEM_IDS:
                    record_zero_item(item_id)
                    if item_id in TEN_PULL_IDS:
                        self.log_callback(f"  [Inventory] {RARE_ITEM_IDS[item_id]} = 0 (无此物品)")

        if self._battle_end_marker in line:
            s.battle_count += 1
            self.log_callback(
                f"[{self._ts()}] [Battle] 完成关卡 (总计: {s.battle_count})"
            )
            try:
                from functions.achievement import battle_watch as _bw
                _bw.settle_turn("战斗结束")
                _bw.mark_battle_end()
            except Exception:
                pass
            unlocked = check_achievements(self.log_callback)
            if unlocked:
                _report_unlocks(self.log_callback, unlocked)
                _notify_toast(unlocked)

        if any(p in line for p in self._game_quit_patterns):
            self.log_callback(f"[{self._ts()}] [Exit] 检测到游戏退出信号")
            quit_seen = True

        return quit_seen

class AchievementHook:

    def __init__(self, log_path: str, log_callback):
        self.log_path = log_path
        self.log_callback = log_callback
        self.log_reader = LogReader(log_path)
        self.log_processor = LogProcessor(log_callback)
        self.running = True
        self.monitor_thread: threading.Thread | None = None
        self.battle_watch = None

    def start_monitoring(self):
        self.monitor_thread = threading.Thread(
            target=self._monitor_logs,
            daemon=False,
        )
        self.monitor_thread.start()
        self.battle_watch = None
        try:
            from functions.achievement import battle_watch as bw
            self.battle_watch = bw.start_battle_watch(self.log_callback)
        except Exception as exc:  # noqa: BLE001
            self.log_callback(f"[AchMonitor] 战斗事件观测不可用（仅日志成就生效）: {exc}")

    def _prepare_tail(self):
        log_path = self.log_path
        try:
            base_size = os.path.getsize(log_path)
        except OSError:
            base_size = 0
        self.log_reader.sync_to_end()
        self.log_callback(f"[AchMonitor] 已同步日志偏移 ({base_size} B), 开始实时监控")

    def _monitor_logs(self):
        self._prepare_tail()

        while self.running:
            try:
                new_lines = self.log_reader.read_new_lines()
                if new_lines:
                    for line in new_lines:
                        quit_seen = self.log_processor.process_log_line(line)
                        if quit_seen:
                            self.log_callback("[AchMonitor] 检测到游戏退出信号, 结束监控")
                            self.running = False
                            break

                if self.running:
                    zero_ids = poll_inventory_window()
                    if zero_ids is not None:
                        self._settle_inventory_browse(zero_ids)
                    self._check_memory_achievements()
                    self._check_battle_achievements()
                    _report_unlocks(self.log_callback,
                                    [a for a in achievements if a.unlocked])

                time.sleep(CHECK_INTERVAL)
            except Exception as e:
                self.log_callback(f"[AchievementHook] 监控错误: {e}")
                time.sleep(1)

    def _check_memory_achievements(self):
        unlocked = []
        for ach in achievements:
            if ach.unlocked or not getattr(ach, "memory_driven", False):
                continue
            try:
                if ach.check():  # type: ignore[attr-defined]
                    unlocked.append(ach)
            except Exception:
                pass
        if unlocked:
            _report_unlocks(self.log_callback, unlocked)
            _notify_toast(unlocked)

    def _check_battle_achievements(self):
        unlocked = []
        for ach in achievements:
            if ach.unlocked or not getattr(ach, "battle_driven", False):
                continue
            if getattr(ach, "wip", False):
                continue
            try:
                if ach.check():  # type: ignore[attr-defined]
                    unlocked.append(ach)
            except Exception:
                pass
        if unlocked:
            _report_unlocks(self.log_callback, unlocked)
            _notify_toast(unlocked)

    def _settle_inventory_browse(self, zero_ids: set[int]):
        try:
            newly = detect_owned_items(zero_ids)
            register_inventory_open()
            if newly:
                for item_id, item_name in newly:
                    self.log_callback(f"  [Item] {item_name} (ID:{item_id})")
            unlocked = check_achievements(self.log_callback)
            if unlocked:
                _report_unlocks(self.log_callback, unlocked, "==== 成就解锁 ====")
                _notify_toast(unlocked)
        except Exception as e:
            self.log_callback(f"[AchievementHook] 浏览结算错误: {e}")

    def stop_monitoring(self):
        self.running = False
        if self.monitor_thread:
            self.monitor_thread.join(timeout=5)
        try:
            from functions.achievement import battle_watch as bw
            bw.stop_battle_watch()
        except Exception:
            pass

    def get_status(self) -> dict:
        s = get_state()
        return {
            "running": self.running,
            "log_path": self.log_path,
            "achievements_total": len(achievements),
            "achievements_unlocked": sum(1 for a in achievements if a.unlocked),
            "battle_count": s.battle_count,
            "owned_items_count": len(s.owned_items),
            "steam_logged": s.steam_logged,
            "death_detected": s.death_detected,
        }

def _hook_boot_path() -> str:
    base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base, "cache", "achievement", "hook_boot.log")

def _boot(message: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] pid={os.getpid()} {message}"
    try:
        path = _hook_boot_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8", errors="replace") as fh:
            fh.write(line + "\n")
    except OSError:
        pass
    if log_sink.write(f"pid={os.getpid()} {message}", "AchLog"):
        return
    try:
        print(line, file=sys.stderr, flush=True)
    except Exception:  # noqa: BLE001
        pass

def _install_child_diagnostics() -> None:
    try:
        import faulthandler
        import threading as _threading
        import traceback as _tb
        path = os.path.join(os.path.dirname(_hook_boot_path()), "hook_fatal.log")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        _fatal_fh = open(path, "a", encoding="utf-8", errors="replace")
        faulthandler.enable(file=_fatal_fh, all_threads=True)
        globals()["_fatal_handle"] = _fatal_fh

        def _dump_hook(exc_type, exc, tb):
            _boot("未捕获异常:\n" + "".join(_tb.format_exception(exc_type, exc, tb)))

        def _thread_hook(args):
            _boot(f"线程 {getattr(args.thread, 'name', '?')} 未捕获异常:\n"
                  + "".join(_tb.format_exception(args.exc_type, args.exc_value,
                                                 args.exc_traceback)))

        sys.excepthook = _dump_hook
        _threading.excepthook = _thread_hook
    except Exception as exc:  # noqa: BLE001
        _boot(f"诊断初始化失败: {type(exc).__name__}: {exc}")
    try:
        _boot(f"启动成就子进程 argv={sys.argv!r} exe={sys.executable}")
    except Exception:  # noqa: BLE001
        pass

_hook_instance: AchievementHook | None = None

def run_achievement_hook(debug = False):
    global _hook_instance
    _install_child_diagnostics()
    _boot("进入成就监测主流程")

    parser = argparse.ArgumentParser(description="Limbus Company 成就追踪器")
    parser.add_argument(
        "--log",
        default=LOG_FILE,
        help=f"游戏日志文件路径 (默认: {LOG_FILE})",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="成就日志输出文件路径 (stdout 默认)",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=CHECK_INTERVAL,
        help=f"检查间隔秒数 (默认: {CHECK_INTERVAL})",
    )
    args, _ = parser.parse_known_args()

    pid_file = _default_pid_file()
    sole, sole_note = _acquire_single_instance(pid_file, on_log=_boot)
    _boot(f"单实例检查：{sole_note}")
    if not sole:
        raise SystemExit(0)
    try:
        from functions.achievement import battle_watch as _bw_mod
        _bw_mod.set_sole_instance(True)
    except Exception:  # noqa: BLE001
        pass

    if args.output:
        import atexit as _atexit
        already_truncated = bool(os.environ.get("FAUST_ACH_TRUNCATED"))
        sink = _LogSink(args.output, truncate=not already_truncated)

        def _write(msg: str, area: str | None = None):
            sink.write_line(msg, area)

        log_callback = _write
        log_sink.install(_write)
        log_callback(f"[AchMonitor] 单实例：{sole_note}")

        def _cleanup():
            log_sink.clear()
            sink.close()
        _atexit.register(_cleanup)
        _boot(f"成就日志 sink 就绪: {args.output}（已独占）")
    else:
        log_callback = lambda msg: print(with_timestamp(msg))  # noqa: E731
        _boot("未指定 --output，日志走 stdout")

    if not os.path.isabs(args.log):
        log_path = os.path.join(
            r"C:\Users\folkskill\AppData\LocalLow\ProjectMoon\LimbusCompany",
            args.log,
        )
    else:
        log_path = args.log

    if not os.path.exists(log_path):
        log_callback(f"[AchMonitor] 等待日志文件: {log_path}")
        for _ in range(300):
            if os.path.exists(log_path):
                break
            time.sleep(0.1)

    from functions.base.terminal_banner import get_banner_with_random_style
    try:
        log_callback(f"{get_banner_with_random_style('Limbus Company')}")
    except Exception as exc:  # noqa: BLE001
        _boot(f"横幅渲染失败（不影响监测）: {type(exc).__name__}: {exc}")
    log_callback(f"监控日志: {log_path}")
    _logged_unlocks.update(
        getattr(a, "id", None) or getattr(a, "name", "") for a in achievements if a.unlocked)
    log_callback("")
    log_callback("开始监控...")
    log_callback("-" * 60)
    log_callback("[AchMonitor] 日志: logs/achievement_hook.log 一份到底"
                 "（成就生命周期 + 子进程 stdout/stderr + 战斗观测事件流）；"
                 "状态 cache/achievement/battle_watch_status.json；"
                 "离线自查 python -m functions.achievement.battle_watch --probe/--status")

    _hook_instance = AchievementHook(log_path, log_callback)
    _boot("AchievementHook 构造完成")
    _start_hook_index_refresh(log_callback)
    _boot("偏移索引刷新已下发（后台）")
    _hook_instance.start_monitoring()
    _boot("监控线程与战斗观测已启动")

    input_ctrl = None
    try:
        from functions.achievement.input_hook import start_input_monitoring
        input_ctrl = start_input_monitoring()
        log_callback("[AchMonitor] 输入统计已启用 (P键/鼠标点击)")
    except Exception:
        input_ctrl = None
        log_callback("[AchMonitor] 输入统计不可用, 跳过按键/点击成就")

    toast_ctrl = None
    try:
        from functions.achievement.toast import ToastController
        toast_ctrl = ToastController()
    except Exception:
        toast_ctrl = None
        log_callback("[AchMonitor] GUI 弹窗不可用, 仅输出日志")

    poll_stop = threading.Event()

    def _poll_loop():
        while _hook_instance is not None and _hook_instance.running and not poll_stop.is_set():
            try:
                _check_input_achievements(log_callback)
            except Exception as exc:  # noqa: BLE001
                log_callback(f"[AchMonitor] 成就轮询异常: {type(exc).__name__}: {exc}")
            poll_stop.wait(ACHIEVEMENT_POLL_SEC)

    poll_thread = threading.Thread(target=_poll_loop, name="achievement-poll", daemon=True)
    poll_thread.start()

    try:
        while _hook_instance.running:
            if toast_ctrl is not None:
                if toast_ctrl.has_work():
                    toast_ctrl.pump()
                    time.sleep(1 / 60)
                else:
                    time.sleep(0.05)
            else:
                time.sleep(0.2)
    except KeyboardInterrupt:
        log_callback("\n[AchMonitor] 收到停止信号，正在关闭...")
    finally:
        poll_stop.set()
        if input_ctrl is not None:
            try:
                from functions.achievement.input_hook import stop_input_monitoring
                stop_input_monitoring()
            except Exception:
                pass
        if toast_ctrl is not None:
            try:
                toast_ctrl.destroy()
            except Exception:
                pass
        if _hook_instance:
            _hook_instance.stop_monitoring()
        log_callback("[AchMonitor] 已停止")

def _start_hook_index_refresh(log_callback):
    refresh = None
    try:
        from functions.achievement.memory_reader import refresh_chain_from_cloud as refresh
    except Exception as exc:  # noqa: BLE001
        log_callback(f"[AchMonitor] 偏移链刷新模块不可用: {exc}")

    if refresh is not None:
        try:
            refresh(background=True, on_log=log_callback)
        except Exception as exc:  # noqa: BLE001
            log_callback(f"[AchMonitor] 云端偏移链刷新不可用: {exc}")

def _check_input_achievements(log_callback=None):
    try:
        get_state()
        unlocked = check_achievements(log_callback or (lambda m: None))
        if unlocked:
            _report_unlocks(log_callback or (lambda m: None), unlocked)
            _notify_toast(unlocked)
    except Exception:
        pass

def start_achievement_monitoring(log_path: str = LOG_FILE) -> AchievementHook:
    global _hook_instance

    def log_callback(msg: str):
        print(with_timestamp(msg))

    try:
        from functions.achievement.input_hook import start_input_monitoring
        start_input_monitoring()
    except Exception:
        pass

    _hook_instance = AchievementHook(log_path, log_callback)
    _hook_instance.start_monitoring()
    return _hook_instance

def stop_achievement_monitoring():
    global _hook_instance
    if _hook_instance:
        _hook_instance.stop_monitoring()

def get_hook(log_path: str = LOG_FILE) -> AchievementHook | None:
    return _hook_instance
