"""另一台机器上的 cocheck 服务（统一接口 /v1/embed、/v1/ask）。比如模型在 Mac 上，别处的 cocheck 都连它。
配置：{"type": "remote", "base_url": "http://mac.local:8796", "provider": "eg2", "token": "${COCHECK_TOKEN}"}"""
import base64, io, json, os, urllib.request
from .base import Provider, needs_audio


def enc_input(x):
    if isinstance(x, str): return {'text': x}
    if 'image' in x:
        b = io.BytesIO(); x['image'].save(b, 'PNG'); return {'image_png': base64.b64encode(b.getvalue()).decode()}
    import numpy as np
    return {'audio_f32': base64.b64encode(np.asarray(x['audio'], dtype=np.float32).tobytes()).decode()}


class Remote(Provider):
    caps = ('embed', 'ask')

    def _post(self, path, body, timeout=300):
        h = {'Content-Type': 'application/json'}
        if self.cfg.get('token'): h['Authorization'] = 'Bearer ' + self.cfg['token']
        req = urllib.request.Request(self.cfg['base_url'].rstrip('/') + path, data=json.dumps(body).encode(), headers=h)
        return json.load(urllib.request.urlopen(req, timeout=timeout))

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
        r = json.load(urllib.request.urlopen(self.cfg['base_url'].rstrip('/') + '/v1/providers', timeout=10))
        return {'ok': True, 'remote': [p['name'] for p in r['providers']]}
