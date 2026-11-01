"""Round delivery regressions: execute the real Live/Battle methods with fake I/O."""
import ast
import pathlib
import threading
import types
import unittest
from unittest.mock import Mock

LIVE = (pathlib.Path(__file__).resolve().parents[1]
        / 'addons' / 'WarpHook' / 'warphook' / 'live.py')


class RoundDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.now = 0.0
        self.hits = 0
        self.logs = Mock()
        self.host = Mock()
        self.host.hits.side_effect = lambda **kw: self.hits
        self.unit = types.SimpleNamespace(id=1, identity=10115, alive=True)
        self.objects = types.SimpleNamespace(
            SLOT_MANAGER=30, access=Mock(return_value=Mock()),
            count=Mock(return_value=1), units=Mock(return_value=[self.unit]))
        self.ns = dict(threading=threading,
                       time=types.SimpleNamespace(monotonic=lambda: self.now),
                       objects=self.objects, SCENES={1: '战斗'}, log=self.logs)
        tree = ast.parse(LIVE.read_text(encoding='utf-8-sig'))
        tree.body = [node for node in tree.body
                     if isinstance(node, ast.ClassDef) and node.name in ('Live', 'Battle')]
        exec(compile(tree, str(LIVE), 'exec'), self.ns)
        self.live = self.ns['Live']('round-test', host=self.host)
        self.live.scene = Mock(return_value={'value': 1})
        self.callback = Mock()
        self.live._round_cbs.append(self.callback)

    def poll(self, hits=None, advance=0):
        if hits is not None:
            self.hits = hits
        self.now += advance
        return self.live._poll_round()

    def test_first_nonzero_hit_delivers_immediately(self):
        self.assertTrue(self.poll(1))
        battle = self.callback.call_args.args[0]
        self.assertIsInstance(battle, self.ns['Battle'])
        self.assertEqual(battle.units, [self.unit])
        self.assertFalse(self.live._round_pending)
        self.host.hits.assert_called_once_with(method='OnRoundStart_Model', owner='round-test')

    def test_zero_baseline_and_time_do_not_fabricate_hook_hits(self):
        for _ in range(30):
            self.assertFalse(self.poll(0, advance=10))
        self.callback.assert_not_called()
        self.objects.units.assert_not_called()
        self.assertTrue(self.poll(1))

    def test_each_new_real_hit_delivers_but_repeated_reads_do_not(self):
        for hits in (0, 1, 1, 2, 2, 3, 3):
            self.poll(hits, advance=1)
        self.assertEqual(self.callback.call_count, 3)
        self.assertEqual(self.objects.units.call_count, 3)

    def test_burst_of_hits_is_one_current_snapshot_not_replayed_history(self):
        self.poll(0)
        self.assertTrue(self.poll(5))
        self.assertFalse(self.poll(5, advance=10))
        self.callback.assert_called_once()

    def test_reset_to_zero_then_new_hit_is_not_hidden_by_old_high_water(self):
        self.poll(8)
        self.assertFalse(self.poll(0))
        self.assertTrue(self.poll(1))
        self.assertEqual(self.callback.call_count, 2)

    def test_reset_already_nonzero_delivers_new_generation(self):
        self.poll(8)
        self.assertTrue(self.poll(1))
        self.assertFalse(self.poll(1))
        self.assertEqual(self.callback.call_count, 2)

    def test_failed_snapshot_is_retried_without_another_hit(self):
        self.objects.units.return_value = []
        self.assertFalse(self.poll(1))
        self.assertTrue(self.live._round_pending)
        self.callback.assert_not_called()
        self.objects.units.return_value = [self.unit]
        self.assertFalse(self.poll(1, advance=0.24))
        self.assertEqual(self.objects.units.call_count, 1)
        self.assertTrue(self.poll(1, advance=0.01))
        self.callback.assert_called_once()
        self.assertFalse(self.poll(1, advance=10))
        self.assertEqual(self.live._round_backoff, 0.25)

    def test_failed_snapshot_merges_more_hits_and_survives_reset(self):
        self.objects.units.return_value = []
        self.poll(4)
        self.poll(6, advance=0.1)
        self.poll(0, advance=0.1)
        self.assertTrue(self.live._round_pending)
        self.objects.units.return_value = [self.unit]
        self.assertTrue(self.poll(1, advance=0.05))
        self.callback.assert_called_once()
        self.assertFalse(self.poll(1, advance=10))

    def test_only_failures_back_off_and_retries_are_bounded(self):
        self.objects.units.return_value = []
        for tick in range(240):
            self.now = tick * 0.25
            self.poll(1)
        self.assertLess(self.objects.units.call_count, 20)
        self.assertEqual(self.live._round_backoff, 4.0)
        self.objects.units.return_value = [self.unit]
        self.now = self.live._round_retry_at
        self.assertTrue(self.poll(1))
        self.assertTrue(self.poll(2))  # no success-path delay
        self.assertEqual(self.callback.call_count, 2)

    def test_snapshot_exception_is_pending_backed_off_logged_and_recovers(self):
        original = self.live.battle
        self.live.battle = Mock(side_effect=RuntimeError('snapshot exploded'))
        self.live._service = types.SimpleNamespace(_phase='monitoring')
        self.live._stop = types.SimpleNamespace(is_set=lambda: False,
                                               wait=Mock(return_value=True))
        self.hits = 1
        self.live._pump()
        self.assertTrue(self.live._round_pending)
        self.assertGreater(self.live._round_retry_at, self.now)
        self.assertIn('snapshot exploded', self.logs.call_args.args[0])
        self.callback.assert_not_called()
        self.live.battle = original
        self.now = self.live._round_retry_at
        self.assertTrue(self.poll(1))
        self.callback.assert_called_once()

    def test_callback_error_is_logged_without_blocking_other_handlers_or_replay(self):
        self.callback.side_effect = RuntimeError('business callback exploded')
        second = Mock()
        self.live._round_cbs.append(second)
        self.assertTrue(self.poll(1))
        second.assert_called_once()
        self.assertIn('business callback exploded', self.logs.call_args.args[0])
        self.assertFalse(self.poll(1, advance=10))
        self.callback.assert_called_once()

    def test_stop_before_poll_never_reads_or_delivers(self):
        self.live._stop.set()
        self.assertFalse(self.poll(1))
        self.host.hits.assert_not_called()
        self.callback.assert_not_called()

    def test_stop_during_snapshot_prevents_callback_and_keeps_pending(self):
        def units(*args, **kwargs):
            self.live._stop.set()
            return [self.unit]
        self.objects.units.side_effect = units
        self.assertFalse(self.poll(1))
        self.callback.assert_not_called()
        self.assertTrue(self.live._round_pending)

    def test_pump_uses_cancellable_event_wait_not_sleep(self):
        self.live._service = types.SimpleNamespace(_phase='monitoring')
        self.live._stop = types.SimpleNamespace(is_set=lambda: False,
                                               wait=Mock(return_value=True))
        self.hits = 1
        self.live._pump()
        self.callback.assert_called_once()
        self.live._stop.wait.assert_called_once_with(0.25)


if __name__ == '__main__':
    unittest.main()
