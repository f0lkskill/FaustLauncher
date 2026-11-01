"""Stopping temporary music must stop the additional layer, not just base BGM."""
import sys
from pathlib import Path
from types import SimpleNamespace
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'addons/WarpHook'))
from warphook import audio


class AudioStopTests(unittest.TestCase):
    def test_stops_added_then_base_then_restores(self):
        calls = []
        def call(method, **kw):
            calls.append((method, kw))
            return '已执行'
        result = audio.stop(SimpleNamespace(call=call))
        self.assertTrue(result['ok'])
        self.assertEqual([m.split('::')[1] for m, _ in calls],
                         ['StopAddedBGM', 'StopBGM', 'StartBGM'])
        self.assertEqual(calls[0][1]['args'], (audio.STOP_MODE_IMMEDIATE, 0))
        self.assertEqual(calls[0][1]['sig'], 'FMOD.Studio.STOP_MODE,B')

    def test_added_stop_failure_does_not_claim_restore(self):
        calls = []
        def call(method, **kw):
            calls.append(method)
            return '超时'
        result = audio.stop(SimpleNamespace(call=call))
        self.assertFalse(result['ok'])
        self.assertIn('停止附加曲失败', result['reason'])
        self.assertEqual(calls, ['BattleSoundGenerator::StopAddedBGM'])

    def test_no_restore_still_stops_both_layers(self):
        calls = []
        def call(method, **kw):
            calls.append(method)
            return '已执行'
        self.assertTrue(audio.stop(SimpleNamespace(call=call), restore=False)['ok'])
        self.assertEqual(len(calls), 2)


if __name__ == '__main__':
    unittest.main()
