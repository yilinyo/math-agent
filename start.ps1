$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

$launcherPython = $env:MATHS_PYTHON
if (-not $launcherPython -and -not $env:MATHS_CONDA_ENV) {
    foreach ($candidate in @('.venv-platform\Scripts\python.exe', '.venv\Scripts\python.exe', 'venv\Scripts\python.exe')) {
        if (Test-Path -LiteralPath $candidate) {
            $launcherPython = (Resolve-Path -LiteralPath $candidate).Path
            break
        }
    }
}
if ($launcherPython) {
    Write-Host "[Python] $launcherPython"
    & $launcherPython scripts/web_launcher.py @args
} elseif (Get-Command conda.exe -ErrorAction SilentlyContinue) {
    $launcherCondaEnv = if ($env:MATHS_CONDA_ENV) { $env:MATHS_CONDA_ENV } else { 'intern' }
    & conda.exe run --no-capture-output -n $launcherCondaEnv python scripts/web_launcher.py @args
} else {
    if ($env:MATHS_CONDA_ENV) {
        throw 'conda.exe was not found; set MATHS_PYTHON to use a local virtual environment.'
    }
    & python scripts/web_launcher.py @args
}
exit $LASTEXITCODE
