# Changelog

## Unreleased

### Added

- 导出隐私扫描：`build`/`render` 默认统计手机号、身份证、邮箱、座机、银行卡；`--redact-pii` 脱敏，`--privacy-strict` 拒绝发布。
- `runs list/status/delete/purge`：run 元数据、任务状态、安全删除和陈旧/失败 run 清理。
- 构建进度：核心 `ProgressEvent`，CLI `--progress`/`--json-progress`；回调异常可作为取消信号。
- evidence `--limit-messages N` pilot；pilot run 带明确标记，并拒绝作为完整运行时人物加载。

### Tests

- 新增 `tests/test_privacy.py`、`tests/test_privacy_build.py`、`tests/test_runs.py`、`tests/test_progress.py`、`tests/test_evidence_pilot.py`。

## 0.2.1 - 2026-10-25

### Changed

- README 重构为「给真人看的说明书 + 给 AI 编码助手的操作说明」，补全安装、聊天文本准备、Mock/真实 API、输出使用、Mode C 体验流程、API Key 配置和常见问题。
- 评估题面升级为 `context-v2`，把最近上下文写入题面；`responses.template.jsonl` 只包含受支持题，`ratings.template.csv` 预填受支持题行。
- 评分器要求所有受支持题都有人工评分和至少两次回答，校验评分维度，并记录 `factual_error` / `unsupported_inference`。
- 修正多评审情况下 `missing` 统计可能为负的问题，质量报告增加覆盖、重复次数和失败标记明细。

### Known limitations

- 真实 evidence API 全流程尚未验收。
- 人物模拟质量尚未完成正式人工评估。
- 不内置公网 TLS/ACME；公网共享依赖隧道/反向代理。
- 客户端目前是 CLI；桌面程序、MCP adapter 未实现。
- 无法绝对阻止推断、提示注入、截图转发或模型服务商访问。

## 0.2.0 - 2026-10-25

### Added

- 模式 C：去中心化、所有者托管的第三方模拟服务。
- 严格运行时人物加载器；拒绝失败、不完整、版本不符和哈希不一致的 run。
- 加密邀请凭证（PBKDF2-HMAC-SHA256 + Fernet）；只含 endpoint、令牌、有效期和限额。
- 客户端优先入口 `connect --invite`，以及浏览器兜底 UI。
- 公开监听器 + 独立 loopback 管理员监听器；管理员接口不在公开端口。
- 内存会话、TTL、空闲超时、轮数/输入/速率限制、结束/删除。
- 输出检查：手机号、身份证、邮箱、座机、银行卡、可配置词表、提示词泄露、内部标记、逐字复述。
- 模拟会话结束时清空消息内容；服务重启清空邀请与会话。
- MIT 许可证、架构/隐私/安全/配置/开发/发布文档、CI 和打包元数据。

### Changed

- `simulation` 配置不参与建模 run 的 `config_hash`，旧 run 保持可 resume。
- `simulate --run` 现在复用严格运行时加载器，拒绝失败/不完整 run。

### Known limitations

- 真实 evidence API 全流程尚未验收。
- 人物模拟质量尚未完成正式人工评估。
- 不内置公网 TLS/ACME；公网共享依赖隧道/反向代理。
- 客户端目前是 CLI；桌面程序、MCP adapter 未实现。
- 无法绝对阻止推断、提示注入、截图转发或模型服务商访问。

## 0.1.0 - 2026-10-23

- 初始工程基线：严格解析、预算切分、evidence 建模、whole-chat 建模、检查点/resume、13 章渲染、评估包与评分器、Mock/OpenAI-compatible Provider。
