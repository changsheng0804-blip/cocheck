"""适配器：把接入方的数据转成 cocheck 条目（item）。

item = {id, image, audio?, desc?, text?, say?, poly?, t0?, t1?, label?}
  image/audio  本地文件绝对路径
  desc         画面说明（用来拆元素核对；声音词会被跳过，声音最好写进 sound）
  sound        声音说明（不出视觉题，留给能听的复核员）
  expect_text  画里有意设计的字，如 ["面包店", "×30 延时"]：文字题改问「字对不对」；[] = 允许有字、不核对
  text / say   配音文案 / 实际读法；poly = {"字": "拼音"} 读音要求
  t0 / t1      在时间线上的位置（秒，可选，网页组件用来画色带）
新接入方：写一个 items(path, **opts) 函数，在 ADAPTERS 里登记即可。
"""
import importlib

ADAPTERS = {'cocut': 'cocut', 'items': 'items_json', 'folder': 'folder'}


def load(name):
    if name not in ADAPTERS: raise ValueError('未知适配器 %r（可用：%s）' % (name, ', '.join(ADAPTERS)))
    return importlib.import_module('.' + ADAPTERS[name], __name__)
