# 开发计划（六阶段）

1. 环境检查与初始化：工程骨架、`docs/contract.md`、CLI 骨架、doctor、测试。
2. 输入、数据模型与长文本切分：严格解析、身份校验、预算、无遗漏切分、`validate`/`plan`。
3. 配置、API 适配与 Mock：配置优先级、OpenAI chat 适配器、错误分类、有界重试、离线 Mock。
4. 证据驱动的人物建模与恢复：提取/汇总、证据校验、覆盖账本、检查点与 resume。
5. 可独立使用的角色扮演 Markdown：确定性渲染、11 章节基础（阶段 8 升级为 13 章）、安全围栏、不完整不发布。
6. 端到端集成与人物模拟评估：完整 CLI、评估包与评分器、最终报告与已知限制。
7. 常见要求补齐：代码语言统计、示例情境覆盖、build_report 选择理由。
8. 输出 v2：13 章、emotion 维度、独立系统提示词 `system_prompt.md`。
9. Whole-chat：整段原文直接生成 system prompt/人物材料；`--strategy whole|evidence`、`simulate`、A/B 接口。

依赖顺序：`1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9`。

工程可用、API 可用、模拟可用是三种不同状态：Mock 全流程通过只证明管线可运行，不等于真实人物相似度；真实 API 未实际调用时保持 `not_verified`。
