# person-simulator

有些人，我们已经很难再和他们聊天了。

可能是曾经很亲近、后来走散的人，可能是分开以后再也没有机会好好说话的恋人，也可能是已经离开的亲人。聊天记录还留在手机或电脑里。那些“吃了吗”“早点睡”“今天好累”的句子，当时只是日常，后来却变成少数还能被翻看的东西。

我做这个项目，不是相信 AI 能让人回来。我不相信这件事。人不能被一段文本恢复，模型说出的话也不等于那个人真实会说的话。

我想试的是另一件更小、也更具体的事：能不能让过去真实发生过的对话，成为人物模拟的依据，而不是让模型凭空扮演一个标签。不是写一段“你是一个温柔的人”的提示词，然后把所有细节交给想象；而是从真实的用词、句长、停顿、玩笑、争吵和沉默里，尽量还原一个人表达和反应的方式。

这件事不可能真正让失去的人回来，也不可能保证 AI 说出的话就是那个人真实会说的话。但我仍然认为，值得尝试。

这个项目也不是“数字永生”产品，不是心理治疗工具，不承诺替代真实关系。它只是一个开源工具：把一份你有权处理的聊天记录，变成一份可检查、可修改、可保存的人物模拟材料；或者在一个受控的范围内，让朋友和这份模拟聊一会儿。

## 这个项目是什么

`person-simulator` 读取一份**已经清洗好的、两人之间的 UTF-8 聊天文本**，指定其中一人作为 `target`，通过兼容 OpenAI Chat Completions 的模型 API（或完全离线的 Mock）进行分析，生成人物模拟材料。

它提供两种使用方式：

- **Mode A：个人档案模式**。在本地生成可阅读、可保存、可复用的人物档案和系统提示词，适合自己查看、修改，或上传到网页版 AI。
- **Mode C：交互体验模式**。在所有者自己的电脑或服务器上启动一个受控服务，让被邀请的人通过客户端或浏览器与人物模拟对话，而不直接拿到完整人物档案。

两种模式复用同一套输入解析、模型调用、预算和存储基础，但它们的产物和访问边界不同。

它模拟的是“基于这些聊天记录，一个人可能怎样说话和反应”，不是那个人本身。它不保证事实正确，不保证人格准确，也不代表被模拟者真实的意愿。聊天记录里没有的东西，它应该承认不知道，而不是补一个听起来合理的答案。

## 能做什么

### Mode A：个人档案模式

适合这样的场景：你有一份聊天记录，想为其中一个人建立一份可以反复使用的模拟材料；你不想每次手工整理提示词；你希望看到材料引用了哪些原话，而不是只拿到一段黑箱生成的角色设定。

Mode A 有两条建模路径：

- **`whole`**：把整段聊天一次性交给长上下文模型，生成 `system_prompt.md`，以及可选的 `person_simulation.md`。
- **`evidence`**：把聊天按会话和预算切分，逐块提取带原文位置的人物观察，校验证据，再汇总成 `persona.json`，最后渲染成固定 13 章的 `person_simulation.md` 和独立的 `system_prompt.md`。

`build` 默认使用 `--strategy auto`：如果整段聊天能放进当前上下文预算，就走 `whole`；否则走 `evidence`。也可以显式指定。对一份很短的双人聊天，`auto` 往往会选择 `whole`，而不是 `evidence`。

Mode A 的产物在本地 `runs/` 下。`evidence` run 可以 `resume`、可以 `render` 到另一个目录；`whole` run 没有同样的检查点和 13 章结构，直接使用它生成的 `system_prompt.md` / `person_simulation.md` 即可。`render` 只适用于 `evidence` run。

Mode A 生成的是“材料”，不是“已经验证过的本人”。`evidence` 产物会明确区分目标自述、对方声称、观察和有依据的推断；Mock 产物会显著标记为合成演示。

### Mode C：交互体验模式

适合这样的场景：你想让一个经过授权的朋友体验“和这个人聊天”，但不想把完整档案、原始聊天或 API Key 直接交给对方。

Mode C 的基本流程是：

1. 所有者先完成一个 Mode A run。
2. 用 `serve` 加载这个 run，启动公开监听器和独立的管理员监听器。
3. 所有者创建一份加密邀请，把邀请文件或浏览器链接通过安全渠道发给体验者。
4. 体验者用 `connect` 客户端或浏览器与模拟对话。
5. 所有者可以列出会话、删除会话、撤销邀请；停止服务会清空内存中的会话和邀请。

体验者只看到对话和“AI 模拟角色，不是本人”的提示，不会拿到 `persona.json`、`system_prompt.md`、原始聊天或完整档案下载入口。公开端口没有 `/admin/*`；管理员接口在独立的 loopback 端口。

Mode C 当前提供 CLI 客户端和浏览器兜底页面。没有独立桌面程序，没有 MCP adapter，也没有内置的公网 TLS/ACME。

## 技术实现

### 1. 输入不是“随便一段聊天”

输入必须是 UTF-8 或 UTF-8-BOM 的 `.txt` / `.md`，按原始顺序保留文本。当前语法是：

```text
[2024-05-01T09:30:00+08:00] A: 早，今天出门吗？
B: 看情况。
  如果不下雨就去。
[2024-05-01T09:32:00+08:00] A：那带上伞。
B: 好。
```

- 消息头是 `A: 文本` 或 `A：文本`。
- 冒号后最多一个 ASCII 空格属于格式分隔，其余字符都属于正文。
- 续行以两个空格开头；这两个空格是结构，不是正文。只由两个空格组成的行表示正文空行。
- 空白行可以形成会话候选边界；有时间戳时，相邻消息间隔超过 30 分钟也会形成会话边界。
- 文件 SHA256 会保存为 `source_hash`；解析错误报告行号和原因，但不会把私人正文回显到错误消息里。

`parser.py` 不根据最后发言人猜角色，不根据文件顺序猜身份，也不自动更换 `target`。`--target` 必须和其中一个说话人标签精确匹配，两个人都必须有有效消息。

项目不解析微信原始数据库。它读取的是已经导出的文本；仓库里的 `tools/convert_wechat_md.py` 只是一个转换辅助。微信聊天记录可以用 [LC044/WeChatMsg](https://github.com/LC044/WeChatMsg) 的 4.x 适配版本导出；那是独立的 GPL-3.0 工具，本项目不包含它的代码、数据库密钥或导出数据。

### 2. 两条建模路径，解决的是不同问题

| | `evidence` | `whole` |
|---|---|---|
| 输入方式 | 按会话/预算切块，逐块提取 | 整段聊天一次送入 |
| 调用次数 | 多（分块、汇总、修复） | 通常一次分析调用 |
| 可追溯性 | 每个特征要能回到 `Observation` 和原消息的字符区间 | 模型自由组织，只有消息 ID 级引用检查 |
| 长聊天 | 可扩展，按预算切分 | 受上下文窗口限制 |
| 检查点 | 有，支持 `resume` | 没有同样的分块检查点 |
| 产物 | `persona.json`、`evidence.jsonl`、13 章 `person_simulation.md`、`system_prompt.md` | `system_prompt.md`、可选自由格式的 `person_simulation.md` |
| 适合 | 想检查证据、处理长聊天、需要失败恢复 | 上下文足够、想保留更多原始语料细节 |

`evidence` 路径的设计重点不是“让模型写得更长”，而是让每条人物特征都有来源：

1. `chunking.py` 把消息切成 core 和 context。每条原文正文字符恰有一次 core 归属；context 只帮助理解，不增加独立支持次数。
2. 每个 chunk 调用模型提取 observations。证据引用使用 Unicode 字符偏移，`quote` 由代码从原文切片，模型不能改写。
3. 代码校验证据 ID、偏移、角色和原文切片；对方说的话只能作为上下文或“对方声称”，不能变成目标人物的事实。
4. 按维度汇总 observations，组装 `Persona`，检查覆盖、来源哈希和身份。
5. `rendering/markdown.py` 确定性地渲染 13 章，并单独生成可直接粘贴的 `system_prompt.md`。

`whole` 路径把消息序列化成带消息 ID 的 transcript，一次调用让模型输出 `<system_prompt>` 和可选的 `<person_simulation>` 标签。代码会检查标签、消息 ID、长度、Mock 标识和外部依赖；但它没有逐特征证据账本，也没有 `coverage=1` 的逐字符覆盖。它保留的是更完整的原始上下文，代价是可审计性和长文本可扩展性。

这也是为什么仓库同时保留两条路径，而不是宣布某一条“更好”。`auto` 只解决上下文放不放得下的问题，不解决人物模拟质量。质量需要留出集和人工评估，不能由工程测试替代。

### 3. 人物材料如何生成

`evidence` 的最终 `person_simulation.md` 固定 13 章：

1. 使用说明
2. 人物模拟总指令
3. 基本交流画像
4. 语言风格与表达习惯
5. 思维与判断模式
6. 情绪表达与冲突应对
7. 对另一位参与者的态度与互动
8. 不同情境下的典型行为
9. 代表性原始表达示例
10. 新情境下的模拟规则
11. 保持人物一致性的规则
12. 历史事实与推测的区分
13. 可直接使用的人物模拟系统提示词

同时生成独立的 `system_prompt.md`，内容与第 13 节一致。文件不依赖项目运行时、外部路径、include 或远程链接。材料不足时写“材料不足，保持未知”，不补造人格、日期或事件。Mock 产物会在标题和首页显著标记为合成演示。

`whole` 的 `person_simulation.md` 是模型自由组织的，不保证 13 章；这正是两条路径的实际差异之一。不要把它当成同一种格式。

### 4. 模型提供方、预算和运行产物

真实模型调用要求兼容 **HTTPS + Bearer Key + 非流式 `POST /chat/completions`** 的服务；只有显式开启 `security.allow_insecure_localhost` 时，loopback 的 HTTP 地址才是例外。当前只实现 `openai_chat` provider：

- 请求只发送 `model`、`messages` 和输出限额；不会默认发送 tools、streaming、thinking、`response_format` 或 `temperature`。
- `json_object`、`temperature`、`disable_thinking` 只有在配置显式启用时才发送。
- 输出限额参数可选 `max_tokens` 或 `max_completion_tokens`。
- 响应必须是 `choices[0].message.content` 的非空文本，`finish_reason` 必须是 `stop`；截断、空内容、工具调用和未知结束原因都不会被当成成功。
- Provider 失败会返回错误，不会静默降级为 Mock。
- API Key 只从 `PSIM_API_KEY` 读取，不写入 TOML、命令行、manifest 或日志。

预算估算使用 `ceil(UTF-8 字节数 × 1.25) + 512` 包装余量（evidence 路径），whole 路径会再按字符数校准；两者都是保守启发式，不是精确 tokenizer。`plan` 会离线打印切分、预算和 coverage，不联网、不打印聊天正文。

`evidence` run 的目录通常包含：

```text
manifest.json
messages.jsonl
chunks.jsonl
analysis/
evidence.jsonl
persona.json
build_report.md
person_simulation.md
system_prompt.md
```

`whole` run 通常包含：

```text
manifest.json
system_prompt.md
person_simulation.md   # 可选
build_report.md
```

`build` 只在整个流程成功后才发布正式 Markdown；失败保留检查点，但不生成貌似完成的正式文件。写入使用临时文件 + 原子替换，run 目录有锁，避免两个进程同时写同一个 run。

### 5. Mode C 的访问边界

Mode C 不是“把档案发给朋友”，而是“让朋友通过受控入口对话”。具体实现是：

- **严格加载**：`load_runtime_persona` 只接受完成、版本兼容、哈希/身份一致的 run。`evidence` 要求 `analysis_status=complete`、`export_status=complete`、coverage 完整、`messages.jsonl` 存在；`whole` 要求 `whole-1.0`、`status=complete`、source/target/interlocutor 和系统提示词齐全。
- **运行时提示词**：把固定安全说明、原始 system prompt、观众说明和运行时优先级组合起来。原始聊天不会加入每一轮模型上下文；它只在本地用于复述检测。
- **加密邀请**：`invite.psim` 是 PBKDF2-HMAC-SHA256（600,000 次）+ Fernet 加密的信封，只包含 endpoint、令牌、有效期、备注、可选指纹/限额；不包含人物档案、system prompt、原始聊天或 API Key。服务端只保存令牌的 SHA256 哈希。
- **双监听器**：公开端口提供对话 API 和打包的静态 UI；管理员端口只绑定 `127.0.0.1` 的随机端口，不经过隧道。公开端口不注册 `/admin/*`。
- **会话边界**：会话在内存中；有全局/每邀请会话上限、TTL、空闲超时、轮数、输入长度、输出 token 和每会话请求速率限制。结束或过期会立即清空消息内容，短暂保留无内容墓碑；删除会立即移除会话；服务停止会清空所有内存会话和邀请。
- **输出检查**：脱敏手机号、身份证号、邮箱、座机、银行卡和可配置的姓名/地址词表；拒绝 60 个字符以上的 system prompt 连续片段、内部标记和逐字复述。`evidence` run 有完整 `messages.jsonl`，复述检测可以使用原文；`whole` run 通常只有提示词，因此是 prompt-only 级别。检查失败不会写入历史。

这些是访问控制和降低风险的措施，不是“绝对隐私”的证明。体验者仍然可以截图、转发对话、把邀请令牌给别人；模型服务商和隧道提供方仍然可能看到流量或请求内容。

### 6. 测试、CI 与发布

测试使用合成聊天、假姓名/电话和 `tmp_path`，不依赖真实聊天、真实 API Key 或个人绝对路径。CI 在 Ubuntu/Windows × Python 3.11/3.12 上安装、运行完整 `pytest`，并在 Linux 上构建 sdist/wheel，检查产物不包含 `data/`、`runs/`、`exports/`、`eval_runs/`、`config.toml`、`.env` 或 `*.psim`。CI 不调用真实模型 API。

本地构建：

```powershell
python -m build
```

产物在 `dist/`。发布、打标签、推送和创建 GitHub Release 都需要单独确认；当前仓库不会因为构建成功就自动发布。

当前工程测试通过只证明代码按契约工作，不证明生成的人物像本人。这个区别在后面的“评测与当前质量”里会再说明一次。

## 快速开始

### 安装

要求 Python **3.11+**。当前主要验证环境是 Windows + Python 3.12.10；CI 也覆盖 Linux。

Windows PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\person-sim.exe --version
```

macOS / Linux：

```bash
python -m venv .venv
./.venv/bin/python -m pip install -e ".[dev]"
./.venv/bin/person-sim --version
```

也可以用 `requirements-dev.lock` 复现开发环境。真实 API Key **只**从 `PSIM_API_KEY` 读取。

### 先验证环境和输入

```powershell
person-sim doctor
person-sim validate --input examples/sample_chat.txt --target A
person-sim plan --input examples/sample_chat.txt --target A
```

`doctor` 默认不联网；`plan` 只做离线切分和预算检查，不调用模型，也不打印聊天正文。

### 构建一份 Mock 档案

Mock 完全离线、确定性输出，不会产生 API 费用。它只用于验证流程，不代表真实人物建模。

```powershell
# 让 auto 选择路径（短聊天通常会选 whole）
person-sim build --input examples/sample_chat.txt --target A --mode mock --out runs

# 强制走 evidence，生成 13 章档案 + 证据账本
person-sim build --input examples/sample_chat.txt --target A --mode mock --strategy evidence --out runs

# 强制走 whole
person-sim build --input examples/sample_chat.txt --target A --mode mock --strategy whole --out runs
```

终端会打印 `run_dir`。查看 `person_simulation.md` 和 `system_prompt.md`；Mock 产物会显著标记为合成演示。

`evidence` run 还可以：

```powershell
person-sim resume --run runs/<evidence-run-id>
person-sim render --run runs/<evidence-run-id> --out exports/demo
```

`render` 遇到已存在的文件会拒绝覆盖。`whole` run 没有 `resume` / `render` 的同等语义，直接使用它的生成文件。

### 启动一次第三方体验（Mock）

先确认 run 能加载：

```powershell
person-sim serve --run runs/<run-id> --mode mock --check
```

`--check` 只校验 run、版本、模式和配置，不监听端口。

启动公开服务：

```powershell
person-sim serve --run runs/<run-id> --mode mock
```

终端会打印：

- `public_url`：本机访问地址；
- `admin_url`：仅本机可达的管理员地址；
- 管理员令牌来源；如果没有设置令牌，`serve` 会自动生成并在终端打印一次。

如果要自己管理管理员令牌，可以提前设置环境变量，或使用文件：

```powershell
$env:PSIM_ADMIN_TOKEN = "<管理员令牌>"
# 或者
person-sim serve --run runs/<run-id> --mode mock --admin-token-file .secrets/admin.txt
```

管理员令牌不接受明文命令行参数，避免出现在进程列表里。

如果 `serve` 在启动时自动生成了管理员令牌，请另开一个终端，把终端打印的 `admin_token` 设为 `PSIM_ADMIN_TOKEN`，再执行下面的邀请命令。自动生成的令牌只打印一次；`serve` 正在前台运行时，不能在同一个终端里继续输入命令。

创建加密邀请：

```powershell
$env:PSIM_ADMIN_TOKEN = "<serve 打印的管理员令牌，或你自己设置的令牌>"
$env:PSIM_INVITE_PASSPHRASE = "<邀请口令>"

person-sim invite create `
  --server <serve 打印的 admin_url> `
  --endpoint <serve 打印的 public_url> `
  --out invite.psim `
  --label "给同学" `
  --expires-in 3600
```

`invite create` 会打印 `invite_id`、`web_url` 和过期时间。`invite.psim` 只包含服务地址、令牌、有效期、备注、可选指纹和限额。把邀请文件或链接通过安全渠道发给体验者；口令最好走另一条渠道。`web_url` 里带有访问令牌，拿到链接的人就能建立会话，不要公开贴出或转发到不受控的群聊。

体验者使用客户端：

```powershell
$env:PSIM_INVITE_PASSPHRASE = "<邀请口令>"
person-sim connect --invite invite.psim
```

不带 `--message` 时进入交互式对话；输入 `/exit` 结束。也可以只发一条：

```powershell
person-sim connect --invite invite.psim --message "在吗？"
```

浏览器兜底：把 `invite create` 打印的 `web_url` 发给体验者，用浏览器打开。页面会常驻显示“AI 模拟角色，不是本人”。

撤销和删除：

```powershell
person-sim session list --server <admin_url>
person-sim session delete --server <admin_url> <session-id>
person-sim invite list --server <admin_url>
person-sim invite revoke --server <admin_url> --invite-id <invite-id>
```

这些管理员命令同样需要 `PSIM_ADMIN_TOKEN` 或 `--admin-token-file`。

默认只监听 `127.0.0.1`。如果确实要监听局域网，必须显式开启：

```powershell
person-sim serve `
  --run runs/<run-id> --mode mock `
  --host 0.0.0.0 --allow-lan `
  --allowed-host 192.168.1.20
```

但要注意：`invite create` 的 `--endpoint` 只接受 loopback 的 `http` 或任意 `https`。纯 HTTP 的局域网地址不能直接用来生成邀请。要在局域网或公网给朋友用，需要一个 HTTPS 入口，例如反向代理、Tailscale Serve 或 Cloudflare Tunnel；项目本身不内置 TLS/ACME。

### 配置真实模型

复制示例配置：

```powershell
Copy-Item config.example.toml config.toml
```

最小配置示例：

```toml
[model]
mode = "api"
provider = "openai_chat"
model = "YOUR_MODEL_ID"
base_url = "https://YOUR_PROVIDER_HOST/v1"
context_window = 32768
max_output_tokens = 4096
```

`base_url` 是 API 根地址，不要包含 `/chat/completions`。真实 API 必须显式 `mode = "api"`，并且需要 `PSIM_API_KEY`：

```powershell
$env:PSIM_API_KEY = "<你的 API Key>"
person-sim doctor --config config.toml
person-sim build --input data/chat.txt --target A --mode api --config config.toml --out runs
```

`doctor` 默认只检查配置，不发送请求。要显式做一次最小真实 API 探测：

```powershell
person-sim doctor --config config.toml --probe-api
```

这会发送一次真实请求，可能产生费用；没有明确授权时不要运行。

模式 C 的常用配置：

```toml
[simulation]
host = "127.0.0.1"
port = 8765
allow_lan = false
secure_cookies = false
max_sessions = 8
ttl_minutes = 30
idle_minutes = 10
max_turns = 30
max_input_chars = 2000
max_output_tokens = 1024
requests_per_minute = 6
max_concurrency = 2
allowed_hosts = ["127.0.0.1", "localhost", "::1"]
blocked_terms = []
log_metadata = false
```

`simulation` 配置不参与建模 run 的 `config_hash`，升级到带模式 C 的版本不会让旧 run 失效。完整配置项、环境变量和优先级见 `docs/configuration.md`；优先级是 **CLI 明示值 > `PSIM_` 环境变量 > TOML > 默认值**。`config.toml` 已被 `.gitignore` 忽略，不要提交。

### 公网共享

0.2.0 不内置公网 TLS、ACME 或端口转发。常见做法：

- **Tailscale**：设备间加密网络，适合只给少数朋友用；
- **Cloudflare Tunnel**：提供公网 HTTPS，但 Cloudflare 会终止 TLS，能看到流量；
- **反向代理**：由所有者自行提供证书。

隧道只转发公开端口，**不要转发管理员端口**。HTTPS 隧道场景建议设置：

```toml
[simulation]
secure_cookies = true
allowed_hosts = ["127.0.0.1", "localhost", "::1", "your-tunnel-host"]
```

并把隧道域名通过 `--allowed-host` 或 `allowed_hosts` 加入白名单。邀请的 `--endpoint` 应填写体验者实际访问的 HTTPS 地址，而不是本机 `public_url`。

## 数据、隐私与边界

### 输入数据放在哪里

原始聊天由你放在自己选择的输入路径（例如 `data/chat.txt`），项目不会上传到中央服务器，也没有中央人物库或中央账号系统。`data/`、`runs/`、`exports/`、`eval_runs/`、`config.toml`、`.env*` 和 `*.psim` 都在 `.gitignore` 中；这不等于它们不会出现在 OneDrive、备份或系统同步里，存放位置需要你自己决定。

### 哪些步骤可能调用外部模型 API

- `build --mode api`：evidence 的分块提取、汇总、修复，或 whole 的整段分析，会把聊天内容发送给你配置的模型服务商。
- `simulate --mode api`：把系统提示词和当前消息发送给模型服务商。
- `serve --mode api`：每轮把运行时提示词、最近的对话历史和当前消息发送给模型服务商。
- `doctor --probe-api`：显式发送一次最小探测请求。

Mock 模式不联网、不产生 API 费用。真实 API 的请求内容、保留策略和费用由所有者与其模型服务商决定；项目无法替服务商承诺数据删除或训练策略。

### 个人档案模式和交互模式分别保存什么

Mode A 的 `evidence` run 目录保存完整档案、证据、原始消息和报告，供所有者查看、编辑、导出；`whole` run 主要保存 manifest、`system_prompt.md`、可选的 `person_simulation.md` 和报告，没有同样的证据账本。Mode C 从已完成的 run 派生运行时提示词，但不会把完整档案放进公开端口；服务端保存邀请元数据、令牌哈希和内存会话。会话消息只在内存中，结束/过期清空内容，删除移除会话，服务重启清空邀请和会话。

run 目录和 `exports/` 不会因为结束 Mode C 会话而删除；它们仍由所有者管理。

### 会话结束、过期、撤销、删除的真实行为

- 体验者结束会话：状态变为 `ended`，消息内容立即清空，保留短暂的无内容墓碑。
- TTL 或空闲超时：状态变为 `expired`，消息内容清空。
- 管理员删除会话：立即从内存移除。
- 撤销邀请：邀请记录标记为 revoked；已有会话下一次请求会因邀请不再有效而被拒绝。
- 邀请过期：服务端按时间拒绝；已有会话同样会被检查。
- 停止服务：所有内存会话和邀请消失；run 文件和导出文件保留。

### 不能保证的事

- 不能保证 A 的模型服务商看不到人物提示词和对话；它必然会看到请求内容。
- 不能保证 C 的远程 AI agent 看不到对话；如果 C 使用自己的 agent，对话还会进入该 agent 的模型服务商。
- 不能阻止 C 从回复中推断人物特征、截图或转发对话。
- 不能绝对阻止提示注入、改写后的复述或所有直接身份信息；输出检查是尽力而为的第二道防线。
- 不能保证所有姓名、地址、暗示性身份信息都能被正则或词表识别。
- 如果邀请文件和口令走同一渠道，加密只剩防静态窥探的作用。
- 不能阻止模型服务商、隧道提供方或云同步服务按自己的条款处理数据。
- 没有经过独立安全审计；不要把它当作高价值秘密的强隔离边界。

### 第三方隐私

聊天记录里通常不只有你一个人。使用前请确认你有权处理这些内容，并尽量尊重另一位参与者的隐私：不要为了做模拟而公开完整聊天，不要在 Issue、PR、截图或演示里粘贴真实姓名、联系方式、地址和可识别的事件。需要分享评估结果时，只分享聚合数字和你自己确认过不含私人信息的内容。

## 评测与当前质量

工程测试通过，不等于人物模拟质量通过。

当前人物模拟质量状态是 **`not_evaluated`**。仓库有评估包生成器和离线评分器，但还没有完成可靠的多评审、重复采集、五维评分。现有的一次 30 题 A/B 实验只能作为探索性观察：

- 30 题、60 次调用，A = `system_prompt.md`，B = 完整训练聊天；
- 一位了解目标人物的评审做了偏好选择：A 更像 16 题，B 更像 10 题，都不像 4 题；
- 没有完成五维 1—5 分评分，没有第二位评审，每题只生成一次，也没有统计检验；
- 部分题面依赖缺失上下文，参考回复与题面不完全对齐。

因此不能宣布 A 或 B 整体更好，也不能把 16:10 当成质量结论。本地原始产物在 `eval_runs/`，该目录被忽略；仓库只保留 `docs/stage-10-ab-eval.md` 的聚合摘要。

评估工具覆盖五个维度：语言风格相似性、人格与决策一致性、对另一位参与者的态度、未见情境的泛化、历史事实准确性；同时记录身份混淆、编造历史、事实错误和无依据推断。`eval score` 拒绝 Mock 回答，要求每题至少两次人工采集，并生成 `quality_report.json` / `quality_report.md`。

完整的数据格式、评分规则、人工步骤、结果保存方式和局限见 [`docs/evaluation.md`](docs/evaluation.md)。如果你想自己评，最低需要：

```powershell
person-sim eval prepare --input data/chat.txt --target A --out eval_runs/my-person
person-sim build --input eval_runs/my-person/train_chat.txt --target A --mode api --out runs
# 人工把回答填入 responses.jsonl，把评分填入 ratings.csv
person-sim eval score `
  --bundle eval_runs/my-person `
  --responses eval_runs/my-person/responses.jsonl `
  --ratings eval_runs/my-person/ratings.csv
```

如果原聊天的说话人标签不是 `A`/`B`，`eval prepare` 和 `build` 都要带上相应的 `--speaker-a` / `--speaker-b` / `--target`；否则标签不会自动匹配。

不要把自动化测试通过率、Mock 输出、输出安全检查通过或单次评分当成“人物模拟质量已达标”。

## 项目状态与参与方式

当前版本：**0.2.0**（2026-10-25），默认分支 `main`。

已经验证的能力：

- UTF-8/BOM、全角冒号、ISO8601、两空格续行、正文伪头和行号错误；
- 精确 target 选择、双人身份隔离、不按顺序猜人；
- 超长消息无损切片、core 覆盖、证据 ID/偏移/原文切片校验；
- 配置优先级、Key 脱敏、URL/loopback 限制、OpenAI-compatible 适配和有界重试；
- evidence 的检查点、锁、run 指纹、损坏缓存重算、请求上限、resume；
- 13 章 Markdown、独立 `system_prompt.md`、Mock 水印、失败不发布、render 不覆盖；
- whole-chat 整段生成和 `--strategy auto|whole|evidence`；
- Mode C 的运行时加载、加密邀请、双监听、会话限额、输出检查和浏览器/CLI 入口，Mock 端到端有测试覆盖；
- CI 和打包产物检查。

仍然未完成或未验证：

- **evidence 真实 API 全流程：`not_verified`**。有 Mock 和 fake client 覆盖，但没有用真实付费 API 重新跑完整证据流水线。
- **Mode C 真实 API 端到端：未验收**。Mock 流程完整，真实服务商调用还没有做同等级验证。
- **人物模拟质量：`not_evaluated`**。不能拿 Mock 结果、工程测试或单评审偏好宣称效果。
- **whole-chat** 在文档中记录过一次 DeepSeek 全量真实运行，但当前代码没有重新做同等级真实 API 验收；它也没有逐条证据账本和 coverage 保证。
- Mode C 客户端目前是 CLI；没有独立桌面程序、MCP adapter 或内置公网 TLS/ACME。
- 会话和邀请默认只在内存中；服务重启即失效，长期运行需要所有者自行设计持久化与备份。
- 不支持微信原始数据库解析；输入必须是预清洗的 UTF-8 双人聊天文本。
- 预算估算是启发式，不是精确 tokenizer；`coverage=1` 只说明原文被切分覆盖，不说明模型理解了全部内容。

下一步最值得做的不是继续加功能，而是把评估题面、留出集和人工评分做扎实：修上下文完整性，至少两位评审、每题重复生成，并分别验证 evidence / whole / Mode C 的真实调用路径。没有这些证据，README 不会把“像”写成已经完成的事实。

参与方式：

- 通过仓库 Issue 报告问题，但**不要**在 Issue 中粘贴真实聊天、人物档案、API Key、邀请令牌或可识别个人的信息。
- 涉及安全问题时，不要公开贴敏感细节；如果仓库启用了 GitHub 私密漏洞报告，请通过 Security / Advisories 联系维护者；否则先开一个不含敏感内容的 Issue 询问私下渠道。
- 提交代码前请运行完整测试，并阅读 `CONTRIBUTING.md`。不要删除测试、降低断言或用 Mock 结果制造“质量通过”。
- 新增功能请优先复用现有的 `RuntimePersona`、`ChatService`、`OutputGuard` 和评测包格式，不要把同一套模型调用复制成第二套。

## 许可证与致谢

MIT，见 [`LICENSE`](LICENSE)。

聊天记录导出可以配合 [LC044/WeChatMsg](https://github.com/LC044/WeChatMsg) 使用；它是独立的 GPL-3.0 项目，不属于本仓库，也不由本项目分发。感谢所有愿意认真处理自己数据、并尊重聊天另一方隐私的人。

更多文档：

- [`docs/architecture.md`](docs/architecture.md) — 模块与数据流
- [`docs/contract.md`](docs/contract.md) — 输入、CLI、运行目录和 Mode C 契约
- [`docs/input-format.md`](docs/input-format.md) — 聊天文本格式
- [`docs/output-format.md`](docs/output-format.md) — 13 章输出
- [`docs/configuration.md`](docs/configuration.md) — 配置项
- [`docs/privacy.md`](docs/privacy.md) — 数据处理与外部处理者
- [`docs/security.md`](docs/security.md) — 威胁模型和控制边界
- [`docs/testing.md`](docs/testing.md) — 测试与质量状态
- [`docs/evaluation.md`](docs/evaluation.md) — 评测数据格式、评分与人工步骤
- [`docs/development.md`](docs/development.md) — 开发环境、测试纪律和代码约定
- [`docs/release.md`](docs/release.md) — 发布流程与验证记录
