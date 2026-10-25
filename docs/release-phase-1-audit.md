# 发布工程第一阶段：仓库审计与基线

- 日期：2026-10-25
- 范围：只读审计、现有测试与离线/Mock 流程复跑；未修改核心代码
- 项目根：`赛博模拟计划/person-simulator`
- 环境：Windows，Python 3.12.10，Git 2.55.0.windows.3

## 结论

1. 现有工程基线可复现：`83 passed`，离线 `doctor` / `validate` / `plan` 均为退出码 0，Mock evidence 与 whole-chat 均能完成并导出。
2. 项目**没有独立 Git 历史**：当前目录嵌在另一个 Git 仓库中，项目本身零个已跟踪文件。这是公开发布的第一阻塞项。
3. 模式 C 尚未实现。现有 `simulate` 只是单次调用入口，且实测可以加载一个 `status=failed` 的伪造 run 并成功返回，不能作为第三方模拟运行时。
4. 发布工程基础缺失：无 LICENSE、CI、架构/隐私/安全/配置/开发/发布文档，打包元数据也不完整。
5. `git-dynamic-index` 本身已经实现并通过测试（`106 passed, 4 skipped`），无需重做；但它自己的 README 尚未生成实际的 `AUTO-STATUS` 区块。

## Git 基线

- 外层仓库：`<workspace>`
- 远端：`campus-beverage-miniprogram`（**不是**本项目远端）
- 分支：`release/phase8-prelaunch-validation`
- HEAD：`2bd098c`
- 本项目状态：`git ls-files -- 赛博模拟计划` 为空，`git log --all -- 赛博模拟计划` 为空，无本项目标签
- 外层工作区存在与本项目无关的未提交删除/未跟踪内容，其中 `校园饮品店小程序/` 目录当前不存在；本次未触碰
- 禁止在外层仓库执行 `git add -A`、`git reset --hard`、`git clean -fd` 或切换/重写分支

已用 `git check-ignore` 验证以下本地数据会被项目 `.gitignore` 忽略：

- `data/`
- `runs/`
- `exports/`
- `eval_runs/`
- `.venv/`
- `.pytest_cache/`
- `src/person_simulator.egg-info/`

从项目目录执行 `git add -n .` 的 dry-run 只列出代码、文档、配置示例与测试，没有列出真实聊天、运行产物或导出。但项目仍不应直接提交到外层仓库，否则会与无关的校园饮品项目历史混在一起。

`config.toml` 当前不存在，但 `.gitignore` 未明确忽略它；初始化独立仓库前应补上，避免本地配置被误提交。

## 测试与环境基线

| 项目 | 命令 | 结果 |
|---|---|---|
| 工程测试 | `.venv\Scripts\python.exe -m pytest` | 83 passed / 0 failed / 0 skipped，1.15s |
| 环境检查 | `python -m person_simulator doctor` | exit 0；mock；无 Key；未联网 |
| 输入校验 | `python -m person_simulator validate ...` | exit 0；16 条消息，8 条目标消息 |
| 离线计划 | `python -m person_simulator plan ...` | exit 0；1 个 chunk，coverage=1.0 |
| Mock evidence | `build --mode mock --strategy evidence` | exit 0；6 次请求；3,193 字符 / 7,408 字节；13 章 + system_prompt |
| Mock whole | `build --mode mock --strategy whole` | exit 0；生成 system_prompt 与 person_simulation |
| 导出 | `render --run ... --out ...` | 首次 exit 0；第二次 exit 5，拒绝覆盖 |
| 动态索引工具 | `python -m pytest -q`（在 `git-dynamic-index`） | 106 passed / 4 skipped，37.13s |

测试使用 Python 3.12.10；`pyproject.toml` 声明 `>=3.11`，但 3.11 未实测。

## 代码与架构基线

- 源码约 6,101 行，测试约 1,173 行；11 个测试文件，83 个测试函数。
- CLI 入口：`src/person_simulator/cli.py`，已有 `doctor`、`validate`、`plan`、`build`、`resume`、`render`、`simulate`、`eval prepare/score`。
- 建模路径：
  - evidence：`pipeline.py`，分片提取、证据回源、按维度 reduce、检查点、锁、配置指纹、失败不发布。
  - whole-chat：`wholechat/pipeline.py`，整段聊天一次调用；产物为模型生成的 `system_prompt.md` 与可选 `person_simulation.md`。
- 存储：`storage.py`，原子写入、单 run 锁、JSON/JSONL 读写、运行目录越界检查。
- 渲染：`rendering/markdown.py`，13 章、独立系统提示词、Mock 水印、失败保护。
- 评估：`evaluation/prepare.py`、`evaluation/score.py`，会话级留出、Mock 回答拒绝、五维评分门槛。
- Provider：`providers/openai_chat.py` 只支持 HTTPS + Bearer + 非流式 `chat/completions`；Mock 离线确定性输出；有界重试与请求上限。
- 模式 A 的默认行为目前是 `build` 的 `auto` 策略与 `mode=mock`，本轮未改变。

## 数据与隐私基线

实际存在三类本地数据：

1. 原始聊天：`data/`（已被忽略）
2. 运行数据：`runs/`，含 `messages.jsonl`、`persona.json`、`person_simulation.md`、`system_prompt.md`
3. 评估数据：`eval_runs/`（含真实留出与评估包）；导出副本在 `exports/`

这些数据都没有进入 Git，也不应进入构建产物。`manifest` 会记录输入文件的绝对路径，分享 run 目录前需要清理。

已核验的正面项：

- API Key 只从 `PSIM_API_KEY` 读取；测试覆盖了 Key 不进入 manifest、日志和鉴权错误文本。
- 真实 API 失败不会静默回退到 Mock。
- Mock 产物带 `MOCK` 标识。
- 运行目录写入有原子替换和路径越界检查。

已发现的安全缺口：

- **`simulate --run` 不校验 run 完整性/版本/状态**。实测创建一个只有 `manifest.json`（内容 `{"status":"failed"}`）和 `system_prompt.md` 的临时目录，`simulate --mode mock` 返回 exit 0 和一条回复。模式 C 不能复用该加载逻辑。
- 没有第三方会话、访问控制、调用限额、上下文窗口管理和删除接口。
- 没有输出侧的直接身份信息检查；提示词约束不能替代输出检查。
- `simulate --input` 会把完整原始聊天发送给模型；模式 C 不应使用该路径。
- 当前没有 HTTP 服务，因此尚未出现静态目录暴露；未来实现必须禁止把 run 目录作为静态文件根。

## 真实 API 与人物质量状态

- 当前没有 `config.toml`，`doctor` 显示 `api_key_present no`；本轮没有发起真实 API 调用。
- 仓库中存在一个已完成的 whole-chat 真实运行产物：13,331 条消息、605,947 字符、`deepseek-flash`，390,632 input / 1,605 output token，状态 complete。这证明历史运行存在，不等于当前代码已重新通过真实 API 验收。
- evidence 模式的真实 API 全流程仍是 `not_verified`。
- A/B：30 个 case、60 次调用已存在；`preferences_rater1.csv` 有 30 条强制选择（A=16，B=10，tie=4），但没有五维评分/多评审，`ratings_template.csv` 未完成。人物质量仍应标为 `not_evaluated`，不能用单评审强制选择替代正式验收。

## 需要修复/建设的事项

按优先级：

1. 建立独立 Git 仓库与安全的初始提交；不混入外层仓库，不提交真实数据。
2. 定义并实现模式 C 的运行时数据契约与严格加载器。
3. 实现本地受控会话、限额、超时、删除、错误映射。
4. 实现直接身份信息输出检查与提示注入/连续追问测试。
5. 补全模式 C 的单元、集成、安全测试；用合成样例建立固定回归集。
6. 补全 LICENSE、README、架构/隐私/安全/配置/开发/发布文档。
7. 补全 `pyproject` 元数据、CI、干净环境安装验证、sdist/wheel。
8. 在明确授权和预算上限下做 evidence 真实 API 探测；再做模式 A/C 可比评估。
9. 最后才创建 GitHub Release、标签与公开发布。

## 阶段计划

### 第二阶段：产品契约与设计

- 明确三个正交概念：产品模式 `archive` / `simulation`、模型调用模式 `mock` / `api`、建模策略 `whole` / `evidence`。
- 不改变现有 `build --mode mock|api` 的含义；模式 C 使用独立入口，例如 `serve`。
- 定义 `RuntimePersona` 版本化契约：run 完整性、schema/版本、source hash、target/interlocutor、system prompt hash、兼容性错误。
- 选择本地优先的访问模型：默认只绑定 `127.0.0.1`，每次启动生成访问令牌；局域网必须显式开启并带访问控制。
- 定义会话 TTL、最大轮数、输入长度、输出 token、全局/会话调用限额、删除语义。
- 定义输出检查与错误码；写明无法绝对阻止推断/提示注入/模型提供商处理的限制。

### 第三阶段：模式 C 最小实现

- 严格加载器：拒绝缺失、失败、未完成、版本不兼容、哈希不一致的 run。
- 复用现有 Provider、RequestRunner、预算与错误分类。
- 本地 HTTP 会话入口 + 最小网页聊天界面；不提供档案下载。
- 会话只保存在内存/临时目录，支持终止与删除；不把 API Key、完整档案、原始聊天写入普通日志。
- 输出检查覆盖普通问题、索取身份、提示注入、连续追问、复述原文。

### 第四阶段：测试与评估

- 单元测试：加载、版本、会话状态、权限、限额、错误映射、脱敏、删除。
- 集成测试：模式 A 回归；模式 C 加载有效 run；Mock 端到端；失败 run 拒绝；多会话隔离；正常接口无法下载档案。
- 安全测试：提示注入、身份索取、历史复述、路径穿越、静态文件暴露。
- 评估：复用现有 A/B 框架，增加合成固定样例；真实 A/B 人工评分单独记录。

### 第五阶段：CLI 与用户体验

- `serve`、`status`、`session list/delete`、`purge` 等命令；保持现有命令兼容。
- README 快速开始覆盖：环境检查、校验、预算预览、A/C 选择、建模、查看状态、模拟/导出、失败恢复、删除、费用与隐私。
- 错误信息可操作，不打印秘密或完整聊天。

### 第六阶段：开源工程化

- 许可证、README、架构/隐私/安全/配置/开发/发布文档、CHANGELOG、CONTRIBUTING。
- 补全打包元数据；在干净 venv 验证安装与测试。
- GitHub Actions：安装、质量检查、离线单元/集成测试、构建产物、产物完整性检查；不调用真实 API。
- 敏感信息扫描；确认构建产物不含真实聊天、run、API Key。

### 第七阶段：发行

- 版本号、CHANGELOG、sdist/wheel、安装验证、README 首次运行验证。
- GitHub 仓库/标签/Release 的创建与推送必须另行获得明确批准。

### 第八阶段：最终验收

- 功能、工程质量、用户体验、发布准备四组验收。
- 如实记录未完成项、已知限制和仍需用户授权的验证。

## 需要用户决策/授权

1. **动态索引与 Git**：是否批准在 `person-simulator` 内建立独立 Git 仓库，并用 `git-dynamic-index` 给 README 生成实际的 `AUTO-STATUS` 区块（推荐）；还是只交付审计报告，或改为给 `git-dynamic-index` 自身 README 加区块。
2. **许可证**：建议 MIT；需用户确认。
3. **模式 C 入口**：建议本地网页界面（默认 127.0.0.1、访问令牌、可选显式局域网）；备选是纯 CLI 交互。
4. **真实 API 验证**：后续是否授权一次有预算上限的 evidence 模式探测。
5. **公开发布**：GitHub 仓库地址、标签、Release 与推送均需在执行前单独批准。

## 当前状态

- 已完成并验证：审计、测试基线、离线/Mock 流程、动态索引工具核验。
- 已实现但未验证：模式 A 的 evidence 真实 API 路径；whole-chat 仅历史产物。
- 已发现问题：项目无 Git 历史；`simulate` 加载器不安全；模式 C 与发布工程缺失。
- 尚未开始：第二至第八阶段。
- 需要用户决策：上述第 1 项是当前阻塞；其余可在第二阶段确认。

## 审计后的已执行动作（2026-10-25）

经用户确认，已执行以下低风险动作：

- 在 `person-simulator` 内初始化独立 Git 仓库，分支 `main`；**尚无提交、未推送**。
- 在 `.gitignore` 增加 `config.toml` 与 `*.local.toml`，避免本地配置误入版本库。
- 使用 `git-dynamic-index` 在 README 末尾生成 `AUTO-STATUS` 区块；当前显示 `HEAD: none yet`、工作区 73 个未跟踪文件，这是首次提交前的真实状态。
- 脱敏 README 与历史报告中的真实人物昵称、个人绝对路径、真实评估目录名和真实聊天哈希；未删除任何运行数据。
- `git add -n .` 复核：待纳入版本控制的只有代码、文档、配置示例、测试与合成示例，不含 `data/`、`runs/`、`exports/`、`eval_runs/`、`.venv/`。

仍未执行：首次提交、动态索引 Hook 安装、推送、Release。首次提交前需要再次检查 diff 与敏感信息。
