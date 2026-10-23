r"""Steam 游戏「启动选项」(Launch Options) 的直接读写。

落盘位置：
    <Steam>/userdata/<账号ID>/config/localconfig.vdf
    → UserLocalConfigStore / Software / Valve / Steam / apps / <appid> / LaunchOptions

设计要点（与 steam_locator / steam_playtime 保持同一套约定）：
  1. 定点修改：只替换 LaunchOptions 的值区间（或在该 app 块内插入一行），
     其余字节一律不动 —— 见 functions/base/vdf_text.py。
  2. 多账号：Steam 的 userdata 下每个登录过的账号各有一份 localconfig.vdf。
     默认写「当前登录账号」（注册表 HKCU\\Software\\Valve\\Steam\\ActiveProcess\\ActiveUser），
     也支持指定账号或一次性写给全部账号。
  3. Steam 运行期间会把内存里的配置周期性/退出时写回 localconfig.vdf，
     会覆盖外部修改。所以先探测 Steam 进程，运行中默认仍然写入但标记
     effective=False 并给出警告；require_steam_closed=True 则直接拒绝。
  4. 写前备份（localconfig.vdf.faustbak）、原子替换（tmp + os.replace）、
     写后回读校验，结果全部体现在返回值里。

对外入口：
    accounts()                     列出所有账号的 localconfig
    get_launch_options()           读当前值
    set_launch_options()           写（唯一的写入口）
    clear_launch_options()         清空（等价于 Steam 界面里留空）
    restore_backup()               用 .faustbak 回滚
"""

from __future__ import annotations

import os
import shutil
import stat as _stat
import subprocess

from functions.base import steam_locator as _sl
from functions.base import vdf_text

__all__ = [
    "LaunchOptionsError",
    "APP_ID",
    "LAUNCH_OPTIONS_KEY",
    "steam_running",
    "shutdown_steam",
    "start_steam",
    "active_account_id",
    "accounts",
    "get_launch_options",
    "set_launch_options",
    "apply_launch_options",
    "clear_launch_options",
    "restore_backup",
]

APP_ID: str = str(_sl.STEAM_APP_ID)
LAUNCH_OPTIONS_KEY = "LaunchOptions"
BACKUP_SUFFIX = ".faustbak"

_APPS_CHAIN: tuple[str, ...] = (
    "UserLocalConfigStore", "Software", "Valve", "Steam", "apps",
)

_CREATE_NO_WINDOW = 0x08000000
_DETACHED_PROCESS = 0x00000008
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


class LaunchOptionsError(RuntimeError):
    """读写启动项失败（找不到 Steam / 账号 / 文件结构异常）。"""


# --------------------------------------------------------------------------- #
# 环境探测
# --------------------------------------------------------------------------- #
def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if handle:
            kernel32.CloseHandle(handle)
            return True
        return False
    except Exception:  # noqa: BLE001
        return False


def steam_running() -> bool:
    """Steam 客户端是否在跑。先看注册表里 Steam 自己维护的 pid，再退回 tasklist。"""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Valve\Steam\ActiveProcess") as key:
            try:
                pid, _ = winreg.QueryValueEx(key, "pid")
                if int(pid) > 0 and _pid_alive(int(pid)):
                    return True
            except OSError:
                pass
    except (ImportError, OSError):
        pass
    try:
        proc = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq steam.exe", "/NH"],
            capture_output=True, text=True, timeout=6,
            creationflags=_CREATE_NO_WINDOW,
        )
        return "steam.exe" in (proc.stdout or "").lower()
    except Exception:  # noqa: BLE001
        return False


def _steam_executable() -> str:
    """从注册表/locator 找出 steam.exe 的绝对路径；找不到返回 ''。"""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
            for name in ("SteamExe", "steamexe"):
                try:
                    value, _ = winreg.QueryValueEx(key, name)
                except OSError:
                    continue
                if value:
                    return str(value).replace("/", os.sep)
    except (ImportError, OSError):
        pass
    for steam_dir in _sl._steam_install_paths():        # noqa: SLF001
        candidate = os.path.join(steam_dir, "steam.exe")
        if os.path.isfile(candidate):
            return candidate
    return ""


def shutdown_steam(timeout: float = 30.0, *, force: bool = False) -> dict:
    """优雅关闭 Steam 并等待进程退出（`steam.exe -shutdown`）。

    改启动项真正生效需要 Steam 完全退出：Steam 在退出时会把内存里的配置写回
    localconfig.vdf，如果它还在跑，外部写入会被覆盖。本函数只是便利工具，
    不会自动被 set_launch_options 调用 —— 关不关由调用方/用户决定。
    """
    if not steam_running():
        return {"ok": True, "already_closed": True, "error": ""}
    exe = _steam_executable()
    if not exe:
        return {"ok": False, "already_closed": False,
                "error": "找不到 steam.exe，无法自动关闭 Steam"}
    try:
        if force:
            subprocess.run(["taskkill", "/F", "/IM", "steam.exe", "/T"],
                           capture_output=True, timeout=15,
                           creationflags=_CREATE_NO_WINDOW)
        else:
            subprocess.Popen([exe, "-shutdown"], creationflags=_CREATE_NO_WINDOW,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "already_closed": False, "error": f"关闭失败: {exc}"}
    import time
    deadline = time.monotonic() + max(1.0, timeout)
    while time.monotonic() < deadline:
        if not steam_running():
            return {"ok": True, "already_closed": False, "error": ""}
        time.sleep(0.5)
    return {"ok": False, "already_closed": False,
            "error": f"等了 {timeout:g}s Steam 仍未退出"}


def start_steam(*, detach: bool = True) -> dict:
    """拉起 Steam 客户端（不阻塞、不等它登录完）。"""
    exe = _steam_executable()
    if not exe:
        return {"ok": False, "error": "找不到 steam.exe，无法启动 Steam"}
    if steam_running():
        return {"ok": True, "already_running": True, "error": ""}
    try:
        flags = _CREATE_NO_WINDOW
        if detach:
            flags |= _DETACHED_PROCESS
        subprocess.Popen([exe], creationflags=flags, close_fds=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "already_running": False, "error": f"启动失败: {exc}"}
    return {"ok": True, "already_running": False, "error": ""}


def active_account_id() -> str | None:
    """当前登录的 Steam 账号 ID（userdata 下的目录名）；未登录返回 None。"""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Valve\Steam\ActiveProcess") as key:
            for name in ("ActiveUser", "activeuser"):
                try:
                    value, _ = winreg.QueryValueEx(key, name)
                except OSError:
                    continue
                try:
                    uid = int(value)
                except (TypeError, ValueError):
                    continue
                if uid > 0:
                    return str(uid)
    except (ImportError, OSError):
        pass
    return None


def _localconfig_path(steam_dir: str, account: str) -> str:
    return os.path.join(steam_dir, "userdata", account, "config", "localconfig.vdf")


def accounts() -> list[dict]:
    """所有 Steam 账号的 localconfig.vdf 清单（按修改时间倒序）。"""
    active = active_account_id()
    found: list[dict] = []
    seen: set[str] = set()
    for steam_dir in _sl._steam_install_paths():        # noqa: SLF001（同包复用）
        userdata = os.path.join(steam_dir, "userdata")
        try:
            names = sorted(os.listdir(userdata))
        except OSError:
            continue
        for name in names:
            path = _localconfig_path(steam_dir, name)
            if not os.path.isfile(path):
                continue
            real = os.path.normcase(os.path.abspath(path))
            if real in seen:
                continue
            seen.add(real)
            try:
                mtime = os.path.getmtime(path)
            except OSError:
                mtime = 0.0
            found.append({
                "account": name,
                "path": path,
                "steam_dir": steam_dir,
                "active": name == active,
                "mtime": mtime,
            })
    found.sort(key=lambda item: (not item["active"], -item["mtime"]))
    return found


def _pick_target(account: str | None = None) -> dict | None:
    """挑一份 localconfig：指定账号 > 当前登录账号 > 最近修改的那份。"""
    items = accounts()
    if not items:
        return None
    if account:
        wanted = str(account).strip()
        for item in items:
            if item["account"] == wanted:
                return item
        raise LaunchOptionsError(f"没有账号 {wanted} 的 localconfig.vdf")
    for item in items:
        if item["active"]:
            return item
    return items[0]


# --------------------------------------------------------------------------- #
# 文本读写（保 BOM / 保换行符 / 保留原文件属性）
# --------------------------------------------------------------------------- #
def _read_text(path: str) -> tuple[str, bool]:
    with open(path, "rb") as handle:
        raw = handle.read()
    bom = raw.startswith(b"\xef\xbb\xbf")
    if bom:
        raw = raw[3:]
    return raw.decode("utf-8", "surrogateescape"), bom


def _write_text_atomic(path: str, text: str, bom: bool) -> None:
    payload = (b"\xef\xbb\xbf" if bom else b"") + text.encode("utf-8", "surrogateescape")
    tmp = path + ".faust.tmp"
    with open(tmp, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        shutil.copystat(path, tmp)
    except OSError:
        pass
    mode = None
    try:
        mode = _stat.S_IMODE(os.stat(path).st_mode)
    except OSError:
        pass
    try:
        os.replace(tmp, path)
    finally:
        if mode is not None:
            try:
                os.chmod(path, mode | _stat.S_IWRITE)
            except OSError:
                pass
    try:
        os.chmod(path, mode if mode is not None else _stat.S_IWRITE)
    except OSError:
        pass


def _apps_path(text: str) -> tuple[str, ...]:
    """定位 apps 表的真实路径；结构被 Steam 改过时退回全树搜索。"""
    roots = vdf_text.parse(text)
    if vdf_text.find_path(roots, _APPS_CHAIN) is not None:
        return _APPS_CHAIN
    stack: list[tuple[list, tuple[str, ...]]] = [(roots, ())]
    while stack:
        nodes, prefix = stack.pop()
        for node in nodes:
            if node.block is None:
                continue
            if node.key == "apps":
                return prefix + (node.key,)
            stack.append((node.block, prefix + (node.key,)))
    return _APPS_CHAIN


def _key_path(apps: tuple[str, ...], app_id: str) -> tuple[str, ...]:
    return tuple(apps) + (str(app_id), LAUNCH_OPTIONS_KEY)


def _backup(path: str) -> str:
    target = path + BACKUP_SUFFIX
    try:
        shutil.copy2(path, target)
        return target
    except OSError:
        return ""


# --------------------------------------------------------------------------- #
# 读
# --------------------------------------------------------------------------- #
def get_launch_options(app_id: str = APP_ID, *, account: str | None = None,
                       path: str | None = None) -> dict:
    """读取指定游戏的启动选项。没配置过时 value 为 ''。"""
    app_id = str(app_id).strip()
    result: dict = {
        "ok": False, "app_id": app_id, "value": "", "previous": "",
        "account": "", "path": "", "steam_running": steam_running(), "error": "",
    }
    try:
        if path:
            target = {"account": "", "path": path}
        else:
            target = _pick_target(account)
    except LaunchOptionsError as exc:
        result["error"] = str(exc)
        return result
    if not target:
        result["error"] = "没找到任何 localconfig.vdf（Steam 未安装 / 没登录过？）"
        return result
    file_path = target["path"]
    result["path"] = file_path
    result["account"] = target.get("account", "")
    if not os.path.isfile(file_path):
        result["error"] = f"文件不存在: {file_path}"
        return result
    try:
        text, _bom = _read_text(file_path)
        apps = _apps_path(text)
        value = vdf_text.get_string(text, _key_path(apps, app_id), "")
    except Exception as exc:  # noqa: BLE001
        result["error"] = f"读取失败: {exc}"
        return result
    result.update(ok=True, value=value or "", previous=value or "")
    return result


# --------------------------------------------------------------------------- #
# 写
# --------------------------------------------------------------------------- #
def _apply_one(file_path: str, app_id: str, value: str, *,
               dry_run: bool, backup: bool) -> dict:
    item: dict = {
        "ok": False, "path": file_path, "previous": "", "value": value,
        "changed": False, "verified": False, "backup": "", "error": "",
        "diff": "",
    }
    try:
        text, bom = _read_text(file_path)
        apps = _apps_path(text)
        key_path = _key_path(apps, app_id)
        previous = vdf_text.get_string(text, key_path, "") or ""
        item["previous"] = previous
        new_text, changed = vdf_text.set_string(text, key_path, value)
        item["changed"] = changed
        if changed:
            item["diff"] = _diff_preview(text, new_text)
        if dry_run:
            item["ok"] = True
            return item
        if not changed:
            item.update(ok=True, verified=True)
            return item
        if backup:
            item["backup"] = _backup(file_path)
        _write_text_atomic(file_path, new_text, bom)
        readback, _ = _read_text(file_path)
        item["verified"] = vdf_text.get_string(readback, _key_path(_apps_path(readback), app_id)) == value
        item["ok"] = item["verified"]
        if not item["verified"]:
            item["error"] = "写入后回读的值与期望不一致"
    except Exception as exc:  # noqa: BLE001
        item["error"] = str(exc)
    return item


def _diff_preview(old: str, new: str, context: int = 2) -> str:
    """只给改动附近几行做预览，方便日志/UI 展示。"""
    import difflib
    old_lines = old.splitlines()
    new_lines = new.splitlines()
    diff = list(difflib.unified_diff(old_lines, new_lines, n=context, lineterm=""))
    if not diff:
        return ""
    body = diff[2:]
    if len(body) > 24:
        body = body[:24] + ["..."]
    return "\n".join(body)


def set_launch_options(options, app_id: str = APP_ID, *,
                       account: str | None = None,
                       path: str | None = None,
                       all_accounts: bool = False,
                       dry_run: bool = False,
                       backup: bool = True,
                       require_steam_closed: bool = False) -> dict:
    """写入启动选项（唯一的写入口）。

    options: 字符串，原样写进 LaunchOptions（Steam 界面里是什么这里就是什么）。
    account: 指定账号目录名；None = 当前登录账号。
    path: 直接指定 localconfig.vdf 路径（测试/离线修复用，优先于 account）。
    all_accounts: True 时写给 userdata 下所有账号。
    dry_run: 只算 diff，不落盘。
    require_steam_closed: Steam 在跑时直接拒绝（默认只告警）。
    """
    app_id = str(app_id).strip()
    value = "" if options is None else str(options)
    running = steam_running()

    result: dict = {
        "ok": False, "app_id": app_id, "value": value, "previous": "",
        "changed": False, "verified": False, "steam_running": running,
        "effective": not running, "dry_run": dry_run, "targets": [],
        "warnings": [], "error": "", "message": "",
    }

    if running and require_steam_closed:
        result["error"] = "Steam 正在运行，请先完全退出 Steam 再修改启动选项"
        return result

    try:
        if path:
            targets = [{"account": "", "path": path}]
        elif all_accounts:
            targets = accounts()
        else:
            picked = _pick_target(account)
            targets = [picked] if picked else []
    except LaunchOptionsError as exc:
        result["error"] = str(exc)
        return result
    if not targets:
        result["error"] = "没找到任何 localconfig.vdf（Steam 未安装 / 没登录过？）"
        return result

    results = [_apply_one(t["path"], app_id, value,
                          dry_run=dry_run, backup=backup) for t in targets]
    for item, target in zip(results, targets):
        item["account"] = target.get("account", "")

    result["targets"] = results
    result["ok"] = all(item["ok"] for item in results)
    result["changed"] = any(item["changed"] for item in results)
    result["verified"] = result["ok"] and all(item["verified"] for item in results)
    first = next((item for item in results if item["previous"] != value), results[0])
    result["previous"] = first["previous"]
    if not result["ok"]:
        result["error"] = "; ".join(item["error"] for item in results if item["error"])

    if running:
        result["effective"] = False
        result["warnings"].append(
            "Steam 正在运行：文件已写入，但 Steam 退出时会用内存里的配置覆盖它。"
            "要让启动项真正生效，请完全退出 Steam 后（或用本模块再写一次）再启动游戏。")
    if result["ok"]:
        if dry_run:
            result["message"] = f"预演：LaunchOptions 将变为 {value!r}（未落盘）"
        elif result["changed"]:
            result["message"] = f"已写入 LaunchOptions = {value!r}"
        else:
            result["message"] = "LaunchOptions 已经是这个值，无需修改"
    return result


def clear_launch_options(app_id: str = APP_ID, **kwargs) -> dict:
    """清空启动选项（写空字符串，等价于 Steam 界面里把输入框删干净）。"""
    kwargs.pop("options", None)
    return set_launch_options("", app_id, **kwargs)


def restore_backup(path: str) -> dict:
    """用同目录的 localconfig.vdf.faustbak 覆盖回去。"""
    backup = path + BACKUP_SUFFIX
    if not os.path.isfile(backup):
        return {"ok": False, "path": path, "error": f"没有备份文件: {backup}"}
    try:
        shutil.copy2(backup, path)
    except OSError as exc:
        return {"ok": False, "path": path, "error": str(exc)}
    return {"ok": True, "path": path, "backup": backup}


# --------------------------------------------------------------------------- #
# 集成流程：强杀 Steam -> 写入启动项 -> 重启 Steam
# --------------------------------------------------------------------------- #
def apply_launch_options(options: str, app_id: str = APP_ID, *,
                         account: str | None = None,
                         path: str | None = None,
                         all_accounts: bool = False,
                         kill_steam: bool = True,
                         restart_steam: bool = True,
                         kill_timeout: float = 20.0,
                         backup: bool = True) -> dict:
    """一步到位把启动项写进 Steam，一条语句即可，外部调用无需关心 Steam 状态。

        from functions.base.steam_launch_options import apply_launch_options
        apply_launch_options("-dx11 -nojoy")

    为什么必须强杀：Steam 退出时会把内存里的整份 localconfig.vdf 写回文件，
    外部改的值会被直接抹掉。所以流程固定为「强杀（不给它写回的机会）→ 写入 →
    重启」。强杀用 `taskkill /F /IM steam.exe /T`，不弹窗、不询问、不等 Steam
    自己收尾。

    返回 dict：ok / value / app_id / path / steps / error。
    `steps` 是执行轨迹，每步一个 {step, ok, detail}，便于上层展示或排查：
        [{'step': 'kill_steam', ...}, {'step': 'write', ...},
         {'step': 'restart_steam', ...}]

    注意：重启 Steam 后它读到的是刚写入的新值，不会再覆盖回去；本函数不在
    Steam 启动后做二次确认（那是调用方或用户自己看属性面板的事）。
    """
    steps: list[dict] = []
    result: dict = {
        "ok": False, "value": options, "app_id": str(app_id),
        "path": "", "steps": steps, "error": "",
    }

    if kill_steam:
        step = {"step": "kill_steam", "ok": True, "detail": ""}
        if not steam_running():
            step["detail"] = "Steam 本来就没在运行"
        else:
            killed = shutdown_steam(timeout=kill_timeout, force=True)
            still = steam_running()
            step["ok"] = bool(killed.get("ok")) or not still
            step["detail"] = "已强杀" if step["ok"] else (killed.get("error") or "强杀后 Steam 仍在运行")
        steps.append(step)
        if not step["ok"]:
            result["error"] = "强杀 Steam 失败: " + step["detail"]
            return result
    else:
        steps.append({"step": "kill_steam", "ok": True, "detail": "已跳过"})

    written = set_launch_options(options, app_id, account=account, path=path,
                                 all_accounts=all_accounts, backup=backup)
    result["path"] = (written.get("targets") or [{}])[0].get("path", "")
    steps.append({"step": "write", "ok": bool(written.get("ok")),
                  "detail": written.get("message") or written.get("error", "")})
    if not written.get("ok"):
        result["error"] = written.get("error") or "写入失败"
        return result

    if restart_steam:
        started = start_steam()
        steps.append({"step": "restart_steam", "ok": bool(started.get("ok")),
                      "detail": "Steam 原本就在运行，无需重启" if started.get("already_running")
                      else (started.get("error") or "已拉起 Steam")})
        if not started.get("ok"):
            result["error"] = "重启 Steam 失败: " + str(started.get("error", ""))
            return result
    else:
        steps.append({"step": "restart_steam", "ok": True, "detail": "已跳过"})

    result["ok"] = True
    return result


if __name__ == "__main__":
    import json
    print("Steam 运行中:", steam_running())
    print("当前账号:", active_account_id())
    print(json.dumps(get_launch_options(), ensure_ascii=False, indent=2))
