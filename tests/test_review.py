import os, unittest
from PIL import Image
from helpers import Env, REPORT
from cocheck.review import verdict


class ReviewFlow(unittest.TestCase):
    def setUp(self): self.e = Env(); self.store = self.e.pr.store

    def tearDown(self): self.e.close()

    def test_open_and_answer(self):
        out = self.e.open()
        self.assertEqual(len(out['opened']), 2)
        tid = out['opened'][0]
        r, code = self.store.answer(tid, 'a', {'0': 'no'})
        self.assertEqual(code, 200); self.assertEqual(r['verdict']['color'], 'red')
        r, _ = self.store.answer(tid, 'b', {'0': 'maybe'})          # 非法答案按 unsure
        self.assertEqual(self.store.load()['answers'][tid]['b']['answers']['0'], 'unsure')
        r, code = self.store.answer('nope', 'a', {})
        self.assertEqual(code, 404)

    def test_stale_and_revert(self):
        tid = self.e.open()['opened'][0]; item = tid.split('-')[0]
        self.store.answer(tid, 'a', {'0': 'yes'})
        img = os.path.join(self.e.film, item + '.png'); orig = open(img, 'rb').read()
        Image.new('RGB', (32, 18), (255, 0, 0)).save(img)            # 改画面
        self.assertEqual(self.store.status(self.e.pr.items())[item]['color'], 'grey')
        out = self.e.open()
        self.assertIn(tid, out['stale'])
        r, code = self.store.answer(tid, 'b', {'0': 'yes'})
        self.assertEqual(code, 409)
        open(img, 'wb').write(orig)                                   # 改回旧版本 → 恢复原判
        out = self.e.open()
        self.assertIn(tid, out['kept'])
        self.assertEqual(self.store.load()['tickets'][tid]['status'], 'answered')
        self.assertEqual(self.store.status(self.e.pr.items())[item]['color'], 'green')

    def test_list_open_skips_own(self):
        out = self.e.open(); tid = out['opened'][0]
        self.store.answer(tid, 'a', {'0': 'yes'})
        self.assertNotIn(tid, [t['id'] for t in self.store.list_open('a', second=True)])
        self.assertIn(tid, [t['id'] for t in self.store.list_open('b', second=True)])


    def test_concurrent_answers_not_lost(self):
        from concurrent.futures import ThreadPoolExecutor
        from cocheck.review import Store
        tid = self.e.open()['opened'][0]
        with ThreadPoolExecutor(16) as ex:                            # 16 个复核员同时交卷，各自新建 Store（像不同请求）
            list(ex.map(lambda i: Store(self.store.dir).answer(tid, 'r%d' % i, {'0': 'yes'}), range(16)))
        self.assertEqual(len(self.store.load()['answers'][tid]), 16)


class Verdict(unittest.TestCase):
    T = {'asks': [{'i': '0', 'k': 'el', 'el': '星星'}, {'i': '1', 'k': 'text'}]}
    A = lambda self, **kw: {r: {'answers': a} for r, a in kw.items()}

    def test_majority_and_tie(self):
        v = verdict(self.T, self.A(a={'0': 'no', '1': 'no'}, b={'0': 'yes', '1': 'no'}))
        self.assertEqual(v['color'], 'red'); self.assertEqual(v['problems'][0]['against'], ['b'])   # 平票算有问题
        v = verdict(self.T, self.A(a={'0': 'yes', '1': 'yes'}))
        self.assertEqual([p['k'] for p in v['problems']], ['text'])                               # text 题答 yes 才是问题

    def test_all_unsure_is_yellow(self):
        self.assertEqual(verdict(self.T, self.A(a={'0': 'unsure', '1': 'unsure'}))['color'], 'yellow')

    def test_human_final(self):
        v = verdict(self.T, self.A(a={'0': 'no', '1': 'yes'}, user={'0': 'yes', '1': 'no'}))
        self.assertEqual((v['color'], v['final'], v['reviewers']), ('green', True, ['user']))


if __name__ == '__main__': unittest.main()
