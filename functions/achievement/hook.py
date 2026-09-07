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
    CHARACTER_ID_MAP,
    get_state, check_achievements,
    record_zero_item, poll_inventory_window,
    achievements,
)


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
                for ach in unlocked:
                    self.log_callback(f"  [成就] 解锁: {ach.name}")
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
            unlocked = check_achievements(self.log_callback)
            if unlocked:
                for ach in unlocked:
                    self.log_callback(f"  [成就] 解锁: {ach.name}")
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

    def start_monitoring(self):
        """启动后台线程监控日志文件。"""
        self.monitor_thread = threading.Thread(
            target=self._monitor_logs,
            daemon=False,  # 非 daemon，确保主进程等待此线程
        )
        self.monitor_thread.start()

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
                    if poll_inventory_window() is not None:
                        self._settle_inventory_browse()

                time.sleep(CHECK_INTERVAL)
            except Exception as e:
                self.log_callback(f"[AchievementHook] 监控错误: {e}")
                time.sleep(1)

    def _settle_inventory_browse(self):
        """一轮背包/兑换页浏览结束: 计数并触发成就检查。"""
        try:
            from functions.achievement.achievements import register_inventory_open
            register_inventory_open()
            s = get_state()
            unlocked = check_achievements(self.log_callback)
            if unlocked:
                self.log_callback("")
                self.log_callback("==== 成就解锁 ====")
                for ach in unlocked:
                    self.log_callback(f"  [成就] {ach.name}: {ach.description}")
                self.log_callback("")
                _notify_toast(unlocked)
        except Exception as e:
            self.log_callback(f"[AchievementHook] 浏览结算错误: {e}")

    def stop_monitoring(self):
        """停止监控。"""
        self.running = False
        if self.monitor_thread:
            self.monitor_thread.join(timeout=5)

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


# ============ 独立进程入口 ============
_hook_instance: AchievementHook | None = None


def run_achievement_hook():
    """成就监测独立进程入口。

    在当前进程中启动成就监测循环（阻塞），
    用于 subprocess 启动时调用。
    """
    global _hook_instance

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
        _log_file = open(args.output, 'w', encoding='utf-8', buffering=1)
        _line_count = 0

        def _write(msg: str):
            nonlocal _line_count
            _log_file.write(msg + '\n')
            _log_file.flush()
            _line_count += 1
            # 每 1000 行截断文件避免无限膨胀
            if _line_count >= 1000:
                _log_file.truncate(0)
                _log_file.seek(0)
                _line_count = 0

        log_callback = _write

        def _cleanup():
            _log_file.close()
        _atexit.register(_cleanup)
    else:
        log_callback = lambda msg: print(msg)  # noqa: E731

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
    log_callback("=" * 60)
    log_callback("Limbus Company - 成就追踪器")
    log_callback(f"监控日志: {log_path}")
    log_callback("=" * 60)
    log_callback("")
    log_callback("成就列表:")
    for ach in achievements:
        status = "[已解锁]" if ach.unlocked else "[未解锁]"
        log_callback(f"  {status} {ach.name}: {ach.description}")
    log_callback("")
    log_callback("开始监控...")
    log_callback("-" * 60)

    # 创建并启动 Hook
    _hook_instance = AchievementHook(log_path, log_callback)
    _hook_instance.start_monitoring()

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

    # 保持运行直到被停止
    try:
        while _hook_instance.running:
            if toast_ctrl is not None:
                # 驱动弹窗动画 (约 60fps)
                for _ in range(16):
                    toast_ctrl.pump()
                    time.sleep(0.016)
                # 输入计数成就: 每秒检查一次
                _check_input_achievements()
            else:
                time.sleep(1)
                _check_input_achievements()
    except KeyboardInterrupt:
        log_callback("\n[成就监测] 收到停止信号，正在关闭...")
    finally:
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


def _check_input_achievements():
    """检查 P键/点击 计数成就 (阈值达成即解锁)。"""
    try:
        s = get_state()
        unlocked = check_achievements(lambda m: None)
        if unlocked:
            for ach in unlocked:
                print(f"[成就] 解锁: {ach.name}")
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
        print(msg)

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