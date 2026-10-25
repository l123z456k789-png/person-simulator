# 阶段 10：A/B 人物模拟对照评估

- **状态**：生成完成；人工盲评未完成
- **范围**：30 题留出评估，A=system_prompt.md，B=完整训练聊天
- **调用**：60 次（30×A/B），模型 `deepseek-flash`，thinking disabled，max_output 6144
- **成本**：**$0.037697**；B 的 30 次调用全部命中 390,144 token 缓存
- **数据**：训练/留出 ID 重叠 0；非历史题全部来自留出；替换 3 道问题题（0001/0002 媒体占位符、0017 错位）
- **结果**：
  - B 在 0025 事实召回、0028 未知承认、0024 任务理解上更好
  - A 在 0020/0021/0022/0023/0027 的部分短句/语气题更好
  - 两者都在 0029/0030 编造未知历史；B 0030 的编造更长、更具体
  - 未发现 target/interlocutor 身份互换
  - 仍有题面/参考对齐问题，不能据此宣布整体胜负或统计显著
- **人工评分**：`ratings_template.csv` 60 行留空；尚未有了解目标人物的评审者评分
- **下一单因素**：修评估题上下文完整性，再重跑；不是改人物提示词
- **产物**：`eval_runs/<local-real>/ab_full/`（calls、blind_pairs、blind_key、ratings_template、evaluation_report、run_summary）
- **真实 API**：DeepSeek whole-chat 已验证；证据模式未验证
