"""生成 warp_thunks.inc —— 钩子 thunk 表（argc 0..9 × WARP_MAX_HOOKS 槽）。

每个 thunk 必须把自己的**槽号**硬编码进函数体（``g_slots[n].hook_index``），
preprocessor 无法在 token 拼接里算下标，所以这张表只能逐条展开。槽数现在
是 128，手写着实难受，改成脚本生成：改完 ``warp_layout.h`` 的
``WARP_MAX_HOOKS`` 后重跑一次即可。

用法::

    python addons/WarpHook/tools/gen_thunks.py
"""

from __future__ import annotations

import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
ADDON = os.path.dirname(HERE)
SRC = os.path.join(ADDON, "src")
LAYOUT_H = os.path.join(SRC, "warp_layout.h")
OUT = os.path.join(SRC, "warp_thunks.inc")

ARGC_COUNT = 10          # warp_layout.h 里 thunk 支持的最大参数个数 + 1
DEF_PER_LINE = 4         # 每个 thunk 定义占 4 列
SEL_PER_LINE = 4         # 指针数组每行 4 个

HEADER = """\
/* warp_thunks.inc —— 由 tools/gen_thunks.py 生成，请勿手改。
 *
 * 钩子 thunk 表：参数个数 0..{argc_max} × 槽 0..{last_slot}，每个 thunk 把
 * 自己的槽号硬编码进函数体（命中时靠它找 g_slots[n] 的配置），因此这张表
 * 只能定长展开，没法用宏算下标。
 *
 * 改了 warp_layout.h 的 WARP_MAX_HOOKS 之后重跑：
 *     python addons/WarpHook/tools/gen_thunks.py
 */
"""


def max_hooks() -> int:
    """从 warp_layout.h 读 WARP_MAX_HOOKS。"""
    with open(LAYOUT_H, "r", encoding="utf-8") as fh:
        text = fh.read()
    match = re.search(r"^#define\s+WARP_MAX_HOOKS\s+(\d+)", text, re.M)
    if not match:
        raise SystemExit("warp_layout.h 里找不到 WARP_MAX_HOOKS")
    return int(match.group(1))


def thunk_defs(count: int) -> list[str]:
    """argc 0..9 的 thunk 定义区。"""
    lines = []
    for argc in range(ARGC_COUNT):
        lines.append(f"/* ---- 参数个数 {argc} ---- */")
        for start in range(0, count, DEF_PER_LINE):
            row = " ".join(f"WARP_THUNK_{argc}({i})"
                           for i in range(start, min(start + DEF_PER_LINE, count)))
            lines.append(row)
        lines.append("")
    return lines


def thunk_tables(count: int) -> list[str]:
    """WARP_SEL_* 别名与 g_thunks0..9 指针数组。"""
    lines = []
    for argc in range(ARGC_COUNT):
        lines.append(f"#define WARP_SEL_{argc}(n) warp_thunk{argc}_##n")
    lines.append("")
    for argc in range(ARGC_COUNT):
        lines.append(f"void *const g_thunks{argc}[WARP_MAX_HOOKS] = {{")
        for start in range(0, count, SEL_PER_LINE):
            row = " ".join(f"WARP_SEL_{argc}({i}),"
                           for i in range(start, min(start + SEL_PER_LINE, count)))
            lines.append("    " + row)
        lines.append("};")
    return lines


def main() -> None:
    count = max_hooks()
    body = [HEADER.format(argc_max=ARGC_COUNT - 1, last_slot=count - 1)]
    body.extend(thunk_defs(count))
    body.extend(thunk_tables(count))
    text = "\n".join(body).rstrip() + "\n"
    with open(OUT, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    print(f"已生成 {OUT}（{count} 槽 × {ARGC_COUNT} 种参数个数）")


if __name__ == "__main__":
    main()
