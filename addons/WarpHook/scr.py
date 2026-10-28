"""WarpHook：插件底层能力（il2cpp 导出 / 注入 / 共享内存 / 共享宿主 / 日志）。

真正的实现在同目录的 ``warphook/`` 包里；这个文件只是入口：

1. 把自己所在目录放进 ``sys.path``，让包能被 import；
2. 接住启动器给的 ``ADDON_ARG``，交给 :func:`warphook.bind`
   （包内模块是正常 import 的，读不到 exec 的那份 globals）；
3. 把能力注册成 ``warp`` 命名空间，别的插件按名字取用。

插件不需要自己的 C 代码：等游戏、注入、挂钩、弹窗、杀进程全由同目录的
``warp_host.dll`` 完成，本包只负责往那块共享内存里写配置。
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

# 插件重载时启动器会重新 exec 本文件。warphook 包若还留在 sys.modules 里，
# 子模块不会重新执行、模块级单例还是上一份的，重载就变成了空操作 ——
# 所以先把它整个摘掉，让下面的 import 重新走一遍。
for _stale in [n for n in list(sys.modules)
               if n == "warphook" or n.startswith("warphook.")]:
    del sys.modules[_stale]

import warphook  # noqa: E402

warphook.bind(
    addon_name=ADDON_ARG['AddonName'],            # type: ignore[name-defined]
    addon_manager=ADDON_ARG.get('AddonManager'),  # type: ignore[name-defined]
    addon_arg=ADDON_ARG,                          # type: ignore[name-defined]
)

#: 命名空间是否注册成功；失败通常意味着启动器版本太旧（没有 Namespaces 容器）。
REGISTERED = warphook.register()

#: 插件卸载入口，启动器在卸载时按名字调用。
on_unload = warphook.on_unload
