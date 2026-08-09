param([switch]$Stop)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root 'backend'
$frontend = Join-Path $root 'frontend'
$pidFile = Join-Path $backend 'ecc-backend.pid'
$frontendPidFile = Join-Path $frontend 'ecc-frontend.pid'
$backendLog = Join-Path $backend 'ecc-backend.log'
$backendErrorLog = Join-Path $backend 'ecc-backend-error.log'
$frontendLog = Join-Path $frontend 'ecc-frontend.log'
$frontendErrorLog = Join-Path $frontend 'ecc-frontend-error.log'

function Stop-EccBackend {
    if (-not (Test-Path $pidFile)) { return }
    $processId = [int](Get-Content $pidFile -Raw)
    $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
    if ($process) { Stop-Process -Id $processId -Force }
    Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
}

function Stop-EccFrontend {
    if (-not (Test-Path $frontendPidFile)) { return }
    $processId = [int](Get-Content $frontendPidFile -Raw)
    $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
    if ($process) { Stop-Process -Id $processId -Force }
    Remove-Item $frontendPidFile -Force -ErrorAction SilentlyContinue
}

function Test-EccBackend {
    try {
        $response = Invoke-WebRequest -Uri 'http://127.0.0.1:8000/' -UseBasicParsing -TimeoutSec 2
        return $response.StatusCode -eq 200
    } catch {
        return $false
    }
}

function Test-EccFrontend {
    try {
        $response = Invoke-WebRequest -Uri 'http://localhost:1420/' -UseBasicParsing -TimeoutSec 2
        return $response.StatusCode -eq 200
    } catch {
        return $false
    }
}

if ($Stop) {
    Stop-EccFrontend
    Stop-EccBackend
    Write-Host 'Engineering Command Center stopped.' -ForegroundColor Yellow
    exit 0
}

Write-Host '==================================================' -ForegroundColor Cyan
Write-Host ' Starting Engineering Command Center...' -ForegroundColor Green
Write-Host '==================================================' -ForegroundColor Cyan

# 1. Start Backend if not already running
if (-not (Test-EccBackend)) {
    Stop-EccBackend
    $python = Join-Path $backend 'venv\Scripts\python.exe'
    if (-not (Test-Path $python)) { $python = 'python' }

    $backendProc = Start-Process -FilePath $python `
        -ArgumentList '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8000' `
        -WorkingDirectory $backend -PassThru -WindowStyle Hidden -RedirectStandardOutput $backendLog -RedirectStandardError $backendErrorLog
    Set-Content -Path $pidFile -Value $backendProc.Id -NoNewline

    $ready = $false
    foreach ($attempt in 1..15) {
        Start-Sleep -Milliseconds 500
        if (Test-EccBackend) { $ready = $true; break }
    }
    if (-not $ready) {
        Stop-EccBackend
        Write-Host "Backend failed to start. Check $backendLog" -ForegroundColor Red
        exit 1
    }
}

Write-Host ' [✓] Backend API running at http://127.0.0.1:8000/' -ForegroundColor Green

# 2. Start Frontend server if not running
if (-not (Test-EccFrontend)) {
    $frontendProc = Start-Process -FilePath 'cmd.exe' -ArgumentList '/c', 'npm.cmd', 'run', 'dev' `
        -WorkingDirectory $frontend -PassThru -WindowStyle Hidden -RedirectStandardOutput $frontendLog -RedirectStandardError $frontendErrorLog
    Set-Content -Path $frontendPidFile -Value $frontendProc.Id -NoNewline

    foreach ($attempt in 1..15) {
        Start-Sleep -Milliseconds 500
        if (Test-EccFrontend) { break }
    }
}

Write-Host ' [✓] Frontend running at http://localhost:1420/' -ForegroundColor Green

# 3. Open Browser
Start-Process 'http://localhost:1420/'

# 4. Also launch desktop app executable if available
$releaseApp = Join-Path $frontend 'src-tauri\target\release\ecc-frontend.exe'
if (Test-Path $releaseApp) {
    Start-Process -FilePath $releaseApp
}

Write-Host ''
Write-Host '==================================================' -ForegroundColor Cyan
Write-Host ' Engineering Command Center is READY!' -ForegroundColor Green
Write-Host ' Web App: http://localhost:1420/' -ForegroundColor White
Write-Host ' API Docs: http://127.0.0.1:8000/docs' -ForegroundColor White
Write-Host ' (Run stop.bat when done to stop services)' -ForegroundColor Yellow
Write-Host '==================================================' -ForegroundColor Cyan
Start-Sleep -Seconds 3
