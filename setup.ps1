$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    py -3.10 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.10 is required.' }
}
& $python -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw 'pip update failed.' }
& $python -m pip install torch==2.7.1 --index-url https://download.pytorch.org/whl/cu126
if ($LASTEXITCODE -ne 0) { throw 'CUDA PyTorch installation failed.' }
& $python -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
& $python generate.py --check
if ($LASTEXITCODE -ne 0) { throw 'GPU verification failed.' }
& $python -m pip check
if ($LASTEXITCODE -ne 0) { throw 'Dependency verification failed.' }
& $python -m pip freeze | Set-Content -LiteralPath (Join-Path $PSScriptRoot 'installed-versions.txt') -Encoding utf8
Write-Host 'Setup complete. Double-click Run.bat to generate a video.'

