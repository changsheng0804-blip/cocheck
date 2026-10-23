import base64, io, json, unittest, urllib.request, urllib.error
from helpers import Env, FakeAsk
from cocheck import mcp, config


def post(url, body, token=None, by=None):
    h = {'Content-Type': 'application/json'}
    if token: h['Authorization'] = 'Bearer ' + token
    if by: h['X-Cocheck-By'] = by
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        r = op.open(urllib.request.Request(url, json.dumps(body).encode(), h), timeout=10); raw = r.read()
        return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e: return e.code, None


class HttpMcp(unittest.TestCase):
    def setUp(self):
        self.e = Env(token='t0k'); self.e.open(); self.url = self.e.serve() + '/mcp'

    def tearDown(self): self.e.close()

    def rpc(self, method, params=None, id=1, by='tester'):
        return post(self.url, {'jsonrpc': '2.0', 'id': id, 'method': method, 'params': params or {}}, 't0k', by)

    def test_auth(self):
        self.assertEqual(post(self.url, {'jsonrpc': '2.0', 'id': 1, 'method': 'ping'})[0], 401)
        self.assertEqual(post(self.url, {'jsonrpc': '2.0', 'id': 1, 'method': 'ping'}, 'wrong')[0], 401)
        op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with self.assertRaises(urllib.error.HTTPError) as cm: op.open(self.e.url + '/v1/projects', timeout=5)
        self.assertEqual(cm.exception.code, 401)
        self.assertEqual(op.open(self.e.url + '/cocheck-strip.js', timeout=5).status, 200)   # 组件不用令牌

    def test_handshake(self):
        code, r = self.rpc('initialize', {'protocolVersion': '2025-06-18'})
        self.assertEqual(r['result']['serverInfo']['name'], 'cocheck')
        self.assertEqual(post(self.url, {'jsonrpc': '2.0', 'method': 'notifications/initialized'}, 't0k')[0], 202)
        names = {t['name'] for t in self.rpc('tools/list')[1]['result']['tools']}
        self.assertTrue({'cocheck_next_ticket', 'cocheck_answer', 'cocheck_status'} <= names)
        self.assertEqual(self.rpc('nope/x')[1]['error']['code'], -32601)
        code, r = post(self.url, [{'jsonrpc': '2.0', 'id': 1, 'method': 'ping'}, {'jsonrpc': '2.0', 'id': 2, 'method': 'ping'}], 't0k')
        self.assertEqual([x['id'] for x in r], [1, 2])                                     # 批量

    def test_ticket_loop(self):
        seen = []
        while True:
            c = self.rpc('tools/call', {'name': 'cocheck_next_ticket', 'arguments': {'project': 'demo'}})[1]['result']['content']
            if c[0]['text'].startswith('没有'): break
            head = json.loads(c[0]['text']); seen.append(head['ticket'])
            img = [x for x in c if x['type'] == 'image'][0]
            self.assertEqual(img['mimeType'], 'image/png')
            self.assertEqual(base64.b64decode(img['data'])[:4], b'\x89PNG')
            r = self.rpc('tools/call', {'name': 'cocheck_answer', 'arguments': {'project': 'demo', 'ticket': head['ticket'], 'answers': {'0': 'yes'}}})[1]
            self.assertFalse(r['result']['isError'])
        self.assertEqual(len(seen), 2)
        st = self.e.pr.store.load()['answers']
        self.assertTrue(all('tester' in st[t] for t in seen))                               # 交卷者用 X-Cocheck-By

    def test_errors_are_tool_errors(self):
        r = self.rpc('tools/call', {'name': 'cocheck_answer', 'arguments': {'project': 'demo', 'ticket': 'bad', 'answers': {}}})[1]
        self.assertTrue(r['result']['isError']); self.assertIn('没有这张单', r['result']['content'][0]['text'])
        r = self.rpc('tools/call', {'name': 'cocheck_status', 'arguments': {'project': '不存在'}})[1]
        self.assertTrue(r['result']['isError'])

    def test_unicode_reviewer_name(self):
        r = self.rpc('tools/call', {'name': 'cocheck_next_ticket', 'arguments': {'project': 'demo', 'by': '云端 复核员'}})[1]
        self.assertFalse(r['result']['isError'])

    def test_review_with_fake_provider(self):
        self.e.engine.reg._p['fake'] = FakeAsk(answer='no')
        res = self.e.pr.review_once('fake', jobs=2)
        self.assertEqual(res['answered'], 2)
        st = self.e.pr.store.status(self.e.pr.items())
        self.assertEqual({v['color'] for v in st.values()}, {'red'})


class StdioMcp(unittest.TestCase):
    def test_stdio(self):
        e = Env(token='t0k'); e.open(); url = e.serve()
        try:
            inp = io.StringIO('\n'.join(json.dumps(m) for m in [
                {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {}},
                {'jsonrpc': '2.0', 'method': 'notifications/initialized'},
                {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call', 'params': {'name': 'cocheck_projects', 'arguments': {}}}]) + '\nnot json\n')
            out = io.StringIO(); mcp.serve(url, 'stdio', 't0k', inp, out)
            lines = [json.loads(l) for l in out.getvalue().splitlines()]
            self.assertEqual([l.get('id') for l in lines], [1, 2, None])
            self.assertIn('demo', lines[1]['result']['content'][0]['text'])
            self.assertEqual(lines[2]['error']['code'], -32700)
        finally: e.close()


class Guard(unittest.TestCase):
    def test_public_needs_token(self):
        from cocheck.server import serve
        with self.assertRaises(SystemExit): serve(Env().engine, host='0.0.0.0', port=0, token=None)

    def test_init_and_token(self):
        import os, tempfile
        from unittest import mock
        d = tempfile.mkdtemp()
        with mock.patch.object(config, 'HOME', d), mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop('COCHECK_TOKEN', None)
            cf, tf, new = config.init([('p', 'folder', d)])
            self.assertTrue(new); self.assertEqual(oct(os.stat(tf).st_mode & 0o777), '0o600')
            self.assertEqual(config.token(), open(tf).read().strip())
            self.assertFalse(config.init([])[2])                                         # 第二次沿用令牌、保留项目
            self.assertIn('p', json.load(open(cf))['projects'])


if __name__ == '__main__': unittest.main()
