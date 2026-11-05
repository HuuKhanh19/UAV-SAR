param([string]$DataRoot = (Join-Path $PSScriptRoot 'datasets'))
$ErrorActionPreference = 'Stop'
New-Item -ItemType Directory -Path $DataRoot -Force | Out-Null
$projectEnv = Join-Path $PSScriptRoot '.venv'
$projectPython = Join-Path $projectEnv 'Scripts\python.exe'
if (-not (Test-Path -LiteralPath $projectPython)) {
    python -m venv --system-site-packages $projectEnv
    if ($LASTEXITCODE -ne 0) { throw 'Could not create environment' }
}
$projectTemp = Join-Path $DataRoot 'tmp'
New-Item -ItemType Directory -Path $projectTemp -Force | Out-Null
$oldTemp, $oldTmp = $env:TEMP, $env:TMP
try {
    $env:TEMP, $env:TMP = $projectTemp, $projectTemp
    & $projectPython -m pip install --no-cache-dir torch==2.7.1 torchvision==0.22.1 --index-url https://download.pytorch.org/whl/cu128
    if ($LASTEXITCODE -ne 0) { throw 'PyTorch installation failed' }
    & $projectPython -m pip install --no-cache-dir -r (Join-Path $PSScriptRoot 'requirements.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed' }
    & $projectPython -c "import torch; print('PyTorch:', torch.__version__); print('CUDA available:', torch.cuda.is_available())"
} finally {
    $env:TEMP, $env:TMP = $oldTemp, $oldTmp
}
