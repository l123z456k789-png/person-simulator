# 阶段 6 报告：集成与评估

- **状态**：completed（工程与 Mock）；真实 API / 真实人物效果未验收
- **实现**：完整 CLI `doctor/validate/plan/build/resume/render/eval prepare/eval score`；退出码 0/2/3/4/5/130；README；评估包按完整会话留出 20%，30 个槽位（五维各 6）；评分器校验 case/persona_hash/重复/范围/来源，拒绝 Mock 回答，输出 quality_report。
- **实跑**：全量 `pytest -q` → 71 passed；A/B Mock build 成功；180 条长文本 180 片段并恢复成功；`eval prepare --input runs\manual\long_chat.txt --target A --out eval_runs\demo` → 30 案例（4 个 unsupported）。
- **通过/失败/跳过**：71 passed / 0 failed / 0 skipped。
- **真实 API**：not_verified（无 Key、未授权真实调用）
- **真实模拟质量**：not_evaluated（未采集人工回答与评分）
- **已知限制**：Mock 只证明管线；API 仅支持 HTTPS Bearer 非流式 chat/completions；评分为人工主观判断；无 GUI/解析器/实时聊天。
