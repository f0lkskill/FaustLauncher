
import os
import sys
import time
import argparse
import signal
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from functions.achievement.hook import AchievementHook, start_achievement_monitoring, stop_achievement_monitoring
from functions.achievement.achievements import LOG_FILE

def parse_args():
    parser = argparse.ArgumentParser(
        description="Limbus Company Achievement Monitor"
    )
    parser.add_argument(
        "--log", type=str, default=None,
        help=f"Path to Player.log (default: {LOG_FILE})"
    )
    parser.add_argument(
        "--interval", type=float, default=0.3,
        help="Check interval in seconds (default: 0.3)"
    )
    parser.add_argument(
        "--retry", type=int, default=3,
        help="Retry count for file operations (default: 3)"
    )
    parser.add_argument(
        "--debug", action="store_true",
        help="Enable debug output"
    )
    parser.add_argument(
        "--pid", type=int, default=None,
        help="PID of game process to monitor (for future use)"
    )
    return parser.parse_args()

def run_hidden(log_path: str, debug: bool = False):
    for stream in (sys.stdout, sys.stderr):
        try:
            if hasattr(stream, 'reconfigure'):
                stream.reconfigure(encoding='utf-8', errors='replace') # pyright: ignore[reportAttributeAccessIssue]
        except Exception:
            pass

    print("=" * 60)
    print("Limbus Company - Achievement Monitor")
    print(f"Log file: {os.path.abspath(log_path)}")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("Running hidden in background...")
    print("=" * 60)
    print("")

    hook = AchievementHook(log_path, None)
    
    def signal_handler(signum, frame):
        print("\n[AchievementMonitor] Shutting down...")
        hook.stop_monitoring()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    hook.start_monitoring()

    try:
        while hook.running:
            time.sleep(10)
            status = hook.get_status()
            if debug:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] "
                      f"Status: {status['achievements_unlocked']}/"
                      f"{status['achievements_total']} achievements | "
                      f"Battles: {status['battle_count']} | "
                      f"Items: {status['owned_items_count']}")
    except KeyboardInterrupt:
        pass
    finally:
        hook.stop_monitoring()
        print("\n[AchievementMonitor] Stopped.")

def main():
    args = parse_args()

    log_path = args.log
    if log_path is None:
        game_dir = os.environ.get('LIMBUS_LOG_DIR', None)
        if game_dir:
            log_path = os.path.join(game_dir, 'Player.log')
        else:
            log_path = LOG_FILE

    run_hidden(log_path, args.debug)

if __name__ == "__main__":
    main()
