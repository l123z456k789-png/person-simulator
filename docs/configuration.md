# 配置

## 优先级

```text
CLI 明示值 > PSIM_ 环境变量 > TOML > 默认值
```

API Key 只从 `PSIM_API_KEY` 读取；TOML、CLI 参数、manifest 和日志都不保存真实 Key。

## 示例文件

```powershell
Copy-Item config.example.toml config.toml
```

`config.toml` 已被 `.gitignore` 忽略。不要提交真实配置。

## [model]

| 项 | 默认 | 说明 |
|---|---|---|
| `mode` | `mock` | `mock` / `api` |
| `provider` | `mock` | `mock` / `openai_chat` |
| `model` | 空 | api 模式必填 |
| `base_url` | 空 | API 根地址，不要包含 `/chat/completions` |
| `context_window` | 空 | api 模式必填 |
| `max_output_tokens` | 4096 | 单次模型输出上限 |
| `output_limit_param` | `max_tokens` | `max_tokens` / `max_completion_tokens` |
| `json_object` | false | 显式启用才发送 `response_format` |
| `disable_thinking` | false | 显式启用才发送 `thinking` |
| `temperature` | 空 | 显式设置才发送 |

## [chunking]

| 项 | 默认 |
|---|---|
| `chunk_input_budget` | 6000 |
| `overlap_messages` | 4 |

## [retry]

| 项 | 默认 |
|---|---|
| `max_attempts` | 3 |
| `connect_timeout` | 10 |
| `read_timeout` | 120 |

## [budget]

| 项 | 默认 |
|---|---|
| `max_repair_attempts` | 1 |
| `max_context_splits` | 8 |
| `max_requests_per_run` | 500 |

## [mock]

| 项 | 默认 |
|---|---|
| `context_window` | 32768 |

## [security]

| 项 | 默认 | 说明 |
|---|---|---|
| `allow_insecure_localhost` | false | 仅允许显式打开的 loopback HTTP |
| `trust_env` | false | Provider 是否读取系统代理环境 |

## [simulation]

| 项 | 默认 | 说明 |
|---|---|---|
| `host` | `127.0.0.1` | 公开监听地址 |
| `port` | 8765 | 公开端口 |
| `allow_lan` | false | 允许非 loopback |
| `secure_cookies` | false | 隧道 HTTPS 场景建议 true |
| `max_sessions` | 8 | 全局活跃会话上限 |
| `ttl_minutes` | 30 | 会话总时长 |
| `idle_minutes` | 10 | 空闲超时 |
| `max_turns` | 30 | 最大成功轮数 |
| `max_input_chars` | 2000 | 单条输入上限 |
| `max_output_tokens` | 1024 | 模拟回复上限 |
| `requests_per_minute` | 6 | 每会话请求速率 |
| `max_concurrency` | 2 | 全局模型并发上限 |
| `allowed_hosts` | `127.0.0.1`, `localhost`, `::1` | Host 白名单 |
| `blocked_terms` | `[]` | 输出中要隐藏的姓名/地址等词表 |
| `log_metadata` | false | 是否输出请求元数据（仍不记录正文） |

`simulation` 配置不参与建模 run 的 `config_hash`，因此升级到带模式 C 的版本不会让旧 run 失效。

## 环境变量

常用：

- `PSIM_API_KEY`
- `PSIM_MODE`、`PSIM_PROVIDER`、`PSIM_MODEL`、`PSIM_BASE_URL`、`PSIM_CONTEXT_WINDOW`
- `PSIM_SIM_HOST`、`PSIM_SIM_PORT`、`PSIM_SIM_ALLOW_LAN`
- `PSIM_SIM_SECURE_COOKIES`、`PSIM_SIM_MAX_SESSIONS`
- `PSIM_SIM_TTL_MINUTES`、`PSIM_SIM_IDLE_MINUTES`、`PSIM_SIM_MAX_TURNS`
- `PSIM_SIM_MAX_INPUT_CHARS`、`PSIM_SIM_MAX_OUTPUT_TOKENS`
- `PSIM_SIM_REQUESTS_PER_MINUTE`
- `PSIM_SIM_ALLOWED_HOSTS`（逗号分隔）
- `PSIM_SIM_BLOCKED_TERMS`（逗号分隔）
- `PSIM_ADMIN_TOKEN`（管理员令牌；优先使用文件）
- `PSIM_INVITE_PASSPHRASE`（邀请口令；不要与邀请文件同渠道）

## 管理员令牌

```powershell
# 推荐：0600 文件
person-sim serve --run runs/<id> --mode mock --admin-token-file .secrets/admin.txt
person-sim invite create ... --admin-token-file .secrets/admin.txt
```

不接受 `--admin-token` 明文参数，避免进程列表泄露。

## 公网/隧道

- 默认只监听 `127.0.0.1`。
- 局域网：`--host 0.0.0.0 --allow-lan --allowed-host <局域网IP或主机名>`。
- 公网：用 Tailscale/Cloudflare Tunnel/反向代理提供 HTTPS；软件仍只绑定 loopback/局域网。
- 隧道只转发公开端口；管理员端口不转发。
- 隧道域名加入 `allowed_hosts`；HTTPS 场景设置 `secure_cookies = true`。

## 错误与退出码

| 退出码 | 含义 |
|---|---|
| 0 | 成功 |
| 2 | 输入/配置/邀请/权限错误 |
| 3 | API/客户端协议错误 |
| 4 | 流水线/运行时/会话/输出检查错误 |
| 5 | IO 错误 |
| 130 | 中断 |
