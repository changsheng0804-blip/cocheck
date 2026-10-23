# cocheck · AI 智能审核插件

把「看图听音找错」做成一个独立、可复用的插件：**反射层先筛，点名复核，按条目红绿灯**。所有模型——本地的、云端的、命令行代理、别的机器上的——都走同一套 `/v1` 接口。

最早为共剪 [cocut](https://github.com/changsheng0804-blip/cocut) 做，但不依赖它：任何「一组画面（+配音/文案）」都能接，写一个适配器即可。

## 它做什么

1. **反射层体检**（快、便宜、本地）：用向量模型做局部对照检查——画里多余的文字（报 3×3 哪一块）、画面说明里的元素缺失或整张换错、配音配错、多音字读错。向量按「模型+内容哈希」缓存，改一条只重算这一条，约 2 秒。
2. **点名复核**：只把可疑处开成复核单，每题只问 yes / no / unsure（「画面里有没有：玻璃管里的 Twin？」），不让大模型泛泛点评。
3. **复核员链**：快模型先答全部新单，强模型（`escalate`）只复核红/黄；人可以一键裁决，人的判断最终。
4. **红绿灯**：每条 green / red / yellow / grey，附问题、谁说的、谁不同意。素材或文案一改，旧单自动过期变灰、重新体检；改回旧版本恢复原判。

## 统一模型接入口

配置里每个模型是一个 provider，只有两种能力：

| 能力 | 含义 | 现有类型 |
|---|---|---|
| `embed` | 文字/图/音 → 向量（体检用） | `local_embed`（sentence-transformers，默认 EmbeddingGemma 2）、`remote` |
| `ask` | 看图/听音答点名是非题（复核用） | `gemini`（AI Studio / Vertex / 本地桥）、`openai`（OpenAI、OpenRouter、vLLM、LM Studio、Ollama…）、`cli`（agy、gemini、claude、codex 等能读文件的命令行代理）、`remote` |

`remote` 指向另一台机器上的 cocheck：模型装在一台有 GPU/MPS 的机器上，其他机器和用户都连它。新增一种模型接入 = 在 `cocheck/providers/` 写一个类、在注册表加一行。密钥只放环境变量，配置里写 `${GEMINI_API_KEY}`。

## 快速开始

```bash
pip install -e .[check]          # 只复核；要本地体检再加 [local]，多音字检查加 [tts]（需 ffmpeg）
cp examples/config.example.json cocheck.json   # 按需删改 providers / projects
cocheck doctor --ping            # 环境自检：依赖、设备、配置、每个模型是否连得上
cocheck serve                    # http://127.0.0.1:8796
```

不开服务也能用：

```bash
cocheck check cocut:~/films/lan          # 体检 + 开单（适配器:路径）
cocheck review lan                       # 按配置的复核员链跑
cocheck review lan --provider g4 --jobs 3 --escalate
cocheck status lan
cocheck answer lan 3b-3c466394ad '{"0":"no"}' --by user
```

## 给任何 AI 用（MCP）

`cocheck mcp` 是零依赖的 stdio MCP 服务，薄壳转发到 `cocheck serve`，不加载模型。工具：
`cocheck_projects`、`cocheck_status`、`cocheck_next_ticket`（直接附上画面图片，问配音时附音频）、`cocheck_answer`、`cocheck_check`、`cocheck_review`、`cocheck_providers`。

```bash
agy mcp add cocheck cocheck mcp --by agy                       # Antigravity CLI
# Claude Desktop / Gemini CLI / Codex 的 mcpServers：
# {"cocheck": {"command": "cocheck", "args": ["mcp", "--by", "claude"], "env": {"COCHECK_URL": "http://127.0.0.1:8796"}}}
```

然后对 AI 说「用 cocheck 把项目 lan 的待复核单都答完」即可；它答的票以 `--by` 的名字计入多人判定。

## 接到自己的页面

```html
<div id="qc"></div>
<script src="http://127.0.0.1:8796/cocheck-strip.js"></script>
<script>
  CoCheck.strip(document.getElementById('qc'), {
    api: 'http://127.0.0.1:8796', project: 'lan',
    onSelect: (item) => player.seek(item.t0),
    onNote: (item, text) => addComment(item.id, text),
  });
</script>
```

## 接自己的数据

适配器把你的数据转成条目：`{id, image, audio?, desc?, text?, say?, poly?, t0?, t1?}`（路径为本地绝对路径）。自带三个：

- `cocut`：cocut 片子目录（doc.json）
- `items`：一个 items.json
- `folder`：一个文件夹的图，同名 `.txt` 作画面说明、同名 `.mp3` 作配音

服务会监视适配器声明的数据文件，一变就自动体检、开单、唤起复核员。

## 实测（《懒》16 拍，Mac M 系列）

- 体检全片约 53 秒（冷），改一拍约 2 秒
- 复核 12 张单：Gemini 3.8 Flash（agy，4 并发）178 秒；Gemini 4 直连（3 并发）约 100 秒，受 Vertex 配额限流
- 两种模型 19/20 题一致；分歧只在模糊题，页面上会标出来

接口细节见 [docs/API.md](docs/API.md)。
