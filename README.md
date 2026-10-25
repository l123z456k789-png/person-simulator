# person-simulator

有些人，我们已经很难再和他们聊天了。

可能是曾经很亲近、后来走散的人，可能是分开以后再也没有机会好好说话的恋人，也可能是已经离开的亲人。聊天记录还留在手机或电脑里。那些“吃了吗”“早点睡”“今天好累”的句子，当时只是日常，后来却变成少数还能被翻看的东西。

我做这个项目，不是相信 AI 能让人回来。我不相信这件事。人不能被一段文本恢复，模型说出的话也不等于那个人真实会说的话。

我想试的是另一件更小、也更具体的事：能不能让过去真实发生过的对话，成为人物模拟的依据，而不是让模型凭空扮演一个标签。不是写一段“你是一个温柔的人”的提示词，然后把所有细节交给想象；而是从真实的用词、句长、停顿、玩笑、争吵和沉默里，尽量还原一个人表达和反应的方式。

这件事不可能真正让失去的人回来，也不可能保证 AI 说出的话就是那个人真实会说的话。但我仍然认为，值得尝试。

这个项目也不是“数字永生”产品，不是心理治疗工具，不承诺替代真实关系。它只是一个开源工具：把一份你有权处理的聊天记录，变成一份可检查、可修改、可保存的人物模拟材料；或者在一个受控的范围内，让朋友和这份模拟聊一会儿。

## 这个项目是什么

`person-simulator` 读取一份**已经清洗好的、两人之间的 UTF-8 聊天文本**，指定其中一人作为 `target`，通过兼容 OpenAI Chat Completions 的模型 API（或完全离线的 Mock）进行分析，生成人物模拟材料。

它有两种使用方式。

### Mode A：个人档案模式

在本地生成可阅读、可保存、可复用的人物档案和系统提示词，适合自己查看、修改，或上传到网页版 AI。

Mode A 有两条建模路径：

- **`whole`**：把整段聊天一次性交给长上下文模型，生成 `system_prompt.md`，以及可选的 `person_simulation.md`。
- **`evidence`**：把聊天按会话和预算切分，逐块提取带原文位置的人物观察，校验证据，再汇总成 `persona.json`，最后渲染成固定 13 章的 `person_simulation.md` 和独立的 `system_prompt.md`。

`build` 默认使用 `--strategy auto`：如果整段聊天能放进当前上下文预算，就走 `whole`；否则走 `evidence`。对一份很短的双人聊天，`auto` 往往会选择 `whole`。

Mode A 的产物在本地 `runs/` 下。`evidence` run 可以 `resume`、可以 `render` 到另一个目录；`whole` run 没有同样的检查点和 13 章结构，直接使用它生成的 `system_prompt.md` / `person_simulation.md` 即可。`render` 只适用于 `evidence` run。

### Mode C：交互体验模式

在所有者自己的电脑或服务器上启动一个受控服务，让被邀请的人通过客户端或浏览器与人物模拟对话，而不直接拿到完整人物档案。

基本流程是：

1. 所有者先完成一个 Mode A run。
2. 用 `serve` 加载这个 run，启动公开监听器和独立的管理员监听器。
3. 所有者创建加密邀请，把邀请文件或浏览器链接通过安全渠道发给体验者。
4. 体验者用浏览器或 `connect` 客户端与模拟对话。
5. 所有者可以列出会话、删除会话、撤销邀请；停止服务会清空内存中的会话和邀请。

体验者只看到对话和“AI 模拟角色，不是本人”的提示，不会拿到 `persona.json`、`system_prompt.md`、原始聊天或完整档案下载入口。公开端口没有 `/admin/*`；管理员接口在独立的 loopback 端口。

Mode C 当前提供 CLI 客户端和浏览器兜底页面。没有独立桌面程序，没有 MCP adapter，也没有内置的公网 TLS/ACME。

### 它不做什么

- 不解析微信原始数据库；输入必须是已经导出的文本。
- 不训练模型，不做向量数据库，不做实时监听。
- 不提供中央人物库、中央账号或公网多租户 SaaS。
- 不保证模拟出来的人就是本人，也不保证事实正确。
- 不把 Mock 产物当成真实人物建模结果。

## 怎么使用

先确认你是哪一种使用者：

| 你的目标 | 看哪里 |
|---|---|
| 我想自己生成一份人物档案 | 第一部分第 1—5 节 |
| 我想让别人体验这个人物 | 第一部分第 1—6 节 |
| 我只是被邀请来聊一次 | 第一部分第 6.4 节，优先用浏览器 |
| 我是 AI 编码助手，要改这个仓库 | 第二部分 |
| 我只想先看看流程 | 第一部分第 3 节，用 Mock |

> 如果你只是被邀请来聊一次，直接看 **6.4 体验者怎么用**。浏览器路径不需要安装 Python，也不需要 API Key。

### 第一部分：给真人看的说明书

这一部分按顺序做就能完成一次完整使用。命令以 Windows PowerShell 为主；macOS / Linux 的差异会单独标出。

#### 0. 先准备什么

你至少需要：

- 一台自己的电脑；
- Python **3.11+**；
- 一份你有权处理的 UTF-8 双人聊天文本；
- 如果想用真实模型，还需要一个兼容 OpenAI Chat Completions 的 API Key。

不需要 GPU，不需要数据库，不需要公网服务器。Mode A 和 Mock 模式都可以只在本机完成。

#### 1. 安装

**Windows PowerShell：**

```powershell
git clone https://github.com/l123z456k789-png/person-simulator.git
cd person-simulator

python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"

person-sim --version
```

最后应看到：

```text
person-simulator 0.2.0
```

如果 PowerShell 不允许执行 `Activate.ps1`，不用强行改系统策略，可以直接用完整路径：

```powershell
.\.venv\Scripts\person-sim.exe --version
```

后面的 `person-sim` 命令都可以替换成 `.\.venv\Scripts\person-sim.exe`。也可以始终用模块方式运行：

```powershell
.\.venv\Scripts\python.exe -m person_simulator --version
```

**macOS / Linux：**

```bash
git clone https://github.com/l123z456k789-png/person-simulator.git
cd person-simulator

python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"

person-sim --version
```

没有 Git 的话，也可以在 GitHub 页面下载 ZIP，解压后进入目录执行同样的 Python 命令。

#### 2. 准备聊天文本

项目不直接读取微信数据库。你需要先准备一份 UTF-8 的双人聊天文本，放在任意路径；下面用 `data/chat.txt` 举例。

如果你的文件目录还不存在：

```powershell
New-Item -ItemType Directory -Force data
```

文本格式如下：

```text
[2024-05-01T09:30:00+08:00] A: 早，今天出门吗？
B: 看情况。
  如果不下雨就去。
[2024-05-01T09:32:00+08:00] A：那带上伞。
B: 好。
```

规则：

- 消息头是 `A: 文本` 或 `A：文本`。
- 冒号后最多一个 ASCII 空格属于格式分隔，其余字符都属于正文。
- 续行以两个空格开头；只由两个空格组成的行表示正文空行。
- 说话人标签必须前后一致。原聊天用 `小明` / `小红`，就写 `小明: ...` / `小红: ...`，不要在同一次运行里混用 `A`/`B`。
- `--target` 必须和其中一个标签完全一致。

如果你使用 **LC044/WeChatMsg 4.x 适配版**导出的固定 Markdown 格式，可以用仓库里的转换辅助：

```powershell
.\.venv\Scripts\python.exe tools\convert_wechat_md.py `
  path\to\export.md `
  --speaker-a 小明 `
  --speaker-b 小红 `
  --out data\chat.txt
```

这个转换器只识别一种已知的 Markdown 导出形状：

```text
## 2025-06-10
**[18:51:34] 小明**
消息正文
```

它不是通用微信解析器。其他导出格式需要你自己整理成上面的 `A:` / `B:` 文本。WeChatMsg 是独立的 GPL-3.0 项目，本项目不包含它的代码、数据库密钥或导出数据。

导入前请先确认：

- 你有权处理这份聊天记录；
- 聊天里另一位参与者知道或同意你用它做这件事；
- 文件里没有你不想让模型服务商看到的 API Key、身份证号、住址等信息。

#### 3. 第一次运行：先不花钱

先用官方合成样例或你自己的文本做一次离线 Mock。Mock 不联网、不产生 API 费用，只用于验证流程，不代表真实人物建模。如果暂时没有自己的聊天，把下面命令里的 `data\chat.txt` 换成 `examples\sample_chat.txt`，并使用 `--target A`（样例标签是 `A`/`B`）。

```powershell
person-sim doctor
person-sim validate --input data\chat.txt --speaker-a 小明 --speaker-b 小红 --target 小明
person-sim plan --input data\chat.txt --speaker-a 小明 --speaker-b 小红 --target 小明
```

如果说话人标签是 `A` / `B`，就改成 `--target A`。

`doctor` 默认不联网；`plan` 只打印切分、预算和 coverage，不调用模型，也不打印聊天正文。

然后运行第一次构建：

```powershell
person-sim build `
  --input data\chat.txt `
  --speaker-a 小明 `
  --speaker-b 小红 `
  --target 小明 `
  --mode mock `
  --out runs
```

终端会打印类似：

```text
status completed
run_dir C:\...\runs\run-...
export C:\...\runs\run-...\person_simulation.md
...
MOCK 合成演示，不代表真实人物建模
```

记住 `run_dir`。打开里面的：

```text
runs\<run-id>\person_simulation.md
runs\<run-id>\system_prompt.md
```

`person_simulation.md` 是人类可读的档案；`system_prompt.md` 是可直接粘贴到网页版 AI 的系统提示词。

如果你只是想看看两种建模路径的差异，可以再显式跑一次：

```powershell
# 13 章 + 证据账本
person-sim build --input data\chat.txt --speaker-a 小明 --speaker-b 小红 --target 小明 --mode mock --strategy evidence --out runs

# 整段原文一次分析；不保证 13 章
person-sim build --input data\chat.txt --speaker-a 小明 --speaker-b 小红 --target 小明 --mode mock --strategy whole --out runs
```

第一次使用不建议同时跑三条；先跑 `auto`，确认流程通了再选路径。

#### 4. 使用真实模型

真实 API 会产生费用。项目不提供价格表，也不保证成功率；先用 Mock 验证流程，再用 `plan` 和 `--max-requests` 控制预算。

复制示例配置：

```powershell
Copy-Item config.example.toml config.toml
```

编辑 `config.toml` 的 `[model]`：

```toml
[model]
mode = "api"
provider = "openai_chat"
model = "YOUR_MODEL_ID"
base_url = "https://YOUR_PROVIDER_HOST/v1"
context_window = 32768
max_output_tokens = 4096
```

说明：

- `base_url` 是 API 根地址，不要包含 `/chat/completions`。
- `context_window` 要填写服务商实际支持的上下文窗口，不要照抄示例。
- 当前只支持 HTTPS + Bearer Key + 非流式 `POST /chat/completions` 的 OpenAI-compatible 服务。
- API Key 只从环境变量读取，不写进 `config.toml`。

##### API Key 到底怎么配置

项目只读取一个环境变量：`PSIM_API_KEY`。

它**不会**读取 `config.toml` 里的 `api_key`，**不会**自动加载 `.env` 文件，也没有 `--api-key` 命令行参数。不要把 Key 写进 `config.toml`；当前配置解析不接受这个项。这样做是为了避免 Key 进入配置文件、Git 提交、manifest、日志或进程参数。

**Windows PowerShell（当前终端有效）：**

```powershell
$env:PSIM_API_KEY = "<你的 API Key>"
person-sim doctor --config config.toml
```

`doctor` 输出里应该能看到：

```text
mode api
provider openai_chat
api_key_present yes
```

如果还是 `api_key_present no`，说明当前终端没有设置成功，或者你设置到了另一个终端。

`$env:` 只对当前 PowerShell 进程及其子进程有效。关掉终端、换一个终端，或者把 `serve` 放到另一个窗口启动，都需要在**实际运行命令的那个终端**重新设置。

**macOS / Linux（当前 shell 有效）：**

```bash
export PSIM_API_KEY="<你的 API Key>"
person-sim doctor --config config.toml
```

**如果确实需要持久化：**

Windows 可以用 `setx`：

```powershell
setx PSIM_API_KEY "<你的 API Key>"
```

`setx` 只影响之后新开的终端，不影响当前终端；它会把 Key 写入用户环境变量，公共电脑或多人账户不要这样做。

macOS / Linux 可以把 `export` 写进自己的 shell 配置文件（例如 `~/.zshrc`），但这同样会让 Key 留在本机配置里。更稳妥的方式是用密码管理器、系统密钥环或临时注入，而不是长期明文保存。

**注意：**

- 不要把 Key 写进 `config.toml`、README、Issue、截图或 Git。
- 不要把 Key 直接写在命令历史里；如果已经写入，轮换 Key。
- `doctor --probe-api` 会发一次真实请求，可能产生费用；没有明确授权时不要运行。
- Mode C 中，所有者启动 `serve --mode api` 的进程需要 `PSIM_API_KEY`；被邀请者不需要 API Key。浏览器体验者只需要访问链接；CLI 体验者需要邀请文件和口令。
- `PSIM_API_KEY` 和 `PSIM_ADMIN_TOKEN` 不是一回事：前者是模型服务商的 Key，后者是本地管理员令牌。

`doctor` 默认只检查配置，不发送请求。确认要花一次最小请求的费用时，再做真实探测：

```powershell
person-sim doctor --config config.toml --probe-api
```

然后先用 `plan` 看预算：

```powershell
person-sim plan --input data\chat.txt --speaker-a 小明 --speaker-b 小红 --target 小明 --config config.toml
```

正式构建：

```powershell
person-sim build `
  --input data\chat.txt `
  --speaker-a 小明 `
  --speaker-b 小红 `
  --target 小明 `
  --mode api `
  --config config.toml `
  --max-requests 100 `
  --out runs
```

`--max-requests` 是本次运行的请求上限，不是费用上限。实际费用由你的模型服务商按 token 计费；`plan` 也不包含 reduce、修复和重试的全部调用。

如果中途失败：

- `evidence` run 保留了检查点，可以继续：

```powershell
person-sim resume --run runs\<evidence-run-id> --config config.toml --mode api
```

- `whole` run 没有同样的分块检查点；超长聊天请改用 `--strategy evidence`，或先用 `--limit-messages` 做 pilot。

#### 5. 使用生成的人物材料

`evidence` run 会生成：

```text
person_simulation.md    # 固定 13 章，人类可读
system_prompt.md        # 可直接粘贴到网页版 AI
persona.json            # 证据审计用，不要直接上传
evidence.jsonl          # 证据审计用
```

`whole` run 会生成：

```text
system_prompt.md
person_simulation.md    # 可选，模型自由组织，不保证 13 章
```

使用方式：

1. 打开网页版 AI 的新会话；
2. 上传 `person_simulation.md`，或把 `system_prompt.md` 贴进系统提示词/自定义指令；
3. 把对话对象设定为聊天中的另一位参与者，或者按材料中的使用说明开始；
4. 不要同时把 `persona.json`、`evidence.jsonl` 和原始聊天交给网页 AI。

如果平台限制文件长度，优先使用 `system_prompt.md`。它本来就是为直接粘贴准备的。

再次强调：材料看起来像，不等于就是本人；它可能记错事实，也可能在新情境里编造历史。

#### 6. 让别人体验：Mode C（可选）

如果你只想自己生成档案，可以跳过这一节。

##### 6.1 先确认 run 能加载

```powershell
person-sim serve --run runs\<run-id> --mode mock --check
```

`--check` 只校验 run、版本、模式和配置，不监听端口。准备用真实模型时，把 `--mode mock` 换成 `--mode api`，并先设置好 `PSIM_API_KEY`。

##### 6.2 启动服务

```powershell
person-sim serve --run runs\<run-id> --mode mock
```

终端会打印：

```text
public_url http://127.0.0.1:8765
admin_url http://127.0.0.1:<随机端口>
admin_token_source ...
```

如果 `admin_token_source` 是 `generated`，终端还会打印一次 `admin_token`。把它复制下来，在另一个终端设置：

```powershell
$env:PSIM_ADMIN_TOKEN = "<刚刚打印的管理员令牌>"
```

`serve` 会占用当前终端。不要关掉它；邀请和会话管理要在另一个终端做。

如果不想用自动生成的令牌，可以提前自己设置，或使用文件：

```powershell
$env:PSIM_ADMIN_TOKEN = "<你自己的令牌>"
# 或者
person-sim serve --run runs\<run-id> --mode mock --admin-token-file .secrets\admin.txt
```

管理员令牌不接受明文命令行参数，避免出现在进程列表里。

##### 6.3 创建邀请

在第二个终端：

```powershell
$env:PSIM_ADMIN_TOKEN = "<管理员令牌>"
$env:PSIM_INVITE_PASSPHRASE = "<邀请口令>"

person-sim invite create `
  --server <serve 打印的 admin_url> `
  --endpoint <serve 打印的 public_url> `
  --out invite.psim `
  --label "给同学" `
  --expires-in 3600
```

会打印：

```text
invite_id ...
web_url http://127.0.0.1:8765/?token=...
expires_at ...
```

`invite.psim` 只包含服务地址、令牌、有效期、备注、可选指纹和限额；不包含人物档案、system prompt、原始聊天或 API Key。

把 `web_url` 或 `invite.psim` 通过安全渠道发给体验者。邀请口令最好走另一条渠道。`web_url` 本身带有访问令牌，拿到链接的人就能建立会话，不要公开贴出。

##### 6.4 体验者怎么用

**最简单：浏览器。** 体验者不需要安装 Python，也不需要 API Key。打开所有者发来的 `web_url` 即可。页面会常驻显示“AI 模拟角色，不是本人”。

**如果使用 CLI：** 体验者需要先安装本项目，然后：

```powershell
$env:PSIM_INVITE_PASSPHRASE = "<邀请口令>"
person-sim connect --invite invite.psim
```

不带 `--message` 时进入交互式对话，输入 `/exit` 结束。也可以只发一条：

```powershell
person-sim connect --invite invite.psim --message "在吗？"
```

体验者不需要 `PSIM_API_KEY`，也不需要管理员令牌，更不应该拿到 `serve`、`session delete` 这些所有者命令。

##### 6.5 结束、删除和撤销

```powershell
person-sim session list --server <admin_url>
person-sim session delete --server <admin_url> <session-id>

person-sim invite list --server <admin_url>
person-sim invite revoke --server <admin_url> --invite-id <invite-id>
```

结束或过期会清空消息内容；删除会移除会话；停止服务会清空所有内存会话和邀请。run 文件和 `exports/` 不会被自动删除。

##### 6.6 局域网和公网

默认只监听 `127.0.0.1`。局域网需要显式开启：

```powershell
person-sim serve `
  --run runs\<run-id> --mode mock `
  --host 0.0.0.0 --allow-lan `
  --allowed-host 192.168.1.20
```

但 `invite create` 的 `--endpoint` 只接受 loopback 的 `http` 或任意 `https`。纯 HTTP 的局域网地址不能直接生成邀请。要在局域网或公网给朋友用，需要 HTTPS 入口，例如反向代理、Tailscale Serve 或 Cloudflare Tunnel。

隧道只转发公开端口，**不要转发管理员端口**。HTTPS 场景建议设置：

```toml
[simulation]
secure_cookies = true
allowed_hosts = ["127.0.0.1", "localhost", "::1", "your-tunnel-host"]
```

体验者实际访问的 HTTPS 地址才是 `--endpoint`，不是本机的 `http://127.0.0.1:8765`。

#### 7. 常见问题

**`person-sim` 不是内部或外部命令**

先激活虚拟环境：

```powershell
.\.venv\Scripts\Activate.ps1
```

或者直接用完整路径：

```powershell
.\.venv\Scripts\person-sim.exe --version
```

**提示 `target` 不匹配**

用 `validate` 看实际标签：

```powershell
person-sim validate --input data\chat.txt --speaker-a 小明 --speaker-b 小红 --target 小明
```

标签必须完全一致；`小明` 和 `A` 不是同一个标签。

**提示 `api 模式需要 PSIM_API_KEY`**

```powershell
$env:PSIM_API_KEY = "<你的 Key>"
```

项目不会自动降级为 Mock。没有 Key 就显式使用 `--mode mock`。

**`whole` 提示上下文不够**

改用 `--strategy evidence`，或先用 `--limit-messages 50` 做 pilot。`auto` 会在整段放不下时自动选 evidence。

**`invite create` 拒绝局域网 HTTP 地址**

这是有意的安全限制。给非 loopback 地址发邀请必须用 HTTPS。用反向代理、Tailscale Serve 或 Cloudflare Tunnel 提供 HTTPS，再把 HTTPS 地址传给 `--endpoint`。

**`render` 说文件已存在**

换一个空的输出目录；`render` 不会覆盖已有文件。

**Mock 输出看起来像模板**

Mock 本来就是确定性合成演示，不是真实人物建模。要真实效果，必须显式 `--mode api`。

**`runs/` 在 Git 里看不到**

`runs/`、`exports/`、`eval_runs/`、`data/` 都被 `.gitignore` 排除。它们是你的本地数据，不会自动进入仓库，也不会自动备份。

**浏览器打开后提示没有有效邀请**

邀请可能已过期、被撤销，或链接对应的服务已经停止。让所有者重新创建邀请；管理员令牌丢失时需要重启服务并重新创建会话。

### 第二部分：给 AI 编码助手（vibecoding）的操作说明

这一节是给 Cursor、Claude Code、OpenCode、Codex 等 AI 编码助手看的。真人用户不需要读。

如果你是被要求修改这个仓库的 AI，请先做这几件事：

1. 读 `AGENTS.md`、`docs/contract.md`、`docs/architecture.md`、`docs/evaluation.md`。
2. 用 `git status` 确认工作区；不要覆盖用户未提交的修改。
3. 以当前代码和测试为准。文档和 `AGENTS.md` 里的旧范围描述如果与实现冲突，先报告，不要按旧描述删除已有功能。

#### 硬性边界

- **默认只用 Mock。** 未经用户明确授权，不得用真实聊天或真实 API Key 调用付费 API。
- **不提交私人数据。** 不读、不复制、不提交 `data/`、`runs/`、`exports/`、`eval_runs/`、`config.toml`、`.env*`、`*.psim`。
- **不伪造质量。** 工程测试通过、Mock 输出、合成评分、单评审偏好都不能写成“人物模拟质量已通过”。真实质量状态仍以 `docs/evaluation.md` 和 manifest 为准。
- **不绕过证据约束。** `quote` 必须由代码从原文切片；对方的话不能变成目标人物的事实；失败或不完整的 run 不能被 Mode C 加载。
- **不削弱安全边界。** 公开端口不能注册 `/admin/*`；管理员监听器只绑定 loopback；不删除输出检查、会话清理或测试断言来让功能“跑通”。
- **不擅自提交、推送、打标签或发布。** 只有用户明确要求时才做这些操作。

#### 代码和测试

- 新功能或 bugfix 先写失败测试，再写最小实现。
- 修 bug 先写复现测试；不得删除测试或降低断言。
- 测试只能使用合成聊天、假姓名/电话和 `tmp_path`；不得使用真实聊天、真实 Key 或个人绝对路径。
- 改动完成后运行完整测试：

```powershell
.\.venv\Scripts\python.exe -m pytest
```

当前基线是 **180 passed**（Windows，Python 3.12.10）。如果你新增了测试，基线数字会变化；以实际输出为准。

- 涉及打包时运行：

```powershell
.\.venv\Scripts\python.exe -m build
```

并确认产物不包含 `data/`、`runs/`、`exports/`、`eval_runs/`、`config.toml`、`.env` 或 `*.psim`。

#### 改哪里

- 输入/解析：`parser.py`、`docs/input-format.md`、`tests/test_parser.py`。
- 切分/预算：`chunking.py`、`budget.py`、相关测试。
- evidence 建模：`pipeline.py`、`modeling/`、`prompts/`。
- whole-chat：`wholechat/`。
- 渲染：`rendering/markdown.py`、`docs/output-format.md`。
- Provider：`providers/`、`config.py`。
- Mode C：`runtime/`、`server/`、`tests/test_*mode_c*`。
- 评测：`evaluation/prepare.py`、`evaluation/score.py`、`docs/evaluation.md`。
- 公共 CLI/契约：`cli.py`、`docs/contract.md`、`README.md`。

新增配置项时，必须同步更新 `config.example.toml`、`docs/configuration.md` 和测试；新增输出检查时，必须同时有正例和反例。

#### 评测时的额外规则

- `eval score` 只汇总真实人工采集的 `human_collected` 回答；不得把 Mock 或合成数据写成 `evaluated`。
- `status=evaluated` 不等于 `gate_passed=true`；报告要同时看数据完整性、维度分数和失败标记。
- 现有 30 题 A/B 只有一次单评审偏好，没有完成五维评分、第二评审或重复生成；不能据此宣布 A/B 整体胜负。
- 需要真实付费调用时，先停止并说明预计调用次数、模型和费用，等待用户明确授权。

#### 完成前检查

- [ ] 测试实际运行并通过，记录真实数量和平台。
- [ ] 新增/修改的命令、路径、版本号与 README/契约一致。
- [ ] 没有提交真实聊天、Key、邀请文件、run 或 eval 产物。
- [ ] 没有把 Mock 或工程测试通过写成人物质量结论。
- [ ] `git diff` 中没有本地绝对路径、密钥或私人数据。
- [ ] 如果改了 CLI、配置或安全边界，相关文档和测试一起更新。

## 技术实现

这一部分解释“为什么这样实现”。如果你只想使用，前面的说明书已经够了。

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

完整的数据格式、评分规则、人工步骤、结果保存方式和局限见 [`docs/evaluation.md`](docs/evaluation.md)。

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
