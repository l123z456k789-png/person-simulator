# person-simulator 公共契约 v1.0

本文件是六个开发阶段共同读取的公开契约。实现与测试以本文件为准；变更接口必须同步更新本文件。

## 1. 输入

- 文件必须是 UTF-8 或 UTF-8-BOM 的 `.txt` / `.md`，按原始顺序保留文本。
- 消息头：`A: 文本`、`B: 文本`，也接受全角冒号 `A：文本`。
- 可选时间头：`[ISO8601时间] A: 文本`，时间保留原时区语义；不带时区不擅自补时区。
- 冒号后最多一个 ASCII 空格属于格式分隔，其余字符全部属于正文。
- 续行必须以**两个空格**开头。剥离这两个结构空格后，其余内容原样保留，并以换行接到当前消息。
- 只由两个空格组成的行表示正文中的空行。
- 空白分隔行（空行或纯空白但不是两空格开头）不组成消息，可形成会话候选边界。
- 正文里看起来像消息头的行必须用两个空格缩进，否则按新消息或错误处理。
- `.md` 文件只按上述语法读取，不解析任意 Markdown 结构。
- 结构解析不 `strip` 正文、不归一化标点、emoji 或内部空格。只统一文件换行以便稳定解析。
- 文件 SHA256 保存为 `source_hash`。

错误必须给出行号和原因，不回显私人正文：无归属非空行、第三人标签、空正文、标签缺失、NUL、损坏编码、空文件、目录或不可读路径。

## 2. 选人

- `--speaker-a` / `--speaker-b` 默认 `A` / `B`，可配置为实际标签。
- `--target` 必填，且必须与其中一个标签精确匹配。
- 标签 `strip` 后非空、互不相同，不得包含冒号、换行、方括号。
- 两人都必须有有效消息。
- 不根据最后发言人猜角色，不根据文件顺序猜身份，不自动更换 target。
- 同一人连续发言合法，不强制轮流。

## 3. 核心数据模型

所有模型拒绝未知字段、非法枚举和越界偏移。

- `Message`：`id, index, speaker, text, timestamp|null, line_start, line_end, session_id`。
- `MessagePart`：`id, message_id, start, end, text`；`start/end` 是 Unicode 字符偏移，左闭右开。
- `EvidenceRef`：`message_id, start, end`；`quote` 由代码回原文切片，模型不得提供或改写。
- `Chunk`：`id, core_parts, context_parts, source_range, budget_estimate`。
- `Observation`：`id, dimension, claim, kind, evidence_refs, counter_evidence_refs, scope, confidence, uncertainty`；`kind` 为 `observed_pattern | reported_fact | inference`；`confidence` 为 `low | medium | high`，表示证据强弱，不是概率。
- `SegmentAnalysis`：`schema_version, chunk_id, target, processed_core_part_ids, observations, processed_no_observation, example_candidates, unknowns, overflow`。
- `Persona`：`schema_version, target, interlocutor, source_hash, coverage, language, behavior, thinking, relationship, history, changes, examples, unknowns, selection_audit`。
- `Manifest`：schema/prompt/package 版本、`source_hash`、target、脱敏 `config_hash`、provider/model、预算、每个任务状态、依赖、尝试次数、coverage、`analysis_status`、`quality_status`。
- 任务状态：`pending | running | succeeded | failed`；只有结构和证据校验通过才能 `succeeded`。
- `quality_status` 初始为 `not_evaluated`。

## 4. 切分

- 每个原文正文字符恰有一次 `core` 归属；`context` 重叠只帮助理解，不增加独立支持次数。
- 优先按会话边界切分：可比较时间的相邻消息间隔超过 30 分钟形成会话；无时间时以空白分隔行为候选边界。
- 每块携带显式 target/interlocutor、core 和最多 4 条前文 context。
- 预算不足先减少 context，不能删除原文。
- 单条消息超过预算时按 Unicode 字符安全切成 `MessagePart`，优先在换行/句末断开，不丢标点、空格或 emoji。
- `coverage` 必须验证每条消息的 core 区间连续覆盖 `[0, len(text))`，无空洞、无重复；重组 core 必须与原文完全一致。

## 5. 预算

- `budget.py` 接受实际将发送的 system/user/schema 文本，估算序列化后的请求输入。
- 初版方法：`ceil(UTF-8 字节数 × 1.25) + 512 包装余量`。这是保守启发式，不是精确 tokenizer。
- 必须满足：`estimated_input + max_output_tokens + max(2048, ceil(context_window × 0.1)) <= context_window`。
- 配置不足以容纳固定提示词时直接报配置错误。

## 6. 配置

- 覆盖顺序：CLI 明示值 > `PSIM_` 环境变量 > TOML > 默认值。
- API Key 只读 `PSIM_API_KEY`；TOML、CLI 参数和日志都禁止包含真实 Key。
- 不自动读取用户其他项目的 `.env`。
- `mode=mock | api`，默认 `mock`。真实 API 必须显式 `mode=api`；未配置不自动降级。
- 编程模型和运行时分析模型相互独立。
- 脱敏 `config_hash` 排除 Key。

## 7. 公开 CLI

- `doctor`
- `validate --input --speaker-a --speaker-b --target`
- `plan` 同输入参数并支持 `--config`
- `build` 同输入参数并支持 `--mode mock|api --config --out runs`
  - `--strategy auto|whole|evidence`
  - `--limit-messages N`：只分析前 N 条消息的 pilot；evidence/whole 均支持；pilot run 不能被 `load_runtime_persona` 当作完整人物加载
  - `--redact-pii`：导出前替换手机号/身份证/邮箱/座机/银行卡
  - `--privacy-strict`：导出前发现直接身份信息则拒绝发布
  - `--progress` / `--json-progress`：向 stderr 输出构建进度
- `resume --run`：支持同样的隐私和进度参数
- `render --run --out exports`：支持同样的隐私和进度参数
- `runs list` / `runs status` / `runs delete` / `runs purge`：run 元数据、状态、单删和批量清理；删除必须显式 `--yes`，拒绝活动锁和根目录外的路径
- `eval prepare --input --target --out eval_runs`
- `eval score --bundle --responses --ratings`

分阶段实现；未实现命令明确报未实现，不能伪成功。

## 8. 运行目录

`build` 在 `out` 下创建独立 `run-ID/`，不覆盖已有文件。目录包含：

`manifest.json`、`messages.jsonl`、`chunks.jsonl`、`analysis/`、`evidence.jsonl`、`persona.json`、`build_report.md`、`person_simulation.md`。

`build_report.md` 包含直接身份信息扫描的分类计数；默认只警告，`--redact-pii` 会修改 `person_simulation.md`/`system_prompt.md`，`--privacy-strict` 会在写入正式导出前拒绝。运行目录中的 `messages.jsonl`/`persona.json` 仍是原始审计材料，不会被导出隐私模式改写。

只有全流程成功才发布正式 Markdown；失败保留检查点，不生成貌似完成的正式文件。写入使用临时文件 + 原子替换，manifest 最后标记 `export_status=complete`。

## 9. 退出码

| 退出码 | 含义 |
|---|---|
| 0 | 成功 |
| 2 | 输入/配置错误 |
| 3 | API/响应协议错误 |
| 4 | 流水线不完整或证据校验错误 |
| 5 | IO 错误 |
| 130 | 中断 |

错误包含安全错误码、阶段、任务 ID、可操作建议；不打印秘密或完整聊天。

## 10. 模型接口

- `ModelClient.complete(request) -> ModelResponse`。
- 请求包含 `task_id, messages, output_limit, schema/能力声明`。
- 结果包含 `content, finish_reason, usage（可空）, request_id（可空）`。
- 分析业务不得依赖 httpx 响应对象。
- 第一版仅支持 HTTPS + Bearer Key + POST `chat/completions` + 非流式 `choices[0].message.content`。
- 默认不发送 tools、streaming、thinking、response_format、temperature。仅显式启用时发送 `json_object`、`temperature`；输出限额参数二选一：`max_tokens` / `max_completion_tokens`。

## 11. 输出文件

`person_simulation.md` 固定 13 个章节（见 `docs/output-format.md`），并同时生成独立 `system_prompt.md`。输出必须：

- 可独立上传使用，不依赖项目运行时、外部路径、include 或远程链接。
- 原话逐字来自原聊天，不由模型重写。
- 明确区分目标自述、对方声称、观察和推断。
- 材料不足时写“材料不足，保持未知”，不补造人格或历史。
- Mock 产物显著标记为合成演示。
- `analysis_status != complete`、覆盖不完整、证据非法或身份缺失时拒绝发布正式文件。
- 第 13 节和 `system_prompt.md` 必须自包含，可直接复制到网页版 AI。

## 12. 模式 C：第三方模拟运行时（0.2.0）

### 12.1 产品与命令

- 产品模式：A=`archive`（现有 build/render），C=`simulation`（`serve`）。
- 模型调用模式仍是 `--mode mock|api`；建模策略仍是 `--strategy whole|evidence`。
- 模式 C 命令：`serve`、`invite create|revoke`、`connect`、`session list|delete`。
- 默认只监听 `127.0.0.1`；非 loopback 必须显式 `allow_lan`。
- 管理员接口在独立 loopback 监听器；公开端口不注册 `/admin/*`。

### 12.2 RuntimePersonaV1

从已完成 run 严格派生，不新增建模流程。字段：

`schema_version="runtime-persona-1.0"`、`run_id`、`strategy`、`package_version`、`prompt_version`、`source_hash`、`target`、`interlocutor`、`system_prompt`、`system_prompt_sha256`、`original_system_prompt_sha256`、`is_mock`、`audience`、`replay_guard`、`created_at`。

加载规则：

- evidence：manifest/persona 可解析，analysis/export complete，coverage 完整，source hash 与身份一致，`messages.jsonl` 存在。
- whole：`schema_version="whole-1.0"`、`status="complete"`、source/target/interlocutor 存在、system prompt 非空。
- 接受 package 主次版本 `0.1`/`0.2`；未知版本拒绝。
- `is_mock` 必须与 `--mode` 一致。
- 原始聊天不加入每轮模型上下文；只用于本地复述检测。

### 12.3 邀请

`invite.psim` 是加密 JSON 信封 + Fernet 密文，只含：

- `format="psim-invite-1"`
- `endpoint`（http/https，无 userinfo/query/fragment）
- `token`
- `expires_at`（带时区）
- `label`
- 可选 `server_fingerprint`、`max_sessions`

不得包含人物档案、system prompt、原始聊天、API Key。服务端只保存令牌哈希；邀请可过期、撤销。

### 12.4 会话

- 状态：`active`、`ended`、`expired`、`deleted`。
- 结束/过期立即清空消息内容；短暂保留无内容墓碑；删除立即移除。
- 限额：全局/每邀请会话数、TTL、空闲、轮数、输入字符、输出 token、每会话请求速率。
- 失败或输出检查失败不写入历史；只保存脱敏后的回复。

### 12.5 HTTP 契约

公开端口：

- `GET /`（可带 `?token=` 换取 Cookie）
- `GET /healthz`
- `POST /api/session`
- `GET /api/session`
- `POST /api/chat`
- `POST /api/session/end`
- `/static/*`

管理员端口：

- `GET /admin/invites`
- `POST /admin/invites`
- `DELETE /admin/invites/{id}`
- `GET /admin/sessions`
- `DELETE /admin/sessions/{id}`
- `POST /admin/shutdown`

不存在档案下载接口。错误返回 `{error_code, message, hint?}`，不返回堆栈、密钥或聊天正文。

### 12.6 输出检查

- 直接身份信息：手机号、身份证、邮箱、座机、银行卡正则；可配置姓名/地址词表。
- 提示词泄露：system prompt 60 字符以上连续片段；内部标记/文件名/路径。
- 复述：evidence 全量逐字检测；whole 至少 prompt-only，若存在 `messages.jsonl` 则升级。
- 空回复、超长回复、脱敏后只剩占位符：拒绝。
- 输出检查不是绝对保证；不得在文档中宣称“无法推断”或“绝对隐私”。

### 12.7 错误码

`E_RUN_NOT_FOUND`、`E_RUN_INCOMPLETE`、`E_RUN_VERSION`、`E_RUN_HASH`、`E_RUN_MODE`、`E_INVITE`、`E_UNAUTHORIZED`、`E_FORBIDDEN`、`E_SESSION_NOT_FOUND`、`E_SESSION_ENDED`、`E_SESSION_EXPIRED`、`E_SESSION_LIMIT`、`E_TURN_LIMIT`、`E_INPUT_TOO_LONG`、`E_SESSION_RATE_LIMIT`、`E_CONTEXT_LIMIT`、`E_OUTPUT_BLOCKED`、`E_CLIENT`、`E_INTERNAL`。

CLI 退出码沿用第 9 节；客户端/API 错误为 3，运行时/会话/输出检查为 4，IO 为 5。
