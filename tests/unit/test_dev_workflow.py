import os
from pathlib import Path
import subprocess
import sys

import pytest
import yaml


@pytest.mark.parametrize("start_exit", [0, 42])
def test_script_deployment_restarts_intern_and_preserves_backend(tmp_path, start_exit):
    workflow = yaml.load(
        (Path(__file__).resolve().parents[2] / ".github/workflows/platform.yml").read_text(),
        Loader=yaml.BaseLoader,
    )
    assert set(workflow["on"]) == {"push", "workflow_dispatch"}
    assert workflow["on"]["push"]["branches"] == ["dev"]
    job = workflow["jobs"]["startup"]
    assert job["if"] == "github.ref == 'refs/heads/dev'"
    assert all("uses" not in step for step in job["steps"])
    command = job["steps"][-1]["run"]
    assert '/opt/conda/envs/intern/bin/python' in job['env']['MATHS_PYTHON']
    python = tmp_path / "python"
    python.write_text('#!/bin/sh\nexit 0\n')
    python.chmod(0o755)
    (tmp_path / "start.sh").write_text(
        'printf "%s|%s|%s\\n" "$MATHS_PYTHON" '
        '"${RUNNER_TRACKING_ID-unset}" "$*" >> "$CALL_LOG"\n'
        'if [ "$1" = --background ]; then exit "$START_EXIT"; fi\n'
    )
    log = tmp_path / "calls"
    result = subprocess.run(
        ["bash", "-c", command], cwd=tmp_path, capture_output=True, text=True,
        env={**os.environ, "INTERN_API_KEY": "test-key",
             "MATHS_PYTHON": str(python), "RUNNER_TRACKING_ID": "runner-id",
             "CALL_LOG": str(log), "START_EXIT": str(start_exit)},
        timeout=10,
    )
    assert result.returncode == start_exit, result.stderr
    expected = [f"{python}|runner-id|stop", f"{python}||--background"]
    if not start_exit:
        expected.append(f"{python}|runner-id|status")
    assert log.read_text().splitlines() == expected


@pytest.mark.parametrize(
    ("secret", "local", "expected"),
    [("secret-value", "local-value", "secret-value"), ("", "local-value", "local-value"),
     ("", "", None)],
)
@pytest.mark.parametrize("override", [False, True])
def test_deployment_key_uses_secret_or_local_env_before_stopping(tmp_path, secret, local, expected, override):
    workflow = yaml.load(
        (Path(__file__).resolve().parents[2] / ".github/workflows/platform.yml").read_text(),
        Loader=yaml.BaseLoader,
    )
    command = workflow["jobs"]["startup"]["steps"][-1]["run"]
    assert "||" not in workflow["jobs"]["startup"]["env"]["MATHS_WEB_PORT"]
    (tmp_path / ".env").write_text(
        f"INTERN_API_KEY={local}\nMATHS_WEB_PORT=9123\nLANGSMITH_TRACING=true\n")
    (tmp_path / "start.sh").write_text(
        '"$MATHS_PYTHON" -c \'import os; from dotenv import load_dotenv; '
        'load_dotenv(".env", override=False); '
        'assert os.environ["INTERN_API_KEY"] == os.environ["EXPECTED_KEY"]; '
        'assert os.environ["MATHS_WEB_PORT"] == os.environ["EXPECTED_PORT"]; '
        'assert os.environ["LANGSMITH_TRACING"] == os.environ["EXPECTED_TRACING"]\'\n'
        'printf "%s\\n" "$*" >> "$CALL_LOG"\n'
    )
    log = tmp_path / "calls"
    result = subprocess.run(
        ["bash", "-c", command], cwd=tmp_path, capture_output=True, text=True,
        env={**os.environ, "MATHS_PYTHON": sys.executable,
             "INTERN_API_KEY": secret, "EXPECTED_KEY": expected or "",
             "MATHS_WEB_PORT": "9020" if override else "",
             "LANGSMITH_TRACING": "false" if override else "",
             "EXPECTED_PORT": "9020" if override else "9123",
             "EXPECTED_TRACING": "false" if override else "true",
             "CALL_LOG": str(log)}, timeout=10,
    )
    if expected is None:
        assert result.returncode != 0
        assert not log.exists()
    else:
        assert result.returncode == 0, result.stderr
        assert log.read_text().splitlines() == ["stop", "--background", "status"]
    assert "secret-value" not in result.stdout + result.stderr
    assert "local-value" not in result.stdout + result.stderr
