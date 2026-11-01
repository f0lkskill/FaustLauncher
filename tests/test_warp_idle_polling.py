"""Offline idle-polling regressions using the actual Live/Service class bodies."""
import ast
import pathlib
import threading
import types
import unittest
from unittest.mock import Mock

WARP = pathlib.Path(__file__).resolve().parents[1] / 'addons' / 'WarpHook' / 'warphook'


def load_class(filename, name, namespace):
    tree = ast.parse((WARP / filename).read_text(encoding='utf-8-sig'))
    tree.body = [node for node in tree.body
                 if isinstance(node, ast.ClassDef) and node.name == name]
    exec(compile(tree, str(WARP / filename), 'exec'), namespace)
    return namespace[name]


class IdlePollingTests(unittest.TestCase):
    def setUp(self):
        self.now = 0.0
        self.host = Mock()
        self.cfg = types.SimpleNamespace(cmd_seq=0, cmd_ack=0, cmd_result=0)
        self.host.block.return_value = types.SimpleNamespace(cfg=self.cfg)
        self.host.object_ptr.return_value = 123
        self.host.read.side_effect = lambda slot, chain, **kw: {
            'ok': True, 'value': {1: 2, 2: 1.0, 3: 4}[chain[0]]}
        specs = {'sceneState': 1, '_currentTimeScale': 2, '_mainSceneEntryCount': 3}
        self.logs = Mock()
        self.ns = dict(threading=threading,
                       time=types.SimpleNamespace(monotonic=lambda: self.now),
                       objects=types.SimpleNamespace(SLOT_SCENE=29),
                       fields=types.SimpleNamespace(read_chain=lambda cls, name: {
                           'off': [specs[name]], 'kind': 'int'}),
                       SCENES={1: '战斗', 2: '主界面'}, log=self.logs)
        self.Service = load_class('service.py', 'Service', self.ns)
        self.Live = load_class('live.py', 'Live', self.ns)
        self.live = self.Live('offline', host=self.host)

    def service(self, phase='monitoring'):
        service = object.__new__(self.Service)
        service._phase = phase
        service._host = self.host
        self.live._service = service
        return service

    def test_empty_scene_slot_never_submits_a_read(self):
        self.service()
        self.host.object_ptr.return_value = 0
        for tick in range(200):
            self.now = tick * 0.25
            self.assertIsNone(self.live.scene()['value'])
        self.host.read.assert_not_called()
        self.assertLess(self.host.object_ptr.call_count, 15)

    def test_connection_phases_do_not_touch_command_channel(self):
        service = self.service()
        for phase in ('idle', 'waiting_game', 'waiting_gameassembly', 'syncing',
                      'injecting', 'stopped'):
            service._phase = phase
            self.now += 20
            self.assertIsNone(self.live.scene()['value'])
        self.host.block.assert_not_called()
        self.host.read.assert_not_called()

    def test_pending_or_executing_command_is_not_repeated(self):
        self.service()
        for seq, ack, result in ((3, 2, -1), (3, 3, -2)):
            self.cfg.cmd_seq, self.cfg.cmd_ack, self.cfg.cmd_result = seq, ack, result
            self.now += 20
            self.assertIsNone(self.live.scene()['value'])
        self.host.read.assert_not_called()

    def test_idle_home_uses_only_public_fields_and_caches(self):
        first = self.live.scene()
        self.assertEqual(first, {'value': 2, 'name': '主界面',
                                 'time_scale': 1.0, 'entries': 4})
        for tick in range(1, 5):
            self.now = tick * 0.1
            self.assertEqual(self.live.scene(), first)
        self.assertEqual(self.host.read.call_count, 3)
        self.now = 0.5
        self.live.scene()
        self.assertEqual(self.host.read.call_count, 6)

    def test_failed_read_stops_batch_and_exponentially_backs_off(self):
        self.host.read.side_effect = None
        self.host.read.return_value = {'ok': False, 'reason': '超时', 'value': None}
        for tick in range(240):
            self.now = tick * 0.25
            self.assertIsNone(self.live.scene()['value'])
        self.assertLessEqual(self.host.read.call_count, 10)
        self.assertEqual(self.live._scene_backoff, 10.0)
        # Recovery remains possible and resets backoff, rather than permanently disabling reads.
        self.now = self.live._scene_retry_at
        self.host.read.return_value = {'ok': True, 'value': 1}
        self.assertEqual(self.live.scene()['value'], 1)
        self.assertEqual(self.live._scene_backoff, 0.5)

    def test_partial_failure_does_not_publish_partial_scene(self):
        self.host.read.side_effect = [dict(ok=True, value=1), dict(ok=False, value=None)]
        self.assertIsNone(self.live.scene()['value'])
        self.assertEqual(self.host.read.call_count, 2)

    def test_unknown_scene_does_not_dispatch_false_battle_end(self):
        self.service()
        self.live._scene_cbs = [Mock()]
        self.live.scene = Mock(side_effect=[{'value': 1}, {'value': None}, {'value': 2}])
        self.live._stop = types.SimpleNamespace(is_set=lambda: False,
                                                wait=Mock(side_effect=[False, False, True]))
        self.live._pump()
        self.live._scene_cbs[0].assert_called_once_with({'value': 2})

    def test_unexpected_fault_is_still_logged_by_pump(self):
        self.service()
        self.live._scene_cbs = [Mock()]
        self.host.block.side_effect = RuntimeError('real shared-memory fault')
        self.live._stop = types.SimpleNamespace(is_set=lambda: False,
                                                wait=Mock(return_value=True))
        self.live._pump()
        self.assertIn('real shared-memory fault', self.logs.call_args.args[0])


if __name__ == '__main__':
    unittest.main()
