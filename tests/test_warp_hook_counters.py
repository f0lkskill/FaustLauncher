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
            'argc': 1, 'actions': 0}
        host._layout = lambda: (hooks, [None] * mod.HOST_MAX_TEXTS, {1})
        row = mod.HostHook.from_address(block.address + mod.HOST_HOOK_OFFSET
                                       + mod.HOST_HOOKS_PRIMARY * mod.HOST_HOOK_SIZE)
        with patch.object(mod, 'ensure_exports'):
            host._write_config(block)
            row.hits, row.blocked = 17, 3
            host._write_config(block)
            self.assertEqual((row.hits, row.blocked), (17, 3))
            hooks[mod.HOST_HOOKS_PRIMARY]['argc'] = 2
            host._write_config(block)
            self.assertEqual((row.hits, row.blocked), (0, 0))

if __name__ == '__main__':
    unittest.main()
