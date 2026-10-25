# 人物模拟评测

这份文档说明当前仓库里**真实存在**的评测工具、数据格式和人工步骤。它不试图证明人物模拟已经“像本人”；它只规定怎样采集证据、怎样打分，以及哪些结论现在还不能下。

工程测试回答的是“代码有没有按契约工作”。人物模拟质量回答的是另一个问题：在没见过的对话里，这个模拟是否仍然保留了这个人的语言习惯、判断方式、关系边界和历史事实。两者不能互相替代。

当前项目状态仍然是：

- 工程测试：通过。
- 人物模拟质量：`not_evaluated`。
- 现有 30 题 A/B 记录：只有探索性观察和一次单评审者偏好选择，没有完成可靠的多评审五维评分。

## 1. 复用什么

评测基础已经在仓库里，不需要另起一套：

| 组件 | 位置 | 作用 |
|---|---|---|
| 评估包生成 | `person_simulator/evaluation/prepare.py`、`person-sim eval prepare` | 按完整会话留出，生成 30 个题目槽位 |
| 评分汇总 | `person_simulator/evaluation/score.py`、`person-sim eval score` | 读取人工回答与评分，生成质量报告 |
| 评估测试 | `tests/test_evaluation.py` | 验证留出、模板、评分器与拒绝 Mock 的边界 |
| 历史 A/B 摘要 | `docs/stage-10-ab-eval.md` | 记录 30 题、60 次调用的探索性实验 |
| 当前指南 | 评估包内的 `evaluation_guide.md` | 给评审者的就地说明 |

评估包和评分报告写入 `eval_runs/`，该目录被 `.gitignore` 排除。真实聊天、真实回答和评分不应提交到公开仓库。

## 2. 五维与标记

`eval prepare` 生成五类主维度，每类 6 个槽位，共 30 个：

| 维度 | 评什么 | 参考从哪里来 |
|---|---|---|
| `language` | 用词、句长、标点、emoji、语气和节奏 | 留出会话中目标的真实下一条回复 |
| `behavior` | 面对同一情境时的行为与决策方式 | 留出会话中的上下文与目标回复 |
| `attitude` | 对另一位参与者的态度、亲疏和互动方式 | 留出会话中的上下文与目标回复 |
| `novel_situation` | 没在聊天里出现过的新情境下是否仍然一致 | 6 个固定的假设情境，无唯一答案 |
| `history_accuracy` | 聊天中已有事实是否准确；未知历史是否承认不知道 | 3 个训练可见事实 + 3 个材料未提供的未知问题 |

评分时还要单独标记失败类型，而不是只给一个总分：

| 标记 | 含义 |
|---|---|
| `identity_error` | 认错人、把自己当成对方、角色混淆 |
| `fabricated_history` | 编造聊天中不存在的具体姓名、日期、事件或原话 |
| `factual_error` | 与聊天中已经出现的事实直接冲突 |
| `unsupported_inference` | 没有证据却作确定断言，或把单次行为推广成稳定人格 |
| `unsupported_history` | 这道题本身缺少可评分证据；跳过该题，并让数据完整性检查失败 |

`unsupported_history` 不是“这题太难所以不评”。它表示题目或参考本身不成立。出现它时，应该回到 `prepare` 修正留出或题目，而不是把跳过当成通过。

## 3. 数据格式

### 3.1 目录

```text
eval_runs/<name>/
  train_chat.txt              # 只用这部分建模，避免留出泄漏
  holdout.jsonl               # 留出消息，不参与建模
  cases.jsonl                 # 30 个题目槽位
  reviewer_references.json    # 参考答案/说明，只给评审者
  responses.template.jsonl    # 受支持题 × 2 次重复的空回答模板
  ratings.template.csv        # 评分表头；只为受支持题填写
  split_manifest.json         # 会话划分、哈希、case_format
  evaluation_guide.md         # 就地指南
  quality_report.json         # eval score 生成
  quality_report.md           # eval score 生成
```

`train_chat.txt` 的标签必须和原聊天一致。如果原聊天使用 `小明`/`小红`，`prepare`、`build` 都要带相同的 `--speaker-a`/`--speaker-b`/`--target`，不能只写默认 `A`/`B`。

`split_manifest.json` 里的 `case_format` 当前是 `context-v2`。它表示 `language`、`behavior`、`attitude` 题面已经包含该题依赖的最近上下文，而不是只给最后一句。

### 3.2 `cases.jsonl`

每行一个题目槽位，主要字段：

```json
{
  "case_id": "case-0001",
  "slot": 1,
  "primary_dimension": "language",
  "status": "candidate",
  "prompt": "以下是A与B的一段聊天记录：...",
  "context_messages": [
    {"message_id": "m000001", "speaker": "A", "text": "...", "timestamp": null}
  ],
  "source_message_ids": ["m000001", "m000002"],
  "reference_message_ids": ["m000002"],
  "needs_review": true
}
```

- `status=candidate` 才是可评分的题。
- `status=unsupported` 表示留出不足，题目不计分；评估包仍保留 30 个槽位，便于看出缺口。
- `prompt` 是给被测模型的文本。
- `context_messages` 是给评审者理解题目的上下文；`context-v2` 已把它写入 `prompt`。
- 参考答案不在 `cases.jsonl` 中，而在 `reviewer_references.json`，避免被测模型看到答案。

### 3.3 `responses.jsonl`

从 `responses.template.jsonl` 复制并填写。模板只包含 `status=candidate` 的题；`unsupported` 槽位没有可采集的回答，跳过它们。每行是一次真实采集：

```json
{
  "case_id": "case-0001",
  "repeat": 1,
  "platform": "网页版 AI 名称/版本",
  "model_visible_name": "界面显示的名称",
  "date": "2026-10-25",
  "persona_hash": "<实际上传文件的 SHA256>",
  "response": "模型原始回答",
  "source": "human_collected"
}
```

规则：

- `source` 必须是 `human_collected`。`mock` 会被评分器拒绝。
- 同一评估包只能使用一个 `persona_hash`。如果换了人物材料，重新建包或重新采集。
- 同一题至少两个 `repeat`；推荐在全新会话中重复，避免上下文污染。
- `response` 原样保存，不替模型润色，不删掉“像 AI”的部分；这些正是评估对象。
- 不要把真实聊天正文、姓名、联系方式写进 `platform` 或 `notes`。

### 3.4 `ratings.csv`

从 `ratings.template.csv` 复制。每行是“一位评审对一道受支持题的主维度评分”：

```csv
case_id,run_id,rater,dimension,score,unsupported_history,identity_error,fabricated_history,factual_error,unsupported_inference,notes
case-0001,run-...,rater1,language,4,false,false,false,false,false,
```

规则：

- `dimension` 必须等于该题的 `primary_dimension`，不能把一道题重复算进两个维度。
- `score` 为 1—5；1 表示明显违背证据，5 表示符合可见习惯且无明显冲突。
- 两位评审就写两行（相同 `case_id`，不同 `rater`）。不要合并成一个平均分后只保留一行。
- 任何一个失败标记为 true，都会让 `gate_passed` 失败；这是有意的，不用总分掩盖具体错误。

## 4. 运行流程

### 第 1 步：准备私有评估包

在本地准备一份有足够会话的 UTF-8 双人聊天，不要把真实文件提交到仓库。

```powershell
person-sim eval prepare `
  --input data\chat.txt `
  --speaker-a 小明 `
  --speaker-b 小红 `
  --target 小明 `
  --out eval_runs\my-person
```

要求：

- 至少 5 个可分会话；不足时 `prepare` 返回 `insufficient_data`，不生成 30 题，也不会随机打散单条消息来凑数。
- 会话按时间间隔或空白分隔识别；留出的是最后约 20% 的完整会话。
- 输出目录必须为空；不覆盖已有评估包。

### 第 2 步：只用 `train_chat.txt` 建模

```powershell
person-sim build `
  --input eval_runs\my-person\train_chat.txt `
  --speaker-a 小明 `
  --speaker-b 小红 `
  --target 小明 `
  --mode api `
  --strategy auto `
  --out runs
```

- 绝不能用完整聊天建模，否则留出题已经泄漏。
- `--strategy auto` 会按上下文预算选择 `whole` 或 `evidence`；记录终端打印的选择。
- 如果只想做 30—50 条 pilot，可以加 `--limit-messages`，但此时不能把结果当成完整评估。
- 评估阶段建议固定模型、平台、参数和材料版本；不要中途更换。

记录实际用于对话的文件哈希：

```powershell
Get-FileHash runs\<run-id>\person_simulation.md -Algorithm SHA256
# 或
Get-FileHash runs\<run-id>\system_prompt.md -Algorithm SHA256
```

把哈希填入每条 response 的 `persona_hash`。如果 `whole` run 没有 `person_simulation.md`，用 `system_prompt.md` 作为上传材料，并在 `notes` 中写明。

### 第 3 步：采集回答

1. 打开网页版 AI 的新会话。
2. 上传人物材料（`person_simulation.md`；没有则用 `system_prompt.md`）。
3. 按 `cases.jsonl` 的 `case_id` 顺序逐题发送 `prompt`。
4. 原样记录回答；每题至少两次，最好每次新会话。
5. 填写 `responses.jsonl`，不要用 Mock 或自己代写回答。

人工步骤无法自动化：平台 UI、模型版本、会话状态和上传方式都会影响结果。把这些写进 `platform`、`model_visible_name`、`date` 和备注。

### 第 4 步：人工评分

至少找一位了解原人物的人；推荐两位独立评审。

- 评审者看 `reviewer_references.json` 和回答，不看被测模型的自我评价。
- 按 `ratings.template.csv` 逐题给 1—5 分，并勾选失败标记。
- 两位评审独立完成后，再比较分歧；不要先讨论再打分。
- 如果题目本身不可评分，标 `unsupported_history`，并记录原因；不要为了凑满 30 题强行给分。

人工步骤必须明确标记为人工完成。脚本和自动化测试不能代替这一步。

### 第 5 步：汇总

```powershell
person-sim eval score `
  --bundle eval_runs\my-person `
  --responses eval_runs\my-person\responses.jsonl `
  --ratings eval_runs\my-person\ratings.csv
```

输出：

- `quality_report.json`：机器可读的完整报告。
- `quality_report.md`：人读摘要。

评分器会检查：

- 所有 response 都是 `human_collected`；
- 只使用一个 `persona_hash`；
- 题目与评分维度一致；
- 每道受支持题目都有评分，且至少两次回答；
- 标记、分布、评审分歧和缺失情况。

## 5. 结果怎么读

先看两个不同的字段：

- `status`：数据是否足够。`evaluated` 只表示真实采集、人工评分和覆盖达到最低门槛。
- `gate_passed`：本项目设定的质量门槛是否通过。它要求五个维度均值至少 4、每维至少 6 条评分、所有受支持题都已评分、每题至少两次回答，并且没有身份错误、编造历史、事实错误或无依据推断。

`status=evaluated` 且 `gate_passed=false` 是正常结果，表示“数据够了，但质量没达到门槛”。不要把前者读成“通过”。

报告中的 `dimensions` 包含每个维度的均值、评分数量、已评题数、缺失题数和分布。`disagreements` 列出评审分差超过 1 分的题；这些题应回看原始回答和参考，而不是直接平均掉。

当前评分器不会自动把 `quality_status` 写回 run 的 `manifest.json`。这是有意的：一次评分只生成一份报告，是否把它当作某个 run 的正式质量结论，需要维护者明确判断。当前项目状态仍是 `not_evaluated`。

## 6. 历史 A/B 实验

仓库外的本地目录曾做过一次 30 题、60 次调用的 A/B：

- A = `system_prompt.md`（压缩人物提示词）
- B = 完整训练聊天（约 390k token）
- 模型：`deepseek-flash`，thinking disabled，output limit 6144
- 成本：约 `$0.037697`
- 30 题 × A/B 各一次生成

结果只能作为探索性观察：

- 一位了解目标人物的评审做了偏好选择：A 更像 16 题，B 更像 10 题，都不像 4 题。
- 没有完成五维 1—5 分评分；没有第二位评审；每题只生成一次；没有统计检验。
- 部分题面依赖缺失上下文，参考回复与题面不完全对齐。
- 因此不能宣布 A 或 B 整体更好，也不能把 16:10 当成质量结论。

本地原始产物在 `eval_runs/`，该目录被忽略；仓库只保留 `docs/stage-10-ab-eval.md` 的聚合摘要。不要把这些记录包装成“已验证效果”。

如果下一轮要做可解释的 A/B：

1. 使用同一份 `cases.jsonl`，分别对 A/B 采集 responses；不要给评审者看选项来源。
2. 至少 2 位评审、每题 2 次生成；随机化 A/B 显示顺序。
3. 用 `eval score` 分别汇总 A 和 B 的五维报告；不要合并成一个 `persona_hash`。
4. 另做偏好选择，并保留盲键；偏好结果和五维结果分开展示。
5. 说明样本量、评审者背景、平台、模型版本和题面质量问题。

## 7. 局限

- 留出按最后约 20% 的完整会话切分，能降低泄漏，但会混入时间漂移：人物后期变化可能被误判为泛化失败。
- 30 个槽位是最低工程基线，不是统计功效足够的样本。
- 参考回复是真实历史中的一条消息，不等于该情境下唯一正确答案。
- `context-v2` 只保证题面包含最近上下文，不保证包含全部关系史。
- 语言、行为、态度、新情境和历史五维仍有主观性；一位评审的结果不能代表普遍判断。
- 没有自动语义评分器、没有 LLM-as-judge、没有统计显著性检验。
- 平台模型版本、系统提示词注入方式、网页 UI 变化都会影响结果；`persona_hash` 只能锁定材料，不能锁定平台。
- 输出安全检查通过、工程测试通过、Mock 结果或合成评分，都不等于人物模拟质量。
- 未知历史题只能检验“是否承认不知道”，不能证明模型在所有未知事实上都诚实。
- 报告中的聚合数字可以被误读；发布时不要只给一个均分，至少同时给出样本、缺失、标记和评审分歧。

## 8. 人工完成清单

- [ ] 使用自己有权处理的聊天记录。
- [ ] 用 `train_chat.txt` 建模，未用完整聊天。
- [ ] 记录实际材料 SHA256。
- [ ] 所有受支持题目逐题采集，至少两次，使用新会话；跳过 unsupported 槽位。
- [ ] 所有 response 都是 `human_collected`。
- [ ] 至少一位了解原人物的评审完成 1—5 分和失败标记。
- [ ] 第二位评审独立完成（如果有）。
- [ ] 检查 `quality_report.md` 的 `status`、`gate_passed`、缺失和标记。
- [ ] 把报告保存在 `eval_runs/`，不要把真实回答或聊天提交到公开仓库。
- [ ] 在 README/发布说明中继续写 `not_evaluated`，直到有足够证据并明确更新。
