# MathS-Agent

最后更新：2026-11-14 04:29:25（UTC+08:00）。

基于 React、FastAPI 和 LangGraph 的数学推理 Web 应用，支持聊天解题、公式展示、题目文件上传、任务进度、取消与恢复。平台负责运行任务，Agent 负责推理，LangGraph 定义节点与路由。

## 项目结构

```text
client/                         # React + TypeScript 前端
agent_platform/
├── app.py                      # HTTP / SSE 接口
├── service.py                  # 任务调度、并发、取消与恢复
├── bootstrap.py                # 注入模型客户端和工具
├── runtime.py                  # 平台与 Agent 的运行接口
├── reasoning_runtime.py        # 将平台任务接入 LangGraph
├── observability.py            # LangSmith 追踪与数据脱敏
├── agent/
│   ├── graph.py                # StateGraph、节点注册与条件边
│   ├── state.py                # 图状态与检查点结构
│   ├── routing.py              # 条件路由规则
│   ├── dependencies.py         # 模型、工具等依赖接口
│   ├── execution.py            # 节点执行、取消、模型调用和检查点边界
│   ├── stage_engine.py         # 各阶段共享推理逻辑
│   ├── checkpoint.py           # 检查点恢复与兼容校验
│   ├── nodes/
│   │   ├── profile.py          # 题目分析
│   │   ├── retrieve.py         # 策略检索
│   │   ├── plan.py             # 解题规划
│   │   ├── solve.py            # 生成解答
│   │   ├── tool.py             # 本地工具核验
│   │   ├── verify.py           # 校验与审查
│   │   ├── repair.py           # 修复解答
│   │   ├── emergency.py        # 紧急恢复
│   │   ├── arbitrate.py        # 候选答案仲裁
│   │   └── finalize.py         # 整理最终答案
│   ├── prompts/               # 现有提示词的兼容入口
│   ├── schemas/               # 结构化模型输出入口
│   ├── retrieval/             # 词法、向量和融合检索入口
│   └── tools/                 # 注入工具的接口入口
├── tools/                     # 工具注册、数学计算、隔离执行与 MCP
├── storage/                   # 内存、Redis、PostgreSQL 存储
├── presentation/              # 答案整理与公开输出
└── static/chat/               # 前端构建产物，由后端提供
reasoning_agent/               # 复用的推理代码、提示词、解析器与检索实现
strategy_data/                 # 策略元数据、词法索引与向量索引
strategyrag/                   # 本地嵌入模型资源
skill2_en/                     # 英文数学技能材料
skill2/                        # 中文回退技能材料
tests/
├── unit/                      # 单元测试
├── integration/               # 图运行与平台集成测试
└── e2e/                       # Web 流程测试
scripts/web_launcher.py        # 启动检查、前端构建、进程和日志管理
start.sh                       # 一键启动入口
.env.example                   # 中文配置模板
local_state/                   # 本地日志、进程记录与题目附件，不提交 Git
```

`reasoning_runtime.py` 编译并运行 `agent/graph.py` 构建的图。节点按条件路由执行，修复、紧急恢复和仲裁按需进入，并非所有节点每次都会运行。

提示词入口为 `agent_platform/agent/prompts/staged.py`，实际复用 `reasoning_agent/custom2/staged_prompts.py` 等共享模块；检索入口同样复用 `reasoning_agent/` 中的既有实现。目录拆分没有改变原有流程、提示词或 state 协议。检查点兼容约束见 [模块结构说明](docs/math-agent-module-structure.md)。

## 环境准备

需要 Python 3.11、Node.js >=22.12 和 npm。以下命令从项目根目录执行，适用于 macOS / Linux。

首次使用且尚未创建环境时：

```bash
conda create -n intern python=3.11
```

安装后端、策略混合检索和前端依赖：

```bash
conda activate intern
python -m pip install -r requirements.txt
python -m pip install -r requirements-platform-m5.txt
npm --prefix client ci
```

默认混合检索还需要以下本地资源：

- `strategyrag/Qwen3-Embedding-0.6B/`：完整模型权重、模型配置和 tokenizer。
- `strategy_data/`：策略元数据、词法索引、向量矩阵及索引清单，条数与策略顺序必须一致。
- `skill2_en/`、`skill2/`：数学技能材料。

`model.safetensors` 由本地独立管理，不纳入 Git 跟踪；拉取代码不会提供权重，需要提前放入上述目录。

启动器不会下载模型、安装依赖或重建索引。若只使用词法检索，可在 `.env` 中设置 `STAGED_STRATEGY_RETRIEVAL_MODE=lexical`，无需嵌入模型及 `requirements-platform-m5.txt` 中的可选依赖。

## 配置

首次配置时复制模板；已有 `.env` 会保留：

```bash
cp -n .env.example .env
```

编辑本地 `.env`，至少填写模型 Key，并确认模型、端口和检索方式：

```dotenv
INTERN_API_KEY=你的模型密钥
INTERN_MODEL=intern-s2-preview
MATHS_WEB_PORT=8010
STAGED_STRATEGY_RETRIEVAL_MODE=hybrid
```

| 配置项 | 用途 |
| --- | --- |
| `INTERN_API_BASE` | 可选的模型接口完整地址，默认使用 Intern API |
| `MATHS_WEB_PORT` | Web 和后端共用端口，默认 `8010` |
| `MATHS_WEB_BIND` | Docker 宿主机监听地址，默认 `0.0.0.0`；设为 `127.0.0.1` 可限制为本机访问 |
| `MATHS_WEB_STATE_DIR` | 启动器记录及日志目录，默认 `local_state/web_launcher` |
| `MATHS_QUESTION_DIR` | 题目附件目录，默认 `local_state/chat_questions` |
| `MATHS_STARTUP_TIMEOUT` | 等待后端就绪的超时秒数，默认 `120` |
| `MATHS_FUNCTION_CALLING` | 工具调用协议，默认 `off`，还支持 `auto`、`native`、`json` |
| `MATHS_CHAT_REDIS_URL` | 可选的 Redis 连接；未配置时使用进程内存存储 |
| `MATHS_CHAT_NAMESPACE` | Redis 数据命名空间，默认 `maths:chat:v1` |

完整配置及中文注释见 [.env.example](.env.example)。终端已导出的变量优先于 `.env`。密钥只保留在后端配置中，不提交 Git，也不要写入 `VITE_*` 变量。

## 启动与停止

```bash
bash start.sh check   # 先检查环境与资源，不启动服务
bash start.sh         # 检查、构建 React、启动 LangGraph 后端并监听日志
```

检查内容包括依赖及版本冲突、模型 Key 是否存在、技能与策略资源、混合检索的本地模型离线推理、目录权限、Redis 配置和端口。检查不会调用远程解题模型，也不验证模型 Key 的有效性；提交题目后才会产生实际模型调用。

服务默认监听 `0.0.0.0`（所有 IPv4 网卡）。看到 `[启动成功]` 后，本机可打开 [聊天页面](http://127.0.0.1:8010/chat/) 和 [/docs](http://127.0.0.1:8010/docs)；其他设备请使用服务器 IP 和对应端口访问。修改端口后使用对应地址。直接使用 `python -m agent_platform` 时，可通过 `--host 127.0.0.1` 限制为本机访问。

启动成功后终端会持续显示后端日志。按 **Ctrl+C** 正常关闭本次启动的 LangGraph 后端及 Web 入口。React 构建产物由同一后端提供，不需要单独启动前端服务。

```bash
bash start.sh status        # 查看本启动器管理的服务
bash start.sh logs          # 查看最近 100 行并持续跟踪日志
bash start.sh stop          # 正常停止本启动器管理的服务
bash start.sh --background  # 后台启动，启动器在服务就绪后退出
```

`logs` 命令中的 Ctrl+C 仅结束日志查看；后台服务用 `stop` 关闭。日志默认保存在 `local_state/web_launcher/runtime.log`，包含启动检查、前端构建和后端输出。执行任务时会显示节点开始/完成、耗时、模型调用、检索命中数及工具事件；模型提供 token 用量时也会打印计数。日志不输出题目、提示词、state 或模型原始响应。图中的 `emergency` 和 `arbitrate` 在平台进度日志中分别归入 `solve` 和 `verify`，原始图节点名称可在 LangSmith 查看。

检索时还会打印向量权重的加载开始、完成、耗时、失败类型及进程内缓存复用。启动检查和后端是不同进程，因此首次实际检索仍可能加载权重。最终召回策略逐条输出排名、ID、名称、`score` 及可用的通道分数，并标记是否实际注入解题策略卡；低置信度或超出卡片长度限制的候选可能召回但未注入。不同检索模式的 `score` 含义不同，不应当作概率或跨模式直接比较。

模型日志同时显示节点和调用类型，例如 `profile 调用=classifier`、`verify 调用=targeted_audit`。工具日志显示名称、调用/操作 ID、执行方式、耗时、状态与错误码，以及从 0 开始的尝试序号；重试、回退和缓存重放分别标记。最终工具结果以脱敏 JSON 输出，包括计算值、核验结论或检索匹配结果，不打印检索提示词和渲染后的策略提示卡；单条结果超过 12000 字符时明确标记截断。

脚本默认激活 Conda `intern` 环境，也可在终端指定解释器或配置文件：

```bash
MATHS_CONDA_ENV=your-env bash start.sh
MATHS_PYTHON=/path/to/python bash start.sh
bash start.sh --env-file /path/to/config.env
```

端口或目录被占用时，启动器会报错，不会关闭其他服务。修改端口、状态目录或配置文件前，先使用原配置执行 `stop`。

## Docker 与 dev 流水线

`compose.web.yaml` 提供单容器 Web + LangGraph，镜像包含前端、Python 依赖和策略索引，模型通过只读目录挂载，不复制到镜像。
宿主机只需安装 Docker 和 Compose v2，无需 uv、Conda 或 Node.js。前端在镜像构建阶段编译。
容器内直接使用官方 Python 3.11 环境安装依赖，不创建 Conda 或额外虚拟环境。
构建默认使用清华 PyPI、npmmirror npm 和上海交大 PyTorch CPU 下载源，分别通过 `PIP_INDEX_URL`、`NPM_REGISTRY`、`TORCH_INDEX_URL` 覆盖。
基础镜像默认来自 Docker Hub，可通过 `NODE_IMAGE`、`PYTHON_IMAGE` 指定可访问仓库中的兼容镜像。
这些构建参数可在本地 `.env` 或 GitHub `dev` Environment Variables 中配置；运行时 Key 不作为构建参数。

先准备完整模型目录，包含 `model.safetensors`、配置、tokenizer 以及 `1_Pooling/` 等原有文件。
只读挂载不能现场合并分片，不能使用只有 Git LFS 指针的文件；容器用户 UID `10001` 需要有目录读取权限。

```bash
export MATHS_MODEL_DIR=/opt/models/Qwen3-Embedding-0.6B
# 本地使用已有 .env 中的 INTERN_API_KEY 等配置；不要将 Key 写进 Compose。
docker compose -f compose.web.yaml up -d --build --wait
docker compose -f compose.web.yaml logs -f web
docker compose -f compose.web.yaml down
```

默认监听所有宿主机 IPv4 网卡，本机页面为 `http://127.0.0.1:8010/chat/`。`MATHS_WEB_PORT` 可修改宿主机端口；仅允许本机访问时设置 `MATHS_WEB_BIND=127.0.0.1`。
题目文件放在 Docker 命名卷 `web-data`；`down` 保留该卷，但当前会话/任务仍在进程内存中，重启不保留。
容器日志通过 Docker 查看，完整模型挂载到 `/app/strategyrag/Qwen3-Embedding-0.6B`；不会自动下载权重。
工具协议固定为 `off`，与 `start.sh` 默认一致。

NVIDIA GPU 服务器需预装显卡驱动和 NVIDIA Container Toolkit。使用 GPU 配置构建并启动：

```bash
docker compose -f compose.web.yaml -f compose.web.gpu.yaml up -d --build --wait
```

GPU 配置默认从上海交大 `cu128` 源安装 CUDA 版 PyTorch，并将 GPU 暴露给容器；可用 `TORCH_INDEX_URL` 选择与驱动和显卡兼容的版本。
宿主机不需要安装 Conda 或 Python CUDA 包。容器启动时检查 CUDA 可用性并打印设备名称，不可用则启动失败。
检索模型自动选择 CUDA，其次 MPS，最后 CPU；GPU 加速的是本地嵌入检索，解题模型仍通过远程 API 调用。

## GitHub 部署

`.github/workflows/platform.yml` 在 `dev` 分支收到 push 时自动触发，包括合并 PR（merge、squash、rebase）及直接推送；同时保留手动触发，手动运行时需选择 `dev`。
也支持 `repository_dispatch` 事件 `gitcode-dev-push`，供外部服务通知部署；该事件需要默认分支 `main` 包含此工作流配置，部署时仍从 `MATHS_GIT_REMOTE` 拉取 `dev`。GitCode push 本身不会自动发送此事件，需要外部服务调用 GitHub 的 repository dispatch API。
未合并的 PR 和其他分支不会自动部署。工作流在 self-hosted runner 的 Conda `intern` 环境中通过 `start.sh` 重启服务，同一部署任务串行运行。
工作流不使用 `actions/checkout` 或 Docker，直接进入 `MATHS_DEPLOY_DIR` 指定的已有仓库，执行 `git pull --ff-only <remote> dev`。
默认目录为 `/home/jovyan/maths/MathS-Agent`，默认远程为 `origin`。
请提前在该目录克隆项目、切换到 `dev` 并配置 runner 用户的 Git 拉取凭据。仓库存在已跟踪文件的未提交改动或无法快进时，更新会失败，不自动覆盖。
runner 需提前准备 Conda `intern`、Python 依赖、Node.js、前端依赖，以及项目内的完整模型、策略索引和技能材料。
拉取时跳过 LFS 下载，复用项目中已有模型。此目录不应同时供其他更新任务修改。
在 GitHub **Settings → Environments → dev** 配置下列 Secrets 和 Variables；也支持同名仓库级配置：

| 类型 | 名称 | 内容 |
| --- | --- | --- |
| Secret | `INTERN_API_KEY` | 解题模型 Key；未配置时读取服务器项目 `.env` 的同名值 |
| Secret | `LANGSMITH_API_KEY` | 开启追踪时填写；未配置时读取服务器项目 `.env` 的同名值 |
| Variable | `MATHS_DEPLOY_DIR` | 项目仓库绝对路径，默认 `/home/jovyan/maths/MathS-Agent` |
| Variable | `MATHS_GIT_REMOTE` | 拉取代码的远程名称，默认 `origin`；需提前确认该远程指向目标仓库 |
| Variable | `MATHS_PYTHON` | 默认 `/opt/conda/envs/intern/bin/python`，直接使用 intern 的解释器，无需查找或激活 conda 命令 |
| Variable | `INTERN_MODEL`、`INTERN_API_BASE` | 模型名称和可选接口地址 |
| Variable | `MATHS_WEB_PORT` | 服务端口；未配置时读取服务器 `.env` |
| Variable | `MATHS_STARTUP_TIMEOUT` | 等待就绪时间；未配置时读取服务器 `.env` |
| Variable | `LANGSMITH_TRACING`、`LANGSMITH_PROJECT`、`LANGSMITH_ENDPOINT` | 可选追踪配置 |
| Variable | `STAGED_STRATEGY_RETRIEVAL_ENABLED`、`STAGED_STRATEGY_RETRIEVAL_MODE` | 检索开关与模式；未配置时读取服务器 `.env` |

runner 固定匹配 `self-hosted`、`Linux`、`X64` 三个标签，需同时满足。
非空 Key 通过 GitHub Secrets 注入进程环境，优先于项目 `.env`；未配置或为空时读取项目 `.env`，不输出密钥。
端口、模型、超时、LangSmith 和检索配置同样遵循“非空 GitHub 配置优先，否则读取 `.env`”，CI 不注入固定应用默认值；显式设置的 `false`、`0` 会保留。
若 GitHub 和 `.env` 均未配置某项，沿用应用本身的默认行为。部署目录、远程名称和解释器路径仍使用上表中约定的部署默认值。
停止旧服务前会确认 Secret 或 `.env` 中存在解题 Key，避免因缺少 Key 导致停机。
项目 `.env` 继续提供启动器状态目录、题目存储、Redis 等其他配置，需与已有服务保持一致，才能定位和正常停止旧进程。
执行顺序为：拉取代码、`bash start.sh stop`、`bash start.sh --background`、`bash start.sh status`，均使用 Conda `intern`。
通过 `MATHS_PYTHON` 指定该环境的 Python，停止、启动和后端子进程均复用同一个解释器。
启动脚本负责依赖与资源检查、前端构建和后端健康检查；任一步骤失败则流水线失败，不自动回滚。
只在后台启动命令上清空 `RUNNER_TRACKING_ID`，防止 self-hosted runner 在任务结束后清理本次启动的后台进程。服务继续运行，日志保存在启动器配置的 `runtime.log` 中。
停止命令只停止当前启动器进程记录所指向的服务，不会按端口杀死其他进程，也不会停止 Docker 容器。
该工作流不再安装或更换 PyTorch；GPU 是否可用取决于 `intern` 中的 PyTorch 与宿主机驱动是否兼容。
流水线不会运行完整测试或提交题目，不验证 API Key 有效性；启动器会按配置执行本地向量推理验证。
本地仍可运行 `python scripts/check_platform_ci.py` 完成完整工程检查。

## 聊天记录持久化

默认会话和任务保存在内存中，重启后不会保留。需要持久化时，先安装 Redis，再从项目根目录在另一个终端运行：

```bash
mkdir -p local_state/chat_redis
redis-server deploy/redis-chat.conf
```

在 `.env` 中设置后启动应用：

```dotenv
MATHS_CHAT_REDIS_URL=redis://127.0.0.1:6388/0
MATHS_CHAT_NAMESPACE=maths:chat:v1
```

提供的 Redis 配置启用 AOF 和 `appendfsync always`，启动器会检查连接与持久化设置，但不负责启停 Redis。保留 Redis 数据、命名空间和题目目录以继续访问历史；原内存会话不会自动迁移。

## LangSmith 追踪

在 `.env` 配置独立的 LangSmith Key，并重新启动应用：

```dotenv
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=你的LangSmith密钥
LANGSMITH_PROJECT=math-reasoning
LANGSMITH_ENDPOINT=https://api.smith.langchain.com
```

在 [LangSmith](https://smith.langchain.com/) 对应项目查看图节点与模型调用的父子层级、耗时和脱敏错误，用 `task:<任务 ID>` 标签关联 Web 任务。其他区域或私有部署请调整 `LANGSMITH_ENDPOINT`。

开启追踪会上传脱敏后的题目、提示词、节点 state、模型请求与回复，便于查看中间过程；模型返回用量时同步记录 input/output/total token。密钥、认证头、客户端对象、本地路径和原始异常内容不会上传。费用统计取决于 LangSmith 是否支持该模型的定价。启动检查只验证本地配置，不验证云端连接或 Key 有效性。设置 `LANGSMITH_TRACING=false` 可关闭上传。旧的空 trace 无法补回，需要执行新任务。官方说明：[LangGraph 与 LangSmith](https://docs.langchain.com/langsmith/trace-with-langgraph)。

## 开发与测试

前端开发时，保持后端运行，在另一个终端启动 Vite 热更新：

```bash
cd client
MATHS_BACKEND_URL=http://127.0.0.1:8010 npm run dev -- --port 5174
```

访问 `http://127.0.0.1:5174/chat/`。只调试界面且无需真实模型时，可用 `python -m agent_platform --port 8010` 启动 Fake 后端；此入口需先用 `npm --prefix client run build` 构建页面，Fake 模式仅返回演示结果。

```bash
python -m pip install -r requirements-platform-dev.txt
python -m pytest -q
npm --prefix client test
npm --prefix client run build
```

完整 CI 使用 `python scripts/check_platform_ci.py`，PostgreSQL 测试需要专用、可丢弃的 `MATHS_TEST_DATABASE_URL`。确定性回归测试无需真实模型请求。

## 使用边界

- 当前仍面向单用户，默认监听 `0.0.0.0`，没有公开访问认证；只在可信网络中开放，或用防火墙、反向代理和身份认证做好访问隔离。
- 支持 PDF / Markdown 题目文件，扫描 PDF 的 OCR 尚不支持。
- 取消或中断后可显式恢复任务；代码或配置更新可能导致旧检查点无法恢复。
- `.env`、日志、聊天记录、题目附件、模型权重和生成结果不应提交 Git。

更多配置见 [后端说明](agent_platform/README.md)，前端行为见 [前端说明](client/README.md)，维护工具见 [脚本说明](scripts/README.md)。
