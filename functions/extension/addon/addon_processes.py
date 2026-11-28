"""插件目录占用清理。

插件经常会拉起自己的子进程（工作台、WebView 窗口、辅助服务……），这些进程
通常把**插件目录**当成工作目录。Windows 不允许删除仍被进程当作当前目录的
文件夹：文件能删掉，最后目录却报"正在被占用"，重装因此失败。

删除/重装插件前先调用 :func:`release_addon_dir`：

1. 只盯当前启动器进程的**后代进程**（避免误杀用户自己的终端）；
2. 后代里命令行包含插件目录的（工作台脚本、``--addon`` 参数等）全部结束；
3. 映像文件就在插件目录里的进程（插件自带的 exe）也一并结束；
4. ``taskkill /T`` 结束整棵进程树，等它们真正退出后再交给删除逻辑。

这里只负责"放掉目录"，不删文件；删除和重试仍由调用方处理。
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import os
import subprocess
import time

_CREATE_NO_WINDOW = 0x08000000
_SYNCHRONIZE = 0x00100000
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_STILL_ACTIVE = 259


class _PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wt.DWORD),
        ("cntUsage", wt.DWORD),
        ("th32ProcessID", wt.DWORD),
        ("th32DefaultHeapID", ctypes.c_void_p),
        ("th32ModuleID", wt.DWORD),
        ("cntThreads", wt.DWORD),
        ("th32ParentProcessID", wt.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wt.DWORD),
        ("szExeFile", ctypes.c_wchar * 260),
    ]


def _kernel32():
    """准备一份声明好原型/返回类型的 kernel32，避免 64 位下句柄被截断。"""
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
    k32.CreateToolhelp32Snapshot.argtypes = [wt.DWORD, wt.DWORD]
    k32.Process32FirstW.argtypes = [ctypes.c_void_p, ctypes.POINTER(_PROCESSENTRY32W)]
    k32.Process32NextW.argtypes = [ctypes.c_void_p, ctypes.POINTER(_PROCESSENTRY32W)]
    k32.CloseHandle.argtypes = [ctypes.c_void_p]
    k32.OpenProcess.restype = wt.HANDLE
    k32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
    k32.TerminateProcess.argtypes = [wt.HANDLE, wt.UINT]
    k32.WaitForSingleObject.argtypes = [wt.HANDLE, wt.DWORD]
    k32.WaitForSingleObject.restype = wt.DWORD
    k32.QueryFullProcessImageNameW.argtypes = [
        wt.HANDLE, wt.DWORD, wt.LPWSTR, ctypes.POINTER(wt.DWORD)]
    k32.QueryFullProcessImageNameW.restype = wt.BOOL
    return k32


def _process_table():
    """返回 ``{pid: {'ppid': int, 'exe': str}}``；读不到时返回空表。"""
    try:
        k32 = _kernel32()
        snap = k32.CreateToolhelp32Snapshot(0x00000002, 0)
        if not snap:
            return {}
        table = {}
        try:
            entry = _PROCESSENTRY32W()
            entry.dwSize = ctypes.sizeof(entry)
            ok = k32.Process32FirstW(snap, ctypes.byref(entry))
            while ok:
                table[int(entry.th32ProcessID)] = {
                    "ppid": int(entry.th32ParentProcessID),
                    "exe": str(entry.szExeFile or ""),
                }
                ok = k32.Process32NextW(snap, ctypes.byref(entry))
        finally:
            k32.CloseHandle(snap)
        return table
    except Exception:
        return {}


def _image_path(pid):
    """读进程的映像文件路径；句柄打不开或查询失败时返回空串。"""
    try:
        k32 = _kernel32()
        handle = k32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not handle:
            return ""
        try:
            size = wt.DWORD(1024)
            buf = ctypes.create_unicode_buffer(1024)
            if k32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                return str(buf.value or "")
        finally:
            k32.CloseHandle(handle)
    except Exception:
        pass
    return ""


def _descendants(root_pid, table):
    """沿父子关系算出 ``root_pid`` 的所有后代进程号（含多层子进程）。

    Args:
        root_pid: 根进程号，通常是当前启动器进程。
        table: :func:`_process_table` 返回的进程表。

    Returns:
        set[int]: 后代 PID 集合，不含根进程自己。
    """
    children = {}
    for pid, info in table.items():
        children.setdefault(info.get("ppid"), []).append(pid)
    out, stack = set(), [int(root_pid)]
    while stack:
        parent = stack.pop()
        for child in children.get(parent, ()):
            if child not in out and child != int(root_pid):
                out.add(child)
                stack.append(child)
    return out


def _command_line_pids(root):
    """命令行里包含 ``root`` 的进程号（PowerShell CIM 查询）。

    插件拉起的 PowerShell / Python / WebView 进程，命令行通常会带工作台脚本
    路径或 ``--addon <插件目录>``，这是识别它们最可靠的方式。

    Args:
        root: 插件目录的绝对路径，作为命令行匹配的关键字。

    Returns:
        set[int]: 命令行引用该目录的进程号；查询失败时为空集合。
    """
    if os.name != "nt":
        return set()
    script = (
        "$ErrorActionPreference='SilentlyContinue';"
        "$root=$env:FAUST_ADDON_RELEASE_DIR;"
        "if(-not $root){exit 0};"
        "Get-CimInstance Win32_Process |"
        "Where-Object { $_.CommandLine -and "
        "$_.CommandLine.IndexOf($root,[StringComparison]::OrdinalIgnoreCase) -ge 0 } |"
        "ForEach-Object { [int]$_.ProcessId }"
    )
    try:
        env = dict(os.environ)
        env["FAUST_ADDON_RELEASE_DIR"] = root
        proc = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=12, env=env, creationflags=_CREATE_NO_WINDOW,
        )
        return {int(line.strip()) for line in (proc.stdout or "").splitlines()
                if line.strip().isdigit()}
    except Exception:
        return set()


def _wait_gone(pid, timeout=3.0):
    """等一个进程真正退出；句柄一有信号就说明内核已回收它的资源。

    Args:
        pid: 被等待的进程号。
        timeout: 最长等待秒数。

    Returns:
        bool: 进程已退出（或句柄打不开）为 True，超时仍存活为 False。
    """
    try:
        k32 = _kernel32()
        handle = k32.OpenProcess(_SYNCHRONIZE, False, int(pid))
        if not handle:
            return True
        try:
            return k32.WaitForSingleObject(handle, int(timeout * 1000)) == 0
        finally:
            k32.CloseHandle(handle)
    except Exception:
        return False


def _terminate_tree(pid):
    """结束进程及其子进程（先 taskkill /T，失败再直接 TerminateProcess）。

    Args:
        pid: 要结束的根进程号。

    Returns:
        bool: 等待后该进程是否已不存在。
    """
    try:
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(int(pid))],
            capture_output=True, creationflags=_CREATE_NO_WINDOW, timeout=12,
        )
    except Exception:
        pass
    if _wait_gone(pid, 0.8):
        return True
    try:
        k32 = _kernel32()
        handle = k32.OpenProcess(0x0001, False, int(pid))  # PROCESS_TERMINATE
        if handle:
            try:
                k32.TerminateProcess(handle, 1)
            finally:
                k32.CloseHandle(handle)
    except Exception:
        pass
    return _wait_gone(pid, 2.0)


def _under(path, root):
    """判断 path 是否位于 root 目录内（含 root 本身），统一大小写与分隔符。

    Args:
        path: 待判断的路径。
        root: 目录边界。

    Returns:
        bool: path 等于 root 或以 ``root + 分隔符`` 开头时为 True。
    """
    try:
        path = os.path.normcase(os.path.abspath(path))
        root = os.path.normcase(os.path.abspath(root)).rstrip("\\/")
        return path == root or path.startswith(root + os.sep)
    except Exception:
        return False


def release_addon_dir(addon_dir):
    """结束仍占用 ``addon_dir`` 的插件子进程，返回被结束的 PID 列表。

    只处理当前启动器进程的后代、映像文件位于插件目录内的进程，以及命令行里
    明确带插件目录的常见脚本宿主（覆盖上一次启动遗留的孤儿工作台进程）；启动器
    自己、游戏进程（``LimbusCompany.exe``）永远不会被结束。

    Args:
        addon_dir: 插件目录的绝对路径。

    Returns:
        list[int]: 成功结束的进程号列表；目录不存在或进程表读不到时为空。
    """
    root = os.path.abspath(str(addon_dir or ""))
    if not root or not os.path.isdir(root):
        return []
    own_pid = os.getpid()
    table = _process_table()
    if not table:
        return []

    helper_exes = {"python.exe", "pythonw.exe", "powershell.exe", "pwsh.exe",
                   "cmd.exe", "node.exe", "msedgewebview2.exe"}
    candidates = set()
    descendants = _descendants(own_pid, table)
    for pid in descendants:
        info = table.get(pid) or {}
        if str(info.get("exe") or "").lower() == "limbuscompany.exe":
            continue
        if _under(_image_path(pid), root):
            candidates.add(pid)
    # 命令行引用了插件目录：后代全收；非后代只收常见脚本宿主，避免误杀
    # 用户自己的编辑器 / 终端（它们一般只在工作目录里，命令行不带该路径）。
    for pid in _command_line_pids(root):
        if pid == own_pid:
            continue
        info = table.get(pid) or {}
        exe = str(info.get("exe") or "").lower()
        if exe == "limbuscompany.exe":
            continue
        if pid in descendants or exe in helper_exes:
            candidates.add(pid)

    killed = []
    for pid in sorted(candidates):
        info = table.get(pid) or {}
        if str(info.get("exe") or "").lower() == "limbuscompany.exe":
            continue
        if _terminate_tree(pid):
            killed.append(pid)
    if killed:
        # 给子进程树一点收尾时间，Windows 的目录句柄不是立刻释放的。
        time.sleep(0.35)
    return killed
