param([switch]$Stop)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root "backend"
$frontend = Join-Path $root "frontend"

$pidFile = Join-Path $backend "ecc-backend.pid"
$frontendPidFile = Join-Path $frontend "ecc-frontend.pid"

$backendLog = Join-Path $backend "ecc-backend.log"
$backendErrorLog = Join-Path $backend "ecc-backend-error.log"
$frontendLog = Join-Path $frontend "ecc-frontend.log"
$frontendErrorLog = Join-Path $frontend "ecc-frontend-error.log"

$python = Join-Path $root "venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Host "Project Python environment not found: $python" -ForegroundColor Red
    exit 1
}
$desktopApp = Join-Path $frontend "src-tauri\target\release\ecc-frontend.exe"

function Test-Backend {
    try {
        $response = Invoke-WebRequest `
            -Uri "http://127.0.0.1:8000/" `
            -UseBasicParsing `
            -TimeoutSec 2

        return $response.StatusCode -eq 200
    }
    catch {
        return $false
    }
}

function Test-Frontend {
    try {
        $response = Invoke-WebRequest `
            -Uri "http://localhost:1420/" `
            -UseBasicParsing `
            -TimeoutSec 2

        return $response.StatusCode -eq 200
    }
    catch {
        return $false
    }
}

function Stop-ProcessFromPidFile($file) {
    if (-not (Test-Path $file)) {
        return
    }

    try {
        $processId = [int](Get-Content $file -Raw)
        $process = Get-Process -Id $processId -ErrorAction SilentlyContinue

        if ($process) {
            # Kill the whole process tree (e.g. cmd.exe -> npm -> vite/node)
            # so child processes are not left orphaned.
            $null = & taskkill.exe /PID $processId /T /F 2>$null

            if ($LASTEXITCODE -ne 0) {
                Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
            }
        }
    }
    catch {
    }

    Remove-Item $file -Force -ErrorAction SilentlyContinue
}

if ($Stop) {
    Stop-ProcessFromPidFile $frontendPidFile
    Stop-ProcessFromPidFile $pidFile

    Write-Host ""
    Write-Host "Engineering Command Center stopped." -ForegroundColor Yellow
    exit 0
}

Write-Host "==================================================" -ForegroundColor Cyan
Write-Host " Starting Engineering Command Center..." -ForegroundColor Green
Write-Host "==================================================" -ForegroundColor Cyan

# --------------------------------------------------
# 1. Backend
# --------------------------------------------------

if (-not (Test-Backend)) {

    if (-not (Test-Path $python)) {
        Write-Host "Python virtual environment not found:" -ForegroundColor Red
        Write-Host $python
        exit 1
    }

    Write-Host "[1/3] Starting backend..." -ForegroundColor Cyan

    $backendProc = Start-Process `
        -FilePath $python `
        -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000" `
        -WorkingDirectory $backend `
        -PassThru `
        -WindowStyle Hidden `
        -RedirectStandardOutput $backendLog `
        -RedirectStandardError $backendErrorLog

    Set-Content -Path $pidFile -Value $backendProc.Id -NoNewline

    $ready = $false

    foreach ($attempt in 1..20) {
        Start-Sleep -Milliseconds 500

        if (Test-Backend) {
            $ready = $true
            break
        }
    }

    if (-not $ready) {
        Write-Host "Backend failed to start." -ForegroundColor Red
        Write-Host "Check:" -ForegroundColor Yellow
        Write-Host $backendErrorLog
        exit 1
    }
}

Write-Host "[OK] Backend running on port 8000" -ForegroundColor Green

# --------------------------------------------------
# 2. Frontend
# --------------------------------------------------

if (-not (Test-Frontend)) {

    Write-Host "[2/3] Starting frontend..." -ForegroundColor Cyan

    $frontendProc = Start-Process `
        -FilePath "cmd.exe" `
        -ArgumentList "/c", "npm.cmd", "run", "dev" `
        -WorkingDirectory $frontend `
        -PassThru `
        -WindowStyle Hidden `
        -RedirectStandardOutput $frontendLog `
        -RedirectStandardError $frontendErrorLog

    Set-Content -Path $frontendPidFile -Value $frontendProc.Id -NoNewline

    $ready = $false

    foreach ($attempt in 1..20) {
        Start-Sleep -Milliseconds 500

        if (Test-Frontend) {
            $ready = $true
            break
        }
    }

    if (-not $ready) {
        Write-Host "Frontend failed to start." -ForegroundColor Red
        Write-Host "Check:" -ForegroundColor Yellow
        Write-Host $frontendErrorLog
        exit 1
    }
}

Write-Host "[OK] Frontend running on port 1420" -ForegroundColor Green

# --------------------------------------------------
# 3. Desktop application
# --------------------------------------------------

Write-Host "[3/3] Launching desktop application..." -ForegroundColor Cyan

if (-not (Test-Path $desktopApp)) {
    Write-Host "Desktop application not found:" -ForegroundColor Red
    Write-Host $desktopApp
    exit 1
}

Start-Process -FilePath $desktopApp

Write-Host ""
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host " Engineering Command Center is READY!" -ForegroundColor Green
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Desktop app launched." -ForegroundColor White
Write-Host "Backend:  http://127.0.0.1:8000" -ForegroundColor White
Write-Host "Frontend: http://localhost:1420" -ForegroundColor White
Write-Host ""
