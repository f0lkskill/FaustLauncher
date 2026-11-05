"""YisangMirrorFlow entry point.

  python tools/workflow/main.py                 # 总览窗口
  python tools/workflow/main.py --worker --package-dir tools/workflow/mods/<包名>
"""

from __future__ import annotations

import argparse
import os
import sys
import traceback

WORKFLOW_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(WORKFLOW_DIR))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import core  # noqa: E402


def _write_error(text: str) -> None:
    try:
        path = os.path.join(WORKFLOW_DIR, "last_error.log")
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(text + "\n")
    except OSError:
        pass


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="YisangMirrorFlow",
        description="把 lunartime .zip 与 .bank 批量打包成 .carra2 / .rebank",
    )
    parser.add_argument("--worker", action="store_true",
                        help="内部参数：作为单个包的打包子进程运行")
    parser.add_argument("--package-dir", default="",
                        help="内部参数：包目录 (worker 模式必填)")
    parser.add_argument("--debug", action="store_true", help="显示 pywebview 调试窗口")
    parser.add_argument("--version", action="store_true", help="输出版本号")
    args = parser.parse_args(argv)

    if args.version:
        print("%s v%s" % (core.WORKFLOW_NAME, core.VERSION))
        return 0

    if args.worker:
        if not args.package_dir:
            print("[workflow] --worker 需要 --package-dir")
            return 2
        from worker import run_worker
        return run_worker(args.package_dir, debug=args.debug)

    core.ensure_dirs()
    from overview_api import run_overview
    return run_overview(debug=args.debug)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except BaseException:
        detail = traceback.format_exc()
        _write_error(detail)
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                None, detail[-3000:], "YisangMirrorFlow", 0x10)
        except Exception:
            pass
        raise
