# 阶段 8 报告：输出 v2（13 章 + 独立系统提示词）

- **状态**：completed
- **修改文件**：`models.py`、`prompts/extract.txt`、`providers/mock.py`、`modeling/persona.py`、`pipeline.py`、`rendering/markdown.py`、`cli.py`、`tests/test_pipeline.py`、`docs/output-format.md`、`docs/contract.md`、`README.md`、`docs/final-report.md`。
- **实现**：
  1. `Persona` 增加 `emotion` 维度；Mock 可从“累/烦/生气/开心/谢谢”等表面词生成演示观察；提示词维度同步。
  2. `person_simulation.md` 改为固定 13 章，包含情绪/冲突、情境行为、使用说明、可直接使用的系统提示词。
  3. 生成独立 `system_prompt.md`，内容自包含，含表达统计、语言/思维/情绪/行为/关系规则、原话示例和启动指令。
  4. `render --run --out` 同时导出两个文件，任一目标已存在则整体拒绝覆盖。
  5. 示例按日常/亲近/冲突/拒绝/修复优先覆盖。
- **实跑**：`python -m pytest -q` → 75 passed；`build ... --mode mock` 成功，13 章、3193 字符、`system_prompt.md` 475 字符。
- **真实数据压测**：15,508 条消息、604 会话、624 片段；Mock 产物 13 章、10,578 字符、`system_prompt.md` 799 字符；详见 `docs/real-data-preflight.md`。
- **限制**：Mock 的系统提示词很短，只证明结构与链路；真实 API 的丰富度取决于材料与模型。
- **真实 API**：not_run
- **人物效果**：not_evaluated
