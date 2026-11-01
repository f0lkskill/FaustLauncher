"""Single-slot mailbox regression using production Host methods, no game."""
import sys
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'addons/WarpHook'))
from warphook.host import Host, CMD_RES_BUSY, _command_transaction


class MailboxTests(unittest.TestCase):
    def test_concurrent_commands_cannot_overwrite_payload(self):
        hdr = SimpleNamespace(cmd_seq=0, cmd_ack=0, cmd_result=0,
                              cmd_text=b'', cmd_type=0, vars=[0]*8)
        host = object.__new__(Host)
        host.block = lambda: SimpleNamespace(cfg=hdr)
        stop = threading.Event()
        received = []
        def pump():
            while not stop.is_set():
                if hdr.cmd_seq != hdr.cmd_ack:
                    seq, text = hdr.cmd_seq, hdr.cmd_text
                    time.sleep(.003)
                    received.append(text)
                    hdr.cmd_result = 0
                    hdr.cmd_ack = seq
                stop.wait(.001)
        worker = threading.Thread(target=pump)
        worker.start()
        results = []
        threads = [threading.Thread(target=lambda n=n: results.append(
            host._command(5, f'payload-{n}', timeout=1))) for n in range(16)]
        try:
            for t in threads: t.start()
            for t in threads: t.join(3)
            self.assertTrue(all(not t.is_alive() for t in threads))
            self.assertEqual(results, ['已执行']*16)
            self.assertEqual(set(received), {f'payload-{n}'.encode() for n in range(16)})
        finally:
            stop.set()
            worker.join(2)

    def test_busy_timeout_does_not_overwrite_previous_request(self):
        hdr = SimpleNamespace(cmd_seq=8, cmd_ack=8, cmd_result=CMD_RES_BUSY,
                              cmd_text=b'original', cmd_type=5, vars=[0]*8)
        host = object.__new__(Host)
        host.block = lambda: SimpleNamespace(cfg=hdr)
        result = host._command(3, 'new', timeout=.01)
        self.assertIn('通道忙', result)
        self.assertEqual((hdr.cmd_seq, hdr.cmd_text, hdr.cmd_type), (8,b'original',5))

    def test_bool_call_returns_real_bool_not_integer(self):
        host = object.__new__(Host)
        hdr = SimpleNamespace(vars=[0]*8)
        host.block = lambda: SimpleNamespace(cfg=hdr)
        host._command = lambda *a, **kw: '已执行'
        for bits, expected in ((0,False),(1,True),(0x123400,False),(0x123401,True)):
            hdr.vars[6] = bits
            value = host.call('SoundManager::IsLoadedBank',ret='bool')
            self.assertIs(value,expected)

    def test_global_lock_covers_result_decoding_across_instances(self):
        state = {'result': None}
        output = []
        @_command_transaction
        def transaction(value):
            state['result'] = value
            time.sleep(.003)
            output.append((value, state['result']))
        threads = [threading.Thread(target=transaction,args=(n,)) for n in range(16)]
        for t in threads: t.start()
        for t in threads: t.join(2)
        self.assertTrue(all(a==b for a,b in output))
        self.assertEqual(len(output),16)

if __name__ == '__main__':
    unittest.main()
