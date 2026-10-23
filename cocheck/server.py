"""cocheck HTTP 服务：统一模型接入口 + 审核接口。cocheck serve 启动。完整说明见 docs/API.md。

模型（所有本地/云端模型同一入口）：
  GET  /v1/providers                       有哪些 provider、各自能力
  POST /v1/embed   {provider?, inputs, prompt?, image_tokens?}            -> {vectors}
  POST /v1/ask     {provider, ticket:{id,desc,text,asks}, files:{image|audio:{name,b64}}} -> {answers}
审核：
  GET  /v1/projects                        项目列表 + 红绿数量
  POST /v1/projects {name, adapter, path, ...}   运行时登记项目
  GET  /v1/projects/<p>/status             每个条目的颜色、问题、复核员、分歧 + 时间位置
  GET  /v1/projects/<p>/tickets?by=&second=1&hot=1   待复核的单（媒体给 URL）
  GET  /v1/projects/<p>/media/<单号>/<image|audio>
  POST /v1/projects/<p>/answer {ticket, by, answers, note?}
  POST /v1/projects/<p>/check              立即体检
  POST /v1/projects/<p>/review {provider?, jobs?, escalate?}   不给 provider = 按配置的复核员链跑
网页组件：GET /cocheck-strip.js
"""
import base64, io, json, os, re, shutil, sys, tempfile, threading
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

WEB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'web')


def dec_input(x):
    if 'text' in x: return x['text']
    if 'image_png' in x:
        from PIL import Image
        return {'image': Image.open(io.BytesIO(base64.b64decode(x['image_png']))).convert('RGB')}
    import numpy as np
    return {'audio': np.frombuffer(base64.b64decode(x['audio_f32']), dtype=np.float32)}


def make_handler(engine, token=None):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a): pass

        def _send(self, obj, code=200, ctype='application/json; charset=utf-8', raw=None):
            b = raw if raw is not None else json.dumps(obj, ensure_ascii=False).encode()
            self.send_response(code); self.send_header('Content-Type', ctype); self.send_header('Content-Length', str(len(b)))
            self.send_header('Access-Control-Allow-Origin', '*'); self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization')
            self.end_headers(); self.wfile.write(b)

        def do_OPTIONS(self): self._send({}, 204, raw=b'')

        def _auth(self):
            return not token or self.headers.get('Authorization') == 'Bearer ' + token

        def _body(self):
            n = int(self.headers.get('Content-Length') or 0); return json.loads(self.rfile.read(n) or b'{}')

        def do_GET(self):
            u = urlparse(self.path); q = {k: v[0] for k, v in parse_qs(u.query).items()}; p = u.path.rstrip('/')
            try:
                if p == '/v1/providers': return self._send(dict(providers=engine.reg.info(), embed=engine.cfg.get('embed'), reviewers=engine.cfg.get('reviewers')))
                if p == '/v1/projects': return self._send(dict(projects=[x.summary() for x in engine.projects.values()]))
                if p == '/cocheck-strip.js':
                    return self._send(None, ctype='application/javascript; charset=utf-8', raw=open(os.path.join(WEB, 'cocheck-strip.js'), 'rb').read())
                m = re.match(r'^/v1/projects/([^/]+)/(status|tickets|media)(?:/([^/]+)/(image|audio))?$', p)
                if m:
                    pr = engine.project(m.group(1)); what = m.group(2)
                    if what == 'status':
                        items = pr.items()
                        return self._send(dict(status=pr.store.status(items), check=pr.check_state, reviewers=pr.review_state,
                                               items=[{k: x.get(k) for k in ('id', 'label', 'desc', 't0', 't1')} for x in items]))
                    if what == 'tickets':
                        only = {v['ticket'] for v in pr.store.status(pr.items()).values() if v['color'] in ('red', 'yellow')} if q.get('hot') else None
                        ts = pr.store.list_open(q.get('by'), bool(q.get('second') or q.get('hot')), only)
                        base = '/v1/projects/%s/media/' % pr.name
                        return self._send(dict(tickets=[dict({k: v for k, v in t.items() if k not in ('image', 'audio')},
                                                             image=base + t['id'] + '/image' if t.get('image') else None,
                                                             audio=base + t['id'] + '/audio' if t.get('audio') else None,
                                                             image_name=os.path.basename(t['image']) if t.get('image') else None,
                                                             audio_name=os.path.basename(t['audio']) if t.get('audio') else None) for t in ts]))
                    t = pr.store.load()['tickets'].get(m.group(3)); f = t and t.get(m.group(4))
                    if not f or not os.path.exists(f): return self._send({'error': '没有这个文件'}, 404)
                    from .providers.base import MIME
                    return self._send(None, ctype=MIME.get(os.path.splitext(f)[1].lower(), 'application/octet-stream'), raw=open(f, 'rb').read())
                return self._send({'error': 'not found'}, 404)
            except KeyError as e: return self._send({'error': str(e)}, 404)
            except Exception as e: return self._send({'error': '%s: %s' % (type(e).__name__, e)}, 500)

        def do_POST(self):
            if not self._auth(): return self._send({'error': 'unauthorized'}, 401)
            p = urlparse(self.path).path.rstrip('/')
            try:
                b = self._body()
                if p == '/v1/embed':
                    prov = engine.reg.get(b.get('provider') or engine.cfg.get('embed'))
                    V = prov.embed([dec_input(x) for x in b['inputs']], prompt=b.get('prompt'), image_tokens=b.get('image_tokens'))
                    return self._send(dict(provider=prov.name, vectors=[[round(float(v), 6) for v in row] for row in V]))
                if p == '/v1/ask':
                    prov = engine.reg.get(b['provider']); work = tempfile.mkdtemp(prefix='cocheck-ask-'); t = dict(b['ticket'])
                    try:
                        for k, f in (b.get('files') or {}).items():
                            path = os.path.join(work, os.path.basename(f['name'])); open(path, 'wb').write(base64.b64decode(f['b64'])); t[k] = path
                        t.setdefault('item', t.get('id', 'x'))
                        return self._send(dict(provider=prov.name, answers=prov.ask(t)))
                    finally: shutil.rmtree(work, ignore_errors=True)
                if p == '/v1/projects':
                    pr = engine.add_project(b.pop('name'), b); pr.request_check(); return self._send(pr.summary())
                m = re.match(r'^/v1/projects/([^/]+)/(answer|check|review)$', p)
                if m:
                    pr = engine.project(m.group(1)); what = m.group(2)
                    if what == 'answer': return self._send(*pr.store.answer(b['ticket'], b['by'], b.get('answers', {}), b.get('note')))
                    if what == 'check': pr.request_check(); return self._send(dict(ok=True, check=pr.check_state))
                    if b.get('provider'):
                        threading.Thread(target=pr.review_once, args=(b['provider'], b.get('jobs', 1), b.get('escalate', False)), daemon=True).start()
                    else: pr.request_review()
                    return self._send(dict(ok=True, reviewers=pr.review_state))
                return self._send({'error': 'not found'}, 404)
            except KeyError as e: return self._send({'error': str(e)}, 404)
            except Exception as e: return self._send({'error': '%s: %s' % (type(e).__name__, e)}, 500)
    return H


def serve(engine, host='127.0.0.1', port=8796, token=None):
    engine.watch()
    print('cocheck: http://%s:%d  项目：%s  provider：%s' % (host, port, ', '.join(engine.projects) or '无', ', '.join(engine.reg.names()) or '无'), flush=True)
    ThreadingHTTPServer((host, port), make_handler(engine, token)).serve_forever()
