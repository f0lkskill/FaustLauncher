"""Compile-free protocol consistency check; does not import/inject WarpHook."""
import ast
import pathlib
import re

root = pathlib.Path(__file__).resolve().parents[1]
py_source = (root / 'warphook' / 'host.py').read_text(encoding='utf-8')
c_source = (root / 'src' / 'warp_layout.h').read_text(encoding='utf-8')
values = {}
for node in ast.parse(py_source).body:
    if isinstance(node, ast.Assign) and len(node.targets) == 1:
        target = node.targets[0]
        if isinstance(target, ast.Name) and target.id.startswith('HOST_'):
            try:
                values[target.id] = eval(compile(ast.Expression(node.value), '', 'eval'), {'__builtins__': {}}, values)
            except (NameError, TypeError, AttributeError):
                pass
c_values = {}
for name, expr in re.findall(r'^#define\s+(WARP_\w+)\s+([^\n]+)', c_source, re.M):
    expr = expr.split('/*')[0].strip()
    if re.fullmatch(r'[A-Z_0-9\s()+*]+', expr):
        try:
            c_values[name] = eval(expr, {'__builtins__': {}}, c_values)
        except (NameError, SyntaxError):
            pass
for suffix in ('VERSION', 'EXPORT_COUNT', 'EXPORTS_OFFSET', 'EV_CTRL_OFFSET', 'EVENTS_OFFSET', 'READ_OFFSET', 'OBJECTS_OFFSET', 'CMD_BUF_OFFSET', 'THREAD_EXPORT_OFFSET', 'MAP_BYTES'):
    assert values['HOST_' + suffix] == c_values['WARP_' + suffix], suffix
assert values['HOST_VERSION'] == 14
assert values['HOST_EXPORT_COUNT'] == 24
assert values['HOST_THREAD_EXPORT_OFFSET'] == 304912
assert values['HOST_MAP_BYTES'] == 304976
assert values['HOST_EXPORT_ORDER'][7] == 'il2cpp_thread_attach'
assert 'il2cpp_thread_detach' not in values['HOST_EXPORT_ORDER']
print('PASS C/Python protocol v14: original offsets unchanged, appended detach slot')
