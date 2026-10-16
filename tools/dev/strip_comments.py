# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import ast
import io
import os
import re
import sys
import tokenize

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SKIP_DIRS = {"venv", ".venv", ".git", "__pycache__", "node_modules", "build",
             "dist", "build_V0.9.2-release", "build_temp", "cache", "logs",
             "lang", "mods", "addons", "resources", "assets", ".assets-pack",
             "test", "tests", "previews"}

KEEP_PATTERNS = (
    re.compile(r"^#![/\w]"),
    re.compile(r"coding[:=]"),
    re.compile(r"\bnoqa\b"),
    re.compile(r"\btype:\s*ignore\b"),
    re.compile(r"\btype:\s*[a-z]+"),
    re.compile(r"\bpragma:\s*no\s*cover\b"),
    re.compile(r"\bpyright:\s*\w+"),
    re.compile(r"\bregion\b|\bendregion\b"),
    re.compile(r"^#\s*!"),
)

def keeps(comment: str) -> bool:
    return any(p.search(comment) for p in KEEP_PATTERNS)

def docstring_spans(src: str, tree: ast.AST) -> list[tuple[int, int, int]]:
    spans = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef)):
            continue
        body = getattr(node, "body", None)
        if not body:
            continue
        first = body[0]
        if not (isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)):
            continue
        v = first.value
        spans.append((v.lineno, v.end_lineno, v.end_col_offset))
    return spans

def comment_lines(src: str) -> dict[int, list[tuple[int, int, str]]]:
    out: dict[int, list[tuple[int, int, str]]] = {}
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type == tokenize.COMMENT:
                out.setdefault(tok.start[0], []).append(
                    (tok.start[1], tok.end[1], tok.string))
    except Exception:
        return {}
    return out

def normalise(src: str) -> str:
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return ""
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)):
            body = getattr(node, "body", None)
            if body and isinstance(body[0], ast.Expr) \
                    and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                body.pop(0)
                if not body:
                    body.append(ast.Pass())
    return ast.dump(tree)

def body_is_only_docstring(tree: ast.AST, span: tuple[int, int, int]) -> bool:
    start, end = span[0], span[1]
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if not isinstance(body, list) or not body:
            continue
        first = body[0]
        value = getattr(first, "value", None)
        if isinstance(value, ast.Constant) and isinstance(value.value, str) \
                and value.lineno == start and value.end_lineno == end:
            return len(body) == 1
    return False

def strip_file(path: str, dry: bool) -> tuple[int, int, bool]:
    with open(path, encoding="utf-8", newline="") as fp:
        src = fp.read()
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return 0, 0, False
    before = normalise(src)
    if not before:
        return 0, 0, False

    newline = "\r\n" if "\r\n" in src else "\n"
    lines = src.splitlines(keepends=False)
    drop: set[int] = set()
    blank: set[int] = set()
    add_pass: set[int] = set()

    spans = docstring_spans(src, tree)
    n_docs = 0
    for span in spans:
        start, end, _end_col = span
        only = body_is_only_docstring(tree, span)
        for idx in range(start - 1, end):
            drop.add(idx)
        if only:
            add_pass.add(end - 1)
        n_docs += 1

    n_comments = 0
    for lineno, tokens in comment_lines(src).items():
        if lineno - 1 in drop:
            continue
        for col_start, col_end, text in tokens:
            if keeps(text):
                continue
            line = lines[lineno - 1]
            prefix = line[:col_start]
            if not prefix.strip():
                drop.add(lineno - 1)
            else:
                blank.add(lineno - 1)
                lines[lineno - 1] = prefix.rstrip()
            n_comments += 1

    out_lines = []
    for idx, line in enumerate(lines):
        if idx in drop:
            if idx in add_pass:
                indent = re.match(r"\s*", line).group(0)
                out_lines.append(indent + "pass")
            continue
        out_lines.append(line)

    cleaned: list[str] = []
    blank_run = 0
    for line in out_lines:
        if not line.strip():
            blank_run += 1
            if blank_run > 1:
                continue
        else:
            blank_run = 0
        cleaned.append(line)

    new_src = newline.join(cleaned)
    if src.endswith(newline):
        new_src += newline
    try:
        ast.parse(new_src)
    except SyntaxError:
        return 0, 0, False
    if normalise(new_src) != before:
        return 0, 0, False
    if not new_src.endswith(newline):
        new_src += newline
    if not dry and (n_docs or n_comments):
        with open(path, "w", encoding="utf-8", newline="") as fp:
            fp.write(new_src)
    return n_docs, n_comments, True

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--path", default=ROOT)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    targets = []
    base = os.path.abspath(args.path)
    for dp, dn, fn in os.walk(base):
        dn[:] = [d for d in dn if d not in SKIP_DIRS and not d.startswith(".")]
        for f in fn:
            if f.endswith(".py"):
                targets.append(os.path.join(dp, f))

    tot_d = tot_c = files = failed = 0
    for path in sorted(targets):
        d, c, ok = strip_file(path, args.dry_run)
        if not ok:
            failed += 1
            print("跳过(校验不通过): %s" % os.path.relpath(path, ROOT))
            continue
        if d or c:
            files += 1
            tot_d += d
            tot_c += c
            if not args.quiet:
                print("%4d 文档串 %4d 注释  %s" % (d, c, os.path.relpath(path, ROOT)))
    mode = "预览" if args.dry_run else "已处理"
    print("--- %s: %d 个文件, 删除 %d 个文档串 + %d 条注释; 跳过 %d 个 ---"
          % (mode, files, tot_d, tot_c, failed))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
