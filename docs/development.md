# 开发

## 环境

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest
```

要求 Python 3.11+；当前主要验证环境是 Windows + Python 3.12.10。

## 测试纪律

- 新功能先写失败测试，看它因缺少功能而失败，再写最小实现。
- 修 bug 先写复现测试；不得删除测试或降低断言来制造通过。
- 测试只能用合成聊天、假姓名/电话、`tmp_path`；不得使用真实聊天、真实 API Key 或个人绝对路径。
- CI 不调用真实模型 API。
- 测试结束时不得留下 `runs/`、`invites`、进程或监听端口。

## 目录

```text
src/person_simulator/
  parser.py chunking.py budget.py config.py storage.py models.py errors.py
  pipeline.py privacy.py progress.py runs.py
  wholechat/
  modeling/
  providers/
  rendering/
  evaluation/
  runtime/        # 模式 C：加载、邀请、会话、输出检查、服务、客户端
  server/         # HTTP + 管理监听器 + 浏览器 UI
tests/
docs/
```

## 代码风格

- 跟随现有模块的命名、错误类型和 Pydantic `StrictModel` 约定。
- 所有用户可见错误使用 `PersonSimError` 子类，带稳定 `error_code` 和安全 hint。
- 不把密钥、完整提示词或聊天正文写入异常/日志。
- 新增配置项要同时更新 `config.example.toml`、`docs/configuration.md` 和测试。
- 新增输出检查规则要补正例与反例，避免误伤正常对话。

## 模式 C 的边界

- 公开监听器不注册 `/admin/*`；管理员只在本机独立端口。
- 不在公开端口提供 run 文件、`persona.json`、`system_prompt.md`。
- 新入口必须复用 `RuntimePersona`、`ChatService`、`OutputGuard`，不要复制一套模型调用。
- 任何“删除/结束”行为都要清空消息内容，而不是只改状态。

## CI

`.github/workflows/ci.yml` 在 Windows/Linux + Python 3.11/3.12 上安装、测试，并在 Linux 上构建 sdist/wheel、检查产物不含私有数据。CI 不读取真实配置。

## 发布前

见 `docs/release.md`。发布、打标签、推送和创建 GitHub Release 必须获得明确批准。
