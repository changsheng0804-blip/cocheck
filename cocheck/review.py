"""点名复核：体检可疑处开成「复核单」，任何 AI（或人）领单、只答点名的是非题，按条目标红绿黄灰。

数据都在 <store>/review.json（一个 JSON，人和 AI 都能直接读）：
  tickets  单号 -> {id, item, fp, asks, status: open|clear|answered|stale, ...}
  answers  单号 -> {复核员: {answers: {题号: yes|no|unsure}, at, note?}}
单号 = 条目id-指纹；指纹覆盖图、配音、画面说明、文案、实际读法、读音要求，任何一样变了旧单过期。
"""
import hashlib, json, os, re, threading, time

NEAR_TEXT = -0.015          # 文字分接近阈值也送复核（反射层阈值 -0.008）
POSITIVE = {'text': 'yes'}  # 这些题答 yes 说明有问题；其余题（是不是/有没有/读得对不对）答 no 说明有问题
TILE = ['左上', '上中', '右上', '左中', '正中', '右中', '左下', '下中', '右下']
HUMAN = 'user'              # 人的裁决是最终的


def fingerprint(x):
    h = hashlib.sha1()
    for p in (x.get('image'), x.get('audio')):
        if p and os.path.exists(p):
            with open(p, 'rb') as f: h.update(f.read())
        else: h.update(b'-')
    h.update(json.dumps([x.get('desc'), x.get('text'), x.get('say'), x.get('poly')] + ([x['expect_text']] if x.get('expect_text') is not None else []), ensure_ascii=False, sort_keys=True).encode())
    return h.hexdigest()[:10]


def asks_for(x, r):
    """把一个条目的体检结果翻译成点名是非题。"""
    asks = []; ti = r.get('text_in_image') or {}; cov = r.get('coverage') or {}
    exp = x.get('expect_text')                     # 画里有意设计的字（路牌、片名…）：不问「有没有字」，问「字对不对」
    if exp is not None and not exp: pass             # expected_text: [] = 这拍允许有字、不核对
    elif exp:
        asks.append(dict(k='text', tile=ti.get('tile'), expect=exp, q='画面里允许出现的有意文字：%s（不一定都出现）。画面里的字有没有错字、乱码，或这些之外多余的字？' % '、'.join('「%s」' % e for e in exp)))
    elif ti.get('flag') or ti.get('score', -1) > NEAR_TEXT:
        where = TILE[ti['tile']] if isinstance(ti.get('tile'), int) and ti['tile'] < 9 else ''
        asks.append(dict(k='text', tile=ti.get('tile'), q='画面里有没有任何可见的字母、单词或文字（包括小字、手写、编号）？' + (f'重点看{where}。' if where else '')))
    if cov.get('swap'):
        from .checks import Reflex                   # 场景题只问画面：去掉声音分句
        vis = '，'.join(c for c in re.split(r'[，；。;]', x.get('desc') or '') if c.strip() and not Reflex.SOUND.search(c)) or x.get('desc', '')
        asks.append(dict(k='swap', q=f'这张图画的是不是这个场景：「{vis}」？'))
    else:
        for el in cov.get('missing') or []:
            asks.append(dict(k='el', el=el, q=f'画面里有没有：「{el}」？画错了也算没有；静态图看不出的动作答 unsure。'))
    if (r.get('vo_match') or {}).get('flag'):
        asks.append(dict(k='vo', q=f'这条配音说的是不是这句话：「{x.get("text", "")}」？'))
    for ch, p in (r.get('polyphone') or {}).items():
        if p.get('flag'):
            asks.append(dict(k='poly', ch=ch, q=f'配音里「{ch}」读的是不是 {(x.get("poly") or {}).get(ch, "")}？'))
    for i, a in enumerate(asks): a['i'] = str(i)
    return asks


def verdict(t, by_reviewer):
    """每题：说「有问题」的人数 ≥ 说「没问题」的人数且至少 1 人 → 有问题；全 unsure → 待定。人答过以人为准。"""
    problems, unsure = [], []; final = HUMAN in by_reviewer
    if final: by_reviewer = {HUMAN: by_reviewer[HUMAN]}
    for a in t['asks']:
        bad_v = POSITIVE.get(a['k'], 'no'); good_v = 'no' if bad_v == 'yes' else 'yes'
        votes = {r: x['answers'].get(a['i'], 'unsure') for r, x in by_reviewer.items()}
        nb = [r for r, v in votes.items() if v == bad_v]; ng = [r for r, v in votes.items() if v == good_v]
        if nb and len(nb) >= len(ng):
            problems.append(dict(k=a['k'], what=a.get('el') or a.get('ch') or ('expect' if a.get('expect') else a['k']), by=nb, against=ng))
        elif not nb and not ng: unsure.append(a.get('el') or a['k'])
    color = 'red' if problems else 'yellow' if unsure and len(unsure) == len(t['asks']) else 'green'
    return dict(color=color, problems=problems, unsure=unsure, reviewers=sorted(by_reviewer), final=final)


class Store:
    _locks = {}                                  # 同一个 review.json 一把锁：多个 AI 同时交卷不丢答案

    def __init__(self, path):
        self.dir = path; os.makedirs(path, exist_ok=True); self.f = os.path.join(path, 'review.json')
        self.lock = Store._locks.setdefault(os.path.abspath(self.f), threading.RLock())

    def load(self):
        if not os.path.exists(self.f): return {'tickets': {}, 'answers': {}}
        with open(self.f, encoding='utf-8') as f: return json.load(f)

    def save(self, db):
        tmp = '%s.%d.tmp' % (self.f, threading.get_ident())
        with open(tmp, 'w', encoding='utf-8') as f: json.dump(db, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.f)

    # ---- 开单 ----
    def open_tickets(self, items, report):
        with self.lock: return self._open_tickets(items, report)

    def _open_tickets(self, items, report):
        R = report.get('items', report); db = self.load(); now = time.strftime('%Y-%m-%d %H:%M:%S')
        out = dict(opened=[], cleared=[], stale=[], kept=[])
        for x in items:
            if x['id'] not in R: continue
            fp = fingerprint(x); tid = f'{x["id"]}-{fp}'
            for old in db['tickets'].values():                    # 同一条目的旧单，指纹不同 → 过期
                if old['item'] == x['id'] and old['fp'] != fp and old['status'] != 'stale':
                    old['status'] = 'stale'; out['stale'].append(old['id'])
            if tid in db['tickets']:
                t = db['tickets'][tid]
                if t['status'] == 'stale':                        # 改回了以前的版本 → 恢复原判
                    t['status'] = 'answered' if db['answers'].get(tid) else ('open' if t['asks'] else 'clear')
                out['kept'].append(tid); continue
            asks = asks_for(x, R[x['id']])
            db['tickets'][tid] = dict(id=tid, item=x['id'], fp=fp, created=now, asks=asks, status='open' if asks else 'clear',
                                      **{k: x.get(k) for k in ('image', 'audio', 'desc', 'text')})
            out['opened' if asks else 'cleared'].append(tid)
        self.save(db); return out

    # ---- 领单 / 交答案 ----
    def list_open(self, by=None, second=False, only=None):
        """second：也给别人答过的（要第二意见）；only：只给这些单号（如只复核红/黄）。"""
        db = self.load(); ok = ('open', 'answered') if second else ('open',)
        return [t for t in db['tickets'].values() if t['status'] in ok and not (by and by in db['answers'].get(t['id'], {}))
                and (only is None or t['id'] in only)]

    def answer(self, tid, by, answers, note=None):
        with self.lock: return self._answer(tid, by, answers, note)

    def _answer(self, tid, by, answers, note=None):
        db = self.load(); t = db['tickets'].get(tid)
        if not t: return {'error': f'没有这张单：{tid}'}, 404
        if t['status'] == 'stale': return {'error': '这张单已过期（素材或文案改过），请重新体检后领新单'}, 409
        clean = {}
        for a in t['asks']:
            v = str(answers.get(a['i'], 'unsure')).strip().lower(); clean[a['i']] = v if v in ('yes', 'no', 'unsure') else 'unsure'
        db['answers'].setdefault(tid, {})[by] = dict(answers=clean, at=time.strftime('%Y-%m-%d %H:%M:%S'), **({'note': note} if note else {}))
        t['status'] = 'answered'; self.save(db)
        return {'ok': True, 'ticket': tid, 'verdict': verdict(t, db['answers'][tid])}, 200

    # ---- 红绿灯 ----
    def status(self, items=None):
        """每个条目当前颜色。给了 items（当前数据）时，指纹对不上的直接 grey（改过了，等重新体检）。"""
        db = self.load(); latest = {}
        cur = {x['id']: fingerprint(x) for x in items if x.get('image')} if items is not None else {}
        for t in db['tickets'].values():
            if t['status'] == 'stale': latest.setdefault(t['item'], t); continue
            c = latest.get(t['item'])
            if not c or c['status'] == 'stale' or t['created'] >= c['created']: latest[t['item']] = t
        out = {}
        for iid, t in latest.items():
            if items is not None and iid not in cur: continue
            base = dict(ticket=t['id'], asks=t['asks'], answers=db['answers'].get(t['id'], {}))
            if t['status'] == 'stale' or (iid in cur and cur[iid] != t['fp']): out[iid] = dict(base, color='grey')
            elif t['status'] == 'clear' and not base['answers']: out[iid] = dict(base, color='green', reviewers=['reflex'], problems=[], unsure=[])
            elif t['status'] == 'open': out[iid] = dict(base, color='yellow', problems=[], unsure=[])
            else: out[iid] = dict(base, **verdict(t, base['answers']))
        for iid in cur:
            if iid not in out: out[iid] = dict(color='grey', ticket=None, asks=[], answers={})
        return out
