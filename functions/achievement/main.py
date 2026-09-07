"""Achievement monitoring entry point - hidden background hook.

Usage:
    python main.py                          # Uses default Player.log path
    python main.py --log PATH              # Custom log file path
    python main.py --interval SEC          # Custom check interval (default 0.3)
    python main.py --retry COUNT           # Custom retry count (default 3)
    python main.py --debug                 # Enable debug output
"""

import os
import sys
import time
import argparse
import signal
from datetime import datetime

# Ensure module can be imported when run directly
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from functions.achievement.hook import AchievementHook, start_achievement_monitoring, stop_achievement_monitoring
from functions.achievement.achievements import LOG_FILE


def parse_args():
    """Parse command line arguments."""
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
    """Run achievement monitoring hidden in background.
    
    Args:
        log_path: Path to the game log file
        debug: Enable debug output
    """
    # Set console to UTF-8 for proper output
    for stream in (sys.stdout, sys.stderr):
        try:
            if hasattr(stream, 'reconfigure'):
                stream.reconfigure(encoding='utf-8', errors='replace') # pyright: ignore[reportAttributeAccessIssue]
        except Exception:
            pass

    # Print startup banner
    print("=" * 60)
    print("🎮 Limbus Company - Achievement Monitor")
    print(f"📁 Log file: {os.path.abspath(log_path)}")
    print(f"⏰ Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("🔒 Running hidden in background...")
    print("=" * 60)
    print("")

    # Create and start hook
    hook = AchievementHook(log_path, None)
    
    # Handle graceful shutdown
    def signal_handler(signum, frame):
        print("\n[AchievementMonitor] Shutting down...")
        hook.stop_monitoring()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Start monitoring
    hook.start_monitoring()

    # Main loop - output status periodically
    try:
        while hook.running:
            time.sleep(10)  # Status update every 10 seconds
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
    """Main entry point."""
    args = parse_args()

    # Determine log path
    log_path = args.log
    if log_path is None:
        # Default: check if game directory is in environment
        game_dir = os.environ.get('LIMBUS_LOG_DIR', None)
        if game_dir:
            log_path = os.path.join(game_dir, 'Player.log')
        else:
            log_path = LOG_FILE

    # Run hidden
    run_hidden(log_path, args.debug)


if __name__ == "__main__":
    main()