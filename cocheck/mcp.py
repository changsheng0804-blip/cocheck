"""cocheck MCP 服务（stdio，零依赖）：让任何支持 MCP 的 AI（Claude、Gemini CLI、Codex、agy……）直接领单、看图听音、交卷。

它只是 cocheck HTTP 服务的薄壳：模型和数据都在 `cocheck serve` 那边，这里不加载任何模型。
  cocheck mcp [--url http://127.0.0.1:8796] [--by 名字]

接到 AI 客户端（以 Claude Desktop / Gemini CLI 的 mcpServers 配置为例）：
  {"mcpServers": {"cocheck": {"command": "cocheck", "args": ["mcp", "--by", "claude"]}}}
"""
import base64, json, os, sys, urllib.request, urllib.error

PROTOCOL = '2025-06-18'
MIME = {'.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png', '.webp': 'image/webp', '.mp3': 'audio/mpeg', '.wav': 'audio/wav'}

S = lambda **p: {'type': 'object', 'properties': p, 'required': [k for k, v in p.items() if not v.pop('_opt', False)]}
STR = lambda d, opt=False: {'type': 'string', 'description': d, '_opt': opt}

TOOLS = [
    dict(name='cocheck_projects', description='列出接入 cocheck 的项目，以及每个项目的红/绿/黄/灰数量、体检和复核员状态。', inputSchema=S()),
    dict(name='cocheck_status', description='一个项目里每个条目当前的审核颜色、问题、谁说的、谁不同意。green 没问题 / red 有问题 / yellow 待复核 / grey 改过了等重新体检。',
         inputSchema=S(project=STR('项目名'))),
    dict(name='cocheck_next_ticket', description='领下一张待复核的单：返回单号、画面说明、配音文案、点名问题，并直接附上画面图片（问配音时附音频）。'
                                                 '逐题只答 yes / no / unsure，只看点名的那一处，然后用 cocheck_answer 交卷。没有单时返回空。',
         inputSchema=S(project=STR('项目名'), by=STR('你的复核员名字（默认用启动参数 --by）', True),
                       hot=dict(type='boolean', description='只领红/黄的（给第二意见）', _opt=True))),
    dict(name='cocheck_answer', description='交卷。answers 的键是题号 i，值是 yes / no / unsure。单号过期（素材改过）会被拒，重新领即可。',
         inputSchema=S(project=STR('项目名'), ticket=STR('单号'), answers=dict(type='object', description='{"0": "no", "1": "yes"}'),
                       by=STR('你的复核员名字（默认用启动参数 --by）', True), note=STR('一句理由（可选）', True))),
    dict(name='cocheck_check', description='立即重新体检一个项目（平时数据一改会自动体检）。', inputSchema=S(project=STR('项目名'))),
    dict(name='cocheck_review', description='唤起配置好的复核员（不给 provider 按复核员链跑）。', inputSchema=S(project=STR('项目名'), provider=STR('provider 名字', True))),
    dict(name='cocheck_providers', description='列出统一模型接入口里登记的模型（embed / ask 能力）和复核员链。', inputSchema=S()),
]


class Client:
    def __init__(self, url, token=None): self.url = url.rstrip('/'); self.token = token

    def _req(self, path, body=None, raw=False):
        h = {'Content-Type': 'application/json'}
        if self.token: h['Authorization'] = 'Bearer ' + self.token
        req = urllib.request.Request(self.url + path, data=None if body is None else json.dumps(body).encode(), headers=h)
        try:
            r = urllib.request.urlopen(req, timeout=120); return r.read() if raw else json.load(r)
        except urllib.error.HTTPError as e:
            try: msg = json.load(e).get('error')
            except Exception: msg = str(e)
            raise RuntimeError(msg)

    get = lambda self, p, raw=False: self._req(p, raw=raw)
    post = lambda self, p, b: self._req(p, b or {})


def call(c, name, a, by):
    pj = lambda: '/v1/projects/' + a['project']
    txt = lambda o: [{'type': 'text', 'text': o if isinstance(o, str) else json.dumps(o, ensure_ascii=False, indent=1)}]
    if name == 'cocheck_projects': return txt(c.get('/v1/projects')['projects'])
    if name == 'cocheck_providers': return txt(c.get('/v1/providers'))
    if name == 'cocheck_status':
        st = c.get(pj() + '/status')
        lines = []
        for x in st['items']:
            v = st['status'].get(x['id'])
            if not v: continue
            why = '；'.join('%s（%s%s）' % (p['what'], ','.join(p['by']), '；%s 不同意' % ','.join(p['against']) if p['against'] else '') for p in v.get('problems', []))
            lines.append('%s %s %s' % (x['id'], v['color'], why or ('拿不准：' + '、'.join(v['unsure']) if v.get('unsure') else '')))
        return txt('\n'.join(lines))
    if name == 'cocheck_next_ticket':
        who = a.get('by') or by
        ts = c.get(pj() + '/tickets?by=%s%s' % (who, '&hot=1' if a.get('hot') else ''))['tickets']
        if not ts: return txt('没有待复核的单。')
        t = ts[0]; head = dict(ticket=t['id'], item=t['item'], remaining=len(ts) - 1, desc=t.get('desc'), asks=[dict(i=q['i'], q=q['q']) for q in t['asks']])
        if any(q['k'] in ('vo', 'poly') for q in t['asks']): head['text'] = t.get('text')
        out = txt(head)
        for kind in ('image', 'audio'):
            u = t.get(kind)
            if not u or (kind == 'audio' and 'text' not in head): continue
            data = c.get(u, raw=True); ext = os.path.splitext(t.get(kind + '_name') or '')[1]
            mime = 'image/jpeg' if kind == 'image' else 'audio/mpeg'
            out.append({'type': kind, 'data': base64.b64encode(data).decode(), 'mimeType': MIME.get(ext, mime)})
        return out
    if name == 'cocheck_answer':
        return txt(c.post(pj() + '/answer', dict(ticket=a['ticket'], by=a.get('by') or by, answers=a['answers'], note=a.get('note'))))
    if name == 'cocheck_check': return txt(c.post(pj() + '/check', {}))
    if name == 'cocheck_review': return txt(c.post(pj() + '/review', {'provider': a['provider']} if a.get('provider') else {}))
    raise RuntimeError('未知工具：' + name)


def serve(url, by='mcp', token=None, inp=sys.stdin, out=sys.stdout):
    c = Client(url, token)
    send = lambda m: (out.write(json.dumps(m, ensure_ascii=False) + '\n'), out.flush())
    for line in inp:
        line = line.strip()
        if not line: continue
        try: m = json.loads(line)
        except Exception: send({'jsonrpc': '2.0', 'id': None, 'error': {'code': -32700, 'message': 'parse error'}}); continue
        mid, meth, p = m.get('id'), m.get('method'), m.get('params') or {}
        if mid is None: continue                                   # 通知（notifications/initialized 等）不回
        res = err = None
        if meth == 'initialize':
            res = {'protocolVersion': p.get('protocolVersion', PROTOCOL), 'capabilities': {'tools': {}},
                   'serverInfo': {'name': 'cocheck', 'version': '0.1.0'},
                   'instructions': '审核复核员：先 cocheck_projects 看项目，再循环 cocheck_next_ticket → 看图/听音逐题答 yes/no/unsure → cocheck_answer，直到没有单。'}
        elif meth == 'ping': res = {}
        elif meth == 'tools/list': res = {'tools': TOOLS}
        elif meth == 'tools/call':
            try: res = {'content': call(c, p['name'], p.get('arguments') or {}, by), 'isError': False}
            except Exception as e: res = {'content': [{'type': 'text', 'text': '出错：%s' % e}], 'isError': True}
        else: err = {'code': -32601, 'message': 'method not found: %s' % meth}
        send({'jsonrpc': '2.0', 'id': mid, **({'error': err} if err else {'result': res})})
