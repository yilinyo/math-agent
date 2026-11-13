import os
from pathlib import Path
import subprocess

import pytest
import yaml


@pytest.mark.parametrize("start_exit", [0, 42])
def test_script_deployment_restarts_intern_and_preserves_backend(tmp_path, start_exit):
    workflow = yaml.load(
        (Path(__file__).resolve().parents[2] / ".github/workflows/platform.yml").read_text(),
        Loader=yaml.BaseLoader,
    )
    assert set(workflow["on"]) == {"workflow_dispatch"}
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
