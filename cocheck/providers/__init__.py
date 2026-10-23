"""provider 注册表：配置里的 type → 类。新增模型接入只要在这里加一行。"""
from .base import Provider

TYPES = {
    'local_embed': ('embeddinggemma', 'LocalEmbed'),
    'gemini': ('gemini', 'Gemini'),
    'openai': ('openai_compat', 'OpenAICompat'),
    'cli': ('cli', 'CLIAgent'),
    'remote': ('remote', 'Remote'),
}


def build(name, cfg):
    t = cfg.get('type')
    if t not in TYPES: raise ValueError('未知的 provider 类型 %r（可用：%s）' % (t, ', '.join(TYPES)))
    import importlib
    mod, cls = TYPES[t]; C = getattr(importlib.import_module('.' + mod, __name__), cls)
    return C(name, **{k: v for k, v in cfg.items() if k != 'type'})


class Registry:
    """按名字懒加载 provider；同一个名字只建一次（本地模型常驻内存）。"""
    def __init__(self, cfg):
        self.cfg = cfg.get('providers', {}); self._p = {}

    def get(self, name):
        if name not in self._p:
            if name not in self.cfg: raise KeyError('没有配置 provider：%s' % name)
            self._p[name] = build(name, self.cfg[name])
        return self._p[name]

    def names(self): return list(self.cfg)

    def info(self):
        out = []
        for n in self.cfg:
            try: out.append(self.get(n).info())
            except Exception as e: out.append(dict(name=n, error=str(e)))
        return out
