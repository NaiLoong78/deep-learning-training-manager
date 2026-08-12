$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$windowsVenvPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
$msysVenvPython = Join-Path $projectRoot '.venv\bin\python.exe'
$venvPython = if (Test-Path -LiteralPath $windowsVenvPython) { $windowsVenvPython } else { $msysVenvPython }
$frontendIndex = Join-Path $projectRoot 'frontend\dist\index.html'

if (-not (Test-Path -LiteralPath $venvPython)) {
    Write-Host 'Not installed. Please run setup.bat first.' -ForegroundColor Yellow
    Read-Host 'Press Enter to exit'
    exit 1
}
if (-not (Test-Path -LiteralPath $frontendIndex)) {
    Write-Host 'Frontend is not built. Please run setup.bat first.' -ForegroundColor Yellow
    Read-Host 'Press Enter to exit'
    exit 1
}

$env:PYTHONPATH = Join-Path $projectRoot 'backend'
Set-Location $projectRoot
$server = Start-Process -PassThru -NoNewWindow -FilePath $venvPython -ArgumentList @(
    '-m', 'uvicorn', 'app.main:app', '--app-dir', (Join-Path $projectRoot 'backend'),
    '--host', '127.0.0.1', '--port', '8000'
)

try {
    $ready = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        if ($server.HasExited) { throw "Server exited with code $($server.ExitCode)." }
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8000/api/health' -TimeoutSec 1
            if ($response.StatusCode -eq 200) { $ready = $true; break }
        }
        catch {
            Start-Sleep -Milliseconds 300
        }
    }
    if (-not $ready) { throw 'Server did not become ready on port 8000.' }
    Write-Host 'Deep Learning Manager is running: http://127.0.0.1:8000' -ForegroundColor Green
    Write-Host 'Close this window to stop the service.'
    if ($env:DL_MANAGER_NO_BROWSER -ne '1') {
        Start-Process 'http://127.0.0.1:8000'
    }
    Wait-Process -Id $server.Id
}
finally {
    if ($server -and -not $server.HasExited) {
        Stop-Process -Id $server.Id -ErrorAction SilentlyContinue
    }
}
