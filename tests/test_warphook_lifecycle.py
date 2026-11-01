"""Offline lifecycle regressions: execute actual classes without Windows/DLL imports."""
import ast
import pathlib
import threading
import time
import types
import unittest
from unittest.mock import Mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
WARP = ROOT / 'addons' / 'WarpHook' / 'warphook'


def load_classes(filename, names, namespace):
    tree = ast.parse((WARP / filename).read_text(encoding='utf-8-sig'))
    tree.body = [node for node in tree.body
                 if isinstance(node, (ast.ClassDef, ast.FunctionDef)) and node.name in names]
    exec(compile(tree, str(WARP / filename), 'exec'), namespace)
    return namespace


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.manager = types.SimpleNamespace(gamestart_funcs=[])
        self.env = types.SimpleNamespace(ADDON_MANAGER=self.manager)
        self.host = Mock()
        self.host.dll_path.return_value = 'offline-host.dll'
        self.host.push.return_value = 'ok'
        self.host._act.side_effect = lambda owner, callback: callback()
        self.ns = dict(threading=threading, time=time, os=__import__('os'),
                       env=self.env, log=Mock(), Host=Mock(return_value=self.host),
                       _owner_of_caller=lambda: 'BattleBGMExtend',
                       find_game_pid=Mock(return_value=None),
                       wait_for_game=Mock(side_effect=AssertionError('synchronous game wait')),
                       wait_for_gameassembly=Mock(side_effect=AssertionError('unexpected DLL wait')),
                       gacha=types.SimpleNamespace(stop=Mock()), _INJECT_LOCK=threading.Lock(),
                       has_gameassembly=Mock(return_value=False), inject_dll=Mock(return_value=(True, 'ok')),
                       audio=types.SimpleNamespace(guard_hook_defs=lambda: []),
                       objects=types.SimpleNamespace(SLOT_MANAGER=3), _LIVES={})
        load_classes('service.py', {'Service', '_service_registry'}, self.ns)
        load_classes('live.py', {'Live'}, self.ns)
        self.live = self.ns['Live']('BattleBGMExtend', host=self.host)

    def tearDown(self):
        self.live.close()
        for service in list(self.ns['Service']._services.values()):
            service.stop()
        for service in list(getattr(self.manager, '_warp_services', {}).values()):
            service.stop()

    def test_registration_never_pushes_on_loading_thread(self):
        called = []
        self.live._push = lambda: called.append(threading.current_thread().name)
        self.live.on_round_start(lambda battle: None)
        self.assertEqual(called, [])
        self.assertFalse(self.live._pushed_ok)
        self.host.beat.assert_not_called()
        self.host.hits.assert_not_called()
        self.ns['wait_for_gameassembly'].assert_not_called()
        self.assertEqual(len(self.manager.gamestart_funcs), 1)

    def test_inject_request_and_prelaunch_event_only_schedule_background(self):
        service = self.ns['Service'](addon_name='manual', host=self.host)
        started = time.monotonic()
        self.assertTrue(service.inject_now(wait=False))
        self.assertTrue(service.inject_now(wait=True))
        self.manager.gamestart_funcs[-1]()  # launcher fires before creating game process
        self.assertLess(time.monotonic() - started, 0.5)
        self.ns['wait_for_game'].assert_not_called()
        self.ns['wait_for_gameassembly'].assert_not_called()
        self.host.push.assert_not_called()
        service.stop()
        self.assertFalse(service.inject_now())

    def test_manual_inject_works_when_automatic_attach_is_disabled(self):
        service = self.ns['Service'](addon_name='manual-disabled', host=self.host,
                                     auto=lambda: False)
        entered = threading.Event()
        self.ns['find_game_pid'].return_value = 123

        def wait_dll(pid, stop_event):
            entered.set()
            stop_event.wait(1)
            return False

        self.ns['wait_for_gameassembly'] = wait_dll
        service._on_game_start()
        self.assertIsNone(service._thread)
        self.assertTrue(service.inject_now())
        self.assertTrue(entered.wait(1))
        self.assertTrue(service.stop())

    def test_gameassembly_wait_is_background_and_cancelled_by_unload(self):
        entered = threading.Event()
        workers = []
        self.ns['find_game_pid'].return_value = 123

        def wait_dll(pid, stop_event):
            workers.append(threading.current_thread())
            entered.set()
            stop_event.wait(2)
            return False

        self.ns['wait_for_gameassembly'] = wait_dll
        self.live.on_round_start(lambda battle: None)
        self.assertTrue(entered.wait(1))
        self.assertIsNot(workers[0], threading.current_thread())
        self.host.beat.assert_not_called()
        self.host.push.assert_not_called()
        started = time.monotonic()
        self.assertTrue(self.live.close())
        self.assertLess(time.monotonic() - started, 0.5)
        self.assertFalse(workers[0].is_alive())

    def test_ready_game_syncs_only_after_background_dll_wait(self):
        order = []
        synced = threading.Event()
        self.ns['find_game_pid'].return_value = 123
        self.ns['wait_for_gameassembly'] = lambda pid, stop_event: order.append('dll') or True
        self.ns['has_gameassembly'].return_value = True
        self.host.poll.return_value = {}
        self.host.hits.return_value = 0

        def push():
            self.assertIsNot(threading.current_thread(), threading.main_thread())
            self.assertEqual(order[0], 'dll')
            order.append('sync')
            synced.set()
            return True

        self.live._push = push
        from unittest.mock import patch
        with patch('os.path.isfile', return_value=True):
            self.live.on_round_start(lambda battle: None)
            self.assertTrue(synced.wait(1))
        self.assertEqual(order[0], 'dll')
        self.assertIn('sync', order)

    def test_reload_uses_fresh_live_and_single_service(self):
        self.live.on_round_start(lambda battle: None)
        old = self.live._service
        self.assertTrue(self.live.close())
        self.live = self.ns['Live']('BattleBGMExtend', host=self.host)
        self.live.on_round_start(lambda battle: None)
        self.assertIsNot(self.live._service, old)
        self.assertTrue(old._closed)
        self.assertFalse(old._thread)
        self.assertEqual(list(self.manager._warp_services), ['BattleBGMExtend'])

    def test_battle_plugin_exec_only_registers_lifecycle(self):
        game = types.SimpleNamespace(on_round_start=self.live.on_round_start,
                                     on_battle_end=self.live.on_battle_end,
                                     start=self.live.start, close=self.live.close)
        space = types.SimpleNamespace(game=game)
        manager = types.SimpleNamespace(get_addon_info=lambda name: {'settings': {'enable': True}})
        namespace = dict(__file__=str(ROOT / 'addons' / 'BattleBGMExtend' / 'scr.py'),
                         ADDON_ARG={'AddonName': 'BattleBGMExtend', 'AddonManager': manager,
                                    'Namespaces': types.SimpleNamespace(space=lambda name: space)})
        source = ROOT / 'addons' / 'BattleBGMExtend' / 'scr.py'
        exec(compile(source.read_text(encoding='utf-8-sig'), str(source), 'exec'), namespace)
        self.host.push.assert_not_called()
        self.host.beat.assert_not_called()
        self.ns['wait_for_game'].assert_not_called()
        self.assertEqual(len(self.live._round_cbs), 1)
        self.assertEqual(len(self.live._scene_cbs), 1)
        self.assertTrue(namespace['on_unload']())
        self.host.set_var.assert_not_called()
        self.host.push.assert_not_called()


if __name__ == '__main__':
    unittest.main()
