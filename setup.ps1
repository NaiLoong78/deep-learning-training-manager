$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$windowsVenvPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
$msysVenvPython = Join-Path $projectRoot '.venv\bin\python.exe'

Write-Host '=== Deep Learning Manager: first-time setup ===' -ForegroundColor Cyan

function Find-CompatiblePython {
    $candidates = @()
    $candidates += Get-ChildItem -Path (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python*\python.exe') -ErrorAction SilentlyContinue | Select-Object -ExpandProperty FullName
    $candidates += Get-ChildItem -Path 'C:\Program Files\Python*\python.exe' -ErrorAction SilentlyContinue | Select-Object -ExpandProperty FullName
    $codexPython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
    if (Test-Path -LiteralPath $codexPython) { $candidates += $codexPython }
    $pathPython = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($pathPython) { $candidates += $pathPython.Source }

    foreach ($candidate in ($candidates | Select-Object -Unique)) {
        $check = & $candidate -c "import sys,sysconfig; print(f'{sys.version_info.major}.{sys.version_info.minor}|{sysconfig.get_platform()}')" 2>$null
        if ($LASTEXITCODE -eq 0 -and $check -notmatch 'mingw') {
            $version = [version]($check -split '\|')[0]
            if ($version -ge [version]'3.10') { return $candidate }
        }
    }
    return $null
}

if (-not (Test-Path -LiteralPath $windowsVenvPython)) {
    if (Test-Path -LiteralPath $msysVenvPython) {
        $backupName = '.venv-incompatible-' + (Get-Date -Format 'yyyyMMdd-HHmmss')
        Move-Item -LiteralPath (Join-Path $projectRoot '.venv') -Destination (Join-Path $projectRoot $backupName)
        Write-Host "An incompatible MSYS2 environment was preserved as $backupName" -ForegroundColor Yellow
    }
    $basePython = Find-CompatiblePython
    if (-not $basePython) {
        throw 'No compatible 64-bit Windows Python 3.10+ was found. Install it from https://www.python.org/downloads/windows/ and retry. MSYS2 Python is not supported.'
    }
    Write-Host '[1/4] Creating an isolated Python environment...'
    & $basePython -m venv (Join-Path $projectRoot '.venv')
}
$venvPython = $windowsVenvPython

Write-Host '[2/4] Installing backend dependencies...'
& $venvPython -m pip install --upgrade pip
& $venvPython -m pip install -r (Join-Path $projectRoot 'backend\requirements.txt')

Write-Host '[3/4] Installing frontend dependencies...'
Push-Location (Join-Path $projectRoot 'frontend')
try {
    npm install
    Write-Host '[4/4] Building the Vue application...'
    npm run build
}
finally {
    Pop-Location
}

Write-Host ''
Write-Host 'Setup completed. Double-click start.bat to launch the application.' -ForegroundColor Green
Read-Host 'Press Enter to exit'
