"""Offline regressions for WarpHook resources surviving module reloads."""
import ast
from pathlib import Path
from types import SimpleNamespace
import threading
import unittest

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'addons/WarpHook/warphook/game.py'
LIVE_SOURCE = ROOT / 'addons/WarpHook/warphook/live.py'
SERVICE_SOURCE = ROOT / 'addons/WarpHook/warphook/service.py'
HOST_SOURCE = ROOT / 'addons/WarpHook/warphook/host.py'
BASE_SOURCE = ROOT / 'addons/WarpHook/warphook/base.py'


def load_start_block():
    tree = ast.parse(BASE_SOURCE.read_text(encoding='utf-8'))
    start_block = next(n for n in tree.body
                       if isinstance(n, ast.FunctionDef) and n.name == '_start_block')
    start_block.body = [n for n in start_block.body
                        if not (isinstance(n, ast.ImportFrom) and n.level == 1)]
    module = ast.fix_missing_locations(ast.Module(body=[start_block], type_ignores=[]))
    namespace = {
        '__name__': 'test_warp_base',
        '__package__': 'test_warp_base',
        '__spec__': None,
        '__path__': [],
        'os': SimpleNamespace(getpid=lambda: 1234),
        'time': SimpleNamespace(strftime=lambda fmt: '2026-11-07 15:00:00'),
        '_env': SimpleNamespace(WARP_HOOK_VERSION='test'),
    }
    exec(compile(module, str(BASE_SOURCE), 'exec'), namespace)
    return namespace['_start_block']


def load_game_lifecycle():
    tree = ast.parse(SOURCE.read_text(encoding='utf-8'))
    watcher = next(n for n in tree.body
                   if isinstance(n, ast.ClassDef) and n.name == 'GachaWatcher')
    gacha = next(n for n in tree.body
                 if isinstance(n, ast.ClassDef) and n.name == 'Gacha')
    stop_single = next(n for n in gacha.body
                       if isinstance(n, ast.FunctionDef) and n.name == 'stop')
    stop_all = next(n for n in gacha.body
                    if isinstance(n, ast.FunctionDef) and n.name == 'stop_all')
    on_buy = next(n for n in gacha.body
                  if isinstance(n, ast.FunctionDef) and n.name == 'on_buy')
    registry = next(n for n in tree.body
                    if isinstance(n, ast.FunctionDef) and n.name == '_watcher_registry')
    initializer = next(n for n in gacha.body
                       if isinstance(n, ast.FunctionDef) and n.name == '__init__')
    registry_method = next(n for n in gacha.body
                           if isinstance(n, ast.FunctionDef) and n.name == '_registry')
    gacha_cls = ast.ClassDef(name='Gacha', bases=[], keywords=[],
                             body=[initializer, registry_method, stop_single, stop_all, on_buy],
                             decorator_list=[])
    module = ast.fix_missing_locations(ast.Module(body=[registry, watcher, gacha_cls],
                                                  type_ignores=[]))
    manager = SimpleNamespace()
    namespace = {
        'env': SimpleNamespace(ADDON_MANAGER=manager),
        'threading': threading,
        'log': lambda *args, **kwargs: None,
        'traceback': __import__('traceback'),
    }
    exec(compile(module, str(SOURCE), 'exec'), namespace)
    return manager, namespace['GachaWatcher'], namespace['Gacha']


def load_live_close_all():
    tree = ast.parse(LIVE_SOURCE.read_text(encoding='utf-8'))
    registry = next(n for n in tree.body
                    if isinstance(n, ast.FunctionDef) and n.name == '_live_registry')
    close_all = next(n for n in tree.body
                     if isinstance(n, ast.FunctionDef) and n.name == 'close_all')
    module = ast.fix_missing_locations(ast.Module(body=[registry, close_all], type_ignores=[]))
    manager = SimpleNamespace()
    logs = []
    namespace = {
        'env': SimpleNamespace(ADDON_MANAGER=manager),
        '_LIVES': {},
        'log': lambda message, **kwargs: logs.append(message),
        'traceback': __import__('traceback'),
    }
    exec(compile(module, str(LIVE_SOURCE), 'exec'), namespace)
    return manager, namespace['close_all'], logs


def load_host_block(replacement):
    tree = ast.parse(HOST_SOURCE.read_text(encoding='utf-8'))
    host_cls = next(n for n in tree.body
                    if isinstance(n, ast.ClassDef) and n.name == 'Host')
    block = next(n for n in host_cls.body
                 if isinstance(n, ast.FunctionDef) and n.name == 'block')
    host_cls = ast.ClassDef(name='Host', bases=[], keywords=[], body=[block], decorator_list=[])
    module = ast.fix_missing_locations(ast.Module(body=[host_cls], type_ignores=[]))
    calls = []
    namespace = {
        'shm_open': lambda *args, **kwargs: calls.append((args, kwargs)) or replacement,
        'HOST_MAGIC': 1,
        'HOST_VERSION': 1,
        'HOST_MAP_BYTES': 4096,
        'HOST_MAP_DEFAULT': 'test-map',
        'HOST_MAP_ENV': 'TEST_MAP',
        '_tick32': lambda: 1,
        'HostHeader': object,
    }
    exec(compile(module, str(HOST_SOURCE), 'exec'), namespace)
    return namespace['Host'], calls


def load_service_stop_all():
    tree = ast.parse(SERVICE_SOURCE.read_text(encoding='utf-8'))
    service_cls = next(n for n in tree.body
                       if isinstance(n, ast.ClassDef) and n.name == 'Service')
    stop_all = next(n for n in service_cls.body
                    if isinstance(n, ast.FunctionDef) and n.name == 'stop_all')
    stop_all.decorator_list = [ast.Name(id='classmethod', ctx=ast.Load())]
    service_cls = ast.ClassDef(name='Service', bases=[], keywords=[],
                               body=[stop_all], decorator_list=[])
    registry = next(n for n in tree.body
                    if isinstance(n, ast.FunctionDef) and n.name == '_service_registry')
    module = ast.fix_missing_locations(ast.Module(body=[registry, service_cls],
                                                  type_ignores=[]))
    manager = SimpleNamespace(_warp_services={})
    namespace = {
        'env': SimpleNamespace(ADDON_MANAGER=manager),
        'log': lambda *args, **kwargs: None,
    }
    exec(compile(module, str(SERVICE_SOURCE), 'exec'), namespace)
    return manager, namespace['Service']


class ReloadLifecycleTests(unittest.TestCase):
    def test_process_marker_is_written_once_across_module_generations(self):
        start_block = load_start_block()

        class Logger:
            def __init__(self):
                self.lines = []

            def info(self, message, *args):
                self.lines.append(message % args)

        logger = Logger()
        start_block(logger)
        start_block(logger)

        self.assertEqual(len(logger.lines), 1)
        self.assertIn('pid=1234', logger.lines[0])

    def test_host_block_reopens_instead_of_reusing_closed_map(self):
        old_map = SimpleNamespace(_view=None, _handle=None)
        replacement = SimpleNamespace(_view=123, _handle=456,
                                      cfg=SimpleNamespace(version=1))
        host_type, calls = load_host_block(replacement)
        host = host_type()
        host._closed = False
        host._block = old_map
        host.log = lambda message: None
        host.enabled = True
        host.dedupe_ms = 800
        host.map_name = 'test-map'
        host._owners = {}
        host._write_config = lambda block: None

        self.assertIs(host.block(), replacement)
        self.assertEqual(len(calls), 1)
        self.assertIs(host._block, replacement)

    def test_close_all_uses_cross_generation_live_registry(self):
        manager, close_all, _ = load_live_close_all()
        stopped = []
        manager._warphook_lives = {
            'old-addon': SimpleNamespace(close=lambda: (stopped.append('old'), True)[1])
        }

        self.assertTrue(close_all())
        self.assertEqual(stopped, ['old'])

    def test_live_timeout_is_logged_and_reported(self):
        manager, close_all, logs = load_live_close_all()
        manager._warphook_lives = {
            'stuck-addon': SimpleNamespace(close=lambda: False)
        }

        self.assertFalse(close_all())
        self.assertTrue(any('stuck-addon' in line for line in logs))

    def test_new_generation_stops_old_service_from_manager_registry(self):
        manager, service_type = load_service_stop_all()
        old = SimpleNamespace()
        old.stop = lambda: (manager._warp_services.pop('old-addon', None), True)[1]
        manager._warp_services['old-addon'] = old

        self.assertTrue(service_type.stop_all())
        self.assertEqual(manager._warp_services, {})

    def test_failed_old_service_remains_registered(self):
        manager, service_type = load_service_stop_all()
        old = SimpleNamespace(stop=lambda: False)
        manager._warp_services['old-addon'] = old

        self.assertFalse(service_type.stop_all())
        self.assertIs(manager._warp_services['old-addon'], old)

    def test_new_generation_stops_old_generation_watcher(self):
        manager, watcher_type, gacha_type = load_game_lifecycle()
        stopped = threading.Event()
        thread = threading.Thread(target=lambda: stopped.wait(2), daemon=True)
        thread.start()
        old_watcher = watcher_type(None, threading.Event(), thread, 'test-addon')
        manager._warphook_watchers = {'test-addon': old_watcher}

        current_generation = gacha_type()
        self.assertTrue(current_generation.stop_all())
        self.assertFalse(thread.is_alive())
        self.assertEqual(manager._warphook_watchers, {})

    def test_single_owner_timeout_is_reported_and_retained(self):
        manager, watcher_type, gacha_type = load_game_lifecycle()
        release = threading.Event()
        thread = threading.Thread(target=lambda: release.wait(6), daemon=True)
        thread.start()
        old_watcher = watcher_type(None, threading.Event(), thread, 'single-owner')
        manager._warphook_watchers = {'single-owner': old_watcher}

        current_generation = gacha_type()
        self.assertFalse(current_generation.stop('single-owner'))
        self.assertIs(manager._warphook_watchers['single-owner'], old_watcher)
        release.set()
        thread.join(1)
        self.assertFalse(thread.is_alive())

    def test_timed_out_watcher_is_retained_and_blocks_unload(self):
        manager, watcher_type, gacha_type = load_game_lifecycle()
        release = threading.Event()
        thread = threading.Thread(target=lambda: release.wait(6), daemon=True)
        thread.start()
        old_watcher = watcher_type(None, threading.Event(), thread, 'stuck-addon')
        manager._warphook_watchers = {'stuck-addon': old_watcher}

        current_generation = gacha_type()
        self.assertFalse(current_generation.stop_all())
        self.assertIs(manager._warphook_watchers['stuck-addon'], old_watcher)
        release.set()
        thread.join(1)
        self.assertFalse(thread.is_alive())


if __name__ == '__main__':
    unittest.main(verbosity=2)
