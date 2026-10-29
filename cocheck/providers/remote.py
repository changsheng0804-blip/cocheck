"""另一台机器上的 cocheck 服务（统一接口 /v1/embed、/v1/ask）。比如模型在 Mac 上，别处的 cocheck 都连它。
配置：{"type": "remote", "base_url": "http://mac.local:8796", "provider": "eg2", "token": "${COCHECK_TOKEN}",
       "ensure": "loco ensure eg2"}
ensure（可选）：连不上时先跑这条命令把服务叫起来（随用随开的本机模型服务），成功后重试一次。"""
import base64, io, json, os, subprocess, urllib.error, urllib.request
from .base import Provider, needs_audio


def enc_input(x):
    if isinstance(x, str): return {'text': x}
    if 'image' in x:
        b = io.BytesIO(); x['image'].save(b, 'PNG'); return {'image_png': base64.b64encode(b.getvalue()).decode()}
    import numpy as np
    return {'audio_f32': base64.b64encode(np.asarray(x['audio'], dtype=np.float32).tobytes()).decode()}


_direct = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _open(url_or_req, timeout):
    """本机地址不走系统代理（Mac 上开着 Clash 系统代理时，127.0.0.1 也可能被转走）。"""
    u = url_or_req.full_url if hasattr(url_or_req, 'full_url') else url_or_req
    host = urllib.request.urlparse(u).hostname or ''
    op = _direct.open if host in ('127.0.0.1', 'localhost', '::1') else urllib.request.urlopen
    return op(url_or_req, timeout=timeout)


class Remote(Provider):
    caps = ('embed', 'ask')

    def _up(self, fn):
        try: return fn()
        except urllib.error.URLError as e:
            if isinstance(e, urllib.error.HTTPError) or not self.cfg.get('ensure'): raise
            r = subprocess.run(self.cfg['ensure'], shell=True, capture_output=True, text=True, timeout=600, stdin=subprocess.DEVNULL)
            if r.returncode: raise RuntimeError('ensure 失败：%s %s' % (self.cfg['ensure'], (r.stderr or r.stdout)[-300:]))
            return fn()

    def _post(self, path, body, timeout=300):
        return self._up(lambda: self._post1(path, body, timeout))

    def _post1(self, path, body, timeout):
        h = {'Content-Type': 'application/json'}
        if self.cfg.get('token'): h['Authorization'] = 'Bearer ' + self.cfg['token']
        req = urllib.request.Request(self.cfg['base_url'].rstrip('/') + path, data=json.dumps(body).encode(), headers=h)
        return json.load(_open(req, timeout))

    def embed(self, inputs, prompt=None, image_tokens=None):
        import numpy as np
        r = self._post('/v1/embed', dict(provider=self.cfg.get('provider'), prompt=prompt, image_tokens=image_tokens,
                                         inputs=[enc_input(x) for x in inputs]))
        return np.array(r['vectors'], dtype=np.float32)

    def ask(self, t):
        files = {}
        for key in ('image', 'audio') if needs_audio(t) else ('image',):
            if t.get(key) and os.path.exists(t[key]):
                files[key] = dict(name=os.path.basename(t[key]), b64=base64.b64encode(open(t[key], 'rb').read()).decode())
        r = self._post('/v1/ask', dict(provider=self.cfg.get('provider'),
                                       ticket={k: t.get(k) for k in ('id', 'item', 'desc', 'text', 'asks')}, files=files))
        return r['answers']

    def ping(self):
        r = self._up(lambda: json.load(_open(self.cfg['base_url'].rstrip('/') + '/v1/providers', 10)))
        return {'ok': True, 'remote': [p['name'] for p in r['providers']]}
