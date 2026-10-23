"""把 Steam 的「启动选项」绑到本启动器上。

绑定之后 Steam 里的 LaunchOptions 形如：

    "D:\\FaustLauncher\\FaustLauncher.exe" --launcher-mode %command%

Steam 会先拉起启动器（`%command%` 是 Steam 对「游戏本身那条命令」的占位符，
交给启动器当参数用），启动器再走 `--launcher-mode` 的后端流程起游戏。

反过来取消绑定会把当初被覆盖掉的启动项原样写回去，不会把用户自己设的
`-dx11 -nojoy` 之类参数吃掉。
"""

import json
import os

from functions.base import steam_launch_options as _slo
from functions.base.common.path_utils import get_app_root
from functions.base.launcher_mode import LAUNCHER_MODE_FLAG, launcher_command

__all__ = [
    "COMMAND_TOKEN",
    "build_launch_options",
    "expected_options",
    "is_bound",
    "apply",
    "unbind",
]

COMMAND_TOKEN = "%command%"

# 与 settings.json 同目录：打包后是 exe 旁的 config/，开发时是仓库根的 config/。
# 不能用 __file__ 推算，onedir 下那会落到 _internal/ 里，更新时容易丢。
_BACKUP_FILE = os.path.join(get_app_root(create=False), "config", "steam_launch_binding.json")


def build_launch_options() -> str:
    """拼出期望写进 Steam 的启动项字符串。"""
    exe, args = launcher_command()
    parts = [f'"{exe}"'] + [f'"{a}"' for a in args]
    parts += [LAUNCHER_MODE_FLAG, COMMAND_TOKEN]
    return " ".join(parts)


# 语义清晰一点的别名
expected_options = build_launch_options


def _norm(text) -> str:
    """压掉多余空白后比较，避免手改多一个空格就判成「不合规」。"""
    return " ".join(str(text or "").split())


def _current_value() -> str:
    got = _slo.get_launch_options()
    if not got.get("ok"):
        return ""
    return got.get("value") or ""


def is_bound(value: str | None = None) -> bool:
    """当前启动项是否已经等于期望值（即「合规」）。"""
    if value is None:
        value = _current_value()
    return _norm(value) == _norm(build_launch_options())


# --------------------------------------------------------------------------- #
# 被覆盖掉的原始启动项的备份/恢复
# --------------------------------------------------------------------------- #
def _save_backup(value: str) -> None:
    try:
        os.makedirs(os.path.dirname(_BACKUP_FILE), exist_ok=True)
        with open(_BACKUP_FILE, "w", encoding="utf-8") as fh:
            json.dump({"launch_options": value or ""}, fh, ensure_ascii=False, indent=2)
    except OSError as exc:
        print(f"[SteamBinding] 备份原启动项失败(继续): {exc}")


def _load_backup() -> str | None:
    try:
        with open(_BACKUP_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            return str(data.get("launch_options") or "")
    except (OSError, ValueError):
        pass
    return None


def _clear_backup() -> None:
    try:
        os.remove(_BACKUP_FILE)
    except OSError:
        pass


# --------------------------------------------------------------------------- #
# 应用/取消
# --------------------------------------------------------------------------- #
def apply(enabled: bool, *, restart_steam: bool = True,
          kill_timeout: float = 20.0) -> dict:
    """勾选设置项时调用：需要时关 Steam -> 写启动项 -> 再拉起 Steam。

    返回 dict：ok / changed / value / previous / message / error / steps。
    """
    expected = build_launch_options() if enabled else (_load_backup() or "")
    current = _current_value()

    if _norm(current) == _norm(expected):
        return {"ok": True, "changed": False, "value": current,
                "previous": current, "steps": [],
                "message": "Steam 启动项已经是目标状态，无需改动"}

    if enabled:
        # 只有第一次绑定才备份，别让「重新勾选」把原始值冲掉
        if _load_backup() is None:
            _save_backup(current)

    written = _slo.apply_launch_options(expected, all_accounts=True,
                                        restart_steam=restart_steam,
                                        kill_timeout=kill_timeout)
    # apply_launch_options 的返回值只有 ok/value/path/steps/error，
    # 具体「写了什么」「改没改」得自己从 steps 和前后值里取。
    write_step = next((s for s in written.get("steps", [])
                       if s.get("step") == "write"), {})
    result = {
        "ok": bool(written.get("ok")),
        "changed": _norm(current) != _norm(expected),
        "value": expected,
        "previous": current,
        "steps": written.get("steps", []),
        "message": write_step.get("detail") or ("已同步 Steam 启动项" if written.get("ok") else ""),
        "error": written.get("error", ""),
    }
    if result["ok"] and not enabled:
        _clear_backup()
    return result


def unbind(**kwargs) -> dict:
    """取消绑定（把启动项还原回绑定前）。"""
    return apply(False, **kwargs)
