# -*- coding: utf-8 -*-
"""删除所有浏览器原生 title 悬浮提示 (web 工具提示)。

范围:
  · HTML/JS 字符串里的 title="..." 属性
  · JS 里对 DOM 元素的 element.title = ... 赋值
保留:
  · <title> 页面标题标签
  · d.title / data.title 这类"数据字段" (不是 DOM 属性)
"""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, "html", "app")

# HTML 属性形式: 前置空白 + title="..."  (不会命中 d.title / <title>)
ATTR = re.compile(r"""\s+title\s*=\s*"[^"]*\"""")
# JS 字符串里拼接的属性: ' title="..."'  同样被上面的规则覆盖

# JS 赋值形式:  xxx.title = ...;   (只针对 DOM 元素; 数据字段是 d.title 读取而非赋值)
ASSIGN = re.compile(r"(?m)^[ \t]*[\w.$\[\]'\"()-]+\.title\s*=[^;\n]*;[ \t]*\n")

changed = []
total_attr = total_assign = 0

for dp, _, ns in os.walk(APP):
    for n in sorted(ns):
        if not n.endswith((".html", ".js")):
            continue
        p = os.path.join(dp, n)
        s = open(p, encoding="utf-8").read()
        before = s

        s, a = ATTR.subn("", s)
        s, b = ASSIGN.subn("", s)

        if s != before:
            open(p, "w", encoding="utf-8", newline="").write(s)
            rel = os.path.relpath(p, APP)
            changed.append((rel, a, b))
            total_attr += a
            total_assign += b

print("=== 已清理 ===")
for rel, a, b in changed:
    print("  %-42s 属性 %2d 处, 赋值 %d 处" % (rel, a, b))
print()
print("  合计: 属性 %d 处, 赋值 %d 处" % (total_attr, total_assign))

# ---------- 校验 ----------
print()
print("=== 复查 (应只剩 <title> 标签与数据字段) ===")
left_attr = []
for dp, _, ns in os.walk(APP):
    for n in sorted(ns):
        if not n.endswith((".html", ".js")):
            continue
        p = os.path.join(dp, n)
        s = open(p, encoding="utf-8").read()
        for m in ATTR.finditer(s):
            left_attr.append((os.path.relpath(p, APP), m.group(0)[:50]))
if left_attr:
    for rel, t in left_attr:
        print("  残留: %-30s %s" % (rel, t))
else:
    print("  无残留 title= 属性")

left_assign = []
for dp, _, ns in os.walk(APP):
    for n in sorted(ns):
        if not n.endswith(".js"):
            continue
        p = os.path.join(dp, n)
        for i, ln in enumerate(open(p, encoding="utf-8").read().split("\n"), 1):
            if re.search(r"\b[\w$]+\.title\s*=", ln):
                left_assign.append((os.path.relpath(p, APP), i, ln.strip()[:60]))
if left_assign:
    for rel, i, t in left_assign:
        print("  残留赋值: %-24s L%-4d %s" % (rel, i, t))
else:
    print("  无残留 title 赋值")

print()
print("  数据字段 (保留, 正常):")
for dp, _, ns in os.walk(APP):
    for n in sorted(ns):
        if not n.endswith(".js"):
            continue
        p = os.path.join(dp, n)
        for i, ln in enumerate(open(p, encoding="utf-8").read().split("\n"), 1):
            if re.search(r"\b[dp]\.title\b", ln):
                print("    %-14s L%-4d %s" % (n, i, ln.strip()[:64]))
