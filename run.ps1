param([switch]$OpenBrowser)
$ErrorActionPreference='Stop'
Set-Location -LiteralPath $PSScriptRoot
$env:PYTHONUTF8 = '1'
$pythonExecutable=Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if(-not (Test-Path -LiteralPath $pythonExecutable)) { $pythonExecutable=(Get-Command python).Source }
if(-not (Test-Path -LiteralPath 'web\dist\index.html')) { throw '请先执行 setup.ps1 构建前端。' }
if($OpenBrowser) { Start-Process 'http://127.0.0.1:17865' }
& $pythonExecutable -m uvicorn server.app:app --host 127.0.0.1 --port 17865
