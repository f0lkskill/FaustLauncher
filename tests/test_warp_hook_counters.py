"""Exercise actual shared-memory configuration writes without injecting."""
import ctypes
from pathlib import Path
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'addons/WarpHook'))
import warphook.host as mod

class CounterTests(unittest.TestCase):
    def test_lock_diagnostics_reads_actual_rows_without_initializing(self):
        from warphook import audio
        memory = ctypes.create_string_buffer(2 * 1024 * 1024)
        cfg = mod.HostHeader.from_buffer(memory)
        block = SimpleNamespace(address=ctypes.addressof(memory), cfg=cfg)
        host = object.__new__(mod.Host)
        host._block = block
        host._owners = {'test': {'on': True}}
        host.dedupe_ms = 0
        hooks = [None] * mod.HOST_MAX_HOOKS
        for i, item in enumerate(audio.guard_hook_defs()):
            hooks[mod.HOST_HOOKS_PRIMARY + i] = dict(item, owner='test')
        host._layout = lambda: (hooks, [None] * mod.HOST_MAX_TEXTS, {1})
        with patch.object(mod, 'ensure_exports'):
            host._write_config(block)
        cfg.vars[audio.LOCK_SLOT] = 0
        row = mod.HostHook.from_address(block.address + mod.HOST_HOOK_OFFSET
                                       + mod.HOST_HOOKS_PRIMARY * mod.HOST_HOOK_SIZE)
        row.hits, row.blocked = 5, 4
        with patch.object(host, 'block', side_effect=AssertionError('must not initialize')):
            status = audio.guard_status(host, owner='test')
        self.assertEqual(status['configured'], 4)
        added = next(row for row in status['rows'] if row['method'] == 'StopAddedBGM')
        self.assertTrue(added['flags'] & mod.HF_BLOCK)
        self.assertEqual(added['guard_var'], audio.LOCK_SLOT)
        self.assertEqual(status['missing'], [])
        self.assertEqual(status['rows'][0]['blocked'], 4)
        self.assertEqual(status['rows'][0]['guard_current'], 0)
        self.assertIsNone(status['rows'][0]['installed'])
        self.assertFalse(status['installed_verified'])
        hooks[mod.HOST_HOOKS_PRIMARY + 2] = None
        self.assertIn('BattleSoundGenerator.StopBGM',
                      audio.guard_status(host, owner='test')['missing'])
        host._block = None
        self.assertEqual(audio.guard_status(host, owner='test')['configured'], 0)

    def test_stop_added_lock_is_not_reported_ready_when_shared_slots_exhausted(self):
        from warphook import audio
        from warphook.live import Live
        memory = ctypes.create_string_buffer(2 * 1024 * 1024)
        cfg = mod.HostHeader.from_buffer(memory)
        host = object.__new__(mod.Host)
        host._block = SimpleNamespace(address=ctypes.addressof(memory), cfg=cfg)
        host.log = lambda *args: None
        host._owners = {
            'other': {'on': True, 'hooks': [{'klass': 'Other', 'method': 'Tick'}], 'texts': []},
            'BattleBGMExtend': {'on': True, 'hooks': [
                {'klass': 'BattleObjectManager', 'method': 'OnRoundStart_Model'}
            ] + audio.guard_hook_defs(), 'texts': []}}
        live = object.__new__(Live)
        live.owner = 'BattleBGMExtend'
        live._extra_hooks = []
        live.host = lambda: host
        live._push = lambda: True
        with patch.object(audio, 'lock', return_value=True):
            result = live.bgm_lock_install()
        self.assertFalse(result['ok'])
        self.assertEqual(result['missing'], ['BattleSoundGenerator.StopAddedBGM'])
        del host._owners['other']
        with patch.object(audio, 'lock', return_value=True):
            result = live.bgm_lock_install()
        self.assertTrue(result['ok'])
        self.assertEqual(result['configured'], 4)

    def test_repush_preserves_live_counters_but_new_entry_resets(self):
        memory = ctypes.create_string_buffer(2 * 1024 * 1024)
        block = SimpleNamespace(address=ctypes.addressof(memory),
                                cfg=SimpleNamespace(enabled=1, dedupe_ms=0))
        host = object.__new__(mod.Host)
        host._owners = {'test': {'on': True}}
        host.dedupe_ms = 0
        hooks = [None] * mod.HOST_MAX_HOOKS
        hooks[mod.HOST_HOOKS_PRIMARY] = {
            'klass': 'BattleObjectManager', 'method': 'OnRoundStart_Model',
            'argc': 1, 'actions': 0, 'block': True, 'guard': (4, 1)}
        host._layout = lambda: (hooks, [None] * mod.HOST_MAX_TEXTS, {1})
        row = mod.HostHook.from_address(block.address + mod.HOST_HOOK_OFFSET
                                       + mod.HOST_HOOKS_PRIMARY * mod.HOST_HOOK_SIZE)
        with patch.object(mod, 'ensure_exports'):
            host._write_config(block)
            self.assertTrue(row.flags & mod.HF_BLOCK)
            self.assertEqual((row.guard_var, row.guard_value), (4, 1))
            row.hits, row.blocked = 17, 3
            host._write_config(block)
            self.assertEqual((row.hits, row.blocked), (17, 3))
            hooks[mod.HOST_HOOKS_PRIMARY]['argc'] = 2
            host._write_config(block)
            self.assertEqual((row.hits, row.blocked), (0, 0))

if __name__ == '__main__':
    unittest.main()
