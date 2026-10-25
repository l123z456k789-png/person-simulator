# 阶段 2 报告：输入、数据模型与切分

- **状态**：completed
- **实现**：严格 UTF-8/BOM 解析、全角冒号、ISO8601 时间、两空格续行、正文伪头、行号错误；标签/target 精确校验；稳定 Message/Part/Chunk ID；UTF-8 字节×1.25+512 预算；会话优先切分；超长消息无损切片；core 覆盖校验；`validate`、`plan`。
- **实跑**：`validate --input examples\sample_chat.txt --target A` → 0；`plan ...` → 0，16 条消息、1 个片段、coverage 1.0000。
- **验证**：`tests/test_parser.py`、`test_identity.py`、`test_budget.py`、`test_chunking.py` 覆盖 BOM、中文/emoji、续行、伪头、非法时间、超长消息、极小预算、确定性 ID、重组一致性。
- **限制**：预算是保守启发式，不是精确 tokenizer；无时间时只能表达消息顺序。
- **真实 API**：not_run
- **人物效果**：not_evaluated
- **下一阶段前置文件**：齐全。
