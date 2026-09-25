"""成就监测Hook - 监控游戏日志以触发成就解锁。

此模块负责：
- 读取并监控 Player.log 文件的变化
- 解析游戏日志行，识别关键事件（战斗、物品、背包等）
- 触发成就检查和自动解锁
- 在后台进程/线程中持续运行

使用方式（独立进程）:
    python main.py --achievement-hook --log "C:/path/to/Player.log"
"""

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

# 成就轮询间隔（独立线程；弹窗动画不受影响）
ACHIEVEMENT_POLL_SEC = 1.0


# ============ 日志读取器 ============
class LogReader:
    """游戏日志读取器 (纯字节 offset 续读)。

    直接对原文件按字节偏移续读, 不做临时复制。
    检测文件截断 (Unity 新会话会清空重写): 若当前尺寸 < 已读偏移,
    则重置偏移为 0 从头重读。
    """

    def __init__(self, log_path: str):
        self.log_path = log_path
        self.last_position = 0
        self.lock = threading.Lock()
        self.last_size = 0

    def _get_file_size(self) -> int:
        """获取文件大小, 带重试。"""
        for _ in range(RETRY_COUNT):
            try:
                return os.path.getsize(self.log_path)
            except (PermissionError, OSError):
                time.sleep(0.1)
        return self.last_size

    def read_new_lines(self) -> list[str]:
        """读取从上次位置到当前末尾的新增行 (二进制安全)。"""
        with self.lock:
            current_size = self._get_file_size()
            if current_size == self.last_size:
                return []

            # 截断检测: 文件变小 → 新会话清空重写, 从头读
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

            # 解码 + 按行拆分 (统一换行)
            text = data.decode('utf-8', errors='replace')
            text = text.replace('\r\n', '\n').replace('\r', '\n')
            lines = text.split('\n')
            last_size = current_size

            if text.endswith('\n'):
                # 完整结束: 全部行有效, 推进偏移
                self.last_position = self.last_position + len(data)
                self.last_size = last_size
                if lines and lines[-1] == '':
                    lines.pop()
                return lines

            # 末尾半行: 只返回完整行; 偏移回退到最后一个完整行之后,
            # 使下一轮能重新读到这半行直到它补齐
            if len(lines) > 1:
                complete = lines[:-1]
                partial_len = len(lines[-1].encode('utf-8'))
                self.last_position = self.last_position + len(data) - partial_len
                self.last_size = last_size
                return complete
            # 整块都是半行: 偏移不动, 等补齐
            self.last_size = last_size
            return []

    def sync_to_end(self):
        """把读取偏移同步到文件末尾 (跳过历史内容, 仅从当前位置开始)。"""
        size = self._get_file_size()
        self.last_position = size
        self.last_size = size


# ============ 日志时间轴 ============
_TS_PREFIX_RE = re.compile(r"^\[\d{2}:\d{2}:\d{2}\]")


def with_timestamp(message: str) -> str:
    """给日志行加时间轴前缀 ``[HH:MM:SS]``（已经有前缀的保持原样）。"""
    text = str(message)
    if _TS_PREFIX_RE.match(text):
        return text
    return f"[{datetime.now().strftime('%H:%M:%S')}] {text}"


# ============ 解锁日志（统一出口）============
_logged_unlocks: set[str] = set()
_unlock_log_lock = threading.Lock()


def _report_unlocks(log_callback, unlocked, header: str = "") -> list:
    """把“新解锁的成就”写进成就日志（**同一个成就只写一次**）。

    为什么要统一出口：成就检查有好几条路径（Player.log 事件 / 输入计数 / 内存 /
    战斗观测），它们跑在不同线程上，谁先跑到谁就把它置成 ``unlocked``。
    以前其中一条（主循环的输入计数）只 ``print``（子进程 stdout 是 DEVNULL），
    于是“成就确实解锁了（弹窗也弹了），但成就日志里看不到”——这里用已写集合
    保证无论哪条路径先解锁，成就日志里都会有且只有一行。

    返回真正新写进日志的成就列表。
    """
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
    if header:
        log_callback(header)
    for ach in fresh:
        detail = getattr(ach, "detail", "")
        log_callback(f"  [成就] 解锁: {ach.name}"
                     + (f"\n     判定依据: {detail}" if detail else ""))
    return fresh


class _LogSink:
    """成就日志写入器：**O_APPEND + 每行一次 os.write + 线程锁**。

    为什么要这么写（本次日志损坏的根因）：

    - 旧实现用 ``open(path, 'w')`` + ``write``：句柄自带固定偏移，一旦有第二个实例
      （或上次没退干净的残留实例）也在写同一个文件，两者就各按自己的偏移覆写 →
      错位、中间夹 NUL 空洞的“损坏”文件；
    - 中途被清空（truncate）时，正在写的旧句柄还会在旧偏移继续写，留下更长的空洞。

    现在：启动时显式清空一次（可关），之后用 ``O_APPEND`` 打开 —— 每次写入都追加到
    文件末尾，不可能再有偏移错位/空洞；一行一次 ``os.write`` + 一把锁，保证多线程
    （监控线程 / 战斗观测线程 / 主线程）写出来的行不会互相插队。

    另外文件头和每行都是 **UTF-8（带 BOM）**：没有 BOM 时，Windows 记事本／
    PowerShell 5.1 的 ``Get-Content`` 会按系统 ANSI(GBK) 解码，中文全变“乱码”
    （实测踩到过）。
    """

    _BOM = b"\xef\xbb\xbf"

    def __init__(self, path: str, truncate: bool = True) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._fd: int | None = None
        self.failures = 0            # 写不进去的次数（不再静默吞掉，见 _report_failure）
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        if truncate:
            try:
                with open(path, "wb") as fh:  # 每次实例运行只留本次运行
                    fh.write(self._BOM)       # 顺手写 BOM，让记事本/PowerShell 认得编码
            except OSError:
                pass
        self._open()

    def _report_failure(self, message: str) -> None:
        """日志写不进去时**必须留痕**：以前这里静默 return／吞 OSError，
        现象就是“成就日志只有 3 字节（BOM）却毫无提示”。
        """
        self.failures += 1
        if self.failures <= 3 or self.failures % 100 == 0:
            try:
                print(f"[成就日志] {message}（第 {self.failures} 次；path={self.path}）",
                      file=sys.stderr, flush=True)
            except Exception:  # noqa: BLE001
                pass

    def _open(self) -> None:
        flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
        if hasattr(os, "O_BINARY"):
            flags |= os.O_BINARY
        try:
            self._fd = os.open(self.path, flags, 0o666)
            # 文件是空的（首次创建 / 被清空）→ 补上 BOM
            if self._fd is not None and os.fstat(self._fd).st_size == 0:
                os.write(self._fd, self._BOM)
        except OSError as exc:
            self._fd = None
            self._report_failure(f"打开失败: {exc}")

    def write_line(self, message: str) -> None:
        text = with_timestamp(message)
        data = (text + "\n").encode("utf-8", "replace")
        with self._lock:
            if self._fd is None:
                self._open()
            if self._fd is None:
                return
            try:
                os.write(self._fd, data)       # 单行一次写入（append）
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


def _other_hook_running(pid_file: str = "") -> int:
    """返回另一个还活着的成就监测子进程 PID（没有则 0）。

    只认“记录的 PID 存在且进程映像 == 本解释器”—— 避免误导（PID 会复用）。
    """
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
        handle = kernel32.OpenProcess(0x1000, False, pid)      # QUERY_LIMITED_INFORMATION
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
    import sys as _sys
    if os.path.normcase(image) != os.path.normcase(_sys.executable):
        return 0
    return pid


def _default_pid_file() -> str:
    base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base, "cache", "achievement", "hook.pid")


# ============ 成就弹窗辅助 ============
def _notify_toast(unlocked):
    """解锁通知: 播放音效 + 推送 GUI 弹窗 (失败自动降级)。"""
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
            show_toast_async(ach.name, ach.description, getattr(ach, 'rarity', 'common'))
    except Exception:
        pass


# ============ 日志处理器 ============
class LogProcessor:
    """日志处理器。

    负责解析游戏日志行，识别关键事件，
    并更新全局状态和触发成就检查。
    """

    def __init__(self, log_callback):
        self.log_callback = log_callback
        # 战斗完成信号 (真实日志验证):
        #   [1991] StageModel:SetStageResult(...)
        #   [1992] StageController:EndStage()   ← 唯一且每场一次
        # 日志中不存在可靠的"战斗开始"标记 (InitStage/PlayVideo 命中 0),
        # 因此以 EndStage() 为完成计数信号, 不用 is_in_battle 门控。
        self._battle_end_marker = "StageController:EndStage()"
        self._game_quit_patterns = [
            "Quit Local Save...",
            "[Physics::Module] Cleanup",
            "Input System module state changed to: Shutdown",
            "OnApplicationQuit",
        ]

    @staticmethod
    def _ts() -> str:
        """返回当前时间字符串 (HH:MM:SS)。"""
        return datetime.now().strftime('%H:%M:%S')

    def process_log_line(self, line: str) -> bool:
        """处理单行日志。

        参数:
            line: 日志行内容

        返回:
            True 表示检测到游戏退出 (应结束监控)
        """
        s = get_state()
        quit_seen = False

        # ── 1. Steam 登录检测 ──
        if "SetLoginInfo : STEAM" in line and not s.steam_logged:
            s.steam_logged = True
            self.log_callback(f"[{self._ts()}] [登录] Steam 登录成功")
            unlocked = check_achievements(self.log_callback)
            if unlocked:
                _report_unlocks(self.log_callback, unlocked)
                _notify_toast(unlocked)

        # ── 2. 0 物品日志 → 视为一次背包/兑换页检视 ──
        # 真实日志: 每次浏览该页会对每个缺货槽连续打印(8连发, 间隔极短);
        # 由主循环的滑动窗口把一簇归并为一次浏览。
        if "아이템 ID:" in line and "갯수가 0입니다." in line:
            match = re.search(r'아이템 ID:\s*(\d+)', line)
            if match:
                item_id = int(match.group(1))
                if item_id in RARE_ITEM_IDS:
                    record_zero_item(item_id)   # 加入滑动窗口 (窗口结束=一次浏览)
                    if item_id in TEN_PULL_IDS:
                        self.log_callback(f"  [背包] {RARE_ITEM_IDS[item_id]} = 0 (无此物品)")

        # ── 3. (浏览归并见主循环 poll_inventory_window) ──

        # ── 4. 战斗完成 (真实日志: 每场结束仅一次 EndStage()) ──
        if self._battle_end_marker in line:
            s.battle_count += 1
            self.log_callback(
                f"[{self._ts()}] [战斗] 完成关卡 (总计: {s.battle_count})"
            )
            # 战斗结束也当作一次回合结算：避免最后那个回合的技能事件被浪费
            try:
                from functions.achievement import battle_watch as _bw
                _bw.settle_turn("战斗结束")
            except Exception:
                pass
            unlocked = check_achievements(self.log_callback)
            if unlocked:
                _report_unlocks(self.log_callback, unlocked)
                _notify_toast(unlocked)

        # ── 5. 游戏退出检测 (参考日志: Quit Local Save → Cleanup → Shutdown) ──
        if any(p in line for p in self._game_quit_patterns):
            self.log_callback(f"[{self._ts()}] [退出] 检测到游戏退出信号")
            quit_seen = True

        return quit_seen


# ============ 成就监测主循环 ============
class AchievementHook:
    """成就监测Hook主类。

    在后台线程中持续监控游戏日志，
    检测到关键事件时触发成就检查。
    """

    def __init__(self, log_path: str, log_callback):
        self.log_path = log_path
        self.log_callback = log_callback
        self.log_reader = LogReader(log_path)
        self.log_processor = LogProcessor(log_callback)
        self.running = True
        self.monitor_thread: threading.Thread | None = None
        self.battle_watch = None

    def start_monitoring(self):
        """启动后台线程监控日志文件。"""
        self.monitor_thread = threading.Thread(
            target=self._monitor_logs,
            daemon=False,  # 非 daemon，确保主进程等待此线程
        )
        self.monitor_thread.start()
        # 战斗事件观测（注入 battle_watch.dll）：与日志监控并行，失败不影响成就监测
        self.battle_watch = None
        try:
            from functions.achievement import battle_watch as bw
            self.battle_watch = bw.start_battle_watch(self.log_callback)
        except Exception as exc:  # noqa: BLE001
            self.log_callback(f"[成就监测] 战斗事件观测不可用（仅日志成就生效）: {exc}")

    def _prepare_tail(self):
        """启动准备: 同步读取偏移到当前文件末尾。

        不做历史收割/推断: 物品拥有完全由**实时日志**驱动——
        每轮背包浏览产生的 0 记录经滑动窗口结算推断, 避免旧日志
        残留缺货记录导致误解锁 (如玩家已抽到但旧文件仍显示曾缺货)。
        """
        log_path = self.log_path
        try:
            base_size = os.path.getsize(log_path)
        except OSError:
            base_size = 0
        self.log_reader.sync_to_end()
        self.log_callback(f"[成就监测] 已同步日志偏移 ({base_size} B), 开始实时监控")

    def _monitor_logs(self):
        """后台线程函数：监控日志文件。"""
        # 启动准备: 同步到末尾 (不收割历史, 不推断物品)
        self._prepare_tail()

        # 持续监控循环
        while self.running:
            try:
                new_lines = self.log_reader.read_new_lines()
                if new_lines:
                    for line in new_lines:
                        quit_seen = self.log_processor.process_log_line(line)
                        if quit_seen:
                            self.log_callback("[成就监测] 检测到游戏退出信号, 结束监控")
                            self.running = False
                            break

                # 浏览归并: 0 记录簇空闲 → 记一次背包/兑换页浏览并查成就
                if self.running:
                    zero_ids = poll_inventory_window()
                    if zero_ids is not None:
                        self._settle_inventory_browse(zero_ids)
                    # 内存成就按轮询周期检查；读取失败时 MemoryAchievement 保持未解锁。
                    self._check_memory_achievements()
                    # 战斗事件成就（注入 DLL 观测：技能/速度/血量/理智）
                    self._check_battle_achievements()
                    # 兜底：不管是哪条路径解锁的，都保证成就日志里有一行
                    _report_unlocks(self.log_callback,
                                    [a for a in achievements if a.unlocked])

                time.sleep(CHECK_INTERVAL)
            except Exception as e:
                self.log_callback(f"[AchievementHook] 监控错误: {e}")
                time.sleep(1)

    def _check_memory_achievements(self):
        """检查基于进程内存的成就（按 ``memory_driven`` 标记，不认具体类名）。"""
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
        """检查战斗事件类成就（battle_watch 观测到的技能 / 速度 / 血量 / 理智）。

        这些成就自带 ``battle_driven`` 标记，``check()`` 只读 battle_watch 的结果，
        所以轮询代价极低（判定由注入 DLL 的事件驱动）。
        """
        unlocked = []
        for ach in achievements:
            if ach.unlocked or not getattr(ach, "battle_driven", False):
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
        """一轮背包/兑换页浏览结束: 反向检测物品并触发成就检查。"""
        try:
            newly = detect_owned_items(zero_ids)
            register_inventory_open()
            if newly:
                for item_id, item_name in newly:
                    self.log_callback(f"  [物品] {item_name} (ID:{item_id})")
            unlocked = check_achievements(self.log_callback)
            if unlocked:
                _report_unlocks(self.log_callback, unlocked, "==== 成就解锁 ====")
                _notify_toast(unlocked)
        except Exception as e:
            self.log_callback(f"[AchievementHook] 浏览结算错误: {e}")

    def stop_monitoring(self):
        """停止监控。"""
        self.running = False
        if self.monitor_thread:
            self.monitor_thread.join(timeout=5)
        try:
            from functions.achievement import battle_watch as bw
            bw.stop_battle_watch()
        except Exception:
            pass

    def get_status(self) -> dict:
        """获取当前成就监测状态。"""
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
    """子进程启动面包屑日志（cache/achievement/hook_boot.log）。

    成就子进程的 stdout/stderr 以前是 DEVNULL：一旦它在写出第一行成就日志之前出事
    （被重复启动的实例杀掉 / 导入期异常 / 原生崩溃），就什么都看不到——只剩“日志只有 3
    字节（BOM）”这个现象。这里把每一步都落到盘上，并开 faulthandler，把“静默死亡”变成可定位记录。
    """
    base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base, "cache", "achievement", "hook_boot.log")


def _boot(message: str) -> None:
    """面包屑：写 cache/achievement/hook_boot.log + stderr（启动器已把 stderr 转存到文件）。"""
    line = f"[{time.strftime('%H:%M:%S')}] pid={os.getpid()} {message}"
    try:
        path = _hook_boot_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8", errors="replace") as fh:
            fh.write(line + "\n")
    except OSError:
        pass
    try:
        print(line, file=sys.stderr, flush=True)
    except Exception:  # noqa: BLE001
        pass


def _install_child_diagnostics() -> None:
    """子进程级诊断：faulthandler（原生崩溃/卡死留堆栈）+ excepthook + 启动面包屑。"""
    try:
        import faulthandler
        import threading as _threading
        import traceback as _tb
        path = os.path.join(os.path.dirname(_hook_boot_path()), "hook_fatal.log")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        _fatal_fh = open(path, "a", encoding="utf-8", errors="replace")   # 进程结束才关闭
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


# ============ 独立进程入口 ============
_hook_instance: AchievementHook | None = None


def run_achievement_hook():
    """成就监测独立进程入口。

    在当前进程中启动成就监测循环（阻塞），
    用于 subprocess 启动时调用。
    """
    global _hook_instance
    _install_child_diagnostics()
    _boot("进入成就监测主流程")

    # 解析命令行参数
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

    # 重定向输出到文件（如果指定了 --output）
    if args.output:
        import atexit as _atexit
        # 双实例保护：另一个实例也在写同一个文件时**不再清空**（改为追加），
        # 否则两边各自按自己的偏移写会把日志写成夹空洞的“损坏”文件。
        other = _other_hook_running(os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "cache", "achievement", "hook.pid"))
        sink = _LogSink(args.output, truncate=not other)

        def _write(msg: str):
            sink.write_line(msg)

        log_callback = _write
        if other:
            log_callback(f"[成就监测] 注意: 已有另一个监测实例在运行（PID {other}），"
                         f"本次不清空日志以免损坏文件；两边日志会交替追加。")

        def _cleanup():
            sink.close()
        _atexit.register(_cleanup)
        _boot(f"成就日志 sink 就绪: {args.output}"
              f"（truncate={not other}，另一实例={other or '无'}）")
    else:
        log_callback = lambda msg: print(with_timestamp(msg))  # noqa: E731

    # 确定游戏日志路径
    if not os.path.isabs(args.log):
        log_path = os.path.join(
            r"C:\Users\folkskill\AppData\LocalLow\ProjectMoon\LimbusCompany",
            args.log,
        )
    else:
        log_path = args.log

    # 等待日志文件出现（最多30秒）
    if not os.path.exists(log_path):
        log_callback(f"[成就监测] 等待日志文件: {log_path}")
        for _ in range(300):
            if os.path.exists(log_path):
                break
            time.sleep(0.1)

    # 不加载任何跨会话缓存: 物品/按键/点击状态均从本次日志实时重建

    # 输出启动信息

    from functions.base.terminal_banner import get_banner_with_random_style
    # 横幅可能因字体/排版抛错，绝不能因此拖死整个监测
    try:
        log_callback(f"{get_banner_with_random_style('Limbus Company')}")
    except Exception as exc:  # noqa: BLE001
        _boot(f"横幅渲染失败（不影响监测）: {type(exc).__name__}: {exc}")
    log_callback(f"监控日志: {log_path}")
    # log_callback("=" * 60)
    # log_callback("")
    # log_callback("成就列表:")
    # for ach in achievements:
    #     status = "[已解锁]" if ach.unlocked else "[未解锁]"
    #     log_callback(f"  {status} {ach.name}: {ach.description}")
    # 启动时就已解锁的（比如从存档恢复）不再重复播报，只播本次运行新解锁的
    _logged_unlocks.update(
        getattr(a, "id", None) or getattr(a, "name", "") for a in achievements if a.unlocked)
    log_callback("")
    log_callback("开始监控...")
    log_callback("-" * 60)
    log_callback("[成就监测] 战斗观测详情: 事件流 logs/battle_watch.log；"
                 "状态 cache/achievement/battle_watch_status.json；"
                 "离线自查 python -m functions.achievement.battle_watch --probe/--status")

    # 创建 Hook（先不要启动监控线程：偏移索引相关模块要先在主线程 import 完，
    # 否则监控线程里的惰性 import 会与主线程撞上 Python 3.14 的 import 锁）
    _hook_instance = AchievementHook(log_path, log_callback)
    _boot("AchievementHook 构造完成")
    _start_hook_index_refresh(log_callback)
    _boot("偏移索引刷新已下发（后台）")
    _hook_instance.start_monitoring()
    _boot("监控线程与战斗观测已启动")

    # 启动全局输入统计 (P键/点击) - 失败不影响主监控
    input_ctrl = None
    try:
        from functions.achievement.input_hook import start_input_monitoring
        input_ctrl = start_input_monitoring()
        log_callback("[成就监测] 输入统计已启用 (P键/鼠标点击)")
    except Exception:
        input_ctrl = None
        log_callback("[成就监测] 输入统计不可用, 跳过按键/点击成就")

    # 尝试启用 GUI 成就弹窗 (若环境无显示则自动降级为纯日志)
    toast_ctrl = None
    try:
        from functions.achievement.toast import ToastController
        toast_ctrl = ToastController()
    except Exception:
        toast_ctrl = None
        log_callback("[成就监测] GUI 弹窗不可用, 仅输出日志")

    # 成就轮询放**独立线程**：``check_achievements`` 里的内存成就要读游戏进程，
    # 未附加时单次能到 ~400ms；以前它跑在驱动弹窗动画的主线程上，
    # 结果就是弹窗“末尾卡顿/看着像卡死”（淡出阶段被 400ms 的读内存卡住）。
    # 现在主线程只负责 pump 动画，轮询线程只负责判定 + 入队（都是线程安全的）。
    poll_stop = threading.Event()

    def _poll_loop():
        while _hook_instance is not None and _hook_instance.running and not poll_stop.is_set():
            try:
                _check_input_achievements(log_callback)
            except Exception as exc:  # noqa: BLE001
                log_callback(f"[成就监测] 成就轮询异常: {type(exc).__name__}: {exc}")
            poll_stop.wait(ACHIEVEMENT_POLL_SEC)

    poll_thread = threading.Thread(target=_poll_loop, name="achievement-poll", daemon=True)
    poll_thread.start()

    # 保持运行直到被停止
    # 主线程只做一件事：弹窗动画。**没有弹窗时不空转**（实测 60fps 空转约 1.3%，
    # 有弹窗 2.6%；降到 20Hz 惰性轮询后空闲≈0，观测线程本身几乎不占 CPU）。
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
        log_callback("\n[成就监测] 收到停止信号，正在关闭...")
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
        log_callback("[成就监测] 已停止")


def _hook_index_auto_enabled() -> bool:
    """设置项 auto_update_hook_index（缺省 true）：是否在游戏启动时自动刷新偏移索引。"""
    try:
        from functions.base.settings_manager import get_settings_manager
        value = get_settings_manager().get_setting("auto_update_hook_index")
        return True if value is None else bool(value)
    except Exception:
        return True


def _start_hook_index_refresh(log_callback):
    """启动时刷新偏移：云端拉链（总是） + 按需重建索引（可通过设置关闭）。

    依赖在主线程先导好（Python 3.14 的 import 锁下，后台线程承担首次导入会有
    deadlock 风险）。
    """
    refresh = None
    auto_update = None
    try:
        from functions.achievement.memory_reader import refresh_chain_from_cloud as refresh
    except Exception as exc:  # noqa: BLE001
        log_callback(f"[成就监测] 偏移链刷新模块不可用: {exc}")
    try:
        from functions.hook import auto_update_async as auto_update
    except Exception as exc:  # noqa: BLE001
        log_callback(f"[成就监测] 偏移索引模块不可用: {exc}")

    if refresh is not None:
        try:
            refresh(background=True, on_log=log_callback)
        except Exception as exc:  # noqa: BLE001
            log_callback(f"[成就监测] 云端偏移链刷新不可用: {exc}")
    if auto_update is None:
        return
    if not _hook_index_auto_enabled():
        log_callback("[成就监测] 已关闭自动刷新偏移索引（设置: 自动刷新游戏偏移索引）")
        return
    try:
        if auto_update(on_log=log_callback):
            log_callback("[成就监测] 已在后台检查偏移索引（游戏更新时会自动重建）")
    except Exception as exc:  # noqa: BLE001
        log_callback(f"[成就监测] 偏移索引自动更新不可用: {exc}")


def _check_input_achievements(log_callback=None):
    """检查 P键/点击 计数成就 (阈值达成即解锁)。

    必须传 ``log_callback``（主循环的循环体）：以前这里用 ``print``，
    子进程 stdout 是 DEVNULL，会出现“成就解锁了但成就日志里没有”的情况。
    """
    try:
        get_state()
        unlocked = check_achievements(log_callback or (lambda m: None))
        if unlocked:
            _report_unlocks(log_callback or (lambda m: None), unlocked)
            _notify_toast(unlocked)
    except Exception:
        pass


def start_achievement_monitoring(log_path: str = LOG_FILE) -> AchievementHook:
    """启动成就监测（后台线程模式）。

    参数:
        log_path: 游戏日志文件路径

    返回:
        AchievementHook 实例
    """
    global _hook_instance

    def log_callback(msg: str):
        print(with_timestamp(msg))

    # 内嵌模式也尝试启用输入统计 (失败不影响)
    try:
        from functions.achievement.input_hook import start_input_monitoring
        start_input_monitoring()
    except Exception:
        pass

    _hook_instance = AchievementHook(log_path, log_callback)
    _hook_instance.start_monitoring()
    return _hook_instance


def stop_achievement_monitoring():
    """停止成就监测。"""
    global _hook_instance
    if _hook_instance:
        _hook_instance.stop_monitoring()


def get_hook(log_path: str = LOG_FILE) -> AchievementHook | None:
    """获取当前 Hook 实例。"""
    return _hook_instance