# -*- coding: utf-8 -*-
import ast
import io
import os
import re
import sys
from collections import Counter

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKIP = {'venv', '.git', '__pycache__', 'node_modules', 'build', 'dist',
        'build_V0.9.2-release', 'tools', 'test', 'cache', 'logs', 'lang',
        'mods', '.assets-pack', 'resources', 'assets', 'previews'}

comment_files = doc_files = n_comment = n_doc = 0
specials = Counter()
prints = Counter()
log_calls = Counter()
for dp, dn, fn in os.walk(ROOT):
    dn[:] = [d for d in dn if d not in SKIP and not d.startswith('.')]
    for f in fn:
        if not f.endswith('.py'):
            continue
        p = os.path.join(dp, f)
        rel = os.path.relpath(p, ROOT).replace('\\', '/')
        try:
            src = open(p, encoding='utf-8').read()
        except Exception:
            continue
        lines = src.split('\n')
        c = [i + 1 for i, l in enumerate(lines) if l.strip().startswith('#')]
        if c:
            comment_files += 1
            n_comment += len(c)
        for i, l in enumerate(lines):
            s = l.strip()
            if s.startswith('#'):
                for pat in ('coding', 'noqa', 'type:', 'pragma', '!/', ':utf-8',
                            'pyright', 'mypy'):
                    if pat in s:
                        specials[pat] += 1
            if '#' in l and not s.startswith('#'):
                tail = l.split('#', 1)[1]
                for pat in ('noqa', 'type: ignore', 'pragma', '!/'):
                    if pat in tail:
                        specials[pat + ' (inline)'] += 1
        try:
            tree = ast.parse(src)
        except Exception:
            continue
        dcount = 0
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.ClassDef)) and ast.get_docstring(node):
                dcount += 1
        if dcount:
            doc_files += 1
            n_doc += dcount
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                f = node.func
                name = getattr(f, 'id', None) or getattr(f, 'attr', None)
                if name == 'print':
                    prints[rel] += 1
                elif name in ('_log', 'log_message', 'add_terminal_message',
                              'log_info', 'log_error', 'log_warn', 'log_debug',
                              'logger', 'logging'):
                    log_calls[name] += 1

print('注释: %d 个文件 / %d 行' % (comment_files, n_comment))
print('文档串: %d 个文件 / %d 个' % (doc_files, n_doc))
print('特殊注释: %s' % dict(specials))
print('print() 调用总数: %d, 涉及文件: %d' % (sum(prints.values()), len(prints)))
print('日志类调用: %s' % dict(log_calls))
print('--- print 最多的文件 ---')
for rel, n in prints.most_common(15):
    print('%4d  %s' % (n, rel))
