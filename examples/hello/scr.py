# -*- coding: utf-8 -*-
"""最小的 WarpHook 插件：什么都不做，只在日志里说话。

学到的三件事：
1. 插件是一个 ``addons/<名字>/`` 目录，里面至少两个文件。
2. ``scr.py`` 被启动器 exec，全局里自带 ``ADDON_ARG``。
3. 打日志就用 ``print(..., flush=True)``，会出现在启动器的控制台与日志文件里。
"""

import os

ADDON_ARG = globals().get('ADDON_ARG') or {}
ADDON_NAME = ADDON_ARG.get('AddonName')
ADDON_MANAGER = ADDON_ARG.get('AddonManager')


def _log(message):
    print(f'[{ADDON_NAME}] {message}', flush=True)


def _greeting():
    """从 addon_info.json 的 settings 里读设置。

    ``settings`` 是启动器帮我们存在清单里的，用户改了会写回同一个文件，
    所以每次用的时候现读，不要缓存。
    """
    try:
        info = (ADDON_MANAGER.get_addon_info(ADDON_NAME)
                if ADDON_MANAGER is not None else None) or {}
    except Exception:  # noqa: BLE001
        info = {}
    st = info.get('settings') or {}
    return str(st.get('招呼语') or '你好，世界')


# 载入时执行一次的代码直接写在这里 —— 没有 ``main()``，也没有注册函数。
_log(_greeting())
_log(f'我拿到的东西：{sorted(k for k in ADDON_ARG)}')


def on_unload():
    """卸载时会被调用；没有要收尾的东西就什么都不用写。

    启动器在关闭、重载插件、或用户停用插件时会调它。
    """
    _log('再见')
