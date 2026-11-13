"""Local LangGraph + built React launcher; no live model request during checks."""
from __future__ import annotations

import argparse
from contextlib import contextmanager, redirect_stdout, redirect_stderr
import fcntl
import importlib.metadata
import json
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from urllib.parse import urlparse
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
VECTOR_PROBE = """Domain: startup validation
Goal: verify local embedding inference
Objects: an offline text encoder and its strategy index
Constraints: no remote model calls
Structure:
- Encode this synthetic readiness description.
"""


class LauncherError(RuntimeError):
    pass


def diagnostic(error):
    message = str(error)
    for key, value in os.environ.items():
        if any(word in key.upper() for word in ("KEY", "TOKEN", "SECRET", "PASSWORD")) and value:
            message = message.replace(value, "[敏感信息已隐藏]")
    message = re.sub(r"https?://[^\s'\"]+", "[接口地址已隐藏]", message)
    return f"{type(error).__name__}: {message[:1500]}"


@contextmanager
def stage(name):
    started = time.monotonic()
    done = threading.Event()
    print(f"[阶段开始] {name}", flush=True)

    def heartbeat():
        while not done.wait(15):
            print(f"[仍在执行] {name}，已耗时 {time.monotonic() - started:.0f} 秒……", flush=True)

    worker = threading.Thread(target=heartbeat, daemon=True)
    worker.start()
    try:
        yield
    except BaseException:
        print(f"[阶段失败] {name}，耗时 {time.monotonic() - started:.1f} 秒。", flush=True)
        raise
    else:
        print(f"[阶段完成] {name}，耗时 {time.monotonic() - started:.1f} 秒。", flush=True)
    finally:
        done.set()
        worker.join()


def inspect_strategy_resources(mode):
    import numpy as np

    data = ROOT / "strategy_data"
    model = ROOT / "strategyrag/Qwen3-Embedding-0.6B"
    print(f"[策略资源] 索引目录：{data}", flush=True)
    metadata_path = data / "strategy_meta.json"
    require(metadata_path.is_file(), "缺少策略元数据 strategy_data/strategy_meta.json。")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    print(f"[策略资源] 当前策略总数：{len(metadata)} 条", flush=True)
    lexical_path = data / "strategy_lexical_index.json"
    if lexical_path.is_file():
        lexical = json.loads(lexical_path.read_text(encoding="utf-8"))
        print(f"[策略资源] 词法索引记录：{len(lexical['cards'])} 条（随后校验索引版本）", flush=True)
    else:
        print("[策略资源] 未发现词法索引文件。", flush=True)
    if mode not in {"hybrid", "legacy_embedding"}:
        return
    print(f"[模型文件] 本地模型目录：{model}", flush=True)
    weights = model / "model.safetensors"
    manifest_path = model / "model.safetensors.parts.json"
    if weights.is_file():
        print(f"[模型文件] 已有合并权重：{weights.stat().st_size} 字节；稍后执行离线加载。", flush=True)
    elif manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        parts = manifest.get("parts", [])
        require(isinstance(parts, list) and parts
                and all(isinstance(name, str) and Path(name).name == name for name in parts),
                "模型分片清单格式错误，请检查 model.safetensors.parts.json。")
        missing = [name for name in parts if not (model / name).is_file()]
        print(f"[模型文件] 已找到 {len(parts) - len(missing)}/{len(parts)} 个权重分片；"
              "分片齐全时，原模型加载器会自动合并并验证完整性。", flush=True)
        require(not missing, "模型分片缺失：" + ", ".join(missing))
    else:
        raise LauncherError("既没有合并模型权重，也没有分片清单；请准备完整本地模型，不会自动下载。")
    vector_path, index_path = data / "strategy_embeddings.npy", data / "strategy_index.json"
    require(vector_path.is_file() and index_path.is_file(), "缺少向量文件或向量索引清单，请检查 strategy_data/。")
    vectors = np.load(vector_path, mmap_mode="r", allow_pickle=False)
    index = json.loads(index_path.read_text(encoding="utf-8"))
    print(f"[向量索引] 矩阵形状：{vectors.shape}；清单记录策略数：{index.get('num_strategies', '未记录')}", flush=True)
    require(vectors.ndim == 2, "向量索引应为二维矩阵，当前文件格式不正确。")
    if vectors.shape[0] != len(metadata):
        difference = len(metadata) - vectors.shape[0]
        detail = (f"向量记录比策略记录少 {difference} 条" if difference > 0
                  else f"向量记录比策略记录多 {-difference} 条")
        raise LauncherError(
            f"策略与向量索引不同步：策略 {len(metadata)} 条，向量 {vectors.shape[0]} 条，{detail}。\n"
            "这一步尚未加载模型，不能据此判断模型损坏或缺失。\n"
            "请核对策略 ID、内容和向量行的对应关系，再补齐或重建匹配的向量索引；"
            "不要只修改清单条数。启动脚本不会改写索引。\n"
            "如需暂时仅用词法检索，请显式设置 STAGED_STRATEGY_RETRIEVAL_MODE=lexical。"
        )
    from reasoning_agent.strategy_retrieval import EMBEDDING_DIM, EMBEDDING_MODEL_NAME
    require(vectors.shape[1] == EMBEDDING_DIM and index.get("embedding_dim") == EMBEDDING_DIM,
            f"向量维度不匹配：矩阵 {vectors.shape[1]}，清单 {index.get('embedding_dim')}，要求 {EMBEDDING_DIM}。")
    require(index.get("embedding_model") == EMBEDDING_MODEL_NAME,
            "向量索引声明的嵌入模型与当前代码不一致，请使用同一模型生成的索引。")
    require(index.get("num_strategies") == len(metadata),
            "向量清单中的 num_strategies 与策略记录数不一致，请核对索引版本。")
    print("[向量索引] 数量、维度与模型声明匹配，继续实际加载校验。", flush=True)


class Tee:
    def __init__(self, console, log):
        self.console, self.log = console, log
        self.line_start = True
        self.lock = threading.Lock()

    def write(self, text):
        with self.lock:
            for part in text.splitlines(keepends=True):
                prefix = time.strftime("[%Y-%m-%d %H:%M:%S] ") if self.line_start else ""
                self.console.write(prefix + part)
                self.log.write(prefix + part)
                self.line_start = part.endswith(("\n", "\r"))
            self.flush()
        return len(text)

    def flush(self):
        self.console.flush()
        self.log.flush()


def require(condition, message):
    if not condition:
        raise LauncherError(message)


def load_environment(path):
    require(sys.version_info >= (3, 11), "需要 Python >=3.11；请通过 MATHS_PYTHON 或 MATHS_CONDA_ENV 选择环境。")
    try:
        from dotenv import load_dotenv
    except ImportError:
        raise LauncherError("缺少 python-dotenv，请执行：python -m pip install -r requirements.txt") from None
    load_dotenv(path, override=False)


def port_value(value):
    try:
        port = int(value)
    except ValueError:
        raise LauncherError("MATHS_WEB_PORT 必须是 1 至 65535 的整数。") from None
    require(1 <= port <= 65535, "MATHS_WEB_PORT 必须在 1 至 65535 之间。")
    return port


def paths():
    directory = Path(os.environ.get("MATHS_WEB_STATE_DIR", "local_state/web_launcher")).resolve()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory.chmod(0o700)
    return directory, directory / "process.json", directory / "runtime.log"


def process_identity(pid):
    result = subprocess.run(["ps", "-p", str(pid), "-o", "lstart=", "-o", "command="],
                            capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else ""


def running(record):
    return bool(record and record.get("identity")
                and process_identity(record["pid"]) == record["identity"])


def read_record(path):
    return json.loads(path.read_text()) if path.exists() else None


def follow_backend(child, logfile):
    # Child output is already in the log; bypass Tee to avoid writing it twice.
    console = getattr(sys.stdout, "console", sys.stdout)
    with logfile.open("r", encoding="utf-8", errors="replace") as stream:
        print("[前台运行] 正在实时显示后端日志；按 Ctrl+C 正常关闭 LangGraph 和 Web 服务。", flush=True)
        stream.seek(0, os.SEEK_END)
        while True:
            content = stream.read()
            if content:
                console.write(content)
                console.flush()
            code = child.poll()
            if code is not None:
                # Drain anything written between the previous read and process exit.
                console.write(stream.read())
                console.flush()
                require(code == 0, f"后端已退出，退出码 {code}；请查看：{logfile}")
                print("[服务结束] 后端与 Web 入口已关闭。", flush=True)
                return
            time.sleep(0.25)


def check_requirements(path, seen=None):
    from packaging.requirements import Requirement
    seen = seen if seen is not None else set()
    path = path.resolve()
    if path in seen:
        return []
    seen.add(path)
    failures = []
    for line in path.read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("-r "):
            failures.extend(check_requirements(path.parent / line[3:].strip(), seen))
            continue
        requirement = Requirement(line)
        if requirement.marker and not requirement.marker.evaluate():
            continue
        try:
            installed = importlib.metadata.version(requirement.name)
        except importlib.metadata.PackageNotFoundError:
            failures.append(str(requirement))
            continue
        if installed not in requirement.specifier:
            failures.append(f"{requirement}（已安装 {installed}）")
    return failures


def preflight(port):
    started = time.monotonic()
    print(f"[环境] Python：{sys.executable}；版本：{sys.version.split()[0]}", flush=True)
    print("[依赖] 正在核对后端依赖版本及依赖冲突……", flush=True)
    failures = check_requirements(ROOT / "requirements.txt")
    require(not failures, "后端依赖缺失或版本不兼容：" + ", ".join(failures)
            + "\n请在当前环境执行：python -m pip install -r requirements.txt")
    result = subprocess.run([sys.executable, "-m", "pip", "check"], capture_output=True, text=True)
    require(result.returncode == 0, "后端依赖存在冲突：" + diagnostic(RuntimeError(result.stdout + result.stderr))
            + "\n请运行 python -m pip check，按冲突提示修复版本。")
    print("[依赖] 后端依赖检查通过。", flush=True)
    from agent_platform.observability import tracing_enabled, tracing_client
    if tracing_enabled():
        tracing_client()
        print("[LangSmith] 已启用：上传脱敏后的节点输入输出、模型请求/回复和 token 用量；未验证云端连接。", flush=True)
    else:
        print("[LangSmith] 未启用；可在 .env 中配置 LANGSMITH_TRACING 和 LANGSMITH_API_KEY。", flush=True)
    require(bool(os.environ.get("INTERN_API_KEY", "").strip()), "缺少 INTERN_API_KEY，请在 .env 或终端环境变量中设置。")
    print("[模型连接] INTERN_API_KEY 已配置（不会打印密钥，也不会调用远程模型）。", flush=True)
    from deployment_bootstrap import provided_client
    from agent_platform.bootstrap import build_runtime
    client = provided_client()
    require(bool(client.model.strip()), "INTERN_MODEL 不能为空。")
    endpoint = urlparse(client.api_base)
    require(endpoint.scheme in {"http", "https"} and bool(endpoint.hostname),
            "INTERN_API_BASE 必须是有效的 HTTP(S) 接口地址。")
    build_runtime(client, client_identity="startup-check", function_calling="off")
    print("[运行时] LangGraph 运行时与注入客户端初始化通过。", flush=True)
    from reasoning_agent.custom.config import AgentConfig
    config = AgentConfig()
    for resource in ("skill2_en", "skill2"):
        require((ROOT / resource).is_dir(), f"缺少技能目录：{resource}")
    mode = config.staged_strategy_retrieval_mode
    require(mode in {"hybrid", "lexical", "legacy_embedding", "disabled"},
            "STAGED_STRATEGY_RETRIEVAL_MODE 无效，可选 hybrid、lexical、legacy_embedding、disabled。")
    print(f"[检索配置] 模式：{mode}；是否启用：{config.staged_strategy_retrieval_enabled}", flush=True)
    if config.staged_strategy_retrieval_enabled and mode != "disabled":
        inspect_strategy_resources(mode)
        if mode in {"hybrid", "legacy_embedding"}:
            failures = check_requirements(ROOT / "requirements-platform-m5.txt")
            require(not failures, "向量依赖缺失或版本不兼容：" + ", ".join(failures)
                    + "\n请执行：python -m pip install -r requirements-platform-m5.txt")
            print("[向量模型] 开始本地离线加载和编码验证，首次合并权重可能需要等待……", flush=True)
            os.environ["HF_HUB_OFFLINE"] = "1"
            os.environ["TRANSFORMERS_OFFLINE"] = "1"
            from reasoning_agent.strategy_retrieval import get_shared_strategy_retriever
            try:
                with stage("向量模型加载与离线编码"):
                    retriever = get_shared_strategy_retriever()
                    print(f"[计算设备] {retriever.device}；正在验证 1024 维向量输出。", flush=True)
                    retriever.retrieve_text(VECTOR_PROBE, top_k=1)
            except Exception as error:
                raise LauncherError(
                    "向量加载或编码验证失败：" + diagnostic(error) + "\n"
                    "请检查模型分片完整性、tokenizer、模型依赖及设备兼容性。"
                    "没有下载模型，也没有切换检索方式。"
                ) from None
            print("[向量模型] 模型、tokenizer 及实际离线编码验证通过。", flush=True)
        if mode in {"hybrid", "lexical"}:
            from reasoning_agent.lexical_strategy_retrieval import get_shared_lexical_strategy_retriever
            try:
                retriever = get_shared_lexical_strategy_retriever()
            except Exception as error:
                raise LauncherError("词法索引加载失败：" + diagnostic(error) + "\n请检查 strategy_data/ 的版本及策略 ID 是否一致。") from None
            print(f"[词法索引] 版本和策略对应关系校验通过，共 {len(retriever.cards)} 条。", flush=True)
    require(shutil.which("node") and shutil.which("npm"), "缺少 Node.js 或 npm，请安装 Node.js >=22.12。")
    node = subprocess.check_output(["node", "--version"], text=True).strip().lstrip("v")
    require(tuple(map(int, node.split(".")[:2])) >= (22, 12), "Node.js 版本过低，需要 >=22.12。")
    print(f"[前端] Node.js {node}；正在检查 npm 依赖……", flush=True)
    result = subprocess.run(["npm", "ls", "--depth=0"], cwd=ROOT / "client", capture_output=True, text=True)
    require(result.returncode == 0, "前端依赖缺失或版本不兼容：" + diagnostic(RuntimeError(result.stdout + result.stderr))
            + "\n请执行：cd client && npm ci")
    print("[前端] npm 依赖检查通过。", flush=True)
    from agent_platform.app import create_app
    # Constructing the app also checks dependencies used only by attachment routes.
    create_app()
    question_root = Path(os.environ.get("MATHS_QUESTION_DIR", "local_state/chat_questions"))
    print(f"[题目存储] 检查目录写入权限和单实例锁：{question_root.resolve()}", flush=True)
    question_root.mkdir(parents=True, exist_ok=True)
    with (question_root / "owner.lock").open("a+b") as owner:
        try:
            fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise LauncherError("MATHS_QUESTION_DIR 正被其他后端使用，请选择独立目录，或明确停止占用它的后端。") from None
        finally:
            fcntl.flock(owner, fcntl.LOCK_UN)
    print("[题目存储] 目录可写，未被其他实例占用。", flush=True)
    redis_url = os.environ.get("MATHS_CHAT_REDIS_URL", "")
    if redis_url:
        from redis import Redis
        from agent_platform.storage.redis import RedisTaskStore
        connection = Redis.from_url(redis_url, decode_responses=True,
                                    socket_timeout=3, socket_connect_timeout=3)
        try:
            store = RedisTaskStore(connection, namespace=os.environ.get("MATHS_CHAT_NAMESPACE", "maths:chat:v1"))
            store.ready()
        except Exception as error:
            raise LauncherError("Redis 检查失败：" + diagnostic(error)
                                + "\n请确认服务已启动、连接和认证配置正确，且启用 AOF 与 appendfsync always。") from None
        finally:
            connection.close()
        print("[存储] Redis 连接与持久化配置检查通过。", flush=True)
    else:
        print("[存储提示] 当前为进程内存存储，重启不会自动保留历史；需要持久化请配置 MATHS_CHAT_REDIS_URL。", flush=True)
    with socket.socket() as listener:
        try:
            listener.bind(("127.0.0.1", port))
        except OSError as error:
            raise LauncherError(f"端口 {port} 无法监听：" + diagnostic(error)
                                + "\n请检查端口是否被占用或缺少权限，必要时修改 MATHS_WEB_PORT；脚本不会停止已有服务。") from None
    print(f"[检查通过] 端口 {port} 可用，启动准备完成；总耗时 {time.monotonic() - started:.1f} 秒，未调用远程 LLM。", flush=True)


def serve(port):
    # Use the existing trusted bootstrap and CLI; no alternative reasoning workflow.
    model = os.environ.get("INTERN_MODEL", "intern-s2-preview")
    sys.argv = ["agent_platform", "--port", str(port), "--runtime", "langgraph",
                "--client-provider", "deployment_bootstrap:provided_client",
                "--client-identity", os.environ.get("MATHS_CLIENT_IDENTITY", f"intern/{model}/local-v1"),
                "--function-calling", os.environ.get("MATHS_FUNCTION_CALLING", "off"),
                "--question-dir", os.environ.get("MATHS_QUESTION_DIR", "local_state/chat_questions")]
    if os.environ.get("MATHS_CHAT_REDIS_URL"):
        sys.argv.extend(["--redis-url-env", "MATHS_CHAT_REDIS_URL", "--namespace",
                         os.environ.get("MATHS_CHAT_NAMESPACE", "maths:chat:v1")])
    from agent_platform.__main__ import main
    main()


def main():
    parser = argparse.ArgumentParser(description="启动 LangGraph 与 Web，检查环境并管理日志和进程。")
    parser.add_argument("action", nargs="?", default="start", choices=["check", "start", "status", "logs", "stop"],
                        help="check 检查、start 启动（默认）、status 状态、logs 日志、stop 停止")
    parser.add_argument("--env-file", default=".env", help="指定环境配置文件，默认 .env")
    parser.add_argument("--background", action="store_true", help="后台启动；默认保持前台并显示日志，Ctrl+C 关闭服务")
    parser.add_argument("--serve", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    os.chdir(ROOT)
    envfile = Path(args.env_file).resolve()
    require(args.env_file == ".env" or envfile.is_file(), "指定的 --env-file 配置文件不存在。")
    load_environment(envfile)
    port = port_value(os.environ.get("MATHS_WEB_PORT", "8010"))
    try:
        timeout = float(os.environ.get("MATHS_STARTUP_TIMEOUT", "120"))
    except ValueError:
        raise LauncherError("MATHS_STARTUP_TIMEOUT 必须是秒数。") from None
    require(0 < timeout <= 3600, "MATHS_STARTUP_TIMEOUT 必须大于 0 且不超过 3600 秒。")
    if args.serve:
        serve(port)
        return
    directory, pidfile, logfile = paths()
    if args.action == "logs":
        logfile.touch(mode=0o600, exist_ok=True)
        os.execvp("tail", ["tail", "-n", "100", "-f", str(logfile)])
    # Serialize start/stop to avoid orphaning a process or overwriting its record.
    with (directory / "launcher.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        record = read_record(pidfile)
        if args.action == "status":
            if running(record):
                print(f"[运行中] 进程 {record['pid']}：http://127.0.0.1:{record['port']}/chat/")
            else:
                print("[状态] 没有发现本启动器管理的运行进程。")
            return
        if args.action == "stop":
            if running(record):
                os.kill(record["pid"], signal.SIGTERM)
                for _ in range(60):
                    if not running(record):
                        pidfile.unlink(missing_ok=True)
                        print("[停止完成] 后端进程已退出。")
                        return
                    time.sleep(0.5)
                raise LauncherError("后端仍在正常退出，请查看日志；未发送强制终止信号。")
            print("[状态] 没有发现本启动器管理的运行进程，没有停止其他服务。")
            return
        require(not running(record), "服务已在运行，请使用 status/logs 查看；重新启动前请先明确执行 stop。")
        with (logfile.open("a", encoding="utf-8") as log,
              redirect_stdout(Tee(sys.stdout, log)), redirect_stderr(Tee(sys.stderr, log))):
            logfile.chmod(0o600)
            log.write("\n=== 启动检查 " + time.strftime("%Y-%m-%d %H:%M:%S") + " ===\n")
            log.flush()
            try:
                print(f"[配置] 文件：{envfile}；终端已导出的变量优先。", flush=True)
                preflight(port)
            except Exception as error:
                print("[检查失败] " + (str(error) if isinstance(error, LauncherError)
                                       else diagnostic(error)), flush=True)
                print(f"[日志位置] {logfile}", flush=True)
                raise
            if args.action == "check":
                return
            print(f"[前端构建] 正在执行 npm run build，详细日志：{logfile}", flush=True)
            with stage("React 前端构建"):
                result = subprocess.run(["npm", "run", "build"], cwd=ROOT / "client", stdout=log, stderr=log)
                if result.returncode != 0:
                    message = f"前端构建失败，退出码 {result.returncode}；请查看：{logfile}"
                    print("[构建失败] " + message, flush=True)
                    raise LauncherError(message)
            print(f"[后端启动] 前端构建成功，启动 LangGraph，等待健康检查，最长 {timeout:g} 秒。", flush=True)
            child = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--serve",
                                      "--env-file", str(Path(args.env_file).resolve())],
                                     stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                     start_new_session=True, env=os.environ.copy())
            record = {"pid": child.pid, "identity": process_identity(child.pid), "port": port}
            pidfile.write_text(json.dumps(record), encoding="utf-8")
            pidfile.chmod(0o600)
            try:
                deadline = time.monotonic() + timeout
                last_hint = time.monotonic()
                last_reason = "尚未收到健康检查响应"
                while time.monotonic() < deadline:
                    if child.poll() is not None:
                        print(f"[启动失败] 后端进程 {child.pid} 已退出，退出码 {child.returncode}；详情：{logfile}", flush=True)
                        raise LauncherError(f"后端进程已退出，请查看：{logfile}")
                    try:
                        with urlopen(f"http://127.0.0.1:{port}/health/ready", timeout=2) as response:
                            ready = json.load(response)
                        if ready.get("status") == "ready" and ready.get("runtime_mode") == "langgraph_staged":
                            print(f"[启动成功] http://127.0.0.1:{port}/chat/\n[运行日志] {logfile}")
                            if not args.background:
                                # Other terminals must still be able to run status/stop.
                                fcntl.flock(lock, fcntl.LOCK_UN)
                                follow_backend(child, logfile)
                                fcntl.flock(lock, fcntl.LOCK_EX)
                                if read_record(pidfile) == record:
                                    pidfile.unlink(missing_ok=True)
                            return
                        last_reason = f"健康状态 {ready.get('status')}，运行模式 {ready.get('runtime_mode')}"
                    except (OSError, ValueError) as error:
                        last_reason = diagnostic(error)
                    if time.monotonic() - last_hint >= 10:
                        print(f"[等待就绪] 后端进程 {child.pid} 仍在运行；{last_reason}", flush=True)
                        last_hint = time.monotonic()
                    time.sleep(0.5)
                print(f"[启动超时] 已等待 {timeout:g} 秒，最后状态：{last_reason}；日志：{logfile}", flush=True)
                raise LauncherError(f"后端健康检查等待超时，请查看：{logfile}")
            except BaseException as error:
                if isinstance(error, KeyboardInterrupt):
                    print("\n[正在停止] 收到 Ctrl+C，正在正常关闭 LangGraph 和 Web 服务……", flush=True)
                if child.poll() is None:
                    child.terminate()
                    try:
                        child.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        print("[退出中] 后端仍在停止，已保留进程记录。", file=sys.stderr)
                        raise
                fcntl.flock(lock, fcntl.LOCK_EX)
                if read_record(pidfile) == record:
                    pidfile.unlink(missing_ok=True)
                if isinstance(error, KeyboardInterrupt):
                    print("[停止完成] LangGraph 和 Web 服务已关闭，运行日志已保留。", flush=True)
                    return
                raise


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[已取消] 启动检查或构建已中断。", file=sys.stderr)
        sys.exit(130)
    except Exception as error:
        message = str(error) if isinstance(error, LauncherError) else diagnostic(error)
        print("[错误] " + message, file=sys.stderr)
        sys.exit(1)
