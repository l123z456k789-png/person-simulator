# 阶段 7 报告：共同要求补齐

- **状态**：completed
- **修改文件**：`src/person_simulator/textstats.py`、`rendering/markdown.py`、`modeling/persona.py`、`pipeline.py`、`tests/test_textstats_examples.py`、`tests/test_pipeline.py`、`docs/output-format.md`、`docs/plan.md`。
- **补齐内容**：
  1. 代码计算的目标消息统计：条数、平均/中位/最短/最长、多行、问号、感叹号、emoji、标点率；分母明确。
  2. 高频字符二元组，明确标注“仅表面统计”。
  3. 典型对话按日常/亲近/冲突/拒绝/修复情境优先覆盖，最多 12 段，按原顺序输出。
  4. build_report 增加语言统计、示例选择理由、未保留历史范围说明。
- **实跑**：`python -m pytest -q` → 73 passed。
- **真实 API**：not_run
- **人物效果**：not_evaluated
