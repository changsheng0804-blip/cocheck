"""最简单：一个文件夹的图片，文件名即 id；同名 .txt 作画面说明，同名 .mp3/.wav 作配音（同名 .vo.txt 作文案）。"""
import os

IMG = ('.jpg', '.jpeg', '.png', '.webp')


def items(path, **_):
    out = []
    for f in sorted(os.listdir(path)):
        stem, ext = os.path.splitext(f)
        if ext.lower() not in IMG: continue
        rd = lambda s: open(os.path.join(path, s), encoding='utf-8').read().strip() if os.path.exists(os.path.join(path, s)) else None
        au = next((os.path.join(path, stem + e) for e in ('.mp3', '.wav') if os.path.exists(os.path.join(path, stem + e))), None)
        out.append(dict(id=stem, image=os.path.join(path, f), audio=au, desc=rd(stem + '.txt'), text=rd(stem + '.vo.txt')))
    return out


def watch_files(path, **_):
    return [path]
