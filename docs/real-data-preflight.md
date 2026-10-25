# 真实数据预检（本地，未调用真实 API）

## 来源与转换

- 来源：用户提供的微信 Markdown 导出（本地路径不写入报告）。
- 来源 SHA256：`<redacted>`
- 转换器：`tools/convert_wechat_md.py`（仅针对该导出格式的本地助手，不是通用微信解析器）
- 输出：`data/<local-chat>.txt`（已加入 `.gitignore`）
- 输出 SHA256：`<redacted>`

## 结构统计（不含正文）

- 原始消息：15,511
- 有效双人消息：15,508
- TARGET：6,825
- OTHER：8,683
- 跳过系统消息：3（不计入分析，已记录）
- 会话：604
- 多行消息：885
- 最长单条：1,720 字符
- 时间范围：2025-06-10 至 2026-02-16
- 格式校验：通过
- 覆盖率：1.0000

## 切分计划（默认预算）

- 片段：624
- map 调用下界：624（不含汇总、修复、重试）
- 默认 `max_requests_per_run=500` **低于**该下界；真实运行必须显式提高 `--max-requests`，否则会在 500 次后保留检查点退出。
- 可通过提高 `chunk_input_budget`（在模型上下文允许时）减少片段数，但必须重新跑 `plan`。

## Mock 压测

- 命令：`build ... --target TARGET --mode mock --out runs/real-mock2 --max-requests 3000`
- 结果：13 章、10,578 字符；`system_prompt.md` 799 字符；Mock 请求 1,696 次。
- 产物：`runs/real-mock2/run-20261023-185651-target-cff404/`
- **状态：Mock 合成演示，不代表真实人物。**

## 真实 API

- 未调用：没有用户 API 配置与付费授权。
- 状态：`not_verified`
- 人物效果：`not_evaluated`
- 运行前必须确认：target 是「TARGET」还是「OTHER」、模型/上下文、预算上限。

## 评估包（已生成）

- 目录：`eval_runs/<local-real>/`
- 训练会话：483；留出会话：121
- 训练消息：13,331；留出消息：2,177
- 案例：30 个，五维各 6；unsupported：0
- 训练文件：`eval_runs/<local-real>/train_chat.txt`（823,139 字节）
- 真实建模必须用 `train_chat.txt`，不能用全量数据后再评留出。
- 训练集 `plan`：500 个片段、map 下界 500；实际汇总/重试会更多，建议 `--max-requests 2000` 起步。
