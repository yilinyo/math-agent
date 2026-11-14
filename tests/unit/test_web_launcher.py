import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
import venv
from unittest.mock import Mock
from urllib.request import urlopen

import pytest


spec = importlib.util.spec_from_file_location(
    "web_launcher", Path(__file__).resolve().parents[2] / "scripts/web_launcher.py")
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


@pytest.mark.parametrize("shell", ["bash", "sh"])
@pytest.mark.skipif(sys.platform == "win32", reason="POSIX executable shell fixtures; Windows entry is tested separately")
def test_conda_hooks_can_read_unset_prompt(shell, tmp_path, monkeypatch):
    conda = tmp_path / "conda"
    conda.write_text(
        "#!/bin/sh\n"
        "printf '%s\\n' 'printf \"%s\" \"$PS1\" >/dev/null' "
        "'conda() { printf \"%s\" \"$PS1\" >/dev/null; }'\n"
    )
    conda.chmod(0o755)
    python = tmp_path / "python"
    python.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n')
    python.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])
    for variable in ("PS1", "MATHS_PYTHON", "BASH_ENV", "ENV"):
        monkeypatch.delenv(variable, raising=False)
    result = subprocess.run(
        [shell, str(launcher.ROOT / "start.sh"), "--help"],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert "scripts/web_launcher.py\n--help" in result.stdout


def test_dotenv_is_data_and_exported_values_win(tmp_path, monkeypatch):
    config = tmp_path / "config.env"
    config.write_text('MATHS_WEB_PORT=18999\nINTERN_API_KEY="$(touch injected)"\n')
    monkeypatch.setenv("MATHS_WEB_PORT", "18001")
    monkeypatch.delenv("INTERN_API_KEY", raising=False)
    launcher.load_environment(config)
    assert launcher.os.environ["MATHS_WEB_PORT"] == "18001"
    assert launcher.os.environ["INTERN_API_KEY"] == "$(touch injected)"
    assert not (tmp_path / "injected").exists()


def test_recursive_requirements_report_wrong_versions(tmp_path, monkeypatch):
    (tmp_path / "requirements.txt").write_text('-r child.txt\n')
    (tmp_path / "child.txt").write_text('example==2\nignored; python_version < "3"\n')
    monkeypatch.setattr(launcher.importlib.metadata, "version", lambda name: "1")
    assert launcher.check_requirements(tmp_path / "requirements.txt") == ["example==2（已安装 1）"]


def test_stop_does_not_signal_reused_pid(tmp_path, monkeypatch):
    record = tmp_path / "process.json"
    record.write_text(json.dumps({"pid": 12345, "identity": "old process", "port": 18001}))
    monkeypatch.setenv("MATHS_WEB_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(launcher, "load_environment", lambda path: None)
    monkeypatch.setattr(launcher, "process_identity", lambda pid: "unrelated process")
    kill = Mock()
    monkeypatch.setattr(launcher.os, "kill", kill)
    monkeypatch.setattr(launcher.sys, "argv", ["web_launcher", "stop"])
    launcher.main()
    kill.assert_not_called()


def test_backend_defaults_to_all_interfaces(monkeypatch):
    from agent_platform import __main__ as backend
    from agent_platform import app

    run = Mock()
    monkeypatch.setattr(backend.uvicorn, "run", run)
    monkeypatch.setattr(app, "create_app", lambda **kwargs: object())
    monkeypatch.setattr(sys, "argv", ["agent_platform"])
    backend.main()
    assert run.call_args.kwargs["host"] == "0.0.0.0"


def test_missing_key_fails_before_runtime_construction(monkeypatch):
    monkeypatch.setattr(launcher, "check_requirements", lambda path: [])
    monkeypatch.setattr(launcher.subprocess, "run", lambda *a, **k: Mock(returncode=0, stdout="", stderr=""))
    monkeypatch.delenv("INTERN_API_KEY", raising=False)
    with pytest.raises(launcher.LauncherError, match="缺少 INTERN_API_KEY"):
        launcher.preflight(18001)


@pytest.mark.parametrize("port", ["0", "65536", "-1"])
def test_invalid_port_is_rejected(port):
    with pytest.raises(launcher.LauncherError):
        launcher.port_value(port)


def test_mismatched_index_reports_counts_before_model_loading(tmp_path, monkeypatch, capsys):
    import numpy as np

    data = tmp_path / "strategy_data"
    model = tmp_path / "strategyrag/Qwen3-Embedding-0.6B"
    data.mkdir()
    model.mkdir(parents=True)
    (model / "model.safetensors").write_bytes(b"not loaded")
    (data / "strategy_meta.json").write_text(json.dumps([{"id": i} for i in range(3)]))
    (data / "strategy_lexical_index.json").write_text(json.dumps({"cards": [{}, {}, {}]}))
    (data / "strategy_index.json").write_text(json.dumps({"num_strategies": 2}))
    np.save(data / "strategy_embeddings.npy", np.zeros((2, 1024), dtype=np.float32))
    monkeypatch.setattr(launcher, "ROOT", tmp_path)
    from reasoning_agent import strategy_retrieval
    load_model = Mock()
    monkeypatch.setattr(strategy_retrieval, "get_shared_strategy_retriever", load_model)
    with pytest.raises(launcher.LauncherError, match="策略 3 条，向量 2 条"):
        launcher.inspect_strategy_resources("hybrid")
    load_model.assert_not_called()
    output = capsys.readouterr().out
    assert "当前策略总数：3 条" in output
    assert "词法索引记录：3 条" in output


def test_diagnostic_hides_credentials_and_url(monkeypatch):
    monkeypatch.setenv("INTERN_API_KEY", "private-model-key")
    message = launcher.diagnostic(ValueError("private-model-key https://user:pass@example.test/?key=secret failed"))
    assert "private-model-key" not in message
    assert "user:pass" not in message
    assert "secret" not in message
    assert "ValueError" in message and "failed" in message


def test_vector_probe_satisfies_real_retrieval_protocol():
    from reasoning_agent.strategy_retrieval import normalize_retrieval_text

    normalized = normalize_retrieval_text(launcher.VECTOR_PROBE)
    assert "Domain:" in normalized and "Goal:" in normalized and "Objects:" in normalized


def test_console_and_log_receive_same_timestamped_split_lines():
    console, log = io.StringIO(), io.StringIO()
    tee = launcher.Tee(console, log)
    tee.write("[检查] ")
    tee.write("开始\n下一行\n")
    assert console.getvalue() == log.getvalue()
    lines = log.getvalue().splitlines()
    assert len(lines) == 2
    assert lines[0].endswith("[检查] 开始")
    assert lines[1].endswith("下一行")
    assert all(line.startswith("[20") for line in lines)


def test_failed_stage_reports_elapsed_time(capsys):
    with pytest.raises(ValueError):
        with launcher.stage("测试阶段"):
            raise ValueError("synthetic failure")
    output = capsys.readouterr().out
    assert "[阶段开始] 测试阶段" in output
    assert "[阶段失败] 测试阶段，耗时" in output
    assert "[阶段完成]" not in output


def test_foreground_stream_does_not_duplicate_log_file(tmp_path, monkeypatch):
    logfile = tmp_path / "runtime.log"
    console = io.StringIO()
    with logfile.open("a", encoding="utf-8") as log:
        monkeypatch.setattr(launcher.sys, "stdout", launcher.Tee(console, log))
        monkeypatch.setattr(launcher.time, "sleep", lambda seconds: None)

        def write_output():
            with logfile.open("a", encoding="utf-8") as backend:
                backend.write("backend-live-message\n")
            return None

        child = Mock()
        states = iter([None, 0])
        child.poll.side_effect = lambda: write_output() if next(states) is None else 0
        launcher.follow_backend(child, logfile)
    assert console.getvalue().count("backend-live-message") == 1
    assert logfile.read_text().count("backend-live-message") == 1
    assert console.getvalue().count("[前台运行]") == 1


def test_foreground_reports_unexpected_backend_exit(tmp_path, capsys):
    logfile = tmp_path / "runtime.log"
    logfile.touch()
    with pytest.raises(launcher.LauncherError, match="退出码 7"):
        launcher.follow_backend(Mock(poll=Mock(return_value=7)), logfile)
    assert "[前台运行]" in capsys.readouterr().out


def test_launcher_lock_excludes_other_processes_and_can_be_reacquired(tmp_path):
    lock_path = tmp_path / "owner.lock"
    probe = (
        "import sys; from scripts.launcher_platform import lock_file; "
        "stream = open(sys.argv[1], 'a+b')\n"
        "try: lock_file(stream, blocking=False)\n"
        "except BlockingIOError: sys.exit(23)\n"
    )
    with lock_path.open("a+b") as stream:
        launcher.lock_file(stream)
        launcher.lock_file(stream)
        blocked = subprocess.run([sys.executable, "-c", probe, str(lock_path)], cwd=launcher.ROOT, timeout=10)
        assert blocked.returncode == 23
        launcher.unlock_file(stream)
        available = subprocess.run([sys.executable, "-c", probe, str(lock_path)], cwd=launcher.ROOT, timeout=10)
        assert available.returncode == 0


@pytest.mark.skipif(sys.platform != "win32", reason="Windows native process identity")
def test_windows_identity_is_stable_and_disappears_after_exit():
    assert launcher.process_identity(os.getpid()) == launcher.process_identity(os.getpid())
    assert launcher.process_identity(os.getpid())
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait(timeout=10)
    assert launcher.process_identity(child.pid) == ""


def test_windows_npm_uses_node_without_a_command_shell(tmp_path, monkeypatch):
    installation = tmp_path / "Node With Spaces"
    cli = installation / "node_modules/npm/bin/npm-cli.js"
    cli.parent.mkdir(parents=True)
    cli.touch()
    node = str(installation / "node.exe")
    monkeypatch.setattr(launcher, "WINDOWS", True)
    monkeypatch.setattr(launcher.shutil, "which", lambda name: node if name == "node" else str(installation / "npm.cmd"))
    assert launcher.npm_command() == [node, str(cli)]


@pytest.mark.skipif(sys.platform != "win32", reason="Native Windows PowerShell and Git Bash entrypoints")
def test_windows_entries_forward_arguments(monkeypatch):
    monkeypatch.setenv("MATHS_PYTHON", sys.executable)
    git = shutil.which("git")
    assert git, "Git for Windows is required for the Bash entrypoint test"
    bash = Path(git).resolve().parents[1] / "bin/bash.exe"
    assert bash.is_file()
    for command in (
        [str(bash), ".\\start.sh", "--help"],
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "start.ps1", "--help"],
    ):
        result = subprocess.run(command, cwd=launcher.ROOT, capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=20)
        assert result.returncode == 0, result.stdout + result.stderr
        assert "--env-file" in result.stdout and "--background" in result.stdout


@pytest.mark.skipif(sys.platform != "win32", reason="Windows virtual environment discovery")
@pytest.mark.parametrize("directory", [".venv-platform", ".venv", "venv"])
def test_windows_entries_prefer_local_venv_over_broken_conda(tmp_path, monkeypatch, directory):
    project = tmp_path / "Project With Spaces"
    project.mkdir()
    for entry in ("start.sh", "start.ps1"):
        shutil.copyfile(launcher.ROOT / entry, project / entry)
    (project / "scripts").mkdir()
    (project / "scripts/web_launcher.py").write_text(
        "import sys; print('SELECTED=' + sys.executable); print('ARGS=' + repr(sys.argv[1:]))\n",
        encoding="utf-8",
    )
    venv.EnvBuilder(with_pip=False).create(project / directory)
    monkeypatch.delenv("MATHS_PYTHON", raising=False)
    monkeypatch.delenv("MATHS_CONDA_ENV", raising=False)
    monkeypatch.setenv("CONDA_EXE", "/cygdrive/z/missing/conda.exe")
    git = shutil.which("git")
    bash = Path(git).resolve().parents[1] / "bin/bash.exe"
    for command in (
        [str(bash), "start.sh", "--env-file", "config with spaces.env"],
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "start.ps1",
         "--env-file", "config with spaces.env"],
    ):
        result = subprocess.run(command, cwd=project, capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=20)
        assert result.returncode == 0, result.stdout + result.stderr
        assert str(project / directory / "Scripts/python.exe").lower() in result.stdout.lower()
        assert "['--env-file', 'config with spaces.env']" in result.stdout


@pytest.mark.skipif(sys.platform != "win32", reason="Windows graceful shutdown without POSIX signals")
def test_windows_stop_request_shuts_uvicorn_down_and_ignores_stale_identity(tmp_path):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    envfile = tmp_path / "test.env"
    envfile.write_text("", encoding="utf-8")
    stopfile = tmp_path / "stop.request"
    code = (
        "import importlib.util, sys; from fastapi import FastAPI; import uvicorn; "
        f"spec = importlib.util.spec_from_file_location('launcher', {str(launcher.ROOT / 'scripts/web_launcher.py')!r}); "
        "launcher = importlib.util.module_from_spec(spec); spec.loader.exec_module(launcher); "
        "app = FastAPI(); app.get('/health')(lambda: {'status': 'ready'}); "
        "launcher.serve = lambda port: uvicorn.run(app, host='127.0.0.1', port=port); "
        f"sys.argv = ['launcher', '--serve', '--env-file', {str(envfile)!r}]; launcher.main()"
    )
    environment = {**os.environ, "MATHS_WEB_STATE_DIR": str(tmp_path), "MATHS_WEB_PORT": str(port),
                   "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"}
    with (tmp_path / "backend.log").open("w", encoding="utf-8") as log:
        child = subprocess.Popen([sys.executable, "-c", code], cwd=launcher.ROOT, env=environment,
                                 stdout=log, stderr=log, **launcher.child_process_options())
        try:
            for _ in range(100):
                assert child.poll() is None, (tmp_path / "backend.log").read_text(encoding="utf-8")
                try:
                    with urlopen(f"http://127.0.0.1:{port}/health", timeout=0.2) as response:
                        assert json.load(response)["status"] == "ready"
                    break
                except OSError:
                    time.sleep(0.1)
            else:
                pytest.fail("isolated backend did not start")
            record = launcher.read_record(tmp_path / "backend.identity.json")
            assert launcher.running(record)
            launcher.request_stop({**record, "identity": "stale identity"}, stopfile)
            time.sleep(0.6)
            assert child.poll() is None
            launcher.request_stop(record, stopfile)
            child.wait(timeout=10)
        finally:
            if child.poll() is None:
                child.terminate()
                child.wait(timeout=10)
    output = (tmp_path / "backend.log").read_text(encoding="utf-8")
    assert "Application shutdown complete" in output
    assert "Finished server process" in output
