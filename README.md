# person-simulator

把**预清洗的双人聊天**转换成指定人物的角色模拟资料；或者在所有者自己的电脑/服务器上运行一个受控的第三方模拟服务。

项目不做微信原始数据库解析、不训练模型、不做向量数据库、不做实时监听，也不提供公网多租户 SaaS。

## 它解决什么问题

- 你有一份已经清洗好的双人聊天文本，想为其中一个人建立可复用的表达/行为资料。
- 你想把这套资料用于自己的角色扮演，而不是每次手动整理提示词。
- 你想让经过授权的朋友体验“和这个人聊天”，但不想把完整人物档案直接发给他们。

## 两种产品模式

| 模式 | 用途 | 谁看得到档案 |
|---|---|---|
| **A：完整人物档案** | 本人查看、编辑、保存、导出 | 所有者 |
| **C：第三方模拟体验** | 朋友/同学通过客户端或浏览器聊天 | 只有所有者；第三方只看到对话 |

模式 A 和模式 C 复用同一套建模结果，不复制两套人物建模流程。

### 三个不要混淆的概念

- **产品模式**：A=archive，C=simulation。
- **模型调用模式**：`--mode mock|api`，默认 `mock`；真实 API 必须显式 `api`。
- **建模策略**：`--strategy whole|evidence`，默认 `auto`。

## 环境要求

- Python **3.11+**；当前验证环境为 Windows + Python 3.12.10。
- 真实模型调用需要一个兼容 **HTTPS + Bearer Key + 非流式 `POST /chat/completions`** 的服务。
- 模式 C 的浏览器兜底需要现代浏览器；客户端优先入口使用同一套 Python 包。
- 公网共享需要隧道/反向代理提供 HTTPS；项目不内置 ACME 自动证书。

## 安装

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

也可以使用 `requirements-dev.lock` 复现开发环境。真实 API Key **只**从 `PSIM_API_KEY` 读取，不写入 TOML、命令行、manifest 或日志。

## 模式 A：完整人物档案

```powershell
# 校验输入、说话人与 target
person-sim validate --input examples/sample_chat.txt --target A

# 离线查看切分与预算（不联网、不打印正文）
person-sim plan --input examples/sample_chat.txt --target A

# Mock 全流程（默认 evidence 策略）
person-sim build --input examples/sample_chat.txt --target A --mode mock --out runs

# whole-chat：整段原文直接生成 system_prompt.md / person_simulation.md
person-sim build --input data/chat.txt --target A --strategy whole --out runs

# 从检查点恢复
person-sim resume --run runs/<run-id>

# 另存一份导出，不覆盖已有文件
person-sim render --run runs/<run-id> --out exports/demo
```

模式 A 的默认行为没有因为模式 C 改变。`person_simulation.md` 固定 13 章，并生成独立 `system_prompt.md`。

## 模式 C：第三方模拟体验

### 1. 准备一个已完成的 run

```powershell
person-sim build --input examples/sample_chat.txt --target A --mode mock --out runs
person-sim serve --run runs/<run-id> --mode mock --check
```

`--check` 只校验 run、版本、模式和配置，不监听端口。

### 2. 启动所有者托管服务

```powershell
person-sim serve --run runs/<run-id> --mode mock
```

终端会打印：

- `public_url`：本机或局域网访问地址；
- `admin_url`：仅本机可达的管理员地址；
- 管理员令牌来源；如果自动生成，会打印一次。

默认只监听 `127.0.0.1`。局域网需要显式：

```powershell
person-sim serve --run runs/<run-id> --mode mock --host 0.0.0.0 --allow-lan --allowed-host 192.168.1.20
```

### 3. 创建加密邀请

管理员令牌只从 `PSIM_ADMIN_TOKEN` 或 `--admin-token-file` 读取，不接受明文命令行参数。

```powershell
$env:PSIM_ADMIN_TOKEN = "<管理员令牌>"
$env:PSIM_INVITE_PASSPHRASE = "<邀请口令>"

person-sim invite create `
  --server <serve 打印的 admin_url> `
  --endpoint <serve 打印的 public_url 或隧道地址> `
  --out invite.psim `
  --label "给同学" `
  --expires-in 3600
```

`invite create` 会打印 `invite_id`、`web_url` 和过期时间；撤销时使用 `invite_id`。也可以先列出：

```powershell
person-sim invite list --server <admin_url>
```

`invite.psim` 是加密邀请文件，**只包含**服务地址、令牌、有效期、备注和限额；**不包含人物档案、system prompt、原始聊天或 API Key**。

`invite create` 会打印 `web_url`。把邀请文件或链接通过安全渠道发给 C；口令最好走另一条渠道。

### 4. C 使用客户端（优先）

```powershell
person-sim connect --invite invite.psim --message "在吗？"
```

不带 `--message` 时进入交互式对话。输入 `/exit` 结束。

### 5. C 使用浏览器（兜底）

把 `invite create` 打印的 `web_url` 发给 C，用浏览器打开即可。网页会常驻显示“AI 模拟角色，不是本人”。

### 6. 撤销与删除

```powershell
# 列出会话元数据
person-sim session list --server <admin_url>

# 删除单个会话
person-sim session delete --server <admin_url> <session-id>

# 撤销邀请
person-sim invite revoke --server <admin_url> --invite-id <invite-id>
```

管理员接口在独立的 loopback 端口，公开端口没有 `/admin/*`。停止服务会清空所有内存会话和邀请。

## 公网共享与隧道

0.2.0 不内置公网 TLS、ACME 或端口转发。推荐：

- **Tailscale**：设备间加密网络，适合只给少数朋友用；
- **Cloudflare Tunnel**：提供公网 HTTPS，但 Cloudflare 会终止 TLS，能看到流量；
- **反向代理**：由所有者自行提供证书。

隧道只转发公开端口，**不要转发管理员端口**。HTTPS 隧道场景建议设置：

```toml
[simulation]
secure_cookies = true
allowed_hosts = ["127.0.0.1", "localhost", "::1", "your-tunnel-host"]
```

隧道提供方、所有者模型服务商和第三方 agent 的数据可见性见 `docs/privacy.md`。

## 隐私边界：能保证与不能保证

**设计目标：**

- 人物档案、`system_prompt.md`、`persona.json`、原始聊天和 API Key 始终留在 A。
- C 的正常接口不能下载完整档案。
- 邀请文件加密；服务端只保存令牌哈希。
- 输出检查会脱敏手机号、身份证号、邮箱、座机、银行卡和可配置姓名/地址词表；提示词长片段、内部标记、逐字复述会被拒绝。
- 会话只在内存中，结束/过期会清空消息内容，删除会移除会话。

**不能保证：**

- A 的模型服务商能看到人物提示词和对话。
- C 的远程 AI agent 会看到对话内容。
- C 可以从回复中推断人物特征、截图或转发对话。
- 无法绝对阻止提示注入、改写后的复述或所有直接身份信息。
- 如果邀请文件和口令走同一渠道，加密只剩防静态窥探的作用。

不要把这些限制从 README 中删掉后宣称“绝对隐私”。

## 配置

示例见 `config.example.toml`。优先级：**CLI > `PSIM_` 环境变量 > TOML > 默认值**。

模式 C 常用项：

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
allowed_hosts = ["127.0.0.1", "localhost", "::1"]
blocked_terms = []
log_metadata = false
```

完整说明见 `docs/configuration.md`。

## 测试

```powershell
.\.venv\Scripts\python.exe -m pytest
```

当前基线：**172 passed**（Windows，Python 3.12.10；新增模式 C 测试后）。测试不依赖真实聊天、真实 API Key 或个人绝对路径；CI 不调用真实模型 API。

工程测试通过只证明代码按契约工作，不证明人物相似度。人物质量仍需真实留出集与独立人工评分；当前为 **not_evaluated**。

## 当前真实状态与限制

- 模式 A：evidence 与 whole-chat 两条路径保留；历史 whole-chat 真实运行产物存在，但当前代码未重新做真实 API 全流程验收。
- 模式 C：已实现严格 run 加载、加密邀请、双监听服务、会话限额、输出检查和浏览器/CLI 入口；**尚未做真实 API 端到端验收**。
- evidence 真实 API：**not_verified**。
- 人物模拟质量：**not_evaluated**；不能拿 Mock 结果宣称真实效果。
- 模式 C 的客户端目前是 CLI；独立桌面程序、MCP adapter、内置公网 TLS/ACME 属于后续工作。
- 会话与邀请默认只在内存中；服务重启即失效。需要长期运行时应由所有者自行设计持久化与备份。
- 不支持微信原始数据库解析；输入必须是预清洗的 UTF-8 双人聊天文本。

## 费用

真实 API 费用由 A 的模型账户承担。Mock 模式完全离线、确定性输出，不产生 API 费用。项目不提供价格表或成功率承诺；运行前请用 `plan` 和 `--max-requests` 控制预算。

## 报告问题

请通过仓库 Issue 报告，但**不要**在 Issue 中粘贴真实聊天、人物档案、API Key、邀请令牌或可识别个人的信息。安全问题请先私下联系维护者（仓库建立后补充联系方式）。

## 许可证

MIT。见 `LICENSE`。

契约见 `docs/contract.md`；架构、隐私、安全、配置、开发与发布说明见 `docs/`。

<!-- AUTO-STATUS-START -->
<!-- Generated by git-dynamic-index from local Git state; edits inside the markers will be overwritten. -->

## Project status

- **Branch**: `feat/mode-c`
- **Last commit (excl. this file)**: `6ea7ac3` fix: harden mode C security boundaries and admin workflow (2026-10-25)
- **Working tree (excl. this file)**: clean
- **Upstream**: not set
<!-- AUTO-STATUS-END -->
