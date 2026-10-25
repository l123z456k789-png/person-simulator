# 阶段 4 报告：证据驱动建模与恢复

- **状态**：completed
- **实现**：extract/reduce 提示词与严格 JSON；证据回源校验；目标发言要求；reported_fact 来源校验；part 处理去向；分层汇总与预算批次；run 指纹、原子检查点、互斥锁、损坏缓存重算、请求上限、截断/溢出拆分、context 超限先降 context 再拆 core；`resume`。
- **实跑**：180 条合成消息、`chunk_input_budget=600` → 180 个片段；中途汇总层级上限失败后，`resume` 复用检查点并完成，导出 `runs/run-20261023-180628-a-73c5b8/person_simulation.md`。
- **验证**：`test_pipeline.py` 覆盖 Mock A/B、失败不留正式文件、恢复、render 不覆盖、坏证据拒绝、聊天内提示注入不执行。
- **真实 API**：not_run
- **人物效果**：not_evaluated
- **下一阶段前置文件**：齐全。
