# -*- coding: utf-8 -*-
"""把 il2cpp 基准名字表生成为内嵌 Python 模块。

用法::

    python tools/build/gen_il2cpp_names.py [源 txt 路径]

默认源文件是 ``addons/全角色随机人格/Assets/runtime/il2cpp-api-names.txt``，
产物固定为 ``functions/base/il2cpp_api_names.py``。

为什么内嵌而不是读文件：插件/启动器不该依赖「某个插件目录里恰好有一份表」，
内嵌进 Python 模块后，打包出来的启动器自带这张表，任何安装都能算出映射。
"""

from __future__ import annotations

import os
import sys

HEADER = '''# -*- coding: utf-8 -*-
"""il2cpp C API 的基准名字表（234 项，顺序即游戏里的接口布局）。

游戏把 ``GameAssembly.dll`` 里这些 ``il2cpp_*`` 导出改成了混淆名，但
``UnityPlayer.dll`` 的 ``.text`` 段仍按固定顺序 ``lea`` 引用它们；把
「基准顺序」和「UnityPlayer 里 lea 的先后顺序」对齐，就能还原混淆名
（见 :mod:`functions.base.il2cpp_exports`）。

表内嵌成 Python 常量，不依赖插件目录或外部文件 —— 打包后的启动器即便
没装任何自带表的插件，也能自己算出映射。游戏更新导致布局变化时，重新
生成本文件即可（``python tools/build/gen_il2cpp_names.py``）。
"""

from __future__ import annotations

CANONICAL_NAMES = (
'''

FOOTER = ''')

__all__ = ["CANONICAL_NAMES"]
'''


def main(argv: list[str]) -> int:
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    src = argv[1] if len(argv) > 1 else os.path.join(
        root, "addons", "全角色随机人格", "Assets", "runtime", "il2cpp-api-names.txt")
    if not os.path.isfile(src):
        print(f"找不到基准表: {src}")
        return 1
    with open(src, "r", encoding="utf-8") as handle:
        names = [line.strip() for line in handle if line.strip()]
    if not names:
        print(f"基准表为空: {src}")
        return 1
    out_path = os.path.join(root, "functions", "base", "il2cpp_api_names.py")
    with open(out_path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(HEADER)
        for name in names:
            handle.write(f"    {name!r},\n")
        handle.write(FOOTER)
    print(f"已写入 {out_path}（{len(names)} 项）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
