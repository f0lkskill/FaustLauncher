"""FaustLauncher 代码签名（Authenticode）助手。

被 ``tools/build/build.py`` 的「签名可执行文件」步骤调用；也可以单独在命令行用：

    python tools/build/code_sign.py build_V0.9.2/FaustLauncher.exe
    python tools/build/code_sign.py --show-config
    python tools/build/code_sign.py --verify build_V0.9.2/FaustLauncher.exe

设计要点
--------
* **证书只放在本机**：私钥 ``signing/FaustLauncher.pfx`` 与含密码的 ``signing.json``
  都在 .gitignore 里，绝不入库（见 signing/README.md 的轮换说明）。
* **没配证书不等于构建失败**：默认 ``required=false`` 时，缺证书/PFX 只在日志里给一条
  醒目警告然后跳过，其它人的机器 clone 下来照样能跑完整构建。
  若显式把 ``required`` 改成 true，签名失败会直接中止构建 —— 发版机器上学得会应该这么配。
* **签名放最后一步之前**：build.py 在「复制 exe」之后、「压缩 zip」之前签名，
  保证 zip 里装的是签好的 exe。

配置优先级（后者覆盖前者）
--------------------------
1. ``tools/build/signing/signing.json``
2. 环境变量 ``FAUST_SIGNTOOL`` / ``FAUST_PFX`` / ``FAUST_PFX_PASSWORD``
"""

from __future__ import annotations

import glob
import json
import os
import shutil
import subprocess
import sys

# tools/build/code_sign.py -> tools/build/signing/
_TOOLS_BUILD_DIR = os.path.dirname(os.path.abspath(__file__))
SIGNING_DIR = os.path.join(_TOOLS_BUILD_DIR, "signing")
CONFIG_PATH = os.path.join(SIGNING_DIR, "signing.json")

# signtool 的默认参数。自签名证书也能拿 DigiCert 的时间戳，加上才能让签名在证书过期后继续有效。
DEFAULT_CONFIG: dict = {
    "pfx": "FaustLauncher.pfx",          # 相对 signing/ 或绝对路径
    "password": "",                       # 也可用环境变量 FAUST_PFX_PASSWORD
    "timestamp_url": "http://timestamp.digicert.com",
    "file_digest": "sha256",              # /fd
    "timestamp_digest": "sha256",         # /td
    "required": False,                    # true = 签名失败就中止构建
    "verify": False,                      # true = 签完再跑一次 signtool verify /pa
    "signtool": "",                       # 留空则自动查找
}

# `/p` 是明文密码；只在日志里打码，别把密码写进构建日志
_LEVEL_OK, _LEVEL_BAD, _LEVEL_WARN = "ok", "bad", "warn"


# --------------------------------------------------------------------------- 配置
def load_config() -> dict:
    """读 signing.json，再让环境变量覆盖，返回一份可直接用的配置。"""
    cfg = dict(DEFAULT_CONFIG)
    if os.path.isfile(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"signing.json 不是合法 JSON：{exc}") from exc
        if isinstance(data, dict):
            for key, value in data.items():
                if value is None or value == "":
                    continue
                cfg[key] = value

    for env_key, cfg_key in (("FAUST_SIGNTOOL", "signtool"),
                             ("FAUST_PFX", "pfx"),
                             ("FAUST_PFX_PASSWORD", "password")):
        value = str(os.environ.get(env_key) or "").strip()
        if value:
            cfg[cfg_key] = value
    return cfg


def pfx_path(cfg: dict) -> str:
    """把配置里的 pfx 解析成绝对路径（相对路径按 signing/ 算）。"""
    raw = str(cfg.get("pfx") or "").strip()
    if not raw:
        return ""
    return raw if os.path.isabs(raw) else os.path.join(SIGNING_DIR, raw)


# --------------------------------------------------------------------------- 找 signtool
def _signtool_candidates(cfg: dict | None = None):
    """按可用性从高到低给出 signtool.exe 候选路径。"""
    cfg = cfg or {}
    explicit = str(cfg.get("signtool") or "").strip()
    if explicit:
        yield os.path.expandvars(explicit)
    env = str(os.environ.get("FAUST_SIGNTOOL") or "").strip()
    if env:
        yield os.path.expandvars(env)
    which = shutil.which("signtool") or shutil.which("signtool.exe")
    if which:
        yield which
    # 跟着仓库走的本机副本（.gitignore 里已挡住，不入库）
    yield os.path.join(SIGNING_DIR, "signtool", "signtool.exe")

    # 常见的 SDK / VS / NuGet 位置。SDK 会同时存在多个版本目录，取版本号最大的那个。
    patterns = [
        r"%ProgramFiles(x86)%\Windows Kits\10\bin\*\x64\signtool.exe",
        r"%ProgramFiles%\Windows Kits\10\bin\*\x64\signtool.exe",
        r"%ProgramFiles(x86)%\Windows Kits\10\bin\*\x86\signtool.exe",
        r"%ProgramFiles%\Windows Kits\10\bin\*\x86\signtool.exe",
        r"%USERPROFILE%\.nuget\packages\microsoft.windows.sdk.buildtools"
        r"\*\bin\*\x64\signtool.exe",
        r"%ProgramFiles%\Microsoft Visual Studio\*\*\Common7\IDE"
        r"\CommonExtensions\Microsoft\VSI\*\signtool.exe",
        r"%ProgramFiles(x86)%\Microsoft Visual Studio\*\*\Common7\IDE"
        r"\CommonExtensions\Microsoft\VSI\*\signtool.exe",
    ]
    found: list[str] = []
    for pattern in patterns:
        expanded = os.path.expandvars(pattern)
        if "%" in expanded:          # 该环境变量不存在（如没有 ProgramFiles(x86)）
            continue
        found.extend(glob.glob(expanded))
    for path in sorted(found, reverse=True):   # 目录名带版本号，倒序 = 新版优先
        yield path


def find_signtool(cfg: dict | None = None) -> str:
    """返回可用的 signtool.exe 绝对路径；找不到返回空串。"""
    for candidate in _signtool_candidates(cfg):
        if candidate and os.path.isfile(candidate):
            return os.path.abspath(candidate)
    return ""


# --------------------------------------------------------------------------- 签名
def _run(args: list[str]) -> tuple[int, str]:
    proc = subprocess.run(
        args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace",
    )
    return int(proc.returncode), (proc.stdout or "").strip()


def sign_file(path: str, cfg: dict | None = None, log=None) -> tuple[bool, str]:
    """给一个 PE 文件打 Authenticode 签名。

    返回 ``(ok, message)``；``message`` 是给日志/报错用的一句话。
    证书没配好时返回 ``(False, 原因)``，由调用方决定是中止还是跳过。
    """
    log = log or (lambda text, level="": None)
    cfg = cfg if cfg is not None else load_config()

    if not os.path.isfile(path):
        return False, f"待签名的文件不存在：{path}"

    cert = pfx_path(cfg)
    if not cert:
        return False, "未配置代码签名证书（signing.json 的 pfx 为空）"
    if not os.path.isfile(cert):
        return False, f"找不到证书文件：{cert}"

    password = str(cfg.get("password") or "")
    if not password:
        return False, "证书密码为空（signing.json 的 password 或环境变量 FAUST_PFX_PASSWORD）"

    signtool = find_signtool(cfg)
    if not signtool:
        return False, ("找不到 signtool.exe；请安装 Windows SDK，"
                       "或在 signing.json 的 signtool 里写死路径")

    args = [signtool, "sign", "/f", cert, "/p", password,
            "/fd", str(cfg.get("file_digest") or "sha256")]
    timestamp_url = str(cfg.get("timestamp_url") or "").strip()
    if timestamp_url:
        args += ["/tr", timestamp_url, "/td", str(cfg.get("timestamp_digest") or "sha256")]
    args.append(path)

    log(f"· signtool：{signtool}\n")
    log(f"· 证书：{cert}（密码 {'*' * len(password)}）\n")
    log(f"· 时间戳：{timestamp_url or '（未启用）'}\n")
    code, output = _run(args)
    for line in output.splitlines():
        log(f"  {line}\n")
    if code != 0:
        return False, f"signtool 签名失败（code {code}）"

    log(f"✔ 已签名：{os.path.basename(path)}\n", _LEVEL_OK)

    if cfg.get("verify"):
        ok, msg = verify_file(path, cfg, log=log)
        if not ok:
            # 自签名根证书没进「受信任的根证书颁发机构」时必然报
            # "terminated in a root certificate which is not trusted" —— 只提示不失败
            log(f"⚠ 签名校验未通过（自签名证书属正常现象）：{msg}\n", _LEVEL_WARN)
    return True, "签名成功"


def verify_file(path: str, cfg: dict | None = None, log=None) -> tuple[bool, str]:
    """``signtool verify /pa``；返回 ``(ok, 一行输出)``。"""
    log = log or (lambda text, level="": None)
    cfg = cfg if cfg is not None else load_config()
    signtool = find_signtool(cfg)
    if not signtool:
        return False, "找不到 signtool.exe"
    code, output = _run([signtool, "verify", "/pa", "/v", path])
    summary = next((ln.strip() for ln in output.splitlines() if ln.strip()), "")
    return code == 0, summary


# --------------------------------------------------------------------------- CLI
def _show_config() -> int:
    cfg = load_config()
    cert = pfx_path(cfg)
    print(f"配置文件      : {CONFIG_PATH}{'' if os.path.isfile(CONFIG_PATH) else '（不存在）'}")
    print(f"证书          : {cert or '（未配置）'}"
          f"{'' if not cert else '  [存在]' if os.path.isfile(cert) else '  [缺失]'}")
    print(f"密码          : {'已设置' if cfg.get('password') else '（空）'}")
    print(f"时间戳        : {cfg.get('timestamp_url') or '（未启用）'}")
    print(f"required      : {bool(cfg.get('required'))}")
    print(f"signtool      : {find_signtool(cfg) or '（找不到）'}")
    return 0


def main(argv: list[str]) -> int:
    # Windows 控制台默认是 GBK(cp936)，日志里的 ✔ / ⚠ 会直接抛 UnicodeEncodeError。
    # 构建工具走 pywebview 的日志队列没这问题，命令行单独用就会踩到。
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass

    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    if argv[0] == "--show-config":
        return _show_config()

    verify_only = argv[0] == "--verify"
    targets = argv[1:] if verify_only else argv
    if not targets:
        print("没有指定要签名的文件", file=sys.stderr)
        return 2

    cfg = load_config()
    failed = 0
    for target in targets:
        if verify_only:
            ok, msg = verify_file(target, cfg, log=lambda t, level="": print(t, end=""))
        else:
            ok, msg = sign_file(target, cfg, log=lambda t, level="": print(t, end=""))
        if not ok:
            failed += 1
            print(f"✕ {target}：{msg}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
