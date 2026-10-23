"""来自雪人片头试用的修正：画内有意文字、声音描述、复核员链默认关闭/进度/取消。"""
import json, time, unittest, urllib.request
from helpers import Env, FakeAsk
from cocheck.checks import Reflex
from cocheck.review import asks_for, verdict


class SlowAsk(FakeAsk):
    def ask(self, t): time.sleep(0.15); return super().ask(t)


class Feedback(unittest.TestCase):
    def test_expected_text(self):
        flagged = {'text_in_image': {'flag': True, 'score': 0.01, 'tile': 2}}
        a = asks_for({'expect_text': ['×30 延时']}, flagged)
        self.assertEqual(len(a), 1); self.assertIn('×30 延时', a[0]['q']); self.assertEqual(a[0]['expect'], ['×30 延时'])
        self.assertEqual(asks_for({'expect_text': []}, flagged), [])            # 允许有字、不核对
        self.assertIn('有没有任何可见的字母', asks_for({}, flagged)[0]['q'])      # 没声明：照旧
        v = verdict({'asks': a}, {'x': {'answers': {'0': 'no'}}}); self.assertEqual(v['color'], 'green')
        v = verdict({'asks': a}, {'x': {'answers': {'0': 'yes'}}}); self.assertEqual(v['problems'][0]['what'], 'expect')

    def test_swap_question_visual_only(self):
        a = asks_for({'desc': '招牌镜头：俯冲到雪人身高，音乐磁带停转进静默'}, {'coverage': {'swap': True}})
        self.assertNotIn('磁带', a[0]['q']); self.assertIn('俯冲', a[0]['q'])

    def test_sound_not_visual(self):
        els = Reflex.elements('实时：只剩海浪和踩雪声，雪人一步一步走到奶奶家门口')
        self.assertEqual(els, ['雪人一步一步走到奶奶家门口'])
        self.assertEqual(Reflex.elements('静默②：海浪也退下，只剩一口风'), ['海浪也退下', '只剩一口风'])

    def test_reviewers_off_and_runtime_default(self):
        e = Env(); e.engine.cfg['reviewers'] = [{'provider': 'fake'}]
        try:
            self.assertEqual(e.pr.reviewers(), [{'provider': 'fake'}])           # 配置文件里的项目：照旧用全局链
            e.pr.spec['reviewers'] = False; self.assertEqual(e.pr.reviewers(), [])
            url = e.serve(); body = json.dumps(dict(name='rt', adapter='folder', path=e.film)).encode()
            urllib.request.build_opener(urllib.request.ProxyHandler({})).open(urllib.request.Request(url + '/v1/projects', data=body, headers={'Content-Type': 'application/json'}), timeout=10)
            self.assertEqual(e.engine.project('rt').reviewers(), [])            # 运行时登记默认不自动复核
        finally: e.close()

    def test_progress_and_cancel(self):
        e = Env(n=6)
        try:
            e.engine.reg._p['slow'] = SlowAsk(); e.pr.spec['reviewers'] = [{'provider': 'slow'}, {'provider': 'slow', 'by': 'b'}]
            e.open(); e.pr.request_review(); time.sleep(0.4)
            s = e.pr.review_state; self.assertTrue(s['running']); self.assertEqual(s['step'], '1/2'); self.assertEqual(s['total'], 6); self.assertGreater(s['done'], 0)
            e.pr.cancel_review()
            for _ in range(40):
                if not s['running']: break
                time.sleep(0.05)
            self.assertFalse(s['running']); self.assertTrue(s['cancelled'])
            answered = e.pr.store.load()['answers']; self.assertLess(len(answered), 6)
            self.assertFalse(any('b' in v for v in answered.values()))          # 第二个复核员没被唤起
        finally: e.close()


if __name__ == '__main__': unittest.main()
