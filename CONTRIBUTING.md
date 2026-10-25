# Contributing

感谢参与。这个项目处理真实人物聊天，隐私和证据约束优先于功能数量。

## 开发环境

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest
```

要求 Python 3.11+。主要验证环境是 Windows + Python 3.12.10。

## 提交前

- 新功能/修复有测试，并且测试先在缺少实现时失败。
- 不删除测试、不降低断言、不把 Mock 结果当真实质量证据。
- 不提交真实聊天、人物档案、API Key、邀请文件、`config.toml`、`.env`、run/export/eval 数据。
- 不在测试输出中打印聊天正文或密钥。
- 更新相关文档：`README.md`、`docs/contract.md`、`docs/configuration.md`、`docs/privacy.md`、`docs/security.md`。
- 运行完整 `pytest`，并检查 `git diff --cached`。

## 代码约定

- 跟随现有模块结构、`StrictModel`、`PersonSimError` 和错误码。
- 复用 `RuntimePersona`、`ChatService`、`OutputGuard`，不要新造一套模型调用。
- 新增配置项要同步示例、文档、测试和 `config_hash` 兼容性。
- 新增输出规则要有正例和反例，避免把正常对话全部误杀。

## 隐私规则

- 只能在获得授权的前提下使用他人聊天记录。
- 不把真实数据放进 Issue、PR、CI、截图或测试夹具。
- 发现问题时先写合成复现；需要真实数据验证时，在本地进行并只报告聚合结果。

## 安全报告

不要公开粘贴真实聊天、人物档案、Key 或邀请令牌。仓库建立后补充私下安全联系方式；在此之前通过维护者可用的私密渠道报告。

## Pull Request

- 说明变更目的、影响范围、测试命令和结果。
- 涉及隐私/权限/网络边界时，明确写出威胁模型和仍然存在的限制。
- 不承诺“绝对隐私”“无法推断”等超出实现能力的保证。

## 许可证

贡献即同意以 MIT 许可证发布。
