"""AST 隔离运行真实缓存代码；只访问临时假 DLL，不导入 Win32/扫描本机游戏。"""
import ast
import builtins
import os
from pathlib import Path
import tempfile
import threading
import types
import unittest
from concurrent.futures import ThreadPoolExecutor

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / 'addons/WarpHook/warphook/base.py'


class ExportRetryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name) / 'game'
        self.directory.mkdir()
        self.settings = {'game_path': str(self.directory)}
        self.now = 100.0
        self.calls = []
        self.logs = []
        self.response = {'ok': True, 'mapping': {'il2cpp_init': 'alias'}}
        self.resolver = None
        self.ix = types.SimpleNamespace(resolve=self.resolve)
        manager = types.SimpleNamespace(get_setting=self.settings.get)
        settings_module = types.SimpleNamespace(get_settings_manager=lambda: manager)
        def importer(name, globals=None, locals=None, fromlist=(), level=0):
            if name == 'functions.base':
                return types.SimpleNamespace(il2cpp_exports=self.ix)
            if name == 'functions.base.settings_manager':
                return settings_module
            raise AssertionError('unexpected import: ' + name)
        tree = ast.parse(BASE.read_text(encoding='utf-8'))
        functions = {'_exports_identity', '_exports_log', 'resolve_exports', 'ensure_exports'}
        nodes = [node for node in tree.body
                 if (isinstance(node, ast.FunctionDef) and node.name in functions)
                 or (isinstance(node, ast.Assign) and any(
                     isinstance(target, ast.Name) and target.id.startswith(('_export_', '_EXPORT_'))
                     for target in node.targets))]
        self.ns = {'__builtins__': dict(vars(builtins), __import__=importer),
                   'os': os, 'threading': threading,
                   'time': types.SimpleNamespace(monotonic=lambda: self.now),
                   'names_table': lambda: '', 'log': lambda *args: self.logs.append(args)}
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(BASE), 'exec'), self.ns)

    def resolve(self, directory, **kwargs):
        self.calls.append((directory, kwargs))
        if self.resolver:
            return self.resolver()
        if isinstance(self.response, Exception):
            raise self.response
        return self.response

    def get(self, refresh=False):
        return self.ns['resolve_exports'](refresh)

    def test_failure_recovers_after_backoff_and_logs_are_throttled(self):
        self.response = {'ok': False, 'mapping': {}, 'reason': 'zero refs'}
        self.assertEqual(self.get(), {})
        self.assertIsNone(self.ns['_export_cache'])
        for _ in range(20):
            self.assertEqual(self.get(), {})
        self.assertEqual(len(self.calls), 1)
        self.now += 3.1
        self.assertEqual(self.get(), {})
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(len(self.logs), 1)
        self.response = {'ok': True, 'mapping': {'il2cpp_init': 'recovered'}}
        self.now += 3.1
        self.assertEqual(self.get(), self.response['mapping'])
        self.assertEqual(self.get(), self.response['mapping'])
        self.assertEqual(len(self.calls), 3)

    def test_exception_recovers_and_refresh_bypasses_backoff(self):
        self.response = OSError('temporarily locked')
        self.assertEqual(self.get(), {})
        self.response = {'ok': True, 'mapping': {'x': 'y'}}
        self.assertEqual(self.get(refresh=True), {'x': 'y'})
        self.assertTrue(self.calls[-1][1]['refresh'])
        self.assertEqual(self.get(refresh=True), {'x': 'y'})
        self.assertEqual(len(self.calls), 3)

    def test_success_bound_to_path_and_returns_copy(self):
        self.get()['injected'] = 'bad'
        self.assertNotIn('injected', self.get())
        other = Path(self.temp.name) / 'other'
        other.mkdir()
        self.settings['game_path'] = str(other)
        self.get()
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(self.calls[-1][0], os.path.abspath(str(other)))

    def test_each_dll_identity_invalidates_success_and_failure(self):
        for filename in ('GameAssembly.dll', 'UnityPlayer.dll'):
            with self.subTest(filename=filename):
                self.get()
                before = len(self.calls)
                target = self.directory / filename
                target.write_bytes(b'new file')
                self.get()
                self.assertEqual(len(self.calls), before + 1)
                self.response = {'ok': False, 'mapping': {}}
                self.get(refresh=True)
                before = len(self.calls)
                target.write_bytes(b'updated content changes size')
                self.response = {'ok': True, 'mapping': {'x': 'y'}}
                self.assertEqual(self.get(), {'x': 'y'})
                self.assertEqual(len(self.calls), before + 1)

    def test_empty_success_is_retryable(self):
        self.response = {'ok': True, 'mapping': {}}
        self.get()
        self.assertIsNone(self.ns['_export_cache'])
        self.now += 4
        self.get()
        self.assertEqual(len(self.calls), 2)

    def test_change_during_resolve_discards_old_mapping(self):
        def change():
            (self.directory / 'UnityPlayer.dll').write_bytes(b'changed')
            return self.response
        self.resolver = change
        self.assertEqual(self.get(), {})
        self.resolver = None
        self.assertEqual(self.get(), self.response['mapping'])
        self.assertEqual(len(self.calls), 2)

    def test_concurrent_requests_share_scan(self):
        entered, release = threading.Event(), threading.Event()
        def slow():
            entered.set()
            if not release.wait(3):
                raise AssertionError('test timeout')
            return self.response
        self.resolver = slow
        with ThreadPoolExecutor(max_workers=8) as pool:
            first = pool.submit(self.get)
            self.assertTrue(entered.wait(3))
            others = [pool.submit(self.get) for _ in range(7)]
            release.set()
            self.assertEqual(first.result(), self.response['mapping'])
            for task in others:
                self.assertEqual(task.result(), self.response['mapping'])
        self.assertEqual(len(self.calls), 1)

    def test_ensure_exports_does_not_spam_or_write_on_failure(self):
        writes = []
        block = types.SimpleNamespace(write_table=lambda *a: writes.append(a) or 1)
        self.response = {'ok': False, 'mapping': {}, 'reason': 'zero refs'}
        for _ in range(10):
            self.assertEqual(self.ns['ensure_exports'](block, ['il2cpp_init'], 42), 0)
        self.assertEqual(writes, [])
        self.assertEqual(len(self.logs), 1)
        self.response = {'ok': True, 'mapping': {'il2cpp_init': 'alias'}}
        self.now += 4
        self.assertEqual(self.ns['ensure_exports'](block, ['il2cpp_init'], 42), 1)
        self.assertEqual(writes, [(42, ['alias'], 64)])

    def test_failure_path_switch_bypasses_backoff(self):
        self.response = {'ok': False, 'mapping': {}}
        self.get()
        other = Path(self.temp.name) / 'other'
        other.mkdir()
        self.settings['game_path'] = str(other)
        self.response = {'ok': True, 'mapping': {'x': 'y'}}
        self.assertEqual(self.get(), {'x': 'y'})
        self.assertEqual(len(self.calls), 2)

    def test_log_window_expires(self):
        self.response = {'ok': False, 'mapping': {}, 'reason': 'zero refs'}
        self.get()
        self.now += 4
        self.get()
        self.assertEqual(len(self.logs), 1)
        self.now += 30
        self.get()
        self.assertEqual(len(self.logs), 2)

    def test_concurrent_failures_share_attempt(self):
        self.response = {'ok': False, 'mapping': {}, 'reason': 'zero refs'}
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: self.get(), range(32)))
        self.assertEqual(results, [{}] * 32)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(len(self.logs), 1)

    def test_refresh_waiting_on_normal_scan_still_refreshes(self):
        original = self.ns['_export_lock']
        queued = threading.Event()
        class TrackingLock:
            def __enter__(self):
                if threading.current_thread().name.startswith('refresh-worker'):
                    queued.set()
                original.acquire()
            def __exit__(self, *args):
                original.release()
        self.ns['_export_lock'] = TrackingLock()
        entered, release = threading.Event(), threading.Event()
        def slow():
            entered.set()
            if not release.wait(3):
                raise AssertionError('test timeout')
            return self.response
        self.resolver = slow
        with ThreadPoolExecutor(max_workers=1) as normal_pool:
            first = normal_pool.submit(self.get)
            self.assertTrue(entered.wait(3))
            with ThreadPoolExecutor(max_workers=1, thread_name_prefix='refresh-worker') as pool:
                refreshed = pool.submit(self.get, True)
                self.assertTrue(queued.wait(3))
                release.set()
                self.assertEqual(refreshed.result(), self.response['mapping'])
            self.assertEqual(first.result(), self.response['mapping'])
        self.assertEqual(len(self.calls), 2)
        self.assertTrue(self.calls[-1][1]['refresh'])

    def test_concurrent_refreshes_share_refresh_scan(self):
        original = self.ns['_export_lock']
        queued = threading.Event()
        class TrackingLock:
            def __enter__(self):
                if threading.current_thread().name.startswith('refresh-worker'):
                    queued.set()
                original.acquire()
            def __exit__(self, *args):
                original.release()
        self.ns['_export_lock'] = TrackingLock()
        entered, release = threading.Event(), threading.Event()
        def slow():
            entered.set()
            if not release.wait(3):
                raise AssertionError('test timeout')
            return self.response
        self.resolver = slow
        with ThreadPoolExecutor(max_workers=1) as initial_pool:
            first = initial_pool.submit(self.get, True)
            self.assertTrue(entered.wait(3))
            with ThreadPoolExecutor(max_workers=1, thread_name_prefix='refresh-worker') as pool:
                refreshed = pool.submit(self.get, True)
                self.assertTrue(queued.wait(3))
                release.set()
                self.assertEqual(refreshed.result(), self.response['mapping'])
            self.assertEqual(first.result(), self.response['mapping'])
        self.assertEqual(len(self.calls), 1)

    def test_names_table_path_and_same_length_edit_invalidate(self):
        table = Path(self.temp.name) / 'names.txt'
        table.write_text('il2cpp_a\n', encoding='utf-8')
        self.ns['names_table'] = lambda: str(table)
        self.get()
        before = len(self.calls)
        previous = table.stat()
        table.write_text('il2cpp_b\n', encoding='utf-8')
        os.utime(table, ns=(previous.st_atime_ns, previous.st_mtime_ns + 1_000_000_000))
        self.get()
        self.assertEqual(len(self.calls), before + 1)
        self.assertEqual(self.calls[-1][1]['names_path'], str(table))
        replacement = Path(self.temp.name) / 'other-names.txt'
        replacement.write_text('il2cpp_b\n', encoding='utf-8')
        self.ns['names_table'] = lambda: str(replacement)
        self.get()
        self.assertEqual(len(self.calls), before + 2)
        self.response = {'ok': False, 'mapping': {}}
        self.get(refresh=True)
        self.ns['names_table'] = lambda: ''
        self.response = {'ok': True, 'mapping': {'x': 'y'}}
        self.assertEqual(self.get(), {'x': 'y'})
        self.assertEqual(len(self.calls), before + 4)

    def test_missing_path_never_invokes_resolver(self):
        self.settings['game_path'] = ''
        self.assertEqual(self.get(), {})
        self.assertEqual(self.calls, [])
        self.settings['game_path'] = str(self.directory)
        self.assertEqual(self.get(), self.response['mapping'])


if __name__ == '__main__':
    unittest.main()
