# -*- coding: utf-8 -*-
"""统计 html/app 下所有原生 title 悬浮提示 (排除 <title> 标签)。"""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, "html", "app")

ATTR = re.compile(r"""\btitle\s*=\s*["'][^"']*["']""")
TAG = re.compile(r"<title>[^<]*</title>")

total = 0
rows = []
for dp, _, ns in os.walk(APP):
    for n in sorted(ns):
        if not n.endswith((".html", ".js")):
            continue
        p = os.path.join(dp, n)
        s = open(p, encoding="utf-8").read()
        attr = ATTR.findall(s)
        tag = TAG.findall(s)
        if attr or tag:
            rows.append((os.path.relpath(p, APP), len(attr), len(tag)))
            total += len(attr)

print("=== title 悬浮提示统计 ===")
for rel, a, t in rows:
    extra = "  (<title> 标签 %d 个, 保留)" % t if t else ""
    print("  %-42s %3d 处%s" % (rel, a, extra))
print()
print("  合计 title= 属性:", total)
print()
print("=== index.html 样例 ===")
s = open(os.path.join(APP, "index.html"), encoding="utf-8").read()
for m in list(ATTR.finditer(s))[:14]:
    print("   ", m.group(0)[:84])
print()
print("=== js 里的动态 title ===")
for dp, _, ns in os.walk(os.path.join(APP, "js")):
    for n in sorted(ns):
        if not n.endswith(".js"):
            continue
        p = os.path.join(dp, n)
        for i, ln in enumerate(open(p, encoding="utf-8").read().split("\n"), 1):
            if re.search(r"\.title\s*=|title:\s*'|title=\"", ln) and "attr(" not in ln:
                print("  %-20s L%-4d %s" % (n, i, ln.strip()[:78]))
