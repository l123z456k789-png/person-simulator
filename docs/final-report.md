# 最终报告

## 结论

第一版工程、Mock 主路径和 Whole-chat 真实调用完成。人物模拟质量**未验收**。

- **PROJECT_ROOT**：`<PROJECT_ROOT>`
- **工程测试**：83 passed / 0 failed / 0 skipped（`.venv\Scripts\python.exe -m pytest -q`）
- **Whole-chat**：DeepSeek `deepseek-flash` 已实跑 13,331 条训练消息；system prompt 1,592 字符；实际 390,632 input / 1,605 output token；成本约 $0.06。
- **A/B**：30 题、60 次调用完成；总成本 $0.037697；B 缓存 30/30。单评审偏好盲评为 A 16 / B 10 / 都不像 4，但未完成五维人工评分、没有第二位评审或重复生成，不能宣布整体胜负；题面/参考对齐仍有问题。
- **Mock E2E**：通过。A/B 双目标、长文本多层汇总、失败后 resume、render 均已实跑。
- **真实 API**：Whole-chat 已用 DeepSeek `deepseek-flash` 实跑；evidence 模式真实 API 未验证。
- **真实模拟质量**：not_evaluated。已采集 30 题 A/B 真实回答，但未完成人工五维评分。

## 实际产物

- A 目标：`runs/run-20261023-180612-a-16e2b3/person_simulation.md`（2235 字符 / 5129 字节）
- B 目标：`runs/run-20261023-180612-b-16e2b3/person_simulation.md`（2031 字符 / 4719 字节）
- 输出 v2：`runs/v2-final/run-20261023-184037-a-16e2b3/person_simulation.md`（3193 字符，13 章）+ `system_prompt.md`（475 字符）
- 长文本 v2：`runs/v2-long/run-20261023-184126-a-73c5b8/person_simulation.md`（12981 字符）
- 长文本：`runs/run-20261023-180628-a-73c5b8/person_simulation.md`（180 条消息、180 个片段，中途失败后 resume 完成）
- Whole-chat pilot：`runs/pilot/whole-run-20261024-160516-target-31a330/`（50 条消息）
- Whole-chat 全量：`runs/whole-full/whole-run-20261024-160627-target-31a330/`（13,331 条训练消息；`system_prompt.md` 1,592 字符，`person_simulation.md` 875 字符）
- 导出副本：`exports/demo-a/person_simulation.md`
- 评估包：`eval_runs/demo/`、`eval_runs/<local-real>/`（30 个槽位，五维各 6；真实留出 0 unsupported）
- A/B 30 题：`eval_runs/<local-real>/ab_full/`（60 次调用、$0.037697、匿名评分表待填）

## 已验证能力

- UTF-8/BOM、全角冒号、ISO8601、两空格续行、正文伪头、行号错误。
- 精确 target 选择；A/B 身份隔离；不按顺序猜人。
- 超长消息无损切片；每条消息 core 区间连续覆盖；coverage=1.0。
- 配置优先级、Key 脱敏、URL/loopback 限制、非流式 chat/completions。
- 401/429/5xx/超时/上下文超限/截断/畸形响应分类；有界重试。
- 证据 ID/偏移/角色/原文切片校验；reported_fact 来源；伪证据拒绝。
- 检查点、锁、run 指纹、损坏缓存重算、请求上限、resume。
- 13 章 Markdown、独立 `system_prompt.md`、Mock 水印、失败不发布、render 不覆盖。
- Whole-chat 整段原文生成、`--strategy whole|evidence`、`simulate` 压缩/原文两种入口。
- 评估按完整会话留出；评分器拒绝 Mock 回答。

## 未满足或未验证

1. evidence 模式真实 API 协议与费用路径：not_verified。
2. 真实人物相似度：not_evaluated；A/B 只做了单评审偏好选择，未完成五维评分、第二评审和重复生成。
3. 语义解释正确性：程序只做结构与引用校验，语义质量仍依赖人工评估。
4. 超长导出的 compact 版本：未实现；主文件超 32000 字符时只记录、不截断。
5. 非 OpenAI-compatible 服务：明确 unsupported，需新 adapter。
6. Whole-chat 超 1M 上下文时的窗口化降级：未实现；目前用 `--limit-messages` 或 evidence 模式。

## 复现命令

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m person_simulator build --input examples\sample_chat.txt --target A --mode mock --out runs
.\.venv\Scripts\python.exe -m person_simulator build --input eval_runs\<local-real>\train_chat.txt --speaker-a "TARGET" --speaker-b "OTHER" --target "TARGET" --mode api --config config.toml --strategy whole --out runs
.\.venv\Scripts\python.exe -m person_simulator simulate --run runs\<whole-run> --message "在吗？" --mode api --config config.toml
.\.venv\Scripts\python.exe -m person_simulator simulate --input eval_runs\<local-real>\train_chat.txt --speaker-a "TARGET" --speaker-b "OTHER" --target "TARGET" --message "在吗？" --mode api --config config.toml
.\.venv\Scripts\python.exe -m person_simulator eval prepare --input eval_runs\<local-real>\train_chat.txt --target "TARGET" --out eval_runs\<local-real>
```

## 真实 API 启用方式

```powershell
$env:PSIM_API_KEY = "YOUR_API_KEY"
python -m person_simulator build --input data\chat.txt --target A --mode api --config config.toml --out runs
```

没有真实 Key 与明确授权时，不得声称 API 已验收，也不得用 Mock 产物宣称人物效果达标。
