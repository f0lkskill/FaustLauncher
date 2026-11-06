"""Offline regression: use the production Host.__new__, without loading Windows APIs."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest

SOURCE = Path(__file__).resolve().parents[2] / 'addons/WarpHook/warphook/host.py'


def generation(holder):
    tree = ast.parse(SOURCE.read_text(encoding='utf-8'))
    host = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'Host')
    new = next(n for n in host.body if isinstance(n, ast.FunctionDef) and n.name == '__new__')
    klass = ast.ClassDef(name='Host', bases=[], keywords=[], body=[new], decorator_list=[])
    module = ast.fix_missing_locations(ast.Module(body=[klass], type_ignores=[]))
    namespace = {'env': SimpleNamespace(ADDON_ARG={'AddonManager': holder})}
    exec(compile(module, str(SOURCE), 'exec'), namespace)
    return namespace['Host']


class ReloadTests(unittest.TestCase):
    def test_old_singleton_gains_bridge_without_losing_state(self):
        holder = SimpleNamespace()
        old = generation(holder)
        inst = old()
        inst._block = object()
        inst._command_lock = object()
        inst._owners = {'BattleBGMExtend': {'on': True}}
        state = inst.__dict__.copy()
        current = generation(holder)
        current.audio_score = lambda self: 'new bridge'
        upgraded = current()
        self.assertIs(upgraded, inst)
        self.assertIs(type(upgraded), current)
        self.assertEqual(upgraded.__dict__, state)
        self.assertEqual(upgraded.audio_score(), 'new bridge')
        self.assertIs(holder._warphook_host, upgraded)

    def test_repeated_reload_keeps_one_host(self):
        holder = SimpleNamespace()
        inst = generation(holder)()
        inst._inited = True
        for _ in range(20):
            current = generation(holder)
            self.assertIs(current(), inst)
            self.assertIs(type(inst), current)
            self.assertTrue(inst._inited)

    def test_same_generation_is_stable(self):
        holder = SimpleNamespace()
        current = generation(holder)
        self.assertIs(current(), current())


if __name__ == '__main__':
    unittest.main(verbosity=2)
