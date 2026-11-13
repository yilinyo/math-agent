#!/usr/bin/env bash
# Support explicit `sh start.sh` before using Bash-only syntax.
if [ -z "${BASH_VERSION:-}" ]; then
    if ! command -v bash >/dev/null 2>&1; then
        printf '[错误] 启动脚本需要 Bash，请先安装 bash。\n' >&2
        exit 1
    fi
    exec bash "$0" "$@"
fi
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
if [[ -n "${MATHS_PYTHON:-}" ]]; then
    if ! command -v "$MATHS_PYTHON" >/dev/null 2>&1; then
        printf '[错误] 找不到 MATHS_PYTHON 指定的解释器：%s\n' "$MATHS_PYTHON" >&2
        exit 1
    fi
    printf '[环境选择] 使用指定 Python 解释器：%s\n' "$MATHS_PYTHON"
    exec "$MATHS_PYTHON" scripts/web_launcher.py "$@"
fi
if command -v conda >/dev/null 2>&1; then
    printf '[环境选择] 使用 Conda 环境：%s\n' "${MATHS_CONDA_ENV:-intern}"
    # 激活后直接交给 Python，避免 conda run 拦截 Ctrl+C 并额外报告异常。
    # Conda hooks may reference unset interactive variables such as PS1.
    set +u
    if ! CONDA_HOOK="$(conda shell.bash hook)"; then
        printf '[错误] 无法初始化 Conda，请检查 Conda 安装。\n' >&2
        exit 1
    fi
    eval "$CONDA_HOOK"
    if ! conda activate "${MATHS_CONDA_ENV:-intern}"; then
        printf '[错误] 无法激活 Conda 环境：%s，请确认环境已创建。\n' "${MATHS_CONDA_ENV:-intern}" >&2
        exit 1
    fi
    set -u
    exec python scripts/web_launcher.py "$@"
fi
if ! command -v python3 >/dev/null 2>&1; then
    printf '[错误] 未找到 Conda 或 python3，请先安装 Python >=3.11，或设置 MATHS_PYTHON。\n' >&2
    exit 1
fi
printf '[环境选择] 未找到 Conda，使用当前 python3；随后检查版本和依赖。\n'
exec python3 scripts/web_launcher.py "$@"
