"""必需插件：声明 + 启动检查 + 自动补齐。

有些启动器功能不是「用户可选的插件」，而是「必须有一个插件在底下撑着」。
例如成就采集：成就的定义和判定留在启动器里，但真正挂钩子、读内存、
把事件送上来的活儿，全在 ``WarpHook`` 这个插件里。

这类关系不应该写死在启动器的业务代码里，也不该让用户在界面上手动勾。
所以这里是**声明式**的：

    REQUIRED_ADDONS = {
        'achievement': {'addon': 'WarpHook', 'reason': '...'},
    }

模块自己说「我需要 WarpHook」，启动器启动时统一检查一遍。
缺了就按普通插件的下载链路去云端拉（WarpHook 是要热更新维护的，
所以它必须能从云端取到新版本）；云端暂时没有条目也不阻塞启动，
只是把原因记下来，对应功能自然降级。

这里刻意不 import 任何 GUI / 下载实现：
下载函数由调用方通过 ``installer`` 注入，避免 extension 层反向依赖 app 层。
"""
from __future__ import annotations

import json
import os
from typing import Any, Callable, Dict, List, Optional

#: 声明表。键是「哪个模块需要」，值是需求描述。
#: 新增一个必需插件只需要往这里加一行，不用改启动流程。
REQUIRED_ADDONS: Dict[str, Dict[str, Any]] = {
    'achievement': {
        'addon': 'WarpHook',
        'reason': '成就需要 WarpHook 提供钩子引擎与事件总线',
        'min_version': '',
    },
}

#: 插件目录名。启动器允许通过参数换目录，这里只作为默认值。
DEFAULT_ADDONS_DIR = 'addons'


def addon_dir(name: str, root: Optional[str] = None) -> str:
    """插件目录的绝对（相对 cwd）路径。"""
    return os.path.join(root or DEFAULT_ADDONS_DIR, str(name))


def read_info(name: str, root: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """读插件的 addon_info.json；目录或文件不存在返回 None。"""
    path = os.path.join(addon_dir(name, root), 'addon_info.json')
    try:
        with open(path, 'r', encoding='utf-8') as fp:
            data = json.load(fp)
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def installed_version(name: str, root: Optional[str] = None) -> Optional[str]:
    """已安装插件的版本号（读不到就返回 None）。"""
    info = read_info(name, root)
    if not info:
        return None
    version = info.get('version')
    return str(version).strip() if version else ''


def _version_tuple(text: str) -> tuple:
    """把 '1.2.3' 变成 (1, 2, 3)；非法片段按 0 处理。"""
    parts: List[int] = []
    for chunk in str(text or '').replace('-', '.').split('.'):
        digits = ''.join(ch for ch in chunk if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def version_at_least(current: str, minimum: str) -> bool:
    """current >= minimum。minimum 为空视为无要求。"""
    if not str(minimum or '').strip():
        return True
    return _version_tuple(current) >= _version_tuple(minimum)


def check(key: str, root: Optional[str] = None) -> Dict[str, Any]:
    """检查一个声明的满足情况，不产生任何副作用。"""
    spec = REQUIRED_ADDONS.get(key) or {}
    addon = str(spec.get('addon') or '').strip()
    minimum = str(spec.get('min_version') or '').strip()
    version = installed_version(addon, root) if addon else None
    present = version is not None
    return {
        'key': key,
        'addon': addon,
        'reason': str(spec.get('reason') or ''),
        'min_version': minimum,
        'present': present,
        'version': version or '',
        'satisfied': present and version_at_least(version or '', minimum),
    }


def check_all(root: Optional[str] = None) -> List[Dict[str, Any]]:
    """检查全部声明，按注册顺序返回。"""
    return [check(key, root=root) for key in REQUIRED_ADDONS]


def ensure(
    key: str,
    installer: Optional[Callable[[str], bool]] = None,
    root: Optional[str] = None,
    log: Callable[[str], None] = print,
) -> Dict[str, Any]:
    """确保一个声明被满足；缺失时调 installer 去下载。

    installer 收到插件名，返回 True 表示安装成功。
    ``root`` 是插件根目录，测试里可以指到临时目录。
    """
    state = check(key, root=root)
    if state['satisfied']:
        state.update(ok=True, status='present')
        return state
    if not state['addon']:
        state.update(ok=False, status='no-declaration')
        return state
    if installer is None:
        state.update(ok=False, status='no-installer')
        log(f"缺少必需插件 {state['addon']}（{state['reason']}），但没有可用的下载器")
        return state
    try:
        log(f"缺少必需插件 {state['addon']}（{state['reason']}），开始自动安装")
        installed = bool(installer(state['addon']))
    except Exception as exc:  # 下载链路出什么错都不该拖垮启动
        state.update(ok=False, status='error', error=str(exc))
        log(f"自动安装 {state['addon']} 失败: {exc}")
        return state
    after = check(key, root=root)
    if installed and after['satisfied']:
        after.update(ok=True, status='installed')
        log(f"必需插件 {state['addon']} 安装完成")
        return after
    after.update(ok=False, status='install-failed')
    log(f"必需插件 {state['addon']} 安装后仍不可用（可能云端没有条目）")
    return after


def ensure_all(
    installer: Optional[Callable[[str], bool]] = None,
    root: Optional[str] = None,
    log: Callable[[str], None] = print,
) -> Dict[str, Dict[str, Any]]:
    """把全部声明过一遍，返回 {key: 结果}。"""
    result: Dict[str, Dict[str, Any]] = {}
    for key in REQUIRED_ADDONS:
        result[key] = ensure(key, installer=installer, root=root, log=log)
    return result


def missing(root: Optional[str] = None) -> List[str]:
    """列出当前还缺的插件名（去重，保持注册顺序）。"""
    names: List[str] = []
    for state in check_all(root=root):
        if not state['satisfied'] and state['addon'] and state['addon'] not in names:
            names.append(state['addon'])
    return names
