"""命令行代理（能自己读文件的 AI CLI，如 agy、gemini、claude、codex）：一次交一批，自己开图、写 answers.json。
配置：{"type": "cli", "cmd": "agy --model gemini-3.8-flash --dangerously-skip-permissions -p {prompt}", "env": {...}}
jobs>1 时把单拆成 jobs 份同时跑。注意：有的 CLI 要在桌面会话里才能读钥匙串，服务就得在那里启动。"""
import json, os, shlex, shutil, subprocess, tempfile
from concurrent.futures import ThreadPoolExecutor
from .base import Provider, needs_audio

PROMPT = ('你是审片复核员。打开当前目录的 tickets.json。对每张单：打开它的 image（有 audio 且题目问配音时听 audio），'
          '按 asks 逐题只回答 yes、no 或 unsure；只看点名的这一处，不评价别的，看不清或听不出就答 unsure，不读当前目录以外的文件。'
          '把结果写成 JSON 到 answers.json：{"单号": {"0": "yes", "1": "no"}, ...}（内层键是 asks 的 i），然后回复"完成"。')


class CLIAgent(Provider):
    caps = ('ask',)

    def ask(self, t):
        return self.ask_batch([t]).get(t['id']) or {}

    def _run(self, chunk):
        work = tempfile.mkdtemp(prefix='cocheck-'); slim = []
        for t in chunk:
            x = dict(ticket=t['id'], desc=t.get('desc'), text=t.get('text'), asks=[dict(i=q['i'], q=q['q']) for q in t['asks']])
            for key in ('image', 'audio') if needs_audio(t) else ('image',):
                if t.get(key) and os.path.exists(t[key]):
                    local = '%s_%s%s' % (t['item'], key, os.path.splitext(t[key])[1]); shutil.copy(t[key], os.path.join(work, local)); x[key] = local
            slim.append(x)
        json.dump(slim, open(os.path.join(work, 'tickets.json'), 'w'), ensure_ascii=False, indent=1)
        env = dict(os.environ, **self.cfg.get('env', {}))
        r = subprocess.run(self.cfg['cmd'].replace('{prompt}', shlex.quote(PROMPT)), shell=True, cwd=work, env=env,
                           capture_output=True, text=True, timeout=self.cfg.get('timeout', 1800))
        f = os.path.join(work, 'answers.json'); ans = {}
        try: ans = json.load(open(f, encoding='utf-8'))
        except Exception: print('[%s] 没交答案：%s' % (self.name, (r.stdout + r.stderr)[-300:]))
        shutil.rmtree(work, ignore_errors=True)
        return {k: {str(i): str(v).lower() for i, v in a.items()} for k, a in ans.items() if isinstance(a, dict)}

    def ask_batch(self, tickets, jobs=1):
        n = max(1, min(jobs, len(tickets))); out = {}
        with ThreadPoolExecutor(n) as ex:
            for a in ex.map(self._run, [tickets[i::n] for i in range(n)]): out.update(a)
        return out

    def ping(self):
        exe = shlex.split(self.cfg['cmd'])[0]; p = shutil.which(exe, path=self.cfg.get('env', {}).get('PATH', os.environ.get('PATH')))
        return {'ok': bool(p), 'exe': p or ('找不到 %s' % exe)}
