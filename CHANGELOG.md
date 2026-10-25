# Changelog

## 0.2.0 - 2026-10-25 (unreleased)

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
