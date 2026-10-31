# -*- coding: utf-8 -*-
"""弹一句：让游戏自己弹一个原版系统弹窗。

这个插件只有三行是有用的：

    game = _W.game
    game.popup('来自插件的问候')

剩下的都是读设置、打日志、收尾。``game.popup()`` 自己会等游戏启动、
自己会注入宿主 DLL、自己会等游戏主循环就绪 —— 插件不需要知道这些。
"""

from typing import cast

if False:  # 仅供类型检查器阅读，运行时不会执行
    from warphook.base import WarpNamespace

ADDON_ARG = globals().get('ADDON_ARG') or {}
ADDON_NAME = ADDON_ARG.get('AddonName')
ADDON_MANAGER = ADDON_ARG.get('AddonManager')
_NS = ADDON_ARG.get('Namespaces')

# ADDON_ARG 里的 Namespaces 就是 WarpHook 暴露给插件的入口，
# game 是「面对游戏」的那一区。
_W = cast("WarpNamespace", _NS.space('warp') if _NS is not None else None)
game = _W.game


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


def _say(text=None):
    text = text or _settings()[0]
    result = game.popup(text)
    _log(f'弹窗「{text}」→ {result}')
    return result


# 托盘菜单两项：手动弹一次、看宿主状态。
# register_menu 是给 Service 用的，这里用最简形式——直接进 on_unload 之外都能调。
game.start(menu=(
    ('弹一句', lambda: _say()),
))

if _settings()[1]:
    # 放到后台线程里弹，免得卡住启动器的主流程。
    import threading

    threading.Thread(target=_say, daemon=True).start()


def on_unload():
    game.close()
