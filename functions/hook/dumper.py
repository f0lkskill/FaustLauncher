"""Il2CppDumper 的获取与执行。

Il2CppDumper 是纯 .NET 程序（Windows 需要 .NET 6/8 运行时，或下载 self-contained
的 win-x64 包）。它做的事正是我们最需要的那件：把 ``（GameAssembly.dll,
global-metadata.dat）`` 还原成带偏移注释的 ``dump.cs``。

下载策略：GitHub Release 的资产名优先选 self-contained（``...win-x64...``），
其次 ``...net8...``，都没有才随便挑一个 zip。下载走项目里既有的 gh-proxy
代理列表（``functions.base.common.github_release``），国内线路更稳。

执行策略：**必须**覆盖 ``RequireAnyKey=false``（否则它 dump 完会等按键，
无人值守时会挂住），所以我们自己写一份 config.json 放进工具目录。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import zipfile
from dataclasses import dataclass

from . import paths as paths_mod

DUMPER_REPO = ("Perfare", "Il2CppDumper")
DUMPER_EXE = "Il2CppDumper.exe"
# 我们需要的输出项：字段偏移 + 方法偏移 + TypeDefIndex（DummyDll/Struct 关掉，省时间与体积）
DUMPER_CONFIG = {
    "DumpMethod": True,
    "DumpField": True,
    "DumpProperty": False,
    "DumpAttribute": False,
    "DumpFieldOffset": True,
    "DumpMethodOffset": True,
    "DumpTypeDefIndex": True,
    "GenerateDummyDll": False,
    "GenerateStruct": False,
    "DummyDllAddToken": False,
    "RequireAnyKey": False,
    "ForceIl2CppVersion": False,
    "ForceVersion": 16,
    "ForceDump": False,
    "NoRedirectedPointer": False,
}
# 常见的手动放置位置（用户自己下过一份时直接复用，不必重新下载）
_EXTRA_SEARCH = (
    os.path.join(os.path.expanduser("~"), "Desktop", "win-x64-net8"),
    os.path.join(os.path.expanduser("~"), "Desktop", "Il2CppDumper"),
    os.path.join(os.path.expanduser("~"), "Downloads", "Il2CppDumper"),
    r"D:\tools\Il2CppDumper",
    r"C:\tools\Il2CppDumper",
)


@dataclass
class DumpResult:
    ok: bool
    dump_cs: str = ""
    script_json: str = ""
    out_dir: str = ""
    elapsed: float = 0.0
    stdout_tail: str = ""
    detail: str = ""


def tool_dir() -> str:
    return paths_mod.cache_path("tools", "il2cppdumper")


def find_dumper(explicit: str = "") -> str:
    """找一个可用的 Il2CppDumper.exe；找不到返回空串。"""
    candidates = []
    if explicit:
        candidates.append(explicit)
    candidates.append(os.path.join(tool_dir(), DUMPER_EXE))
    for folder in _EXTRA_SEARCH:
        candidates.append(os.path.join(folder, DUMPER_EXE))
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    return ""


def write_config(folder: str) -> str:
    """写入我们的 config.json（覆盖，确保 RequireAnyKey=false）。"""
    path = os.path.join(folder, "config.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(DUMPER_CONFIG, fh, ensure_ascii=False, indent=2)
    return path


def dumper_version(dumper_exe: str) -> str:
    """尽力读出工具版本（deps.json / 同目录的 dll 元数据）。"""
    folder = os.path.dirname(dumper_exe)
    deps = os.path.join(folder, "Il2CppDumper.deps.json")
    try:
        with open(deps, "r", encoding="utf-8", errors="replace") as fh:
            data = json.load(fh)
        return str(data.get("runtimeTarget", {}).get("name") or "") or "unknown"
    except Exception:
        return "unknown"


# --------------------------------------------------------------------------- 下载


def _download(url: str, dest: str, proxies=(), on_log=None) -> bool:
    """下载文件（直连失败时依次尝试代理前缀）。"""
    log = on_log or (lambda _m: None)
    import requests

    attempts = [url] + [p.rstrip("/") + "/" + url for p in (proxies or ())]
    for index, target in enumerate(attempts):
        try:
            log(f"[dumper] 下载{'（直连）' if index == 0 else f'（代理 {index}）'}: {target}")
            with requests.get(target, stream=True, timeout=(20, 120),
                               headers={"User-Agent": "FaustLauncher-hook-index/1.0"}) as resp:
                resp.raise_for_status()
                total = int(resp.headers.get("content-length") or 0)
                done = 0
                with open(dest, "wb") as fh:
                    for chunk in resp.iter_content(1 << 16):
                        if not chunk:
                            continue
                        fh.write(chunk)
                        done += len(chunk)
                log(f"[dumper] 下载完成: {done} 字节"
                    + (f" / 预期 {total}" if total else ""))
                if total and done < total:
                    log("[dumper] 警告：下载长度小于预期，可能被中断")
                return True
        except Exception as exc:  # noqa: BLE001
            log(f"[dumper] 下载失败: {type(exc).__name__}: {exc}")
    return False


def download_dumper(on_log=None) -> str:
    """从 GitHub Release 下载 Il2CppDumper 到工具目录；成功返回 exe 路径。"""
    log = on_log or (lambda _m: None)
    folder = tool_dir()
    os.makedirs(folder, exist_ok=True)
    try:
        from functions.base.common.github_release import GitHubReleaseFetcher
        fetcher = GitHubReleaseFetcher(use_proxy=True, ignore_ssl=True)
        release = fetcher.get_latest_release(*DUMPER_REPO)
    except Exception as exc:  # noqa: BLE001
        log(f"[dumper] 查询 GitHub Release 失败: {exc}")
        return ""
    if not release:
        log("[dumper] 未能获取 Il2CppDumper 的 Release 信息")
        return ""
    log(f"[dumper] 最新版本: {release.tag_name}")
    assets = [a for a in release.assets if a.name.lower().endswith(".zip")]
    if not assets:
        log("[dumper] Release 里没有 zip 资产")
        return ""

    def rank(asset) -> tuple:
        name = asset.name.lower()
        return (
            0 if "win-x64" in name else (1 if "net8" in name else (2 if "win" in name else 3)),
            -asset.size,
        )

    asset = sorted(assets, key=rank)[0]
    proxies = list(getattr(asset.proxys, "get_proxies", lambda: [])())
    zip_path = os.path.join(paths_mod.cache_path("tools"), asset.name)
    if not _download(asset.download_url, zip_path, proxies, on_log=log):
        return ""
    try:
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(folder)
        log(f"[dumper] 已解压到 {folder}")
    except Exception as exc:  # noqa: BLE001
        log(f"[dumper] 解压失败: {exc}")
        return ""
    exe = os.path.join(folder, DUMPER_EXE)
    if not os.path.isfile(exe):
        # 有些包外面套了一层目录
        for root, _dirs, files in os.walk(folder):
            if DUMPER_EXE in files:
                exe = os.path.join(root, DUMPER_EXE)
                break
    return exe if os.path.isfile(exe) else ""


def ensure_dumper(on_log=None, allow_download: bool = True, explicit: str = "") -> str:
    """确保有可用的 Il2CppDumper：本地 → 常见位置 → 下载。"""
    log = on_log or (lambda _m: None)
    found = find_dumper(explicit)
    if found:
        log(f"[dumper] 使用已存在的 Il2CppDumper: {found}")
    elif allow_download:
        log("[dumper] 本地没有 Il2CppDumper，尝试自动下载...")
        found = download_dumper(on_log=log)
    if not found:
        return ""
    folder = os.path.dirname(found)
    write_config(folder)
    return found


# --------------------------------------------------------------------------- 执行


def run_dumper(dumper_exe: str, gameassembly: str, metadata: str, out_dir: str,
               on_log=None, timeout: float = 2400.0) -> DumpResult:
    """执行 Il2CppDumper（阻塞），返回产物路径。

    注意第三个参数是**输出目录**：给它一个真实路径，别加引号（Il2CppDumper 不会
    去掉首尾引号，会当成相对目录写到工具目录里去）。
    """
    log = on_log or (lambda _m: None)
    if not os.path.isfile(dumper_exe):
        return DumpResult(False, detail=f"Il2CppDumper 不存在: {dumper_exe}")
    for path, label in ((gameassembly, "GameAssembly.dll"), (metadata, "global-metadata.dat")):
        if not os.path.isfile(path):
            return DumpResult(False, detail=f"{label} 不存在: {path}")
    out_dir = os.path.abspath(out_dir)
    os.makedirs(out_dir, exist_ok=True)
    folder = os.path.dirname(dumper_exe)
    write_config(folder)
    cmd = [dumper_exe, os.path.abspath(gameassembly), os.path.abspath(metadata), out_dir]
    log(f"[dumper] 执行: {' '.join(cmd)}")
    started = time.time()
    try:
        proc = subprocess.run(
            cmd, cwd=folder, capture_output=True, timeout=timeout,
            creationflags=0x08000000,          # CREATE_NO_WINDOW：不弹控制台
        )
    except subprocess.TimeoutExpired:
        return DumpResult(False, elapsed=time.time() - started,
                          detail=f"执行超时（>{timeout:.0f}s）")
    except Exception as exc:  # noqa: BLE001
        return DumpResult(False, elapsed=time.time() - started, detail=f"执行失败: {exc}")
    elapsed = time.time() - started
    stdout = _decode(proc.stdout)
    stderr = _decode(proc.stderr)
    tail = (stdout.strip().splitlines() or [""])[-6:]
    log(f"[dumper] 耗时 {elapsed:.1f}s，返回码 {proc.returncode}；输出尾部: {' | '.join(tail)}")
    if stderr.strip():
        log(f"[dumper] stderr: {stderr.strip()[:400]}")

    def locate(name: str) -> str:
        for folder_ in (out_dir, os.path.dirname(dumper_exe), os.getcwd()):
            path = os.path.join(folder_, name)
            if os.path.isfile(path):
                return path
        return ""

    dump_cs = locate("dump.cs")
    script_json = locate("script.json")
    combined = stdout + "\n" + stderr
    if not dump_cs:
        return DumpResult(False, out_dir=out_dir, elapsed=elapsed,
                          stdout_tail=combined[-1200:],
                          detail="没有生成 dump.cs（元数据/版本可能不匹配）")
    detail = "dump.cs 已生成"
    if "ERROR" in combined.upper() or "not valid" in combined.lower():
        detail += f"；但输出里有错误提示: {_first_error(combined)}"
    return DumpResult(True, dump_cs=dump_cs, script_json=script_json, out_dir=out_dir,
                      elapsed=elapsed, stdout_tail=combined[-1200:], detail=detail)


def _decode(raw) -> str:
    if not raw:
        return ""
    for encoding in ("utf-8", "gbk", "mbcs"):
        try:
            return raw.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


def _first_error(text: str) -> str:
    for line in text.splitlines():
        if "error" in line.lower():
            return line.strip()[:200]
    return ""


def cleanup(out_dir: str, keep_dump_cs: bool = True) -> None:
    """清理 dump 产物（默认保留 dump.cs）。"""
    if not os.path.isdir(out_dir):
        return
    for name in os.listdir(out_dir):
        if keep_dump_cs and name == "dump.cs":
            continue
        path = os.path.join(out_dir, name)
        try:
            shutil.rmtree(path) if os.path.isdir(path) else os.remove(path)
        except OSError:
            pass
