# cocheck HTTP 接口（v1）

默认 `http://127.0.0.1:8796`。POST 可用 `--token` / `$COCHECK_TOKEN` 要求 `Authorization: Bearer <token>`；服务默认只听本机，对外开放时务必设 token。所有响应 JSON，带 CORS。

## 模型（统一入口）

### GET /v1/providers
```json
{"providers": [{"name": "eg2", "type": "LocalEmbed", "caps": ["embed"], "model": "google/embeddinggemma-2"}, ...],
 "embed": "eg2", "reviewers": [{"provider": "flash", "jobs": 4}, ...]}
```

### POST /v1/embed
```json
{"provider": "eg2", "prompt": "Retrieval-query", "image_tokens": 70,
 "inputs": [{"text": "玻璃管里的星星"}, {"image_png": "<base64>"}, {"audio_f32": "<base64 float32 16kHz 单声道>"}]}
→ {"provider": "eg2", "vectors": [[...768 维...], ...]}
```
不给 provider 用配置里的 `embed`。

### POST /v1/ask
```json
{"provider": "g4",
 "ticket": {"id": "x", "desc": "画面说明", "text": "配音文案", "asks": [{"i": "0", "k": "el", "q": "画面里有没有：…？"}]},
 "files": {"image": {"name": "a.jpg", "b64": "..."}, "audio": {"name": "a.mp3", "b64": "..."}}}
→ {"provider": "g4", "answers": {"0": "no"}}
```

## 审核

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/v1/projects` | 项目列表、红绿数量、体检/复核员状态 |
| POST | `/v1/projects` | `{name, adapter, path, ...}` 运行时登记，登记后立即体检 |
| GET | `/v1/projects/<p>/status` | `{status: {条目: {color, problems, unsure, asks, answers, reviewers, final, ticket}}, check, reviewers, items: [{id, label, desc, t0, t1}]}` |
| GET | `/v1/projects/<p>/tickets?by=<名字>&second=1&hot=1` | 待复核的单；`by` 去掉它答过的；`second` 含别人答过的；`hot` 只要红/黄。媒体字段是 URL |
| GET | `/v1/projects/<p>/media/<单号>/image\|audio` | 单上的图/音 |
| POST | `/v1/projects/<p>/answer` | `{ticket, by, answers: {"0": "yes"}, note?}`；`by: "user"` 是人的最终裁决 |
| POST | `/v1/projects/<p>/check` | 立即体检 |
| POST | `/v1/projects/<p>/review` | `{provider?, jobs?, escalate?}`；不给 provider 按配置的复核员链跑 |

### 题型与判定

| k | 问题 | 哪个答案算有问题 |
|---|---|---|
| text | 画面里有没有文字（附 `tile` 0–8，3×3 从左上起） | yes |
| swap | 是不是这个场景 | no |
| el | 有没有某元素（`el`） | no |
| vo | 配音是不是这句 | no |
| poly | 「字」（`ch`）读得对不对 | no |

多人答同一题：有问题票 ≥ 没问题票（且至少 1 票）→ 红，并列出 `against`；全 unsure → 黄；人答过以人为准。

### 颜色
green 没问题 · red 有问题 · yellow 待复核/拿不准 · grey 改过了，等重新体检

## 外部 AI 自己领单

任何能发 HTTP 的 AI 都能当复核员，不必写 provider：
1. `GET /v1/projects/lan/tickets?by=myai`
2. 下载 `image`/`audio` URL，逐题答 yes/no/unsure
3. `POST /v1/projects/lan/answer {"ticket": "...", "by": "myai", "answers": {...}}`
