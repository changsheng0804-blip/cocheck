import json, os, tempfile, unittest
import helpers  # noqa: F401  路径
from cocheck.adapters import cocut


class CocutLexicon(unittest.TestCase):
    def doc(self, **kw):
        d = tempfile.mkdtemp(); doc = dict(beats=[dict(id='1a', dur=3, image='a.png', vo=dict(text='六百万行老代码'))], **kw)
        json.dump(doc, open(os.path.join(d, 'doc.json'), 'w')); return cocut.items(d)[0]

    def test_no_lexicon_unchanged(self):                     # 没读音表时和以前一样（指纹不变）
        x = self.doc(); self.assertIsNone(x['say']); self.assertIsNone(x['poly'])

    def test_lexicon_applies(self):
        x = self.doc(lexicon=[dict(w='六百万行', say='六百万航', py={'行': 'háng'})])
        self.assertEqual((x['say'], x['poly']), ('六百万航老代码', {'行': 'háng'}))


if __name__ == '__main__': unittest.main()
