import unittest
from unittest import mock
from helpers import FakeAsk
from cocheck.providers.base import parse_answers
from cocheck.providers import build

T = [{'id': 'x-1', 'asks': [{'i': '0', 'k': 'el', 'q': '?'}]}, {'id': 'y-1', 'asks': [{'i': '0', 'k': 'el', 'q': '?'}]}]


class Retry(unittest.TestCase):
    def test_429_backoff_then_ok(self):
        p = FakeAsk(fail=2)
        with mock.patch('cocheck.providers.base.time.sleep') as sl:
            out = p.ask_batch(T[:1])
        self.assertEqual(out, {'x-1': {'0': 'yes'}})
        self.assertEqual([c.args[0] for c in sl.call_args_list], [4, 8])     # 429 指数退避

    def test_other_error_short_retry(self):
        p = FakeAsk(fail=1, err='connection reset')
        with mock.patch('cocheck.providers.base.time.sleep') as sl: p.ask_batch(T[:1])
        self.assertEqual(sl.call_args_list[0].args[0], 2)

    def test_give_up_leaves_ticket_open(self):
        p = FakeAsk(fail=99)
        with mock.patch('cocheck.providers.base.time.sleep'), mock.patch('builtins.print'):
            out = p.ask_batch(T, jobs=2)
        self.assertEqual(out, {}); self.assertEqual(p.calls, 10)


class Parse(unittest.TestCase):
    def test_parse_noisy(self):
        self.assertEqual(parse_answers('好的：```json\n{"0": "Yes", "1": "可能"}\n```'), {'0': 'yes', '1': 'unsure'})

    def test_unknown_type(self):
        with self.assertRaises(ValueError): build('x', {'type': 'nope'})




class BackendPick(unittest.TestCase):
    def test_pick(self):
        from unittest import mock
        from cocheck.providers import embeddinggemma as eg
        self.assertEqual(eg.pick_backend('torch'), 'torch'); self.assertEqual(eg.pick_backend('mlx'), 'mlx')
        with mock.patch.object(eg, 'apple_silicon', return_value=False): self.assertEqual(eg.pick_backend(), 'torch')
        with mock.patch.object(eg, 'apple_silicon', return_value=True), mock.patch.dict('sys.modules', {'mlx_vlm': object()}):
            self.assertEqual(eg.pick_backend(), 'mlx')

class RemoteEnsure(unittest.TestCase):
    def test_ensure_then_retry(self):
        import os, tempfile, threading, json
        from http.server import HTTPServer, BaseHTTPRequestHandler
        from cocheck.providers.remote import Remote
        class H(BaseHTTPRequestHandler):
            def do_GET(self):
                b = json.dumps({'providers': [{'name': 'eg2'}]}).encode()
                self.send_response(200); self.send_header('Content-Length', str(len(b))); self.end_headers(); self.wfile.write(b)
            def log_message(self, *a): pass
        srv = HTTPServer(('127.0.0.1', 0), H); port = srv.server_port; srv.server_close()   # 先占号再放掉：此时连不上
        flag = os.path.join(tempfile.mkdtemp(), 'up')
        holder = {}
        def start():
            holder['s'] = s = HTTPServer(('127.0.0.1', port), H); threading.Thread(target=s.serve_forever, daemon=True).start()
        import cocheck.providers.remote as R
        real = R.subprocess.run
        def fake_run(cmd, **k):
            start(); open(flag, 'w').close(); return real('true', **k)
        with mock.patch.object(R.subprocess, 'run', fake_run):
            p = Remote('eg2', base_url='http://127.0.0.1:%d' % port, ensure='loco ensure eg2')
            self.assertTrue(p.ping()['ok']); self.assertTrue(os.path.exists(flag))
        holder['s'].shutdown()


if __name__ == '__main__': unittest.main()
