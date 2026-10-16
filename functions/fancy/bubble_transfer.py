
import glob
import os
import shutil
import sys

def _bubble_source_dir() -> str:
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
    if not config_path:
        print("[Cosmetic] 未指定气泡目标目录，跳过气泡文件转移")
        return False
    if not os.path.isdir(config_path):
        print(f"[Cosmetic] 气泡目标目录不存在: {config_path}，跳过气泡文件转移")
        return False

    source = _bubble_source_dir()
    files = sorted(glob.glob(os.path.join(source, "*.json")))
    if not files:
        print(f"[Cosmetic] 没找到气泡文件: {source}")
        return False

    done = 0
    for path in files:
        try:
            shutil.copy2(path, config_path)
            done += 1
        except Exception as exc:  # noqa: BLE001
            print(f"[Cosmetic] 转移气泡文本文件失败 {os.path.basename(path)}: {exc}")
    print(f"[Cosmetic] 气泡文件已转移 {done}/{len(files)} 份 → {config_path}")
    return done > 0

def main(config_path: str = ""):
    print(f"[Cosmetic] 开始转移气泡文件, 目标目录: {config_path}")
    source = _bubble_source_dir()
    if not glob.glob(os.path.join(source, "*.json")):
        print("[Cosmetic] 云端气泡资源尚未下载, 跳过气泡美化 (资源更新后会自动应用)")
        return
    success = transfer_bubble_files(config_path=config_path)

    if success:
        print("[Cosmetic] 气泡文件转移完成!")
    else:
        print("[Cosmetic] 气泡文件转移失败!")

if __name__ == "__main__":
    main()
