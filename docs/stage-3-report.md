# 阶段 3 报告：配置、API 适配与 Mock

- **状态**：completed
- **实现**：CLI > PSIM_ 环境变量 > TOML > 默认值；Key 仅 `PSIM_API_KEY`；HTTPS Bearer + 非流式 chat/completions；默认不发送 tools/temperature/response_format/stream；URL、重定向、loopback 限制；错误分类；有界指数退避与 Retry-After；确定性离线 Mock 与故障注入。
- **实跑**：`doctor` 默认离线、退出码 0；Provider 测试使用 `httpx.MockTransport`，无真实网络。
- **验证**：`tests/test_config.py`、`test_providers.py` 覆盖配置优先级、Key 脱敏、URL 规则、URL 拼接、鉴权头、最小请求体、429/401/400/5xx、截断、畸形 200、重试次数与注入 sleep。
- **真实 API**：not_run（未提供 Key，未授权付费探测）
- **人物效果**：not_evaluated
- **下一阶段前置文件**：齐全。
