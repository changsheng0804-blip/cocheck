// cocheck 审核色带：任何网页一行嵌入，按条目显示红/绿/黄/灰，点开看问题、复核员意见和分歧，人可以一键裁决。
//
//   <div id="qc"></div>
//   <script src="http://localhost:8796/cocheck-strip.js"></script>
//   <script>
//     CoCheck.strip(document.getElementById('qc'), {
//       api: 'http://localhost:8796', project: 'lan',
//       onSelect: (item) => seek(item.t0),                  // 可选：点色块跳到这条
//       onNote: (item, text) => addNote(item.id, text),     // 可选：「转成意见」
//     });
//   </script>
//
// 只依赖 cocheck 的 HTTP 接口（/v1/projects/<p>/status、/answer、/check），不依赖宿主页面。
(function () {
  'use strict';
  const CSS = `
.cq{font:13px/1.45 -apple-system,"PingFang SC",sans-serif;color:#ecebf1}
.cq-sum{display:flex;gap:10px;align-items:center;margin:0 0 6px}.cq-sum b{font-variant-numeric:tabular-nums}
.cq-g{color:#59c48a}.cq-r{color:#f07a7a}.cq-y{color:#f0b54a}.cq-n{color:#9d9cab}
.cq-bar{position:relative;height:14px;border-radius:5px;overflow:hidden;background:#222}
.cq-c{position:absolute;top:0;bottom:0;border-right:1px solid #111;cursor:pointer}
.cq-c.green{background:#59c48a}.cq-c.red{background:#f07a7a}.cq-c.yellow{background:#f0b54a}
.cq-c.grey{background:repeating-linear-gradient(90deg,#8a8a96 0 6px,#55555f 6px 12px)}.cq-c.split{background:linear-gradient(90deg,#f07a7a 50%,#f0b54a 50%)}
.cq-c.sel{outline:2px solid #86aefc;outline-offset:-2px}
.cq-d{margin-top:8px;background:#292932;border-radius:9px;padding:9px 11px;border-left:5px solid #6f6e7c}
.cq-d.red{border-left-color:#f07a7a}.cq-d.yellow{border-left-color:#f0b54a}.cq-d.green{border-left-color:#59c48a}
.cq-d .m{color:#9d9cab;font-size:12px}.cq-d .p{margin-top:3px}
.cq button{background:#31313b;color:#ecebf1;border:1px solid #444;border-radius:7px;padding:3px 9px;margin:6px 6px 0 0;cursor:pointer;font:inherit}
`;
  const NAME = (r) => ({ user: '你', reflex: '反射层' })[r] || r;
  const LABEL = { green: '没问题', red: '有问题', yellow: '待复核', grey: '改过了，重新体检中' };
  const DESC = (p) => ({ text: '画面里有字', swap: '不是这个场景', el: '缺：' + p.what, vo: '配音不是这句', poly: `「${p.what}」读错` })[p.k] || p.what;
  const cls = (s) => (s.color === 'red' && !s.final && (s.problems || []).some((p) => p.against.length) ? 'red split' : s.color);
  const h = (t, c, x) => { const e = document.createElement(t); if (c) e.className = c; if (x != null) e.textContent = x; return e; };

  function client(api, project, token) {
    const base = api.replace(/\/$/, '') + '/v1/projects/' + encodeURIComponent(project);
    const hd = { 'Content-Type': 'application/json' }; if (token) hd.Authorization = 'Bearer ' + token;
    const post = (p, b) => fetch(base + p, { method: 'POST', headers: hd, body: JSON.stringify(b || {}) }).then((r) => r.json());
    return {
      status: () => fetch(base + '/status').then((r) => r.json()),
      answer: (ticket, by, answers, note) => post('/answer', { ticket, by, answers, note }),
      check: () => post('/check'), review: (o) => post('/review', o),
      judge(s, bad) { const a = {}; for (const q of s.asks) a[q.i] = (q.k === 'text') === bad ? 'yes' : 'no'; return this.answer(s.ticket, 'user', a); },
      line(s) {
        if (s.color === 'red') return s.problems.map((p) => DESC(p) + `（${p.by.map(NAME).join('、')}${p.against.length ? '；' + p.against.map(NAME).join('、') + ' 不同意' : ''}）`).join('；');
        if (s.color === 'green') return '没问题（' + (s.reviewers || ['reflex']).map(NAME).join('、') + '）';
        if (s.color === 'yellow') return s.unsure && s.unsure.length ? '拿不准：' + s.unsure.join('、') : `等 AI 复核 ${s.asks.length} 题`;
        return LABEL.grey;
      },
    };
  }

  function strip(root, o) {
    if (!document.getElementById('cq-css')) { const st = h('style'); st.id = 'cq-css'; st.textContent = CSS; document.head.appendChild(st); }
    const c = client(o.api, o.project, o.token); let data = null, sel = null, key = '';
    root.classList.add('cq'); const sum = h('div', 'cq-sum'), bar = h('div', 'cq-bar'), det = h('div'); root.append(sum, bar, det);
    function render() {
      const st = data.status, items = data.items, v = Object.values(st), n = (k) => v.filter((x) => x.color === k).length;
      sum.innerHTML = `审核 <b class="cq-g">${n('green')}</b>绿 <b class="cq-r">${n('red')}</b>红 <b class="cq-y">${n('yellow')}</b>待 ${n('grey') ? `<b class="cq-n">${n('grey')}</b>重查` : ''}`
        + (data.check.running ? ' · 体检中…' : data.reviewers.who ? ` · ${NAME(data.reviewers.who)} 复核中…` : '');
      const timed = items.every((x) => x.t1 != null), end = timed ? Math.max(...items.map((x) => x.t1)) : items.length;
      bar.innerHTML = '';
      items.forEach((x, i) => {
        const s = st[x.id]; if (!s) return; const e = h('div', 'cq-c ' + cls(s) + (x.id === sel ? ' sel' : ''));
        const a = timed ? x.t0 : i, b = timed ? x.t1 : i + 1; e.style.left = (a / end) * 100 + '%'; e.style.width = ((b - a) / end) * 100 + '%';
        e.title = `${x.id}：${c.line(s)}`; e.onclick = () => { sel = x.id; render(); o.onSelect && o.onSelect(x, s); }; bar.appendChild(e);
      });
      det.innerHTML = ''; const x = items.find((y) => y.id === sel), s = x && st[x.id]; if (!s) return;
      const d = h('div', 'cq-d ' + cls(s)); d.appendChild(h('div', '', `${x.id} · ${LABEL[s.color]}${s.final ? ' · 你已裁决' : ''}`));
      if (x.desc) d.appendChild(h('div', 'm', x.desc));
      if (s.color === 'red') for (const p of s.problems) d.appendChild(h('div', 'p', `${DESC(p)} —— ${p.by.map(NAME).join('、')} 说有问题${p.against.length ? '，' + p.against.map(NAME).join('、') + ' 不同意' : ''}`));
      if (s.color === 'yellow') for (const q of s.asks) d.appendChild(h('div', 'p', '？ ' + q.q));
      for (const [who, a] of Object.entries(s.answers || {})) if (a.note) d.appendChild(h('div', 'm', `${NAME(who)}：${a.note}`));
      const btn = (t, f) => { const b = h('button', '', t); b.onclick = f; d.appendChild(b); };
      if (s.color === 'red' && o.onNote) btn('转成意见', () => o.onNote(x, '审核：' + s.problems.map(DESC).join('；')));
      if (s.ticket && s.asks.length && s.color !== 'grey') { btn('我判没问题', () => c.judge(s, false).then(poll)); btn('我判有问题', () => c.judge(s, true).then(poll)); }
      det.appendChild(d);
    }
    async function poll() {
      try { const j = await c.status(); const k = JSON.stringify([j.status, j.check.running, j.reviewers.who, j.items]); if (k !== key) { key = k; data = j; render(); } } catch (e) { sum.textContent = 'cocheck 服务没连上'; }
    }
    poll(); const iv = setInterval(poll, o.every || 2000);
    return { refresh: poll, stop: () => clearInterval(iv), select: (id) => { sel = id; data && render(); }, client: c };
  }

  window.CoCheck = { strip, client };
})();
