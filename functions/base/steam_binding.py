"""把 Steam 的「启动选项」绑到本启动器上。

绑定之后 Steam 里的 LaunchOptions 形如：

    "D:\\FaustLauncher\\FaustLauncher.exe" --launcher-mode %command%

Steam 会先拉起启动器（`%command%` 是 Steam 对「游戏本身那条命令」的占位符，
交给启动器当参数用），启动器再走 `--launcher-mode` 的后端流程起游戏。

反过来取消绑定就是把启动项直接清空——不落任何备份文件，也不去猜「当初是什么」。
启动项本来就是用户随时可改的自由文本，留一份影子副本只会让人怀疑它还会自己长回来。
"""

from functions.base import steam_launch_options as _slo
from functions.base.launcher_mode import LAUNCHER_MODE_FLAG, launcher_command

__all__ = [
    "COMMAND_TOKEN",
    "build_launch_options",
    "expected_options",
    "is_bound",
    "apply",
    "unbind",
    "reconcile",
]

COMMAND_TOKEN = "%command%"


def build_launch_options() -> str:
    """拼出期望写进 Steam 的启动项字符串。"""
    exe, args = launcher_command()
    parts = [f'"{exe}"'] + [f'"{a}"' for a in args]
    parts += [LAUNCHER_MODE_FLAG, COMMAND_TOKEN]
    return " ".join(parts)


# 语义清晰一点的别名
expected_options = build_launch_options


def _norm(text) -> str:
    """压掉多余空白并统一小写后比较。

    Steam 自己会把这行路径重新序列化，盘符会从小写变成大写（或反过来），
    逐字节比就会把「我们写的值」误判成「不是我们的」，于是启动器又会去走
    `steam://` 把启动器套起来。Windows 路径本来就大小写不敏感。
    """
    return " ".join(str(text or "").split()).lower()


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
# 应用/取消
# --------------------------------------------------------------------------- #
def apply(enabled: bool, *, restart_steam: bool = True,
          kill_timeout: float = 20.0) -> dict:
    """勾选设置项时调用：需要时关 Steam -> 写启动项 -> 再拉起 Steam。

    开启写绑定值，关闭写空字符串（等价于「没有启动项」）。
    返回 dict：ok / changed / value / previous / message / error / steps。
    """
    expected = build_launch_options() if enabled else ""
    current = _current_value()

    if _norm(current) == _norm(expected):
        return {"ok": True, "changed": False, "value": current,
                "previous": current, "steps": [],
                "message": "Steam 启动项已经是目标状态，无需改动"}

    written = _slo.apply_launch_options(expected, all_accounts=True,
                                        restart_steam=restart_steam,
                                        kill_timeout=kill_timeout)
    # apply_launch_options 的返回值只有 ok/value/path/steps/error，
    # 具体「写了什么」「改没改」得自己从 steps 和前后值里取。
    write_step = next((s for s in written.get("steps", [])
                       if s.get("step") == "write"), {})
    return {
        "ok": bool(written.get("ok")),
        "changed": _norm(current) != _norm(expected),
        "value": expected,
        "previous": current,
        "steps": written.get("steps", []),
        "message": write_step.get("detail") or ("已同步 Steam 启动项" if written.get("ok") else ""),
        "error": written.get("error", ""),
    }


def unbind(**kwargs) -> dict:
    """取消绑定（把启动项清空）。"""
    return apply(False, **kwargs)


# --------------------------------------------------------------------------- #
# 启动器初始化时自检
# --------------------------------------------------------------------------- #
def reconcile(*, restart_steam: bool = True, kill_timeout: float = 20.0) -> dict:
    """按当前设置项核对 Steam 启动项，不符合就纠正。

    跟 `apply` 的分工：`apply` 是「用户刚拨了开关，照着这个值写」；`reconcile`
    是「启动器自己看看现在符不符合我」，事实源是设置项那一份。

    存在的理由是个很结实的坑：A 启动器把启动项绑成自己的路径，用户卸了 A 装了
    B。这时 Steam 点「开始游戏」拉起的是已经被删掉的 A，什么都不发生，用户根本
    进不了 B 的启动流程——检查点放在「启动游戏」里是永远走不到的。所以 B 一被
    打开（哪怕只是来看看设置）就要把启动项抢回来。

    覆盖是彻底的：启动项里原来有什么（用户手加的 `-dx11`、别的启动器留下的路径、
    残缺的绑定）都不作数，以设置项为唯一事实源——开启就写满，关闭就清空。
    已经一致时直接返回，不关 Steam 也不写文件。
    """
    from functions.base.launcher_mode import STEAM_BINDING_KEY
    from functions.base.settings_manager import get_settings_manager

    enabled = bool(get_settings_manager().get_setting(STEAM_BINDING_KEY))
    return apply(enabled, restart_steam=restart_steam, kill_timeout=kill_timeout)
