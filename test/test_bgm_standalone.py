"""无需游戏、DLL、启动器的 BGM 回归：python -m unittest discover -s test -p test_bgm_standalone.py -v"""
import contextlib
import importlib.util
import io
from pathlib import Path
import sys
import threading
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
REAL_THREAD = threading.Thread


def load_audio():
    package = '_bgm_regression_warp'
    modules = {
        package: types.ModuleType(package),
        package + '.objects': types.SimpleNamespace(scene=lambda host: {'scene': 1}),
        package + '.base': types.SimpleNamespace(log=lambda text: None),
    }
    modules[package].__path__ = []
    with patch.dict(sys.modules, modules):
        spec = importlib.util.spec_from_file_location(package + '.audio', ROOT / 'addons/WarpHook/warphook/audio.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


class Host:
    def __init__(self, loaded=False):
        self.events = []
        self.strings = {}
        self.loaded = loaded
        self.error = None

    def make_str(self, text, slot, timeout=2):
        self.strings[slot] = text
        self.events.append(('string', slot, text))
        return '已执行'

    def static_get(self, name, out_slot, timeout=2):
        self.events.append(('static', name, out_slot))
        return '已执行'

    def call(self, method, **kw):
        self.events.append(('call', method, kw, dict(self.strings)))
        if self.error and self.error[0] == method:
            return self.error[1]
        if method.endswith('IsLoadedBank'):
            return self.loaded
        if method.endswith('LoadBankFromLocal') and self.strings[24].endswith('.bank') and not self.strings[24].endswith('.assets.bank'):
            self.loaded = True
        return '已执行'

    def release(self, slot):
        self.events.append(('release', slot))


class AudioRegression(unittest.TestCase):
    def setUp(self):
        self.audio = load_audio()
        self.audio.game_dir = lambda: 'C:/Games/Limbus Company'

    def test_bank_preload_absolute_paths_receiver_and_no_extra_recheck(self):
        host = Host()
        ok, why = self.audio.ensure_bank(host, 'BGM_Default_S7_3')
        self.assertTrue(ok, why)
        calls = [e for e in host.events if e[0] == 'call']
        loads = [e for e in calls if e[1].endswith('LoadBankFromLocal')]
        self.assertEqual([e[3][24] for e in loads], [
            'C:/Games/Limbus Company/LimbusCompany_Data/StreamingAssets/Assets/Sound/FMODBuilds/Desktop/BGM_Default_S7_3.assets.bank',
            'C:/Games/Limbus Company/LimbusCompany_Data/StreamingAssets/Assets/Sound/FMODBuilds/Desktop/BGM_Default_S7_3.bank'])
        self.assertTrue(all(e[2]['slot'] == 26 for e in calls))
        self.assertTrue(all(e[2]['via'] == 'invoke' for e in calls))
        self.assertTrue(all(e[2]['sig'] == 'S,B,B' for e in loads))
        self.assertEqual(sum(e[1].endswith('IsLoadedBank') for e in calls), 1)
        self.assertTrue(calls[-1][3][24].endswith('.bank'))
        self.assertEqual(host.events[-2:], [('release', 24), ('release', 26)])

    def test_unregistered_local_bank_continues_to_play_like_legacy(self):
        host = Host()
        original = host.call
        def not_registered(method, **kw):
            result = original(method, **kw)
            if method.endswith('IsLoadedBank'):
                return False
            return result
        host.call = not_registered
        result = self.audio.play(host, 'Battle_Test', bank='BGM_Test')
        self.assertTrue(result['ok'], result)
        self.assertIs(result['verified'], False)
        calls = [e for e in host.events if e[0] == 'call']
        self.assertEqual(sum(e[1].endswith('IsLoadedBank') for e in calls), 1)
        self.assertEqual([e[1] for e in calls[-2:]],
                         ['BattleSoundGenerator::StopBGM',
                          'BattleSoundGenerator::StartAddBGM'])

    def test_bank_failure_never_stops_current_music(self):
        host = Host()
        host.error = ('SoundManager::LoadBankFromLocal', '调用失败')
        result = self.audio.play(host, 'Battle_Test', bank='BGM_Test')
        self.assertFalse(result['ok'])
        self.assertEqual(result['stage'], 'bank')
        self.assertFalse(any(e[0] == 'call' and e[1].startswith('BattleSoundGenerator') for e in host.events))

    def test_already_loaded_bank_does_not_resolve_directory(self):
        self.audio.game_dir = lambda: self.fail('should not resolve directory')
        self.assertTrue(self.audio.ensure_bank(Host(True), 'BGM_Test')[0])

    def test_missing_game_dir_never_uses_relative_path(self):
        self.audio.game_dir = lambda: None
        host = Host()
        self.assertFalse(self.audio.ensure_bank(host, 'BGM_Test')[0])
        self.assertFalse(any(e[0] == 'call' and e[1].endswith('LoadBankFromLocal') for e in host.events))

    def test_stop_failure_prevents_start_and_releases_string(self):
        host = Host()
        host.error = ('BattleSoundGenerator::StopBGM', '超时')
        result = self.audio.play(host, 'Battle_Test')
        self.assertFalse(result['ok'])
        self.assertEqual(result['stage'], 'stop')
        self.assertFalse(any(e[0] == 'call' and e[1].endswith('StartAddBGM') for e in host.events))
        self.assertEqual(host.events[-1], ('release', 27))

    def test_success_means_submitted_not_audibly_verified(self):
        host = Host()
        result = self.audio.play(host, 'event:/BGM/Battle/Battle_Test')
        self.assertTrue(result['ok'])
        self.assertIs(result['verified'], False)
        calls = [e for e in host.events if e[0] == 'call']
        self.assertEqual([e[1] for e in calls], ['BattleSoundGenerator::StopBGM', 'BattleSoundGenerator::StartAddBGM'])
        self.assertEqual(calls[-1][3][27], 'Battle_Test')
        self.assertNotIn('slot', calls[-1][2])

    def test_make_string_failure_and_exception_release_slot(self):
        for failure in ('超时', RuntimeError('mock string failure')):
            with self.subTest(failure=str(failure)):
                host = Host()
                def make_string(*args, **kwargs):
                    if isinstance(failure, Exception):
                        raise failure
                    return failure
                host.make_str = make_string
                try:
                    result = self.audio.play(host, 'Battle_Test')
                    self.assertFalse(result['ok'])
                except RuntimeError:
                    self.assertIsInstance(failure, RuntimeError)
                self.assertIn(('release', 27), host.events)
                self.assertFalse(any(e[0] == 'call' for e in host.events))

    def test_default_restore_failure_is_reported(self):
        host = Host()
        host.error = ('BattleSoundGenerator::StartBGM', '失败')
        self.assertFalse(self.audio.stop(host)['ok'])


class QueuedThread:
    queue = []
    def __init__(self, target, **kwargs):
        self.target = target
    def start(self):
        self.queue.append(self.target)


class Game:
    def __init__(self):
        self.calls = []
        self.result = {'ok': True, 'verified': False}
    def bgm_lock_install(self):
        return {'ok': True}
    def bgm_lock(self, allow):
        self.calls.append(('lock', allow))
        return True
    def bgm(self, name, **kwargs):
        self.calls.append(('play', name, kwargs))
        return self.result
    def bgm_stop(self):
        self.calls.append(('stop',))
        return {'ok': True}
    def inject(self):
        return {'ok': False, 'reason': '游戏未运行'}


class PluginRegression(unittest.TestCase):
    def setUp(self):
        self.game = Game()
        manager = types.SimpleNamespace(get_addon_info=lambda name: {'settings': {'enable': False, '播报切换': False}})
        namespaces = types.SimpleNamespace(space=lambda name: types.SimpleNamespace(game=self.game))
        spec = importlib.util.spec_from_file_location('_bgm_test_plugin', ROOT / 'addons/BattleBGMExtend/scr.py')
        self.plugin = importlib.util.module_from_spec(spec)
        self.plugin.ADDON_ARG = {'AddonManager': manager, 'Namespaces': namespaces}
        with contextlib.redirect_stdout(io.StringIO()):
            spec.loader.exec_module(self.plugin)
        self.rule = {'id': 'test', 'name': '测试', 'identity': 1,
                     'condition': {'type': 'has_active_buff', 'keyword': 'TestBuff'},
                     'priority': 1, 'bgm': 'Battle_Test', 'bank': 'BGM_Test'}
        self.plugin.RULES = [self.rule]
        self.plugin.WATCHED = {'TestBuff'}
        self.battle = types.SimpleNamespace(units=[types.SimpleNamespace(id=1, identity=1, buffs=[types.SimpleNamespace(key='TestBuff', stack=0)])])
        QueuedThread.queue = []
        self.thread_patch = patch.object(self.plugin.threading, 'Thread', QueuedThread)
        self.thread_patch.start()
        self.addCleanup(self.thread_patch.stop)

    def test_load_rules_keeps_existing_bank_without_editing_rules_file(self):
        raw = (ROOT / 'addons/BattleBGMExtend/rules.json').read_bytes()
        rules = self.plugin._load_rules()
        self.assertTrue(rules)
        self.assertTrue(all(r['bank'] for r in rules))
        self.assertEqual(raw, (ROOT / 'addons/BattleBGMExtend/rules.json').read_bytes())

    def test_zero_stack_buff_counts_as_present(self):
        table = {'TestBuff': types.SimpleNamespace(stack=0)}
        self.assertTrue(self.plugin._match(self.rule, table, {}))
        absence = dict(self.rule, condition={'type': 'round_start_without_buff', 'keyword': 'TestBuff'})
        self.assertFalse(self.plugin._match(absence, table, {}))

    def test_duplicate_round_does_not_enqueue_duplicate_playback(self):
        self.plugin._apply(self.battle)
        self.plugin._apply(self.battle)
        self.assertEqual(len(QueuedThread.queue), 1)
        QueuedThread.queue.pop()()
        plays = [c for c in self.game.calls if c[0] == 'play']
        self.assertEqual(len(plays), 1)
        self.assertEqual(plays[0][2], {'bank': 'BGM_Test', 'wait': False})

    def test_battle_end_cancels_queued_playback_without_battle_audio_call(self):
        self.plugin._apply(self.battle)
        self.plugin._on_battle_end(None)
        QueuedThread.queue.pop()()
        self.assertFalse(any(c[0] in ('play', 'stop') for c in self.game.calls))
        self.assertFalse(self.plugin._pending)

    def test_restore_cancels_queue_and_clears_active_rule(self):
        self.plugin._apply(self.battle)
        self.plugin._active = self.rule
        self.plugin._restore()
        QueuedThread.queue.pop()()
        self.assertIsNone(self.plugin._active)
        self.assertFalse(any(c[0] == 'play' for c in self.game.calls))

    def test_no_match_cancels_queue(self):
        self.plugin._apply(self.battle)
        self.battle.units[0].buffs = []
        self.plugin._apply(self.battle)
        QueuedThread.queue.pop()()
        self.assertFalse(any(c[0] == 'play' for c in self.game.calls))

    def test_errors_are_visible_even_when_announcements_disabled(self):
        self.game.result = {'ok': False, 'reason': '音库未加载'}
        self.plugin._apply(self.battle)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            QueuedThread.queue.pop()()
        self.assertIn('音库未加载', output.getvalue())
        self.assertIn('BGM_Test', output.getvalue())
        self.assertIsNone(self.plugin._active)

    def test_plugin_log_uses_host_persistent_writer(self):
        written = []
        self.plugin.ADDON_ARG['Namespaces'] = types.SimpleNamespace(
            space=lambda name: types.SimpleNamespace(log=types.SimpleNamespace(
                write=lambda text, **kw: written.append((text, kw)))))
        self.plugin._log('diagnostic event')
        self.assertEqual(written, [('diagnostic event', {'prefix': '[BattleBGMExtend]'})])

    def test_submit_has_no_artificial_sleep(self):
        with patch('time.sleep', side_effect=AssertionError('artificial delay')):
            self.plugin._apply(self.battle)
            QueuedThread.queue.pop()()
        self.assertIs(self.plugin._active, self.rule)

    def test_roster_changes_do_not_replay_active_music(self):
        self.plugin._apply(self.battle)
        QueuedThread.queue.pop()()
        mark = self.plugin._battle_id
        for unit_id in (None, 8, 1):
            self.battle.units[0].id = unit_id
            self.battle.units.append(types.SimpleNamespace(id=99, identity=99, buffs=[]))
            self.plugin._apply(self.battle)
            self.battle.units.pop()
        self.assertIs(self.plugin._battle_id, mark)
        self.assertEqual(QueuedThread.queue, [])
        self.assertEqual(sum(c[0] == 'play' for c in self.game.calls), 1)

    def test_priority_floor_survives_absent_condition_and_empty_roster(self):
        self.plugin._apply(self.battle)
        QueuedThread.queue.pop()()
        self.battle.units[0].buffs = []
        self.plugin._apply(self.battle)
        self.battle.units = []
        self.plugin._apply(self.battle)
        self.assertIs(self.plugin._active, self.rule)
        self.assertEqual(QueuedThread.queue, [])
        self.assertEqual(self.game.calls[-1], ('lock', False))

    def test_lower_priority_cannot_replace_active_even_after_condition_disappears(self):
        self.rule['priority'] = 100
        self.plugin._apply(self.battle)
        QueuedThread.queue.pop()()
        lower = dict(self.rule, id='lower', priority=1, bgm='Battle_Lower')
        self.plugin.RULES = [lower]
        self.plugin._apply(self.battle)
        self.assertIs(self.plugin._active, self.rule)
        self.assertEqual(QueuedThread.queue, [])
        self.assertEqual(sum(c[0] == 'play' for c in self.game.calls), 1)

    def test_new_battle_after_end_allows_same_rule_again(self):
        self.plugin._apply(self.battle)
        QueuedThread.queue.pop()()
        self.plugin._on_battle_end(None)
        self.plugin._apply(self.battle)
        QueuedThread.queue.pop()()
        self.assertEqual(sum(c[0] == 'play' for c in self.game.calls), 2)

    def test_higher_priority_replaces_queued_token(self):
        self.plugin._apply(self.battle)
        higher = dict(self.rule, id='higher', priority=2, bgm='Battle_Higher')
        self.plugin.RULES = [higher]
        self.plugin._apply(self.battle)
        QueuedThread.queue.pop(0)()
        self.assertTrue(self.plugin._pending)
        QueuedThread.queue.pop(0)()
        self.assertEqual([c[1] for c in self.game.calls if c[0] == 'play'], ['Battle_Higher'])

    def test_manual_check_logs_entry_queue_duplicate_and_maintenance(self):
        self.game.battle = lambda: self.battle
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.plugin._check_now()
            self.plugin._check_now()
            QueuedThread.queue.pop(0)()
            self.plugin._check_now()
            QueuedThread.queue.pop()()  # 检查仍在队列，播放尚未执行
            QueuedThread.queue.pop(0)()
            self.plugin._check_now()
            QueuedThread.queue.pop(0)()
        text = output.getvalue()
        self.assertIn('收到请求', text)
        self.assertIn('跳过重复请求', text)
        self.assertIn('已排队换曲', text)
        self.assertIn('正在排队', text)
        self.assertIn('维持规则', text)

    def test_manual_snapshot_unavailable_no_match_and_exception_are_visible(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.game.battle = lambda: None
            self.plugin._check_now()
            QueuedThread.queue.pop()()
            self.battle.units = []
            self.game.battle = lambda: self.battle
            self.plugin._check_now()
            QueuedThread.queue.pop()()
            self.game.battle = lambda: (_ for _ in ()).throw(RuntimeError('mock snapshot error'))
            self.plugin._check_now()
            QueuedThread.queue.pop()()
        text = output.getvalue()
        self.assertIn('快照不可用', text)
        self.assertIn('无命中规则', text)
        self.assertIn('手动检测异常：mock snapshot error', text)
        self.assertFalse(self.plugin._check_guard.locked())

    def test_manual_menu_returns_while_state_lock_is_busy(self):
        entered = threading.Event()
        release = threading.Event()
        def hold_state():
            with self.plugin._state_lock:
                entered.set()
                release.wait(2)
        holder = REAL_THREAD(target=hold_state)
        holder.start()
        self.assertTrue(entered.wait(1))
        returned = threading.Event()
        def invoke_menu():
            self.plugin._check_now()
            returned.set()
        menu = REAL_THREAD(target=invoke_menu)
        menu.start()
        try:
            self.assertTrue(returned.wait(0.5), '菜单线程等待了状态锁')
            self.assertEqual(len(QueuedThread.queue), 1)
        finally:
            release.set()
            holder.join(2)
            menu.join(2)

    def test_manual_inject_result_is_not_silent(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.plugin._inject()
        self.assertIn('游戏未运行', output.getvalue())


if __name__ == '__main__':
    unittest.main()