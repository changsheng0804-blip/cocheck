"""cocheck 命令行。

  cocheck doctor [--ping]                    环境自检：依赖、设备、配置、各 provider 是否连得上
  cocheck providers                          列出 provider 和能力
  cocheck serve [--port 8796] [--project 名=适配器:路径 ...]
  cocheck mcp [--url http://127.0.0.1:8796] [--by 名字]   MCP 服务（stdio），给任何支持 MCP 的 AI 领单交卷
  cocheck check  <项目|适配器:路径>           体检 + 开单
  cocheck review <项目> [--provider X --jobs N --escalate]   不给 provider = 按配置的复核员链
  cocheck status <项目>
  cocheck answer <项目> <单号> '{"0":"no"}' --by 名字
配置见 examples/config.example.json；项目也可以临时用「适配器:路径」，如 cocut:~/films/lan。
"""
import argparse, importlib, json, os, platform, shutil, sys
from . import config as C
from .engine import Engine


def _engine(a):
    cfg = C.load(a.config); e = Engine(cfg)
    specs = getattr(a, 'project', None)
    for spec in (specs if isinstance(specs, list) else []):   # 子命令的位置参数 project 会覆盖全局 --project（字符串），别逐字符拆
        name, rest = spec.split('=', 1); ad, path = rest.split(':', 1); e.add_project(name, dict(adapter=ad, path=path))
    return e


def _proj(e, ref):
    if ref in e.projects: return e.project(ref)
    if ':' in ref:
        ad, path = ref.split(':', 1); return e.add_project(os.path.basename(path.rstrip('/')) or 'p', dict(adapter=ad, path=path))
    raise SystemExit('没有这个项目：%s（配置里登记，或写成 适配器:路径）' % ref)


def doctor(a):
    ok = lambda b: '✓' if b else '✗'; rows = []
    rows.append(('python', ok(sys.version_info >= (3, 9)), platform.python_version()))
    from .providers.embeddinggemma import apple_silicon, pick_backend
    local = [('mlx_vlm', '本地向量模型（苹果芯片走 MLX）')] if apple_silicon() else [('torch', '本地向量模型'), ('sentence_transformers', '本地向量模型')]
    for mod, why in [('numpy', '体检'), ('PIL', '体检（切块）')] + local + [('edge_tts', '多音字参照合成')]:
        try: m = importlib.import_module(mod); rows.append((mod, '✓', getattr(m, '__version__', '')))
        except Exception: rows.append((mod, '–', '缺，影响：' + why))
    if pick_backend() == 'mlx': rows.append(('device', '✓', 'MLX（Metal）'))
    else:
        try:
            import torch; rows.append(('device', '✓', 'mps' if torch.backends.mps.is_available() else 'cuda' if torch.cuda.is_available() else 'cpu（慢）'))
        except Exception: pass
    rows.append(('ffmpeg', ok(shutil.which('ffmpeg')), shutil.which('ffmpeg') or '缺，影响：配音检查'))
    cfg = C.load(a.config); rows.append(('config', ok(cfg['_path']), cfg['_path'] or '没找到配置文件（cocheck.json 或 ~/.config/cocheck/config.json）'))
    e = Engine(cfg)
    for n in e.reg.names():
        try:
            p = e.reg.get(n); info = ','.join(p.caps)
            if a.ping: r = p.ping(); rows.append(('provider ' + n, ok(r.get('ok')), info + ' ' + json.dumps({k: v for k, v in r.items() if k != 'ok'}, ensure_ascii=False)))
            else: rows.append(('provider ' + n, '·', info + '（加 --ping 实测）'))
        except Exception as ex: rows.append(('provider ' + n, '✗', str(ex)[:120]))
    if not cfg.get('embed'): rows.append(('embed', '–', '没配 embed provider：只能复核，不能体检'))
    for pr in e.projects.values():
        try: rows.append(('project ' + pr.name, '✓', '%s · %d 条' % (pr.spec.get('adapter'), len(pr.items()))))
        except Exception as ex: rows.append(('project ' + pr.name, '✗', str(ex)[:120]))
    w = max(len(r[0]) for r in rows)
    for r in rows: print('%s  %s  %s' % (r[1], r[0].ljust(w), r[2]))


def main(argv=None):
    ap = argparse.ArgumentParser(prog='cocheck'); ap.add_argument('--config')
    sub = ap.add_subparsers(dest='cmd', required=True)
    s = sub.add_parser('init', help='写用户配置和令牌'); s.add_argument('--project', action='append', default=[], help='名字=路径[@适配器]，适配器 cocut/items/folder，缺省 cocut')
    s.add_argument('--force', action='store_true')
    s = sub.add_parser('doctor'); s.add_argument('--ping', action='store_true')
    sub.add_parser('providers')
    s = sub.add_parser('serve'); s.add_argument('--host', default='127.0.0.1'); s.add_argument('--port', type=int, default=8796)
    s.add_argument('--project', action='append'); s.add_argument('--token', default=C.token())
    s = sub.add_parser('mcp'); s.add_argument('--url', default=os.environ.get('COCHECK_URL', 'http://127.0.0.1:8796'))
    s.add_argument('--by', default=os.environ.get('COCHECK_BY', 'mcp')); s.add_argument('--token', default=C.token())
    s = sub.add_parser('check'); s.add_argument('project')
    s = sub.add_parser('review'); s.add_argument('project'); s.add_argument('--provider'); s.add_argument('--jobs', type=int, default=1)
    s.add_argument('--escalate', action='store_true'); s.add_argument('--second', action='store_true'); s.add_argument('--by')
    s = sub.add_parser('status'); s.add_argument('project')
    s = sub.add_parser('answer'); s.add_argument('project'); s.add_argument('ticket'); s.add_argument('answers'); s.add_argument('--by', required=True); s.add_argument('--note')
    a = ap.parse_args(argv)
    if a.cmd == 'init':
        ps = []
        for x in a.project:
            n, _, rest = x.partition('='); path, _, ad = rest.rpartition('@') if '@' in rest else (rest, '', '')
            ps.append((n, ad or 'cocut', path))
        cf, tf, new = C.init(ps, a.force)
        print('配置：%s\n令牌：%s%s\n下一步：编辑配置里的 providers（密钥写成 ${环境变量}），然后 cocheck doctor、cocheck serve' % (cf, tf, '（新生成）' if new else '（沿用）'))
        return
    if a.cmd == 'doctor': return doctor(a)
    if a.cmd == 'mcp':
        from .mcp import serve as mcp_serve; return mcp_serve(a.url, a.by, a.token)
    e = _engine(a)
    if a.cmd == 'providers': return print(json.dumps(e.reg.info(), ensure_ascii=False, indent=1))
    if a.cmd == 'serve':
        from .server import serve; return serve(e, a.host, a.port, a.token)
    pr = _proj(e, a.project)
    if a.cmd == 'check':
        rep, opened = pr.check(); print(json.dumps(dict(seconds=rep['seconds'], cache=rep['cache'], **{k: len(v) for k, v in opened.items()}), ensure_ascii=False))
    elif a.cmd == 'review':
        if a.provider: print(json.dumps(pr.review_once(a.provider, a.jobs, a.escalate, a.second, a.by), ensure_ascii=False))
        else:
            for r in pr.reviewers():
                if not r.get('off'): print(json.dumps(pr.review_once(r['provider'], r.get('jobs', 1), r.get('escalate', False), by=r.get('by')), ensure_ascii=False))
    elif a.cmd == 'status':
        for iid, v in pr.store.status(pr.items()).items():
            why = '；'.join('%s（%s）' % (p['what'], ','.join(p['by'])) for p in v.get('problems', []))
            print('%-6s %-6s %s' % (iid, v['color'], why))
    elif a.cmd == 'answer':
        print(json.dumps(pr.store.answer(a.ticket, a.by, json.loads(a.answers), a.note)[0], ensure_ascii=False))


if __name__ == '__main__':
    main()
