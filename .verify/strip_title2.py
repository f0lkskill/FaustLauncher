# -*- coding: utf-8 -*-
"""补删残留的 title 悬浮提示:
  · skins.js 里写在单行 if 中的 btn.title = '自动轮播' / '暂停轮播'
  · icons.js 里生成 <svg><title> 的逻辑 (SVG title 同样是悬浮提示)
"""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, "html", "app")

# ---------- 1) skins.js: 行内的 xxx.title = '...' ----------
for rel, pats in (
    ("js/features/skins.js", [
        "; btn.title = '自动轮播'; ", "; btn.title = '暂停轮播'; ",
        "; btn.title = '自动轮播';", "; btn.title = '暂停轮播';",
    ]),
):
    p = os.path.join(APP, rel)
    s = open(p, encoding="utf-8").read()
    before = s
    # 通用兜底: 行内形式的 赋值
    s = re.sub(r";\s*\w+\.title\s*=\s*'[^']*';", ";", s)
    s = re.sub(r"\s*\w+\.title\s*=\s*'[^']*';", "", s)
    if s != before:
        open(p, "w", encoding="utf-8", newline="").write(s)
        print("%s: 残留 title 赋值已删除" % rel)
    else:
        print("%s: 无残留" % rel)

# ---------- 2) icons.js: 去掉 SVG <title> ----------
p = os.path.join(APP, "js/core/icons.js")
s = open(p, encoding="utf-8").read()
before = s
# 删掉生成 title 的局部变量
s = re.sub(r"\n\s*const title = opts\.title \? '<title>' \+ esc\(opts\.title\) \+ '</title>' : '';", "", s)
# 拼装处去掉 title
s = s.replace("size + '>' + title + '</svg>'", "size + '>' + '</svg>'")
s = s.replace("size + '>' + title +", "size + '>' +")
# 注释同步
s = s.replace("//   opts.cls  附加 class; opts.size 字号(px, 同时决定宽高); opts.title 悬浮提示",
              "//   opts.cls  附加 class; opts.size 字号(px, 同时决定宽高)")
if s != before:
    open(p, "w", encoding="utf-8", newline="").write(s)
    print("icons.js: SVG <title> 生成逻辑已移除")
else:
    print("icons.js: 无需改动")

# ---------- 校验 ----------
print()
print("=== 最终复查: 全项目 title 悬浮提示 ===")
ATTR = re.compile(r"""\s+title\s*=\s*"[^"]*\"""")
left = []
for dp, _, ns in os.walk(APP):
    for n in sorted(ns):
        if not n.endswith((".html", ".js")):
            continue
        q = os.path.join(dp, n)
        t = open(q, encoding="utf-8").read()
        for m in ATTR.finditer(t):
            left.append((os.path.relpath(q, APP), "属性", m.group(0)[:44]))
        for i, ln in enumerate(t.split("\n"), 1):
            if re.search(r"\b[\w$]+\.title\s*=", ln):
                left.append((os.path.relpath(q, APP), "L%d" % i, ln.strip()[:56]))
            if re.search(r"opts\.title|<title>'", ln):
                left.append((os.path.relpath(q, APP), "L%d" % i, ln.strip()[:56]))
if left:
    for rel, where, t in left:
        print("  残留: %-28s %-6s %s" % (rel, where, t))
else:
    print("  已无任何 title 悬浮提示")

# 语法
import subprocess
bad = []
for dp, _, ns in os.walk(os.path.join(APP, "js")):
    for n in ns:
        if n.endswith(".js"):
            q = os.path.join(dp, n)
            r = subprocess.run(["node", "--check", q], capture_output=True, text=True,
                               shell=False)
            if r.returncode != 0:
                bad.append(n + ": " + (r.stderr or "").strip().split("\n")[0][:80])
print()
print("  JS 语法:", "全部 OK" if not bad else bad)
print("  <title> 标签保留:", 
      "OK" if "<title>FaustLauncher" in open(os.path.join(APP, "index.html"), encoding="utf-8").read() else "检查")
