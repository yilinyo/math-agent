import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import Mock

import pytest


spec = importlib.util.spec_from_file_location(
    "web_launcher", Path(__file__).resolve().parents[2] / "scripts/web_launcher.py")
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


@pytest.mark.parametrize("shell", ["bash", "sh"])
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
