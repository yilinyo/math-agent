## Context

仓库由 GitCode 托管，当前没有 `.gitcode/workflows` 配置。测试基于 `pytest`/`unittest`，正式入口是 `user_agent.py`，依赖集中在 `requirements.txt`，其中包含 PyPI 包和 Git 来源依赖。CI 必须在不注入 `INTERN_API_KEY` 的情况下验证确定性行为。

## Goals / Non-Goals

**Goals:**

- 使用 GitCode 原生、仓库内版本化的工作流提供单一合并质量门禁。
- 固定 Python 3.11，减少 Runner 默认工具链变化造成的差异。
- 将依赖安装、编译、全量确定性测试和入口契约分成名称清晰的步骤，便于定位失败原因。
- 让同一工作流同时覆盖 PR、`main` 推送与手动验证。

**Non-Goals:**

- 不执行需要真实模型服务或 API Key 的端到端评测。
- 不自动同步 `main` 到 `judge`，不执行部署、发布或分数回填。
- 第一版不引入 lint、类型检查、覆盖率门槛和多 Python 版本矩阵。
- 第一版不拆分或优化现有依赖集合。

## Decisions

### 使用单个 GitCode 工作流和单个 Job

采用 `.gitcode/workflows/ci.yml`，在一个托管 Runner 中顺序执行所有检查。这样依赖只安装一次，失败步骤也容易识别。备选的多 Job 方案会重复安装 PyTorch 等大型依赖，第一版成本过高。

### 同时监听 pull_request、push 和 workflow_dispatch

`pull_request` 面向 `main` 提供合并前检查，`push` 到 `main` 用于确认合并结果，`workflow_dispatch` 便于首次启用与故障复现。流水线本身只能产出检查状态；是否强制阻止合并需要在 GitCode 分支保护中把该检查设为必需。

### 完整安装 requirements.txt

第一版直接安装正式依赖，再安装 `pytest`，从而真实验证声明依赖是否可下载和安装。备选的最小 CI 依赖文件速度更快，但无法满足“检查依赖是否可以下载”的目标；后续若耗时不可接受，再独立设计依赖分层。

### 将入口契约作为独立测试步骤

先运行完整 `tests/`，再单独运行 `tests/test_user_agent_contract.py`。虽然存在少量重复，但 GitCode 页面会明确显示入口合同是否成功，满足对评测接口的重点保护。

### 不向 CI 提供模型密钥

工作流不声明 `INTERN_API_KEY`，测试必须依赖 fake client。这样 PR（包括潜在 fork 来源）不会接触比赛密钥，也不会产生非确定性费用和外部副作用。

## Risks / Trade-offs

- [完整依赖含 PyTorch、Transformers 和 Git 来源的 lagent，下载慢或占用较大] → 启用 pip 缓存并先使用单 Job；后续根据实际耗时再拆分 `requirements-ci.txt`。
- [Runner 无法访问 GitHub 上的 lagent 来源] → 依赖步骤明确失败，暴露正式环境同样可能面对的可获得性问题；必要时再迁移依赖镜像或固定制品。
- [GitCode 工作流语法或 Action 名称随平台能力变化] → 采用官方文档当前的 `checkout`、`setup-python` 与托管 Runner 标签，并保留手动触发进行首次验证。
- [CI 通过不等于自动禁止合并] → 在仓库设置中将工作流状态配置为 `main` 分支的必需检查。
- [全量测试可能包含后续新增的在线测试] → 保持测试规范：默认测试不得需要真实 API；在线评测未来应使用独立标记与手动工作流。

## Migration Plan

1. 提交 `.gitcode/workflows/ci.yml` 并通过 `workflow_dispatch` 首次运行。
2. 根据 GitCode 实际日志校正 Runner/Action 可用性，但不降低四类检查要求。
3. 首次运行成功后，在 `main` 分支保护中把该 CI 设为合并必需检查。
4. 如需回滚，删除或禁用该工作流并撤销分支必需检查；不影响 Agent 运行代码。
