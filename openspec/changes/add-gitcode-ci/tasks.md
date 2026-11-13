## 1. GitCode 工作流

- [x] 1.1 新增 `.gitcode/workflows/ci.yml`，配置面向 `main` 的 push、pull_request 和 workflow_dispatch 触发器，并使用只读仓库权限与单并发队列。
- [x] 1.2 配置 GitCode 托管 Runner、源码检出、Python 3.11 和 pip 缓存。
- [x] 1.3 增加依赖安装步骤，安装 `requirements.txt` 与 `pytest`，并确保失败会终止流水线。

## 2. 质量检查

- [x] 2.1 增加 `user_agent.py`、`main.py` 和 `reasoning_agent` 的 `compileall` 静态编译步骤。
- [x] 2.2 增加 `tests/` 全量确定性单元测试步骤，且不配置任何真实模型 API 密钥。
- [x] 2.3 增加独立的 `tests/test_user_agent_contract.py` 入口契约检查步骤，使 Agent 发现、构造、solve 签名和返回合同具有明确状态。

## 3. 验证与启用

- [ ] 3.1 在本地验证 YAML 可解析，并运行静态编译、入口契约及完整测试命令。
- [x] 3.2 校验 OpenSpec 变更，核对工作流未包含密钥、在线评测或自动 judge 同步。
- [ ] 3.3 提交并推送工作流后，通过 GitCode 手动触发验证首次运行；成功后在仓库设置中将该检查设为 `main` 的必需合并检查。
