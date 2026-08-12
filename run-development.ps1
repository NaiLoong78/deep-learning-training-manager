$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$windowsVenvPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
$msysVenvPython = Join-Path $projectRoot '.venv\bin\python.exe'
$venvPython = if (Test-Path -LiteralPath $windowsVenvPython) { $windowsVenvPython } else { $msysVenvPython }
if (-not (Test-Path -LiteralPath $venvPython)) { throw 'Run setup.ps1 first.' }

$backend = Start-Process -PassThru -WindowStyle Hidden -FilePath $venvPython -ArgumentList @(
    '-m', 'uvicorn', 'app.main:app', '--app-dir', (Join-Path $projectRoot 'backend'), '--reload', '--port', '8000'
)
try {
    Push-Location (Join-Path $projectRoot 'frontend')
    npm run dev
}
finally {
    Pop-Location
    Stop-Process -Id $backend.Id -ErrorAction SilentlyContinue
}
