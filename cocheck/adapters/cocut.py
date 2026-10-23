"""cocut 片子目录（doc.json）→ 条目。每拍一条，时间由拍点时长顺推。"""
import json, os, re


def _lex(text, lex):
    """cocut 全片读音表（doc.lexicon）套到旁白上，规则同 cocut/api.py。"""
    es = sorted([e for e in lex or [] if e.get('w') and e.get('say') is not None], key=lambda e: -len(e['w']))
    if not es or not text: return text
    m = {e['w']: e['say'] for e in es}
    return re.sub('|'.join(re.escape(e['w']) for e in es), lambda x: m[x.group(0)], text)


def _exp(beat, film):
    if beat is None and film is None: return None
    return list(dict.fromkeys((beat or []) + (film or [])))


def items(path, **_):
    d = json.load(open(os.path.join(path, 'doc.json'), encoding='utf-8')); out = []; t = 0.0
    film_text = d.get('expected_text')                 # 全片一直在的画内字（如角落的速度牌），每拍都算有意文字
    ab = lambda rel: os.path.join(path, rel) if rel else None
    for b in d['beats']:
        vo = b.get('vo') or {}; dur = float(b.get('dur') or 0); lex = d.get('lexicon') or []
        say = vo.get('say') or (_lex(vo.get('text'), lex) if vo.get('text') else None)
        poly = {}
        for e in lex:
            if e.get('w') and e['w'] in (vo.get('text') or '') and isinstance(e.get('py'), dict): poly.update(e['py'])
        poly.update(vo.get('poly') or {})
        if b.get('image'):
            out.append(dict(id=b['id'], label=b.get('verb') or '', image=ab(b['image']), audio=ab(vo.get('file')),
                            desc=b.get('what'), sound=b.get('sound'), expect_text=_exp(b.get('expected_text'), film_text), text=vo.get('text'), say=say if say != vo.get('text') else None, poly=poly or None, t0=round(t, 3), t1=round(t + dur, 3)))
        t += dur
    return out


def watch_files(path):
    return [os.path.join(path, 'doc.json')]
