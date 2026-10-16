# -*- coding: utf-8 -*-
"""把 spec 里的 UPX 压缩关掉（幂等）。

UPX 加壳是 PyInstaller 产物被杀软启发式误报的经典诱因之一；本仓库历史上也没有
把 upx 放进依赖，实际打包时它多半根本没生效，但这个开关留在 spec 里既容易误导，
也会被误报模型计入。这里显式关掉，并把理由写进 spec 注释。
"""

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
SPEC = os.path.join(ROOT, "tools", "build", "FaustLauncher.spec")

COMMENT = "# UPX 加壳会显著抬高杀软误报率（本仓库并未依赖 upx，这里显式关掉）\n"
MARK = "# UPX 加壳会显著抬高杀软误报率"


def main() -> int:
    src = open(SPEC, encoding="utf-8").read()
    if MARK in src:
        print("spec 已关闭 UPX，跳过")
        return 0

    count = src.count("upx=True,")
    if count == 0:
        print("spec 里没有 upx=True,，无需改动")
        return 0

    src = src.replace("upx=True,", COMMENT + "    upx=False,")
    src = src.replace("    upx_exclude=[],\n", "")

    with open(SPEC, "w", encoding="utf-8", newline="") as fh:
        fh.write(src)
    print("spec 已关闭 UPX（替换 %d 处）" % count)
    return 0


if __name__ == "__main__":
    sys.exit(main())
