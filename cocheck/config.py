"""配置：一个 JSON 文件。查找顺序：--config / $COCHECK_CONFIG / ./cocheck.json / ~/.config/cocheck/config.json。
字符串里的 ${VAR} 用环境变量替换（密钥只放环境变量，不写进文件）。"""
import json, os, re

DEFAULT = {
    'providers': {},          # 名字 -> {type, ...}
    'embed': None,            # 体检用哪个 embed provider（名字）；不配就只做不需要模型的部分
    'reviewers': [],          # [{provider, jobs?, escalate?, off?}] 依次唤起
    'projects': {},           # 名字 -> {adapter, path, ...}
    'auto': {'check': True, 'review': True},
}


def _expand(x):
    if isinstance(x, str): return re.sub(r'\$\{(\w+)\}', lambda m: os.environ.get(m.group(1), ''), x)
    if isinstance(x, list): return [_expand(v) for v in x]
    if isinstance(x, dict): return {k: _expand(v) for k, v in x.items()}
    return x


def find(path=None):
    for p in (path, os.environ.get('COCHECK_CONFIG'), 'cocheck.json', os.path.expanduser('~/.config/cocheck/config.json')):
        if p and os.path.exists(p): return p
    return None


def load(path=None):
    p = find(path); cfg = json.loads(json.dumps(DEFAULT))
    if p: cfg.update(_expand(json.load(open(p, encoding='utf-8'))))
    cfg['_path'] = p; return cfg
