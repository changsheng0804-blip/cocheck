"""测试公用：临时项目（folder 适配器）、假模型、起一个真服务。不联网、不加载真模型。"""
import os, shutil, sys, tempfile, threading
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # 不安装也能跑
from http.server import ThreadingHTTPServer
from PIL import Image

from cocheck.engine import Engine
from cocheck.providers.base import Provider
from cocheck.server import make_handler


class FakeAsk(Provider):
    """按预设回答；fail 个数内先抛错（模拟 429 等）。"""
    caps = ('ask',)

    def __init__(self, name='fake', answer='yes', fail=0, err='HTTP 429 Too Many Requests'):
        super().__init__(name); self.answer = answer; self.fail = fail; self.err = err; self.calls = 0

    def ask(self, t):
        self.calls += 1
        if self.calls <= self.fail: raise RuntimeError(self.err)
        return {q['i']: self.answer for q in t['asks']}


def make_film(root, n=2):
    """n 个条目：图 + 画面说明。"""
    os.makedirs(root, exist_ok=True)
    for i in range(n):
        Image.new('RGB', (32, 18), (40 * i, 80, 160)).save(os.path.join(root, 's%d.png' % i))
        open(os.path.join(root, 's%d.txt' % i), 'w', encoding='utf-8').write('玻璃管里打盹的星星 %d' % i)
    return root


REPORT = lambda ids: {'items': {i: {'coverage': {'missing': ['星星']}} for i in ids}}   # 假体检结果：每条点名问一题


class Env:
    """一个临时目录 + Engine（项目 demo）+ 可选真 HTTP 服务。"""
    def __init__(self, token=None, n=2):
        self.dir = tempfile.mkdtemp(prefix='cocheck-test-'); self.film = make_film(os.path.join(self.dir, 'film'), n)
        self.engine = Engine({'providers': {}, 'reviewers': [], 'auto': {'check': False, 'review': False},
                              'projects': {'demo': {'adapter': 'folder', 'path': self.film}}})
        self.pr = self.engine.project('demo'); self.token = token; self.srv = None

    def open(self):
        items = self.pr.items(); return self.pr.store.open_tickets(items, REPORT([x['id'] for x in items]))

    def serve(self):
        self.srv = ThreadingHTTPServer(('127.0.0.1', 0), None); port = self.srv.server_address[1]
        self.url = 'http://127.0.0.1:%d' % port
        self.srv.RequestHandlerClass = make_handler(self.engine, self.token, self.url)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start(); return self.url

    def close(self):
        if self.srv: self.srv.shutdown(); self.srv.server_close()
        shutil.rmtree(self.dir, ignore_errors=True)
