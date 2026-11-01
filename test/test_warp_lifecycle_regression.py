"""Warp lifecycle regression tests, extracted from production AST without imports."""
import ast
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "addons" / "WarpHook" / "warphook"


def source_tree(name):
    return ast.parse((SOURCE / (name + ".py")).read_text(encoding="utf-8-sig"))


def method_node(module, owner, name):
    tree = source_tree(module)
    scope = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == owner) if owner else tree
    return next(n for n in scope.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)


def extracted(module, owner, name, **dependencies):
    """Compile the actual production method; never import Windows/addon modules."""
    node = method_node(module, owner, name)
    node.decorator_list = []
    code = ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[]))
    namespace = dict(dependencies)
    exec(compile(code, str(SOURCE / (module + ".py")), "exec"), namespace)
    return namespace[name]


class FakeThread:
    def __init__(self, alive=True, exit_on_join=False):
        self.alive = alive
        self.exit_on_join = exit_on_join
        self.joins = []

    def is_alive(self):
        return self.alive

    def join(self, timeout=None):
        self.joins.append(timeout)
        if self.exit_on_join:
            self.alive = False


class FakeKernel32:
    """No Win32 calls: record allocation ownership and remote-thread lifetime."""
    def __init__(self, wait_result):
        self.wait_result = wait_result
        self.freed = []
        self.closed = []
        self.waits = []
        self.exit_reads = []

    def OpenProcess(self, *args):
        return 101

    def VirtualAllocEx(self, *args):
        return 303

    def WriteProcessMemory(self, proc, remote, data, size, written):
        written._obj.value = size
        return True

    def GetModuleHandleW(self, *args):
        return 404

    def GetProcAddress(self, *args):
        return 505

    def CreateRemoteThread(self, *args):
        return 202

    def WaitForSingleObject(self, thread, timeout):
        self.waits.append((thread, timeout))
        return self.wait_result

    def GetExitCodeThread(self, thread, code):
        self.exit_reads.append(thread)
        code._obj.value = 1
        return True

    def VirtualFreeEx(self, *args):
        self.freed.append(args)
        return True

    def CloseHandle(self, handle):
        self.closed.append(handle)
        return True


class WarpLifecycleRegression(unittest.TestCase):
    def host(self):
        cls = type("ExtractedHost", (), {
            "_act": extracted("host", "Host", "_act"),
            "_current_owner": extracted("host", "Host", "_current_owner",
                                        _owner_of_caller=lambda: None),
        })
        host = cls()
        host._owner_context = threading.local()
        host.addon_name = "default"
        return host

    def test_host_act_nested_restores_owner_and_return(self):
        host = self.host()
        host._owner_context.owner = "original"

        def outer():
            self.assertEqual(host._current_owner(), "outer")
            self.assertEqual(host._act("inner", host._current_owner), "inner")
            self.assertEqual(host._current_owner(), "outer")
            return "result"

        self.assertEqual(host._act("outer", outer), "result")
        self.assertEqual(host._current_owner(), "original")

    def test_host_act_exception_restores_owner(self):
        host = self.host()
        def fail():
            raise RuntimeError("callback failed")
        with self.assertRaisesRegex(RuntimeError, "callback failed"):
            host._act("temporary", fail)
        self.assertEqual(host._current_owner(), "default")
        self.assertIsNone(host._owner_context.owner)

    def test_host_act_threadlocal_isolation(self):
        host = self.host()
        host._owner_context.owner = "main"
        entered = threading.Barrier(3, timeout=3)
        sampled = threading.Barrier(3, timeout=3)
        observations, errors = [], []

        def worker(owner):
            try:
                def callback():
                    entered.wait()
                    observations.append((owner, host._current_owner()))
                    sampled.wait()
                host._act(owner, callback)
                observations.append((owner + "-restored", host._current_owner()))
            except BaseException as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(owner,), daemon=True)
                   for owner in ("alpha", "beta")]
        for thread in threads:
            thread.start()
        try:
            entered.wait()
            self.assertEqual(host._current_owner(), "main")
            sampled.wait()
        finally:
            for thread in threads:
                thread.join(timeout=4)
        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(errors, [])
        self.assertCountEqual(observations, [("alpha", "alpha"), ("beta", "beta"),
                                           ("alpha-restored", "default"),
                                           ("beta-restored", "default")])

    def test_host_initializes_threadlocal_context(self):
        node = method_node("host", "Host", "__init__")
        assignments = [n for n in ast.walk(node) if isinstance(n, ast.Assign)]
        self.assertTrue(any(
            any(isinstance(t, ast.Attribute) and t.attr == "_owner_context"
                for t in n.targets)
            and isinstance(n.value, ast.Call)
            and ast.dump(n.value.func) == ast.dump(ast.parse("threading.local", mode="eval").body)
            for n in assignments), "Host must initialize a per-thread owner context")

    def test_live_start_passes_its_host_to_service(self):
        node = method_node("live", "Live", "start")
        calls = [n for n in ast.walk(node) if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Name) and n.func.id == "Service"]
        self.assertEqual(len(calls), 1)
        host_args = [kw.value for kw in calls[0].keywords if kw.arg == "host"]
        self.assertEqual(len(host_args), 1)
        self.assertEqual(ast.dump(host_args[0]),
                         ast.dump(ast.parse("self.host()", mode="eval").body))

    def service(self, thread):
        host = SimpleNamespace(close=Mock())
        gacha = SimpleNamespace(stop=Mock())
        registry = {}
        service = SimpleNamespace(_stop=threading.Event(), _thread=thread,
                                  _closed=False, host=host, _host=host,
                                  addon_name="plugin", log=Mock())
        registry[service.addon_name] = service
        stop = extracted("service", "Service", "stop", threading=threading,
                         gacha=gacha, _service_registry=lambda: registry)
        return service, stop, host, gacha, registry

    def test_service_stop_timeout_retains_thread_and_shared_host(self):
        thread = FakeThread()
        service, stop, host, gacha, registry = self.service(thread)
        self.assertIs(stop(service), False)
        self.assertTrue(service._stop.is_set())
        self.assertEqual(thread.joins, [5.0])
        self.assertIs(service._thread, thread)
        self.assertFalse(service._closed)
        self.assertIs(registry["plugin"], service)
        host.close.assert_not_called()
        gacha.stop.assert_not_called()

    def test_service_stop_success_does_not_close_shared_host(self):
        thread = FakeThread(exit_on_join=True)
        service, stop, host, gacha, registry = self.service(thread)
        self.assertIs(stop(service), True)
        self.assertEqual(thread.joins, [5.0])
        self.assertIsNone(service._thread)
        self.assertTrue(service._closed)
        self.assertNotIn("plugin", registry)
        host.close.assert_not_called()
        gacha.stop.assert_called_once_with("plugin")

    def injection(self, wait_result):
        kernel = FakeKernel32(wait_result)
        fake_os = SimpleNamespace(path=SimpleNamespace(abspath=lambda p: p,
                                                      isfile=lambda p: True))
        inject = extracted("base", None, "inject_dll", os=fake_os, time=time,
                           ctypes=ctypes, wintypes=wintypes, _kernel32=kernel,
                           PROCESS_ACCESS=1, MEM_COMMIT_RESERVE=0x3000,
                           PAGE_READWRITE=4, MEM_RELEASE=0x8000,
                           _win_error=lambda stage, pid: f"{stage} PID={pid}")
        return inject(123, "fake-host.dll"), kernel

    def test_inject_timeout_never_frees_live_remote_path(self):
        (ok, message), kernel = self.injection(258)
        self.assertIs(ok, False)
        self.assertIn("超时", message)
        self.assertEqual(kernel.waits, [(202, 10000)])
        self.assertEqual(kernel.freed, [])
        self.assertEqual(kernel.exit_reads, [])
        self.assertCountEqual(kernel.closed, [202, 101])

    def test_inject_wait_failure_never_frees_live_remote_path(self):
        (ok, message), kernel = self.injection(0xFFFFFFFF)
        self.assertIs(ok, False)
        self.assertIn("WaitForSingleObject", message)
        self.assertEqual(kernel.freed, [])
        self.assertEqual(kernel.exit_reads, [])
        self.assertCountEqual(kernel.closed, [202, 101])

    def test_inject_completed_thread_frees_remote_path(self):
        (ok, message), kernel = self.injection(0)
        self.assertIs(ok, True, message)
        self.assertEqual(kernel.exit_reads, [202])
        self.assertEqual(kernel.freed, [(101, 303, 0, 0x8000)])
        self.assertCountEqual(kernel.closed, [202, 101])

    def worker_scenario(self, pid_at, assembly_results=None, injection_results=None):
        """Run the real worker synchronously with an advancing, bounded fake clock."""
        clock = SimpleNamespace(now=0.0)

        class FakeStop:
            def __init__(self):
                self.waits = []

            def is_set(self):
                return clock.now >= 12.0

            def wait(self, timeout):
                self.waits.append(timeout)
                clock.now += max(float(timeout), 0.01)
                return self.is_set()

        stop = FakeStop()
        host = SimpleNamespace(dll_path=lambda: "fake-host.dll", beat=Mock(),
                               poll=Mock(return_value=None))
        service = SimpleNamespace(host=lambda: host, interval=1.0, log=Mock(),
                                  sync=Mock(return_value=True),
                                  _already_running=Mock(return_value=False),
                                  _last_key="old", _hit_seen={"old": 1},
                                  _hit_done={"old"}, _dispatch_hits=Mock(),
                                  _dispatch_events=Mock())
        find_pid = Mock(side_effect=lambda: pid_at(clock.now))
        assembly_values = iter(assembly_results or [])
        assembly = Mock(side_effect=lambda *a, **kw: next(assembly_values, True))
        inject_values = iter(injection_results or [])
        inject = Mock(side_effect=lambda *a: next(inject_values, (True, "loaded")))
        worker = extracted(
            "service", "Service", "_worker", time=SimpleNamespace(monotonic=lambda: clock.now),
            os=SimpleNamespace(path=SimpleNamespace(isfile=lambda p: True)),
            find_game_pid=find_pid, wait_for_gameassembly=assembly,
            inject_dll=inject, _INJECT_LOCK=threading.Lock())
        worker(service, stop)
        self.assertEqual(service._phase, "stopped")
        self.assertFalse(any("后台异常" in str(c.args[0])
                             for c in service.log.call_args_list),
                         service.log.call_args_list)
        self.assertEqual(service._hit_seen, {})
        self.assertEqual(service._hit_done, set())
        return service, host, stop, find_pid, assembly, inject

    def test_service_worker_connects_when_game_starts_late(self):
        service, host, stop, find_pid, assembly, inject = self.worker_scenario(
            lambda now: None if now < 3.0 else 101)
        self.assertGreaterEqual(find_pid.call_count, 4)
        assembly.assert_called_once_with(101, stop_event=stop)
        inject.assert_called_once_with(101, "fake-host.dll")
        self.assertGreater(host.beat.call_count, 0)
        self.assertGreaterEqual(service.sync.call_count, 2)

    def test_service_worker_retries_gameassembly_timeout(self):
        service, host, stop, find_pid, assembly, inject = self.worker_scenario(
            lambda now: 101, assembly_results=[False, True])
        self.assertEqual(assembly.call_count, 2)
        for call in assembly.call_args_list:
            self.assertEqual(call.args, (101,))
            self.assertIs(call.kwargs["stop_event"], stop)
        self.assertIn(2.0, stop.waits)
        inject.assert_called_once_with(101, "fake-host.dll")
        self.assertGreater(host.beat.call_count, 0)

    def test_service_worker_retries_injection_failure(self):
        service, host, stop, find_pid, assembly, inject = self.worker_scenario(
            lambda now: 101, injection_results=[(False, "temporary failure"),
                                               (True, "loaded")])
        self.assertEqual(inject.call_count, 2)
        self.assertEqual([c.args for c in inject.call_args_list],
                         [(101, "fake-host.dll"), (101, "fake-host.dll")])
        self.assertIn(5.0, stop.waits)
        self.assertGreater(host.beat.call_count, 0)
        self.assertEqual(assembly.call_count, 2)

    def test_service_worker_reconnects_when_pid_changes(self):
        service, host, stop, find_pid, assembly, inject = self.worker_scenario(
            lambda now: 101 if now < 4.0 else 202)
        self.assertEqual([c.args for c in inject.call_args_list],
                         [(101, "fake-host.dll"), (202, "fake-host.dll")])
        self.assertEqual([c.args[0] for c in assembly.call_args_list], [101, 202])
        self.assertGreater(host.beat.call_count, 0)
        self.assertTrue(any("old_pid=101 new_pid=202" in c.args[0]
                            for c in service.log.call_args_list))

    def test_sources_parse(self):
        for module in ("host", "live", "service", "base"):
            with self.subTest(module=module):
                self.assertIsInstance(source_tree(module), ast.Module)


if __name__ == "__main__":
    unittest.main(verbosity=2)
