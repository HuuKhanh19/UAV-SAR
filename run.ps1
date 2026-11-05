# Call from the repository root. Arguments are passed unchanged to run.py.
$ErrorActionPreference = 'Stop'
$projectPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $projectPython)) {
    throw 'Project environment not found. Run setup.ps1 first.'
}
Push-Location $PSScriptRoot
try {
    $env:PYTHONUNBUFFERED = '1'
    $env:YOLO_CONFIG_DIR = Join-Path $PSScriptRoot 'datasets\ultralytics_settings'
    New-Item -ItemType Directory -Path $env:YOLO_CONFIG_DIR -Force | Out-Null
    & $projectPython -u run.py @args
    if ($LASTEXITCODE -ne 0) { throw "Python exited with code $LASTEXITCODE" }
} finally {
    Pop-Location
}
