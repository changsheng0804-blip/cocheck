"""通用：一个 items.json（列表，字段见 adapters/__init__.py），相对路径以文件所在目录为准。"""
import json, os


def items(path, file='items.json', **_):
    f = path if path.endswith('.json') else os.path.join(path, file); base = os.path.dirname(os.path.abspath(f))
    out = json.load(open(f, encoding='utf-8'))
    for x in out:
        for k in ('image', 'audio'):
            if x.get(k) and not os.path.isabs(x[k]): x[k] = os.path.join(base, x[k])
    return out


def watch_files(path, file='items.json', **_):
    return [path if path.endswith('.json') else os.path.join(path, file)]
