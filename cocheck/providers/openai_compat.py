"""OpenAI chat/completions 兼容接口（OpenAI、OpenRouter、vLLM、LM Studio、Ollama 等）。
配置：{"type": "openai", "base_url": "https://openrouter.ai/api/v1", "model": "...", "api_key": "${OPENROUTER_API_KEY}"}
图片用 data URI；音频用 input_audio（模型不支持时那张单会失败，换别的复核员）。"""
import base64, json, urllib.request
from .base import Provider, media_of, prompt_of, parse_answers


class OpenAICompat(Provider):
    caps = ('ask',)

    def _post(self, body, timeout=180):
        url = self.cfg.get('base_url', 'https://api.openai.com/v1').rstrip('/') + '/chat/completions'
        h = {'Content-Type': 'application/json'}
        if self.cfg.get('api_key'): h['Authorization'] = 'Bearer ' + self.cfg['api_key']
        return json.load(urllib.request.urlopen(urllib.request.Request(url, data=json.dumps(body).encode(), headers=h), timeout=timeout))

    def ask(self, t):
        m = media_of(t); content = []
        for x in m:
            b64 = base64.b64encode(open(x['path'], 'rb').read()).decode()
            if x['kind'] == 'image': content.append({'type': 'image_url', 'image_url': {'url': 'data:%s;base64,%s' % (x['mime'], b64)}})
            else: content.append({'type': 'input_audio', 'input_audio': {'data': b64, 'format': x['path'].rsplit('.', 1)[-1]}})
        content.append({'type': 'text', 'text': prompt_of(t, any(x['kind'] == 'audio' for x in m))})
        r = self._post({'model': self.cfg['model'], 'temperature': 0, 'messages': [{'role': 'user', 'content': content}]})
        return parse_answers(r['choices'][0]['message']['content'])

    def ping(self):
        r = self._post({'model': self.cfg['model'], 'messages': [{'role': 'user', 'content': '只回答 ok'}], 'max_tokens': 5}, timeout=60)
        return {'ok': True, 'model': r.get('model')}
