# 发布流程

## 版本

- 当前开发版本：`0.2.0`（模式 C 已实现，尚未正式发版）。
- 发布 `0.2.0` 前完成验收；`__version__`、`pyproject.toml`、`CHANGELOG.md` 已对齐。
- `resume` 接受 `0.1.0` 与 `0.2.0` 的旧 run 指纹，避免升级后无法续跑。
- 版本号采用语义化版本；破坏 CLI/数据契约时必须升主版本并写迁移说明。

## 发布前检查

1. `git status` 干净，分支与提交可追溯。
2. `pytest` 全绿；记录测试数量、平台、Python 版本。
3. `git diff --cached` 不含真实数据、Key、邀请文件、`config.toml`、`.env`。
4. `README.md`、`docs/contract.md`、`docs/privacy.md`、`docs/security.md`、`docs/configuration.md` 与实际功能一致。
5. 默认监听仍是 loopback；管理员接口不在公开端口。
6. 失败 run 不能加载；输出检查、会话删除、跨邀请隔离测试通过。
7. 没有把 Mock 结果写成真实人物质量结论。
8. 许可证、CHANGELOG、CONTRIBUTING 存在。

## 构建

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m build
```

产物在 `dist/`：

- `person_simulator-<version>-py3-none-any.whl`
- `person_simulator-<version>.tar.gz`

## 干净环境验证

在仓库外的临时 venv：

```powershell
python -m venv $env:TEMP\psim-release-venv
$env:TEMP\psim-release-venv\Scripts\python.exe -m pip install dist\person_simulator-<version>-py3-none-any.whl
$env:TEMP\psim-release-venv\Scripts\person-sim.exe --version
$env:TEMP\psim-release-venv\Scripts\person-sim.exe doctor
```

再用一个合成样例：

```powershell
person-sim build --input examples\sample_chat.txt --target A --mode mock --out $env:TEMP\psim-release-runs
person-sim serve --run $env:TEMP\psim-release-runs\<run-id> --mode mock --check
```

必须实际运行并记录输出；不能只凭构建成功宣称可用。

## 产物完整性

构建后检查 wheel/sdist：

- 包含 `person_simulator/server/static/index.html`、`app.js`、`style.css`。
- 不包含 `data/`、`runs/`、`exports/`、`eval_runs/`、`config.toml`、`.env`、`*.psim`。
- 不包含真实聊天、人物档案或 API Key。

## GitHub Release

以下操作必须**单独获得批准**：

- 创建/公开 GitHub 仓库；
- 推送分支或标签；
- 创建 Release、上传 wheel/sdist；
- 修改仓库可见性或发布公告。

Release 说明至少包含：版本、变更、安装、快速开始、隐私/费用限制、已知问题、测试环境。

## 验证记录（2026-10-25）

环境：Windows，Python 3.12.10，Git 2.55.0.windows.3。

- 完整测试：`172 passed`。
- 构建：`python -m build` 成功生成 `person_simulator-0.2.0-py3-none-any.whl` 与 `person_simulator-0.2.0.tar.gz`。
- 产物检查：wheel/sdist 均包含 `person_simulator/server/static/index.html`；未发现 `data/`、`runs/`、`exports/`、`eval_runs/`、`config.toml`、`.env`、`.psim`。
- 干净 venv 安装 wheel：成功。
- `person-sim --version`：`person-simulator 0.2.0`。
- `person-sim doctor`：退出 0。
- `person-sim build --input examples/sample_chat.txt --target A --mode mock`：退出 0。
- `person-sim serve --run <mock-run> --mode mock --check`：退出 0，输出 `runtime-persona-1.0`。
- 未调用真实模型 API；未使用真实聊天或真实人物档案。

## 当前未完成

- 真实 evidence API 全流程未验收。
- 人物模拟质量未做正式人工评分。
- 独立桌面客户端、MCP adapter、内置公网 TLS/ACME 未实现。
- GitHub 仓库地址、安全联系方式和正式发布尚未确定。
- `--allow-lan` 需要显式 `--allowed-host` 加入局域网 IP/隧道域名；不会自动信任所有 Host。
