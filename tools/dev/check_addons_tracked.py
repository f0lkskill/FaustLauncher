#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""守住 addons/ 的白名单：除 WarpHook 外，任何插件都不许进版本库。

背景
----
仓库的 .gitignore 里写着 `addons/*`，只对 `addons/WarpHook/` 开白名单。
但 .gitignore 只影响「未被跟踪」的文件 —— 只要有一次提交用 `git add -f`
（或 `git add -f addons/`）把别的插件强塞进索引，之后它就一路跟着推送，
忽略规则再也管不住它。历史上已经发生过两次（1d2ee03、26e02db）。

用法
----
    python tools/dev/check_addons_tracked.py

退出码 0 表示干净；1 表示发现了不该入库的插件，并会打印修复命令。
"""
from __future__ import annotations

import subprocess
import sys

ALLOWED = "addons/WarpHook/"


def tracked_under(addons: str = "addons") -> list[str]:
    """返回索引里 addons/ 下的全部路径（失败时抛 RuntimeError）。"""
    try:
        out = subprocess.run(
            ["git", "ls-files", "-z", "--", addons],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ).stdout
    except FileNotFoundError as exc:  # 没有 git
        raise RuntimeError("找不到 git 命令") from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(exc.stderr.decode("utf-8", "replace").strip()) from exc
    return [p for p in out.decode("utf-8", "replace").split("\0") if p]


def main() -> int:
    try:
        files = tracked_under()
    except RuntimeError as exc:
        print(f"[addons-guard] 读取 git 索引失败: {exc}")
        return 2

    offenders = [p for p in files if not p.startswith(ALLOWED)]
    if not offenders:
        print(f"[addons-guard] OK：addons/ 下 {len(files)} 个文件全部属于 WarpHook")
        return 0

    # 按一级目录归组，方便直接照抄修复命令
    plugins = sorted({p.split("/", 2)[1] for p in offenders if p.count("/") >= 1})
    print("[addons-guard] 发现不该入库的插件内容（.gitignore 对已跟踪文件无效）：")
    for path in offenders:
        print(f"  - {path}")
    print("\n修复（本地文件会保留，只是移出索引）：")
    for name in plugins:
        print(f"  git rm -r --cached --quiet -- addons/{name}")
    print("  git commit -m \"chore: 移出误跟踪的插件目录\"")
    return 1


if __name__ == "__main__":
    sys.exit(main())
