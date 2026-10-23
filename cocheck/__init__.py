"""cocheck：AI 智能审核插件。

三层，各自可单独用：
  providers  统一模型接入口：本地/云端模型都注册成 provider，能力只有两种——embed（向量）和 ask（看图/听音答是非题）
  checks     反射层体检：用任意 embed provider 做高频、局部、对照式检查（画中字、元素缺失、配错音、多音字）
  review     点名复核：体检可疑处开成复核单，ask provider（或人）答 yes/no/unsure，按条目标红绿黄灰
对外：Python 库、CLI（cocheck）、HTTP（cocheck serve，/v1/...）、可嵌入网页的 web/cocheck-strip.js。
接入方（如 cocut）只需写一个 adapter，把自己的数据转成 items。
"""
__version__ = '0.1.0'
