"""Production Host.call policy and command-wait diagnostic regressions."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'addons/WarpHook'))
from warphook.host import Host


class CallPolicyTests(unittest.TestCase):
    def make_host(self):
        host = object.__new__(Host)
        host.block = lambda: SimpleNamespace(cfg=SimpleNamespace(vars=[0] * 8))
        return host

    def test_bank_load_is_dispatched_without_unsafe_override(self):
        host = self.make_host()
        calls = []
        host._command = lambda *a, **kw: calls.append((a, kw)) or '已执行'
        self.assertEqual(host.call('SoundManager::LoadBankFromLocal', slot=24,
                                   args=(('slot', 25), 0, 0), sig='S,B,B',
                                   ret='void'), '已执行')
        self.assertEqual(len(calls), 1)
        self.assertIn('LoadBankFromLocal', calls[0][0][1])

    def test_method_name_is_not_a_policy_gate_but_arguments_are_validated(self):
        host = self.make_host()
        host._command = lambda *a, **kw: '已执行'
        self.assertEqual(host.call('Example::Method', ret='void'), '已执行')
        self.assertIn('对象槽', host.call('Example::Method', slot=999, ret='void'))
        self.assertIn('未知返回值', host.call('Example::Method', ret='invalid'))

    def test_repeated_waits_are_coalesced_without_hiding_first_failure(self):
        host = self.make_host()
        with patch('warphook.host.time.monotonic', side_effect=[10, 11, 12, 41]), \
             patch('warphook.host.log') as log:
            for _ in range(4):
                host._command_warning('seq=1 ack=0')
        self.assertEqual(log.call_count, 2)
        self.assertIn('合并 2 条', log.call_args.args[0])


if __name__ == '__main__':
    unittest.main()
