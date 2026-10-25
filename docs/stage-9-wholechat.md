# 阶段 9：Whole-chat 极简模拟框架

- **状态**：completed（工程与真实 API 全流程）；盲评未完成
- **目标**：用长上下文模型直接读原始聊天，减少 chunk→map→reduce 加工层，提高模拟效果。

## 复用

- `parser.py` / `wechat` 转换器
- `config.py`、`providers/openai_chat.py`、`retry.py`
- `storage.py`（RunStore、原子写、锁）
- `evaluation/`（30 题评估包与评分器）
- `render` 的系统提示词思路

## 新增

- `src/person_simulator/wholechat/transcript.py`：带消息 ID 的序列化、校准 token 估算
- `wholechat/prompts.py`：整段分析提示词、原文驱动模拟提示词
- `wholechat/pipeline.py`：整段 build、`simulate`（压缩/原文）、预算检查
- `wholechat/verify.py`：标签、消息引用、长度、Mock 标识、外部依赖检查
- CLI：`build --strategy auto|whole|evidence`、`--limit-messages`、`simulate`
- `disable_thinking` 配置（DeepSeek 默认思考模式会耗尽输出预算）

## 实跑

### Pilot（50 条）

- 模型：`deepseek-flash`，关闭 thinking
- 输入：2,011 prompt tokens / 1,024 completion tokens
- system prompt：1,105 字符
- person_simulation：423 字符
- 成本：约 $0.001

### 完整训练集

- 输入：`eval_runs/<local-real>/train_chat.txt`
- 消息：13,331 条
- 估算输入：605,948 token（保守校准；实际 390,632）
- 实际：390,632 prompt / 1,605 completion
- 产物：`runs/whole-full/whole-run-20261024-160627-target-31a330/`
  - `system_prompt.md`：1,592 字符
  - `person_simulation.md`：875 字符
  - `build_report.md`
  - `manifest.json`
- 成本：约 $0.06（off-peak，$0.15/$0.60 每百万 token）
- 没有把原始聊天写入普通日志或 transcript 文件

### A/B 最小探测

同一句新消息“在吗？今天好累，不想画图了。”：

- A（system prompt）：短回复，保留“在的/画啥图/不想画就不画”的口气
- B（完整原文）：回复更长，带“累了就歇着/别硬撑”的安抚
- **未做盲评，不能据此判断 A 或 B 更好**

## 测试

- `python -m pytest -q` → **83 passed**
- 新增 `tests/test_wholechat.py`：序列化、标签解析、引用校验、Mock build、真实风格 fake client、simulate
- 现有 evidence 模式测试全部保留

## 兼容性

- `--strategy evidence` 仍走旧的 chunk→map→reduce 证据流水线。
- `--strategy auto` 根据校准后的 transcript 预算与 `context_window` 选择；不是只看标称上下文。
- `--strategy whole` 强制整段；超预算时明确报错，不静默截断。
- 降级手段：`--limit-messages` 做 pilot；超预算用 `evidence` 模式。窗口化压缩尚未实现。

## 风险与未完成

- Whole-chat 输出是模型自由组织，**没有逐条证据账本、coverage=1、逐特征 offset**。
- 系统提示词可能包含聊天中的敏感事实；本地文件需自行保管。
- 真实 API 仅验证了 DeepSeek `deepseek-flash`；其他 provider 未验证。
- 30 题 A/B 盲评、重复生成、人工评分尚未完成。
- 人物效果：`not_evaluated`。
