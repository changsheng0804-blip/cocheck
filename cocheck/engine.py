"""把三层串起来：项目（适配器 + 存储）→ 体检 → 开单 → 唤起复核员。服务和 CLI 共用。

后台行为（cocheck serve 时）：
  - 监视每个项目的数据文件（如 cocut 的 doc.json），一变就重新体检（向量有缓存，只重算改过的条目）
  - 体检开出新单后，按 reviewers 依次唤起复核员：普通的答全部新单，escalate 的只看当前红/黄
"""
import json, os, threading, time
from . import checks
from .adapters import load as load_adapter
from .providers import Registry
from .review import Store


class Project:
    def __init__(self, engine, name, spec):
        self.e = engine; self.name = name; self.spec = spec
        self.adapter = load_adapter(spec.get('adapter', 'items'))
        self.path = os.path.abspath(os.path.expanduser(spec['path']))
        self.store = Store(spec.get('store') or os.path.join(self.path if os.path.isdir(self.path) else os.path.dirname(self.path), '.cocheck'))
        self.check_state = dict(running=False, pending=False, last=None, seconds=None, error=None)
        self.review_state = dict(running=False, pending=False, who=None, last=None, error=None)
        rp = os.path.join(self.store.dir, 'reflex.json')
        if os.path.exists(rp):
            try: self.check_state.update(last=time.strftime('%m-%d %H:%M', time.localtime(os.path.getmtime(rp))), seconds=json.load(open(rp)).get('seconds'))
            except Exception: pass
        self._mt = self._mtime()

    @property
    def opts(self): return {k: v for k, v in self.spec.items() if k not in ('adapter', 'path', 'store', 'reviewers', 'embed')}

    def items(self): return self.adapter.items(self.path, **self.opts)

    def item(self, iid): return next((x for x in self.items() if x['id'] == iid), None)

    def reviewers(self): return self.spec.get('reviewers', self.e.cfg.get('reviewers', []))

    # ---- 体检 ----
    def check(self):
        name = self.spec.get('embed', self.e.cfg.get('embed'))
        if not name: raise RuntimeError('没有配置 embed provider，无法体检')
        items = self.items()
        rep = checks.run(items, self.e.reg.get(name), os.path.join(self.store.dir, 'cache'))
        json.dump(rep, open(os.path.join(self.store.dir, 'reflex.json'), 'w'), ensure_ascii=False, indent=1)
        return rep, self.store.open_tickets(items, rep)

    # ---- 复核 ----
    def review_once(self, provider, jobs=1, escalate=False, second=False, by=None):
        by = by or provider
        only = None
        if escalate:
            only = {v['ticket'] for v in self.store.status(self.items()).values() if v['color'] in ('red', 'yellow')}
        tickets = self.store.list_open(by, second or escalate, only)
        if not tickets: return dict(by=by, tickets=0, answered=0, seconds=0)
        t0 = time.time(); ans = self.e.reg.get(provider).ask_batch(tickets, jobs)
        for t in tickets:
            if t['id'] in ans: self.store.answer(t['id'], by, ans[t['id']])
        return dict(by=by, tickets=len(tickets), answered=len([t for t in tickets if t['id'] in ans]), seconds=round(time.time() - t0, 1))

    # ---- 后台 ----
    def request_check(self):
        s = self.check_state; s['pending'] = True
        if not s['running']: s['running'] = True; threading.Thread(target=self._check_loop, daemon=True).start()

    def _check_loop(self):
        s = self.check_state
        while s['pending']:
            s['pending'] = False
            try:
                rep, opened = self.check(); s.update(last=time.strftime('%H:%M:%S'), seconds=rep['seconds'], error=None)
            except Exception as ex: s['error'] = '%s: %s' % (type(ex).__name__, ex)
        s['running'] = False
        if s['error'] is None and self.e.cfg.get('auto', {}).get('review', True) and self.store.list_open(): self.request_review()

    def request_review(self):
        s = self.review_state; s['pending'] = True
        if not s['running']: s['running'] = True; threading.Thread(target=self._review_loop, daemon=True).start()

    def _review_loop(self):
        s = self.review_state
        while s['pending']:
            s['pending'] = False
            for r in self.reviewers():
                if r.get('off'): continue
                s['who'] = r.get('by') or r['provider']
                try:
                    res = self.review_once(r['provider'], r.get('jobs', 1), r.get('escalate', False), by=r.get('by'))
                    s.update(last='%s %s：%d 张，%ss' % (time.strftime('%H:%M:%S'), res['by'], res['answered'], res['seconds']), error=None)
                except Exception as ex: s['error'] = '%s: %s' % (type(ex).__name__, ex)
        s.update(running=False, who=None)

    def _mtime(self):
        try: return max(os.path.getmtime(f) for f in self.adapter.watch_files(self.path, **self.opts) if os.path.exists(f))
        except Exception: return 0

    def poll(self):
        m = self._mtime()
        if m != self._mt: self._mt = m; return True
        return False

    def summary(self):
        st = self.store.status(self.items()); n = lambda c: sum(1 for v in st.values() if v['color'] == c)
        return dict(name=self.name, adapter=self.spec.get('adapter'), path=self.path,
                    counts=dict(green=n('green'), red=n('red'), yellow=n('yellow'), grey=n('grey')),
                    check=self.check_state, reviewers=self.review_state)


class Engine:
    def __init__(self, cfg):
        self.cfg = cfg; self.reg = Registry(cfg)
        self.projects = {n: Project(self, n, s) for n, s in cfg.get('projects', {}).items()}

    def project(self, name):
        if name not in self.projects: raise KeyError('没有这个项目：%s' % name)
        return self.projects[name]

    def add_project(self, name, spec):
        self.projects[name] = Project(self, name, spec); return self.projects[name]

    def watch(self, every=2.0):
        """数据一变就自动体检（cocheck serve 时开）。"""
        if not self.cfg.get('auto', {}).get('check', True): return
        def loop():
            while True:
                time.sleep(every)
                for p in list(self.projects.values()):
                    try:
                        if p.poll(): p.request_check()
                    except Exception: pass
        threading.Thread(target=loop, daemon=True).start()
