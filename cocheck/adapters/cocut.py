"""cocut 片子目录（doc.json）→ 条目。每拍一条，时间由拍点时长顺推。"""
import json, os


def items(path, **_):
    d = json.load(open(os.path.join(path, 'doc.json'), encoding='utf-8')); out = []; t = 0.0
    ab = lambda rel: os.path.join(path, rel) if rel else None
    for b in d['beats']:
        vo = b.get('vo') or {}; dur = float(b.get('dur') or 0)
        if b.get('image'):
            out.append(dict(id=b['id'], label=b.get('verb') or '', image=ab(b['image']), audio=ab(vo.get('file')),
                            desc=b.get('what'), text=vo.get('text'), say=vo.get('say'), poly=vo.get('poly'), t0=round(t, 3), t1=round(t + dur, 3)))
        t += dur
    return out


def watch_files(path):
    return [os.path.join(path, 'doc.json')]
