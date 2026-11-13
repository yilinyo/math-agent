## Why

仓库目前缺少托管端的自动检查，合并到 `main` 前无法稳定确认依赖可安装、Python 源码可编译、确定性单元测试通过，以及平台入口仍能导出并调用合法的 `ReasoningAgent.solve`。增加一个轻量 GitCode CI，可以尽早阻止破坏评测入口或基础运行环境的改动进入主分支。

## What Changes

- 新增 GitCode 原生工作流，在提交到 `main` 和面向 `main` 的合并请求上触发，并支持手动运行。
- 在干净的 Python 3.11 Runner 中检出仓库并安装 `requirements.txt` 与测试工具，以验证依赖可下载、可安装。
- 对平台入口、运行脚本和 `reasoning_agent` 包执行静态字节码编译检查。
- 运行仓库全部确定性单元测试，不配置真实 API 密钥，也不执行在线模型评测。
- 单独运行入口契约测试，验证 `user_agent.ReasoningAgent` 可被发现、可用注入客户端构造，并保持 `solve(problem, metadata) -> dict` 合同。

## Capabilities

### New Capabilities

- `gitcode-ci-validation`: 定义 GitCode 上针对 `main` 合并与推送的依赖、静态编译、单元测试和 Agent 入口契约检查。

### Modified Capabilities

无。

## Impact

- 新增 `.gitcode/workflows/ci.yml`，由 GitCode 托管 Runner 执行。
- 不修改 Agent 的运行时行为、平台接口或模型调用逻辑。
- CI 需要访问 Python 包索引及 `requirements.txt` 中声明的 Git 依赖来源；网络或上游依赖不可用时流水线将失败并明确暴露问题。
- 普通 CI 不使用 `INTERN_API_KEY`，不会产生评测输出、数据集或原始模型响应。
