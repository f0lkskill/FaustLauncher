"""Per-process bank submission cache, including unreliable IsLoadedBank=False."""
import importlib.util
from pathlib import Path
import threading
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('bank_test_helpers', Path(__file__).resolve().parents[1] / 'test/test_bgm_standalone.py')
helpers = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helpers)


class BankCacheTests(unittest.TestCase):
    def setUp(self):
        self.audio = helpers.load_audio()
        self.audio.game_dir = lambda: 'C:/Games/Limbus Company'
        self.session = (123, 456)
        self.audio._bank_session = lambda: self.session
        self.host = helpers.Host()
        original = self.host.call
        def call(method, **kw):
            result = original(method, **kw)
            return False if method.endswith('IsLoadedBank') else result
        self.host.call = call

    def loads(self):
        return [e for e in self.host.events if e[0] == 'call' and e[1].endswith('LoadBankFromLocal')]

    def test_false_query_repeated_bank_loads_pair_only_once(self):
        for _ in range(4):
            self.assertTrue(self.audio.ensure_bank(self.host, 'BGM_Test')[0])
        self.assertEqual(len(self.loads()), 2)
        self.assertFalse(self.audio.play(self.host, 'Test', bank='BGM_Test')['verified'])
        self.assertEqual(len(self.loads()), 2)

    def test_pid_reuse_creation_time_and_bank_name_are_isolated(self):
        self.audio.ensure_bank(self.host, 'BGM_A')
        self.audio.ensure_bank(self.host, 'BGM_B')
        self.session = (123, 789)
        self.audio.ensure_bank(self.host, 'BGM_A')
        self.assertEqual(len(self.loads()), 6)

    def test_failure_not_cached(self):
        self.host.error = ('SoundManager::LoadBankFromLocal', '超时')
        self.assertFalse(self.audio.ensure_bank(self.host, 'BGM_Test')[0])
        self.host.error = None
        self.assertTrue(self.audio.ensure_bank(self.host, 'BGM_Test')[0])
        self.assertEqual(len(self.loads()), 3)

    def test_unknown_session_never_reuses_cache(self):
        self.session = None
        for _ in range(2):
            self.audio.ensure_bank(self.host, 'BGM_Test')
        self.assertEqual(len(self.loads()), 4)

    def test_explicit_invalidation(self):
        self.audio.ensure_bank(self.host, 'BGM_Test')
        self.audio.invalidate_bank_cache()
        self.audio.ensure_bank(self.host, 'BGM_Test')
        self.assertEqual(len(self.loads()), 4)

    def test_parallel_requests_share_one_pair_and_scratch_transaction(self):
        barrier = threading.Barrier(8)
        results = []
        def run():
            barrier.wait()
            results.append(self.audio.ensure_bank(self.host, 'BGM_Test')[0])
        threads = [threading.Thread(target=run) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(3)
            self.assertFalse(t.is_alive())
        self.assertEqual(results, [True] * 8)
        self.assertEqual(len(self.loads()), 2)

    def test_game_restart_during_load_not_cached(self):
        with patch.object(self.audio, '_bank_session', side_effect=[(1, 2), (2, 3)]):
            self.audio.ensure_bank(self.host, 'BGM_Test')
        self.assertFalse(self.audio._BANK_SUBMITTED)


if __name__ == '__main__':
    unittest.main()
