"""Gemini generateContent 兼容接口：Google AI Studio、Vertex、或任何同格式的本地桥。
配置：{"type": "gemini", "base_url": "https://generativelanguage.googleapis.com", "model": "gemini-3.8-flash",
       "api_key": "${GEMINI_API_KEY}"}   # 本地桥不需要 api_key"""
import base64, json, urllib.request
from .base import Provider, media_of, prompt_of, parse_answers


class Gemini(Provider):
    caps = ('ask',)

    def _post(self, body, timeout=180):
        url = '%s/v1beta/models/%s:generateContent' % (self.cfg.get('base_url', 'https://generativelanguage.googleapis.com').rstrip('/'), self.cfg['model'])
        h = {'Content-Type': 'application/json'}
        if self.cfg.get('api_key'): h['x-goog-api-key'] = self.cfg['api_key']
        return json.load(urllib.request.urlopen(urllib.request.Request(url, data=json.dumps(body).encode(), headers=h), timeout=timeout))

    def ask(self, t):
        m = media_of(t)
        parts = [{'inlineData': {'mimeType': x['mime'], 'data': base64.b64encode(open(x['path'], 'rb').read()).decode()}} for x in m]
        parts.append({'text': prompt_of(t, any(x['kind'] == 'audio' for x in m))})
        r = self._post({'contents': [{'role': 'user', 'parts': parts}],
                        'generationConfig': {'responseMimeType': 'application/json', 'temperature': 0}})
        return parse_answers(''.join(p.get('text', '') for p in r['candidates'][0]['content']['parts'] if not p.get('thought')))

    def ping(self):
        r = self._post({'contents': [{'role': 'user', 'parts': [{'text': '只回答 ok'}]}]}, timeout=60)
        return {'ok': True, 'model': r.get('modelVersion', self.cfg['model'])}
