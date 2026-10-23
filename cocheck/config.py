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


HOME = os.path.expanduser('~/.config/cocheck')


def token():
    """令牌：$COCHECK_TOKEN，否则 ~/.config/cocheck/token（cocheck init 生成）。"""
    t = os.environ.get('COCHECK_TOKEN')
    if t: return t
    f = os.path.join(HOME, 'token')
    return open(f).read().strip() if os.path.exists(f) else None


TEMPLATE = {
    'providers': {
        'gemini': {'type': 'gemini', 'model': 'gemini-3.8-flash', 'api_key': '${GEMINI_API_KEY}', 'note': '示例：换成你自己的模型；本地 embed 见 README'},
    },
    'embed': None,
    'reviewers': [{'provider': 'gemini', 'jobs': 2}],
    'projects': {},
    'auto': {'check': True, 'review': True},
}


def init(projects=(), force=False):
    """写 ~/.config/cocheck/config.json（已存在则只追加项目）和令牌文件。projects: [(名字, 适配器, 路径)]"""
    import secrets
    os.makedirs(HOME, exist_ok=True)
    cf = os.path.join(HOME, 'config.json')
    cfg = json.load(open(cf, encoding='utf-8')) if os.path.exists(cf) and not force else json.loads(json.dumps(TEMPLATE))
    for name, adapter, path in projects:
        cfg.setdefault('projects', {})[name] = {'adapter': adapter, 'path': os.path.abspath(os.path.expanduser(path))}
    json.dump(cfg, open(cf, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    tf = os.path.join(HOME, 'token'); new = not os.path.exists(tf)
    if new:
        open(tf, 'w').write(secrets.token_hex(16)); os.chmod(tf, 0o600)
    return cf, tf, new
