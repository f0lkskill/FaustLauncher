# 新版本采用蓝奏云云端更新，而不是数据库，所以本集成库现在为纯粹的文件操作。
# bubble_dow.py 更名为 bubble_transfer.py

import glob
import os
import shutil
import sys


def _bubble_source_dir() -> str:
    """气泡源目录 ``resources/bubble_speech``（不依赖当前工作目录）。

    以前直接 ``glob("resources\\\\bubble_speech\\\\*.json")``：cwd 不是应用根时**一个都找不到**，
    而且静默返回成功，现象就是"气泡美化没生效"。
    """
    candidates = []
    try:
        from functions.base.common.path_utils import get_app_root
        candidates.append(os.path.join(get_app_root(), "resources", "bubble_speech"))
    except Exception:  # noqa: BLE001
        pass
    candidates.append(os.path.join("resources", "bubble_speech"))
    meipass = getattr(sys, "_MEIPASS", "")
    if meipass:
        candidates.append(os.path.join(meipass, "resources", "bubble_speech"))
    for path in candidates:
        if os.path.isdir(path):
            return path
    return candidates[0]


def transfer_bubble_files(config_path: str = "") -> bool:
    """把 ``resources/bubble_speech/*.json`` 覆盖到目标汉化目录。

    ``config_path`` 必须是**汉化包目录**（启动器侧 ``lang/<平台>`` 或游戏侧的
    ``LimbusCompany_Data/Lang/<平台>``）—— 传到 ``lang`` 这种父目录就会在它下面漏一堆
    气泡文件（曾经就是这么漏的）。
    """
    if not config_path:
        print("[美化] 未指定气泡目标目录，跳过气泡文件转移")
        return False
    if not os.path.isdir(config_path):
        print(f"[美化] 气泡目标目录不存在: {config_path}，跳过气泡文件转移")
        return False

    source = _bubble_source_dir()
    files = sorted(glob.glob(os.path.join(source, "*.json")))
    if not files:
        print(f"[美化] 没找到气泡文件: {source}")
        return False

    done = 0
    for path in files:
        try:
            shutil.copy2(path, config_path)
            done += 1
        except Exception as exc:  # noqa: BLE001
            print(f"[美化] 转移气泡文本文件失败 {os.path.basename(path)}: {exc}")
    print(f"[美化] 气泡文件已转移 {done}/{len(files)} 份 → {config_path}")
    return done > 0


def main(config_path: str = ""):
    """命令行入口点"""
    print(f"[美化] 开始转移气泡文件, 目标目录: {config_path}")
    success = transfer_bubble_files(config_path=config_path)

    if success:
        print("[美化] 气泡文件转移完成!")
    else:
        print("[美化] 气泡文件转移失败!")


if __name__ == "__main__":
    main()
