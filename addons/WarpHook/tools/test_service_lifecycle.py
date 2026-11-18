"""Offline regressions for Service.stop shared-host cleanup."""

import ast
import pathlib
import threading
import unittest
from types import SimpleNamespace


SOURCE = pathlib.Path(__file__).resolve().parents[1] / 'warphook' / 'service.py'


def load_service_stop():
    tree = ast.parse(SOURCE.read_text(encoding='utf-8'))
    source_cls = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == 'Service'
    )
    stop = next(
        node for node in source_cls.body
        if isinstance(node, ast.FunctionDef) and node.name == 'stop'
    )
    service_cls = ast.ClassDef(
        name='Service', bases=[], keywords=[], body=[stop], decorator_list=[]
    )
    module = ast.fix_missing_locations(
        ast.Module(body=[service_cls], type_ignores=[])
    )
    state = {
        'calls': [],
        'logs': [],
        'registry': {},
    }
    namespace = {
        'threading': threading,
        'traceback': __import__('traceback'),
        'gacha': SimpleNamespace(
            stop=lambda owner: state['calls'].append(('gacha.stop', owner)) or True
        ),
        '_service_registry': lambda: state['registry'],
        'log': lambda message: state['logs'].append(message),
    }
    exec(compile(module, str(SOURCE), 'exec'), namespace)
    return namespace['Service'], state


class FakeHost:
    def __init__(self, state, push_result='已停用'):
        self.state = state
        self.push_result = push_result
        self._closed = False

    def _act(self, owner, callback):
        self.state['calls'].append(('host._act', owner))
        return callback()

    def configure(self, **kwargs):
        self.state['calls'].append(('host.configure', kwargs))
        return self

    def push(self, enabled=None):
        self.state['calls'].append(('host.push', enabled))
        return self.push_result


class ServiceLifecycleTests(unittest.TestCase):
    def make_service(self, service_type, state, *, host=None, shared=True):
        service = service_type()
        service.addon_name = 'NoGacha'
        service.name = 'NoGacha'
        service.shared = shared
        service._stop = threading.Event()
        service._thread = None
        service._host = host
        service._closed = False
        service.log = lambda message: state['logs'].append(message)
        state['registry'][service.addon_name] = service
        return service

    def test_stop_clears_shared_owner_after_stopping_watcher(self):
        service_type, state = load_service_stop()
        host = FakeHost(state)
        service = self.make_service(service_type, state, host=host)

        self.assertTrue(service.stop())

        self.assertEqual(
            [call[0] for call in state['calls']],
            ['gacha.stop', 'host._act', 'host.configure', 'host.push'],
        )
        self.assertEqual(state['calls'][2][1], {'hooks': [], 'texts': []})
        self.assertFalse(state['calls'][3][1])
        self.assertTrue(service._closed)
        self.assertNotIn(service.addon_name, state['registry'])

    def test_failed_shared_cleanup_keeps_service_registered(self):
        service_type, state = load_service_stop()
        host = FakeHost(state, push_result='共享内存不可用')
        service = self.make_service(service_type, state, host=host)

        self.assertFalse(service.stop())

        self.assertFalse(service._closed)
        self.assertIs(state['registry'][service.addon_name], service)
        self.assertTrue(any('保留服务登记' in line for line in state['logs']))

    def test_non_shared_service_skips_shared_host_cleanup(self):
        service_type, state = load_service_stop()
        host = FakeHost(state)
        service = self.make_service(service_type, state, host=host, shared=False)

        self.assertTrue(service.stop())

        self.assertEqual([call[0] for call in state['calls']], ['gacha.stop'])
        self.assertTrue(service._closed)

    def test_closed_host_is_not_reopened_during_unload(self):
        service_type, state = load_service_stop()
        host = FakeHost(state)
        host._closed = True
        service = self.make_service(service_type, state, host=host)

        self.assertTrue(service.stop())

        self.assertEqual([call[0] for call in state['calls']], ['gacha.stop'])
        self.assertTrue(service._closed)


if __name__ == '__main__':
    unittest.main(verbosity=2)
