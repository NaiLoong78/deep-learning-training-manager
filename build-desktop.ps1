$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
$npm = 'C:\Program Files\nodejs\npm.cmd'

if (-not (Test-Path -LiteralPath $python)) {
    throw '请先运行 setup.bat 创建项目虚拟环境。'
}

& $python -m pip install -r (Join-Path $projectRoot 'requirements-desktop.txt')
if ($LASTEXITCODE -ne 0) { throw '桌面打包依赖安装失败。' }

Push-Location (Join-Path $projectRoot 'frontend')
try {
    & $npm run build
    if ($LASTEXITCODE -ne 0) { throw 'Vue 前端构建失败。' }
}
finally {
    Pop-Location
}

Push-Location $projectRoot
try {
    & $python -m PyInstaller --noconfirm --clean 'DeepLearningManager.spec'
    if ($LASTEXITCODE -ne 0) { throw 'EXE 打包失败。' }
}
finally {
    Pop-Location
}

Write-Host "桌面应用已生成：$projectRoot\dist\DeepLearningManager.exe" -ForegroundColor Green
