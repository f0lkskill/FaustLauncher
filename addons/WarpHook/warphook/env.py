"""插件作用域：包内模块看不到 scr.py 被 exec 时的那套 globals。

启动器载入插件的方式是 ``exec(源码, globals)``，``ADDON_ARG`` / ``ADDON_NAME``
只存在于那份 globals 里；包里的模块是正常 import 的，读不到它们。
所以 scr.py 先调 :func:`bind` 把三样东西放进来。
"""

WARP_HOOK_VERSION = "0.5.0"

ADDON_ARG = None
ADDON_NAME = ""
ADDON_MANAGER = None


def bind(addon_name, addon_manager, addon_arg):
    global ADDON_ARG, ADDON_NAME, ADDON_MANAGER
    ADDON_NAME = str(addon_name or "")
    ADDON_MANAGER = addon_manager
    ADDON_ARG = addon_arg
