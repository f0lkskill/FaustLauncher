"""离线验证真实源码中的调试门控和自动强杀禁用。"""
import ast
from pathlib import Path
import types
import unittest

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / 'addons/WarpHook/warphook/base.py'

class DebugModeTests(unittest.TestCase):
    def setUp(self):
        tree = ast.parse(BASE.read_text(encoding='utf-8'))
        nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef)
                 and n.name in ('is_debug_enabled', 'debug_log')]
        self.env = types.SimpleNamespace(ADDON_MANAGER=None, ADDON_NAME='WarpHook')
        self.lines = []
        def importer(name, globals=None, locals=None, fromlist=(), level=0):
            return types.SimpleNamespace(env=self.env)
        self.ns = {'__builtins__': dict(vars(__import__('builtins')), __import__=importer),
                   'log': lambda *a, **kw: self.lines.append((a, kw))}
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(BASE), 'exec'), self.ns)

    def test_default_quiet(self):
        self.ns['debug_log']('poll')
        self.assertEqual(self.lines, [])

    def test_setting_live_switch(self):
        settings = {'调试模式': False}
        self.env.ADDON_MANAGER = types.SimpleNamespace(
            get_addon_info=lambda name: {'settings': settings})
        self.ns['debug_log']('hidden')
        settings['调试模式'] = True
        self.ns['debug_log']('visible', prefix='[NoGacha]')
        settings['调试模式'] = False
        self.ns['debug_log']('hidden again')
        self.assertEqual(len(self.lines), 1)
        self.assertEqual(self.lines[0][0], ('visible',))
        self.assertEqual(self.lines[0][1]['prefix'], '[NoGacha]')

    def test_settings_failure_quiet(self):
        def broken(name):
            raise RuntimeError('unloaded')
        self.env.ADDON_MANAGER = types.SimpleNamespace(get_addon_info=broken)
        self.assertFalse(self.ns['is_debug_enabled']())

    def test_monitor_never_terminates(self):
        tree = ast.parse((ROOT / 'functions/pages/app/app_web.py').read_text(encoding='utf-8-sig'))
        monitor = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                       and n.name == '_monitor_game_process')
        check = next(n for n in monitor.body if isinstance(n, ast.FunctionDef)
                     and n.name == '_check_hang')
        self.assertFalse(any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                             and n.func.attr == 'terminate' for n in ast.walk(check)))

if __name__ == '__main__':
    unittest.main()
