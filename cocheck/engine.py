"""把三层串起来：项目（适配器 + 存储）→ 体检 → 开单 → 唤起复核员。服务和 CLI 共用。

后台行为（cocheck serve 时）：
  - 监视每个项目的数据文件（如 cocut 的 doc.json），一变就重新体检（向量有缓存，只重算改过的条目）
  - 体检开出新单后，按 reviewers 依次唤起复核员：普通的答全部新单，escalate 的只看当前红/黄
  - 项目 spec 的 reviewers：不写 = 用全局复核员链；false / [] = 只做反射层体检、不自动花模型额度；列表 = 这个项目自己的链
    运行时登记（POST /v1/projects）默认 reviewers=false，要显式给 true 或列表才自动唤起
  - 复核进度：review_state 里 who / step（第几个复核员/共几个）/ done / total；POST .../review/cancel 取消（正在问的那一批问完即停）
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
        self.review_state = dict(running=False, pending=False, who=None, step=None, done=0, total=0, started=None, last=None, error=None, cancelled=False)
        self._cancel = False
        rp = os.path.join(self.store.dir, 'reflex.json')
        if os.path.exists(rp):
            try: self.check_state.update(last=time.strftime('%m-%d %H:%M', time.localtime(os.path.getmtime(rp))), seconds=json.load(open(rp)).get('seconds'))
            except Exception: pass
        self._mt = self._mtime()

    @property
    def opts(self): return {k: v for k, v in self.spec.items() if k not in ('adapter', 'path', 'store', 'reviewers', 'embed')}

    def items(self): return self.adapter.items(self.path, **self.opts)

    def item(self, iid): return next((x for x in self.items() if x['id'] == iid), None)

    def reviewers(self):
        r = self.spec.get('reviewers', True)
        if r is True or r is None: return self.e.cfg.get('reviewers', [])
        return r or []

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
        t0 = time.time(); prov = self.e.reg.get(provider); s = self.review_state; s.update(done=0, total=len(tickets)); n = 0; jobs = max(1, int(jobs or 1))
        step = jobs * getattr(prov, 'per_call', 1)                 # 一批 jobs×per_call 张（命令行代理一次答几张）：每批后更新进度、检查取消
        for i in range(0, len(tickets), step):
            if self._cancel: break
            chunk = tickets[i:i + step]; ids = {t['id'] for t in chunk}; got = []
            def done(tid, a):
                if tid in ids and tid not in got: got.append(tid); self.store.answer(tid, by, a); s['done'] += 1
            ans = prov.ask_batch(chunk, jobs, on_done=done)
            for tid, a in ans.items(): done(tid, a)                # 不支持回调的 provider 在这里补落盘
            n += len(got)
        return dict(by=by, tickets=len(tickets), answered=n, seconds=round(time.time() - t0, 1), cancelled=self._cancel)

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
        if s['error'] is None and self.e.cfg.get('auto', {}).get('review', True) and self.reviewers() and self.store.list_open(): self.request_review()

    def cancel_review(self):
        s = self.review_state; s['pending'] = False
        if s['running']: self._cancel = True
        return s

    def request_review(self, chain=None):
        # chain：这次只跑这些复核员（手动指定 provider 时）；不给 = 项目配置的链。进度和取消同一套
        s = self.review_state; s['pending'] = True; self._cancel = False; self._chain = chain
        if not s['running']: s['running'] = True; threading.Thread(target=self._review_loop, daemon=True).start()

    def _review_loop(self):
        s = self.review_state; s.update(started=time.strftime('%H:%M:%S'), cancelled=False)
        while s['pending'] and not self._cancel:
            s['pending'] = False; chain = [r for r in (getattr(self, '_chain', None) or self.reviewers()) if not r.get('off')]
            for k, r in enumerate(chain):
                if self._cancel: break
                s.update(who=r.get('by') or r['provider'], step='%d/%d' % (k + 1, len(chain)), done=0, total=0)
                try:
                    res = self.review_once(r['provider'], r.get('jobs', 1), r.get('escalate', False), by=r.get('by'))
                    s.update(last='%s %s：%d 张，%ss' % (time.strftime('%H:%M:%S'), res['by'], res['answered'], res['seconds']), error=None)
                except Exception as ex: s['error'] = '%s: %s' % (type(ex).__name__, ex)
        if self._cancel: s.update(cancelled=True, last='%s 已取消' % time.strftime('%H:%M:%S'))
        self._cancel = False; self._chain = None; s.update(running=False, who=None, step=None)

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
