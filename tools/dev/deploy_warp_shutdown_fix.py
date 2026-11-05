"""仅在游戏未运行时备份并部署本次原生候选，不注入进程。"""
from pathlib import Path
import hashlib
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'addons/WarpHook'))
from warphook.base import find_game_pid

candidate = Path(tempfile.gettempdir()) / 'warphookobj/warp_host_candidate.dll'
target = ROOT / 'addons/WarpHook/warp_host.dll'
if find_game_pid():
    raise SystemExit('游戏正在运行，未修改生产 DLL')
if not candidate.is_file() or candidate.stat().st_size < 4096:
    raise SystemExit('候选 DLL 缺失或过小')
digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
old_hash = digest(target)
new_hash = digest(candidate)
backup = ROOT / 'cache/warphook-backups' / f'warp_host_before_0950_{old_hash[:12]}.dll'
backup.parent.mkdir(parents=True, exist_ok=True)
if not backup.exists():
    shutil.copy2(target, backup)
if digest(backup) != old_hash:
    raise SystemExit('备份校验失败，未部署')
if find_game_pid():
    raise SystemExit('游戏已启动，取消部署')
shutil.copy2(candidate, target)
if digest(target) != new_hash:
    raise SystemExit('部署校验失败')
print(f'Deployed sha256={new_hash}')
print(f'Backup: {backup}')
