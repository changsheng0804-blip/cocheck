"""反射层体检：用任意 embed provider 做高频、局部、对照式检查。

不判"好不好"，只做可核对的局部问题：
  text_in_image  画面切 3×3 块 vs 合成参照（叠字块/原块），找画里多余的文字（报最可疑的块）
  coverage       把画面说明拆成元素，逐元素在全部条目的块里检索，报缺失元素 / 整张换错
  vo_match       配音 ↔ 本条文案（在全部文案中排名），报配错音频
  polyphone      多音字：同一音色合成两种读音参照，在配音上按字长滑窗 A/B（需要 edge-tts、ffmpeg）
所有向量按「模型 + 内容哈希」缓存，只重算改过的东西。
"""
import hashlib, json, os, re, subprocess, time, asyncio
import numpy as np

POLY = {  # 字: [(读音, 同音替身), ...]，第一个不一定是正确读音；正确读音由 vo.poly 或调用方指定
    '行': [('háng', '航'), ('xíng', '形')], '重': [('chóng', '虫'), ('zhòng', '众')],
    '还': [('huán', '环'), ('hái', '孩')], '中': [('zhòng', '众'), ('zhōng', '钟')],
    '长': [('cháng', '常'), ('zhǎng', '掌')], '为': [('wèi', '未'), ('wéi', '维')],
    '好': [('hǎo', '郝'), ('hào', '号')], '调': [('diào', '吊'), ('tiáo', '条')],
}
VOICE = 'zh-CN-YunxiNeural'; RATE = '-8%'


class Reflex:
    """embedder：任何有 embed 能力的 provider（本地模型、远端 cocheck……）。"""
    def __init__(self, embedder, cache='.cocheck/cache'):
        self.m = embedder; self.tag = getattr(embedder, 'cfg', {}).get('model', '')
        self.cache = cache; os.makedirs(cache, exist_ok=True); self.stats = dict(hit=0, miss=0)
        self._refs = None

    # ---- 嵌入 + 缓存 ----
    def _key(self, kind, payload):
        h = hashlib.sha1((self.tag + '|' + kind).encode())     # 换了模型缓存自动失效
        h.update(payload if isinstance(payload, bytes) else str(payload).encode()); return h.hexdigest()
    def embed(self, items, kinds, prompt=None, pk=None):
        out = [None] * len(items); todo = []
        for n, (x, k) in enumerate(zip(items, kinds)):
            f = f'{self.cache}/{k}.npy'
            if os.path.exists(f): out[n] = np.load(f); self.stats['hit'] += 1
            else: todo.append(n)
        if todo:
            E = self.m.embed([items[n] for n in todo], prompt=prompt, image_tokens=(pk or {}).get('image', {}).get('max_soft_tokens'))
            for n, e in zip(todo, E): np.save(f'{self.cache}/{kinds[n]}.npy', e); out[n] = e
            self.stats['miss'] += len(todo)
        return np.stack(out)
    def text(self, xs, prompt):
        return self.embed(list(xs), [self._key('t' + prompt, x) for x in xs], prompt)
    def tiles(self, path, g=3):
        from PIL import Image
        raw = open(path, 'rb').read(); im = Image.open(path).convert('RGB'); im.thumbnail((1024, 1024)); W, H = im.size
        crops = [im] + [im.crop((x * W // g, y * H // g, (x + 1) * W // g, (y + 1) * H // g)) for y in range(g) for x in range(g)]
        return self.embed([{'image': c} for c in crops], [self._key(f'tile{g}_{n}', raw) for n in range(len(crops))],
                          pk={'image': {'max_soft_tokens': 70}})
    def audio(self, wavs, keys):
        return self.embed([{'audio': w} for w in wavs], [self._key('a', k) for k in keys])

    # ---- 参照：叠字块 vs 原块 ----
    def text_refs(self, ref_images):
        if self._refs is not None: return self._refs
        from PIL import Image, ImageDraw, ImageFont
        fp = next((f for f in ['/System/Library/Fonts/Helvetica.ttc', '/System/Library/Fonts/Supplemental/Arial.ttf',
                               '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'] if os.path.exists(f)), None)
        font = ImageFont.truetype(fp, 46) if fp else ImageFont.load_default()
        words = ['DELETE', 'PUSH!', 'CLICK', '3D MODEL', 'TEMPLE', 'OUTLINE', 'SPEED', 'ERROR']
        pos, neg, keys = [], [], []
        for k, p in enumerate(ref_images):
            im = Image.open(p).convert('RGB'); im.thumbnail((1024, 1024)); W, H = im.size
            for j in range(0, 9, 2):
                x, y = j % 3, j // 3; t = im.crop((x * W // 3, y * H // 3, (x + 1) * W // 3, (y + 1) * H // 3))
                q = t.copy(); ImageDraw.Draw(q).text((20, q.size[1] // 2 - 25), words[(k + j) % 8],
                                                      fill=(20, 20, 20) if j % 4 else (255, 255, 255), font=font)
                neg.append({'image': t}); pos.append({'image': q}); keys.append(f'{p}:{j}')
        pk = {'image': {'max_soft_tokens': 70}}
        Ep = self.embed(pos, [self._key('refpos', k) for k in keys], pk=pk)
        En = self.embed(neg, [self._key('refneg', k) for k in keys], pk=pk)
        self._refs = (Ep.mean(0), En.mean(0)); return self._refs

    # ---- 检查 ----
    def text_in_image(self, path, refs, thr=-0.008):
        cp, cn = refs; T = self.tiles(path)[1:]; s = T @ cp - T @ cn
        return dict(score=round(float(s.max()), 4), tile=int(s.argmax()), flag=bool(s.max() > thr))

    @staticmethod
    def elements(what):
        w = re.sub(r'[（(][^）)]*[）)]', '', what or '')
        w = re.sub(r'(?<=\d),(?=\d)', '', w)  # 1,000,000 不拆
        return [x.strip() for x in re.split(r'[，、；。,;]', w) if len(x.strip()) >= 3][:6]

    def coverage(self, beats, images, miss_rank=3, bad_rank=10, swap_frac=0.6):
        """beats: [(id, what)], images: [path] 同序；每个元素在全片块里排第几"""
        TE = [self.tiles(p) for p in images]; out = {}
        for i, (bid, what) in enumerate(beats):
            els = self.elements(what)
            if not els: continue
            E = self.text(els, 'Retrieval-query'); rows = []
            for e, t in zip(E, els):
                m = np.array([float((A @ e).max()) for A in TE]); rows.append((t, int((m > m[i]).sum()) + 1))
            miss = [t for t, r in rows if r > miss_rank]; worst = max(r for _, r in rows)
            out[bid] = dict(elements=[dict(el=t, rank=r) for t, r in rows], missing=miss, worst=worst,
                            swap=len(miss) / len(rows) >= swap_frac, flag=worst >= bad_rank)
        return out

    @staticmethod
    def wav(path, a=None, b=None):
        x = np.frombuffer(subprocess.run(['ffmpeg', '-v', 'quiet', '-i', path, '-ac', '1', '-ar', '16000', '-f', 'f32le', '-'],
                                         capture_output=True).stdout, dtype=np.float32)
        return x if a is None else x[int(a * 16000):int(b * 16000)]

    def vo_match(self, pairs):
        """pairs: [(id, audio_path, text)]；音频在全部文案中检索，自己的文案排第几"""
        A = self.audio([self.wav(p) for _, p, _ in pairs], [open(p, 'rb').read() for _, p, _ in pairs])
        T = self.text([t for *_, t in pairs], 'Retrieval-query'); S = A @ T.T; out = {}
        for n, (bid, _, _) in enumerate(pairs):
            r = int((S[n] > S[n, n]).sum()) + 1; out[bid] = dict(rank=r, flag=r > 1, best=pairs[int(S[n].argmax())][0])
        return out

    def _synth(self, text, path):
        import edge_tts
        async def go():
            c = edge_tts.Communicate(text, VOICE, rate=RATE, boundary='WordBoundary'); wb = []
            with open(path, 'wb') as f:
                async for ch in c.stream():
                    if ch['type'] == 'audio': f.write(ch['data'])
                    elif ch['type'] == 'WordBoundary': wb.append((ch['offset'] / 1e7, ch['duration'] / 1e7, ch['text']))
            return wb
        if not os.path.exists(path + '.wb.json'):
            json.dump(asyncio.run(go()), open(path + '.wb.json', 'w'))
        return json.load(open(path + '.wb.json'))

    def polyphone(self, audio_path, text, char, good_sub, bad_sub):
        refs = []
        for sub in (good_sub, bad_sub):
            t = text.replace(char, sub, 1); p = f'{self.cache}/ref_{self._key("tts", VOICE + RATE + t)}.mp3'
            wb = self._synth(t, p); w = next(((o, d) for o, d, tx in wb if sub in tx), None)
            refs.append((p, w))
        segs = [self.wav(p, max(0, w[0] - 0.25), w[0] + w[1] + 0.25) if w else self.wav(p) for p, w in refs]
        R = self.audio(segs, [f'{p}:{w}' for p, w in refs])
        x = self.wav(audio_path); L = len(segs[0]); hop = 1600; raw = open(audio_path, 'rb').read()
        starts = list(range(0, max(1, len(x) - L), hop))
        W = self.audio([x[s:s + L] for s in starts], [raw + f':{s}:{L}'.encode() for s in starts])
        g, b = W @ R[0], W @ R[1]; j = int(np.argmax(np.maximum(g, b)))
        return dict(good=round(float(g[j]), 4), bad=round(float(b[j]), 4), at=round(starts[j] / 16000, 2), flag=bool(b[j] > g[j]))


def run(items, embedder, cache):
    """items：适配器给的条目（image/audio 为本地路径）。返回 {item_id: {检查名: 结果}}。"""
    rx = Reflex(embedder, cache); t0 = time.time()
    B = [x for x in items if x.get('image') and os.path.exists(x['image'])]
    res = {x['id']: {} for x in B}
    if not B: return dict(items=res, seconds=0, cache=rx.stats)
    imgs = [x['image'] for x in B]
    refs = rx.text_refs(imgs[:4])
    for x in B: res[x['id']]['text_in_image'] = rx.text_in_image(x['image'], refs)
    for k, v in rx.coverage([(x['id'], x.get('desc', '')) for x in B], imgs).items(): res[k]['coverage'] = v
    vb = [(x['id'], x['audio'], x['text']) for x in B if x.get('audio') and os.path.exists(x['audio']) and x.get('text')]
    if len(vb) > 1:
        for k, v in rx.vo_match(vb).items(): res[k]['vo_match'] = v
    for x in B:
        for ch, py in (x.get('poly') or {}).items():          # poly: {"行": "háng"}
            opts = dict(POLY.get(ch, [])); good = opts.get(py); bad = next((s for p, s in POLY.get(ch, []) if p != py), None)
            if good and bad and x.get('audio'):
                try: res[x['id']].setdefault('polyphone', {})[ch] = rx.polyphone(x['audio'], x.get('say') or x['text'], ch, good, bad)
                except Exception as e: res[x['id']].setdefault('polyphone', {})[ch] = dict(error=str(e), flag=False)
    return dict(items=res, seconds=round(time.time() - t0, 1), cache=rx.stats)
