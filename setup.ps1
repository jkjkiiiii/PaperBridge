$ErrorActionPreference='Stop'
Set-Location -LiteralPath $PSScriptRoot
if(-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) { python -m venv .venv }
$requirementsFile=if(Test-Path -LiteralPath 'requirements.lock.txt') {'requirements.lock.txt'} else {'requirements.txt'}
& '.\.venv\Scripts\python.exe' -m pip install -r $requirementsFile
if($LASTEXITCODE -ne 0) { throw 'Python 依赖安装失败' }
Push-Location web
try {
    npm ci
    if($LASTEXITCODE -ne 0) { throw '前端依赖安装失败' }
    npm run build
    if($LASTEXITCODE -ne 0) { throw '前端构建失败' }
} finally { Pop-Location }
Write-Output '安装完成。运行 .\run.ps1 -OpenBrowser 启动。'
