"""统一模型接入口的约定。

一个 provider 只需实现下面两种能力中的一种或两种：
  embed(inputs, prompt=None, image_tokens=None) -> numpy (n, d)，已归一化
      inputs 每项是 str（文字）、{'image': PIL.Image}、或 {'audio': float32 16 kHz 单声道 numpy}
  ask(ticket) -> {"题号": "yes|no|unsure"}
      ticket = {id, desc, text, asks:[{i,q,k}], image: 本地路径|None, audio: 本地路径|None}
ask_batch(tickets, jobs) 默认按 jobs 并发调 ask；命令行代理这类「一次读一批文件」的会覆盖它。
"""
import json, os, time
from concurrent.futures import ThreadPoolExecutor

MIME = {'.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png', '.webp': 'image/webp',
        '.mp3': 'audio/mpeg', '.wav': 'audio/wav', '.m4a': 'audio/mp4', '.ogg': 'audio/ogg'}

ASK_PROMPT = ('你是审片复核员。下面是一张画面{audio}和几个点名问题。逐题只回答 yes、no 或 unsure；只看点名的这一处，'
              '不评价别的，看不清或听不出就答 unsure。只输出 JSON：{{"题号": "yes|no|unsure", ...}}。\n'
              '画面说明：{desc}\n{text}问题：\n{asks}')


def needs_audio(t): return any(q.get('k') in ('vo', 'poly') for q in t['asks'])


def media_of(t):
    """这张单要给模型看的文件：总是图，问配音时再加音频。"""
    out = []
    for key in ('image', 'audio') if needs_audio(t) else ('image',):
        p = t.get(key)
        if p and os.path.exists(p): out.append(dict(kind=key, path=p, mime=MIME.get(os.path.splitext(p)[1].lower(), 'application/octet-stream')))
    return out


def prompt_of(t, has_audio):
    asks = '\n'.join('%s. %s' % (q['i'], q['q']) for q in t['asks'])
    text = ('配音文案：%s\n' % t['text']) if has_audio and t.get('text') else ''
    return ASK_PROMPT.format(audio='、一段配音' if has_audio else '', desc=t.get('desc') or '', text=text, asks=asks)


def parse_answers(txt):
    txt = txt[txt.find('{'):txt.rfind('}') + 1]
    v = json.loads(txt)
    return {str(k): (str(x).strip().lower() if str(x).strip().lower() in ('yes', 'no', 'unsure') else 'unsure') for k, x in v.items()}


class Provider:
    caps = ()                     # ('embed',) / ('ask',) / 两者

    def __init__(self, name, **cfg):
        self.name = name; self.cfg = cfg

    def info(self):
        return dict(name=self.name, type=type(self).__name__, caps=list(self.caps),
                    **{k: v for k, v in self.cfg.items() if k in ('model', 'base_url', 'device', 'note')})

    def embed(self, inputs, prompt=None, image_tokens=None):
        raise NotImplementedError('%s 不支持 embed' % self.name)

    def ask(self, ticket):
        raise NotImplementedError('%s 不支持 ask' % self.name)

    def ask_batch(self, tickets, jobs=1, on_done=None):
        """返回 {单号: answers}；某张失败就不在结果里（下次再领）。on_done(单号, answers) 每答完一张就回调（进度、及时落盘）。"""
        def one(t):
            err = None
            for attempt in range(5):
                try: return t['id'], self.ask(t)
                except Exception as e:                       # 429 限流指数退避，其余短重试
                    err = e; time.sleep((4 * 2 ** attempt) if '429' in str(e) else 2 + attempt * 3)
            print('[%s] %s 没答上：%s' % (self.name, t['id'], err), flush=True); return t['id'], None
        out = {}
        with ThreadPoolExecutor(max(1, jobs)) as ex:
            for tid, a in ex.map(one, tickets):
                if a:
                    out[tid] = a
                    if on_done: on_done(tid, a)
        return out

    def ping(self):
        return {'ok': True}
