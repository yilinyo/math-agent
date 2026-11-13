## Purpose

为 GitCode 托管仓库提供可重复、无在线模型调用的合并质量门禁，确保进入 `main` 的代码具备可安装依赖、可编译源码、通过单元测试并保持官方 Agent 入口合同。

## ADDED Requirements

### Requirement: 面向 main 的自动触发
系统 SHALL 在面向 `main` 的合并请求以及推送到 `main` 后运行 CI，并 SHALL 提供手动触发入口用于配置验证和故障复现。

#### Scenario: 创建面向 main 的合并请求
- **WHEN** GitCode 收到一个目标分支为 `main` 的合并请求事件
- **THEN** 系统启动完整的轻量 CI 检查

#### Scenario: main 收到推送
- **WHEN** 新提交被推送到 `main`
- **THEN** 系统启动同一套 CI 检查以确认主分支状态

### Requirement: 依赖可安装性检查
CI SHALL 在干净的 Python 3.11 环境中安装仓库声明的运行依赖和测试工具；任何依赖无法下载或安装时，CI MUST 失败。

#### Scenario: 所有依赖均可获得
- **WHEN** 包索引和 Git 依赖来源可访问且依赖解析成功
- **THEN** CI 继续执行静态编译和测试阶段

#### Scenario: 依赖下载失败
- **WHEN** 任一声明依赖无法下载、解析或安装
- **THEN** CI 以失败状态结束并保留安装步骤日志

### Requirement: Python 静态编译检查
CI SHALL 对平台入口、本地运行入口和 `reasoning_agent` 包执行 Python 字节码编译检查，语法错误 MUST 阻止流水线通过。

#### Scenario: 源码存在语法错误
- **WHEN** 任一受检 Python 文件无法由选定解释器编译
- **THEN** 静态编译步骤失败且后续合并检查不得显示为通过

### Requirement: 确定性单元测试
CI SHALL 运行 `tests/` 下的确定性测试，并 MUST NOT 要求真实模型 API 密钥或发起在线模型评测。

#### Scenario: 单元测试全部通过
- **WHEN** 所有确定性测试均成功
- **THEN** 单元测试检查显示为通过

#### Scenario: 任一单元测试失败
- **WHEN** 测试进程报告至少一个失败或错误
- **THEN** CI 以失败状态结束并显示失败用例

### Requirement: Agent 入口契约检查
CI SHALL 单独验证 `user_agent` 导出名为 `ReasoningAgent` 的类，该类可使用注入客户端构造，并提供 `solve(problem, metadata)` 方法且测试返回值满足非空 `final_response` 字典合同。

#### Scenario: 入口合同保持有效
- **WHEN** 入口契约测试加载当前提交的 `user_agent.py`
- **THEN** `ReasoningAgent` 可被发现、构造和调用，且合同断言全部通过

#### Scenario: 入口合同被破坏
- **WHEN** 类名、构造签名、solve 签名或返回合同不满足要求
- **THEN** 入口契约检查失败并阻止 CI 通过
