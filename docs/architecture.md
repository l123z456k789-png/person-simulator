# 架构

## 总览

`person-simulator` 有两条产品路径，共用同一套输入解析、Provider、预算和存储基础：

```text
预清洗双人聊天
   |
   v
parser -> chunking -> evidence pipeline ─┐
   |                                      ├──> persona.json / system_prompt.md
   └────────-> whole-chat pipeline ───────┘
                                             |
                    ┌────────────────────────┴─────────────────────┐
                    v                                              v
             模式 A：导出档案                              模式 C：运行时服务
             build / resume / render                       load_runtime_persona
                                                           -> runtime HTTP server
                                                           -> sessions / guard
                                                           -> client / browser
```

## 模块职责

| 模块 | 职责 |
|---|---|
| `parser.py` | 严格解析 UTF-8 双人聊天、校验身份、保留原文偏移 |
| `chunking.py` | 按会话/预算切分，保证 core 覆盖完整 |
| `budget.py` | 保守 token 估算与上下文预算 |
| `config.py` | CLI/环境变量/TOML/默认值优先级 |
| `providers/` | OpenAI-compatible HTTP、Mock、重试、请求上限 |
| `pipeline.py` | evidence 分片、证据回源、reduce、检查点、resume |
| `wholechat/` | 整段聊天一次建模与 whole 输出校验 |
| `rendering/markdown.py` | 13 章 Markdown、独立 system prompt、失败不发布 |
| `storage.py` | 原子写入、run 锁、路径越界检查 |
| `evaluation/` | 会话级留出、评分器、质量报告 |
| `runtime/persona.py` | 严格加载已完成 run，生成版本化 `RuntimePersonaV1` |
| `runtime/prompts.py` | 固定安全披露 + 原提示词 + 观众说明 + 运行时优先级 |
| `runtime/invite.py` | 加密邀请凭证（PBKDF2 + Fernet） |
| `runtime/session.py` | 内存会话、TTL、轮数/输入/速率限制、墓碑 |
| `runtime/guard.py` | 身份信息脱敏、提示词泄露、内部标记、逐字复述 |
| `runtime/service.py` | 上下文预算、Provider 调用、输出检查、历史写入 |
| `server/registry.py` | 邀请记录与令牌哈希 |
| `server/app.py` | 公开监听器 + 独立 loopback 管理员监听器 |
| `server/static/` | 无框架浏览器兜底 UI |
| `runtime/client.py` | 管理员/第三方 HTTP 客户端 |

## 模式 A 数据流

1. `parse_chat` 校验输入并保留消息 ID、行号和 source hash。
2. evidence：`build_chunk_plan` 切分；每个 chunk 调用模型提取 observations；校验证据引用；按维度 reduce；组装 Persona。
3. whole：序列化整段聊天，一次调用生成 `system_prompt.md` 与可选 `person_simulation.md`。
4. 渲染前检查 `analysis_status=complete`、覆盖、来源哈希、身份；失败不发布正式文件。
5. run 目录保留 manifest、消息、chunk、分析、evidence、persona、报告和导出。

## 模式 C 数据流

1. `load_runtime_persona` 只接受完成、版本兼容、哈希/身份一致的 run。
2. 组合私有运行时提示词；不把原始聊天加入每次模型上下文（原始消息仅用于本地复述检测）。
3. 所有者启动公开监听器和独立管理员监听器。
4. C 通过加密邀请获得 endpoint + token；浏览器换 Cookie，客户端用 Bearer + 会话头。
5. 每轮：校验会话/限额 -> 构造 system + 历史 + 当前输入 -> 估算预算、丢最旧轮次 -> 调用 Provider -> 输出检查 -> 只保存脱敏后的回复。
6. 结束/过期清空消息内容；删除移除会话；服务重启清空邀请和会话。

## 信任边界

- **所有者机器**：信任。持有 run、API Key、运行时提示词和邀请注册表。
- **C 的客户端/浏览器**：不信任。只接收对话和邀请凭证。
- **模型服务商**：外部处理者。会看到运行时提示词和对话。
- **隧道/反向代理**：传输层外部处理者。可能看到流量；Tailscale 与会终止 TLS 的隧道不同。
- **管理员监听器**：只绑定 loopback，不经过隧道；仍需管理员令牌。

## 不做的架构

- 没有中央人物库、中央账号、中央会话库。
- 没有把完整档案放进公开下载目录。
- 没有把 Base64/压缩/字段映射当加密。
- 没有用“隐藏 UI 按钮”代替权限边界。
