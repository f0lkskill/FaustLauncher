# -*- coding: utf-8 -*-
"""弹一句：让游戏自己弹一个原版系统弹窗。

这一篇比 hello 多出来的东西只有一件：**我们和游戏之间隔着一个进程**。
插件跑在启动器里，游戏是另一个进程，所以要让游戏做事，必须先把宿主的
``warp_host.dll`` 注入进去，然后通过共享内存给它下命令。

这些事全在 ``warp.plugin.Service`` 里，插件只需要交两样东西：
``sync``（怎么把设置写进去）和 ``menu``（托盘里点哪一项干什么）。
"""

import threading
import time
from typing import cast

if False:  # 只为让类型检查器知道 WarpNamespace 长什么样，运行时不会执行
    from warphook.base import WarpNamespace

ADDON_ARG = globals().get('ADDON_ARG') or {}
ADDON_NAME = ADDON_ARG.get('AddonName')
ADDON_MANAGER = ADDON_ARG.get('AddonManager')
_NS = ADDON_ARG.get('Namespaces')

# ADDON_ARG 里的 Namespaces 就是 WarpHook 暴露给插件的入口。
_W = cast("WarpNamespace", _NS.space('warp') if _NS is not None else None)


def _log(message):
    print(f'[{ADDON_NAME}] {message}', flush=True)


def _settings():
    """返回 (弹窗内容, 是否自动弹一次)，每次都现读，用户改了立刻生效。"""
    try:
        info = (ADDON_MANAGER.get_addon_info(ADDON_NAME)
                if ADDON_MANAGER is not None else None) or {}
    except Exception:  # noqa: BLE001
        info = {}
    st = info.get('settings') or {}
    return (str(st.get('弹窗内容') or '来自插件的问候'),
            bool(st.get('自动弹一次', True)))


def _push():
    """把当前设置写进共享内存 —— Service 在注入前、注入后各调一次。

    这个插件没有要钩的方法，所以 ``hooks`` 是空表；``push()`` 仍然要做，
    因为它同时负责把「本插件启用了哪些东西」告诉 DLL。
    """
    host = service.host()
    host.configure(hooks=[], texts=[])
    return host.push(True) not in ('共享内存不可用',)


def _say(text=None):
    """让游戏弹一句。"""
    text = text or _settings()[0]
    result = service.host().popup(text)
    _log(f'弹窗「{text}」→ {result}')
    return result


def _auto_once():
    """等宿主挂上之后自动弹一次，然后线程退出。

    为什么要等：插件载入时游戏可能还没起来。``service.status()`` 里的
    ``hooked`` 变成 True，就说明 DLL 已经在游戏进程里跑起来了。
    """
    for _ in range(1200):  # 最多等两分钟
        try:
            st = service.status()
        except Exception:  # noqa: BLE001
            st = {}
        if st.get('hooked'):
            time.sleep(1.0)  # 给游戏主循环一点时间，别卡在加载画面里
            _say()
            return
        time.sleep(0.1)
    _log('等了 2 分钟没等到宿主挂上，放弃自动弹窗')


service = _W.plugin.Service(
    addon_name=ADDON_NAME,
    name=ADDON_NAME,
    sync=_push,
    auto=lambda: True,          # True = 插件启用着的时候，游戏一起来就自动注入
    menu=(
        ('弹一句', lambda: _say()),
        ('注入并弹一句', lambda: (service.inject_now(wait=True), _say())),
    ),
)
service.start()

if _settings()[1]:
    threading.Thread(target=_auto_once, daemon=True).start()


def on_unload():
    """卸载时收尾：Service 会停掉自己的线程、断开映射。"""
    return service.stop()
