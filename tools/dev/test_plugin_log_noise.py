"""插件日志回归：不注入、不启动游戏，不依赖第三方测试库。"""
import contextlib
import io
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]


def load_plugin(name):
    output, debug = [], []
    logging = SimpleNamespace(write=lambda text, **_: output.append(text),
                              debug=lambda text, **_: debug.append(text),
                              is_debug_enabled=lambda: False)
    service = SimpleNamespace(start=lambda: None)
    space = SimpleNamespace(log=logging, plugin=SimpleNamespace(Service=lambda **_: service))
    ns = SimpleNamespace(space=lambda _: space)
    manager = SimpleNamespace(get_addon_info=lambda _: {'settings': {'enable': False, '自动注入': False, '播报切换': False}})
    path = ROOT / 'addons' / name / 'scr.py'
    env = {'__file__': str(path), 'ADDON_ARG': {'AddonName': name, 'Namespaces': ns, 'AddonManager': manager}}
    exec(compile(path.read_text(encoding='utf-8'), str(path), 'exec'), env)
    output.clear()
    return env, space, output, debug


class PluginLoggingTests(unittest.TestCase):
    def test_no_gacha_uses_namespace_logger(self):
        env, _, output, _ = load_plugin('NoGacha')
        with contextlib.redirect_stdout(io.StringIO()) as console:
            env['_log']('manual feedback')
        self.assertEqual(output, ['manual feedback'])
        self.assertEqual(console.getvalue(), '')

    def test_repeated_rounds_are_quiet_and_skip_diagnostics(self):
        env, space, output, _ = load_plugin('BattleBGMExtend')
        space.game = SimpleNamespace(bgm_lock=lambda _: True,
                                     bgm_lock_status=lambda: self.fail('normal mode read lock counters'))
        env['_lock_ready'] = True
        battle = SimpleNamespace(ok=True, units=[])
        for _ in range(10):
            env['_on_round'](battle)
        self.assertEqual(output, [])

    def test_errors_are_throttled_but_first_and_new_error_visible(self):
        env, _, output, _ = load_plugin('BattleBGMExtend')
        with patch.object(env['time'], 'monotonic', side_effect=[0, 1, 2, 31]):
            for text in ['failure A', 'failure A', 'failure B', 'failure A']:
                env['_log_error'](text)
        self.assertEqual(output, ['failure A', 'failure B', 'failure A'])

    def test_debug_lock_counters_use_debug_channel(self):
        env, space, output, debug = load_plugin('BattleBGMExtend')
        space.log.is_debug_enabled = lambda: True
        space.game = SimpleNamespace(bgm_lock_status=lambda: {'rows': []})
        env['_log_lock_status']()
        self.assertEqual(output, [])
        self.assertTrue(any('换曲锁实况' in row for row in debug))

    def test_manual_actions_visible_when_announcements_disabled(self):
        env, space, output, _ = load_plugin('BattleBGMExtend')
        space.game = SimpleNamespace(bgm_lock=lambda _: True, bgm_stop=lambda: {'ok': True})
        env['_restore']()
        env['_reload']()
        self.assertTrue(any('手动操作' in row for row in output))
        self.assertTrue(any('规则已重新载入' in row for row in output))

    def test_manual_restore_failure_always_has_feedback(self):
        env, space, output, _ = load_plugin('BattleBGMExtend')
        space.game = SimpleNamespace(bgm_lock=lambda _: False)
        env['_restore']()
        env['_restore']()
        self.assertEqual(sum('手动恢复原曲失败' in row for row in output), 2)

    def test_duplicate_battle_end_does_not_repeat_announcement(self):
        env, space, output, _ = load_plugin('BattleBGMExtend')
        space.game = SimpleNamespace(bgm_lock=lambda _: True)
        env['_say'] = env['_log']
        env['_battle_id'] = object()
        env['_on_battle_end'](None)
        env['_on_battle_end'](None)
        self.assertEqual(len(output), 1)


if __name__ == '__main__':
    unittest.main()
