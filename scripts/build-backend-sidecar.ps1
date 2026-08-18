$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root 'backend'
$frontend = Join-Path $root 'frontend'
$venv = Join-Path $backend 'packaging-venv'
$venvPython = Join-Path $venv 'Scripts\python.exe'
$packagingPython = if ($env:ECC_PYTHON) { $env:ECC_PYTHON } else { 'python3.12' }

if (-not (Test-Path $venvPython)) {
    $version = & $packagingPython -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
    if ($LASTEXITCODE -ne 0) {
        throw 'Python 3.12 is required to package Orbit. Install it, or set ECC_PYTHON to its executable path.'
    }
    if ($version -notmatch '^(3\.1[01]|3\.12)$') {
        throw "Orbit packaging requires Python 3.10–3.12; found Python $version. Set ECC_PYTHON to a compatible interpreter."
    }
    & $packagingPython -m venv $venv
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the Orbit packaging environment.' }
}

& $venvPython -m pip install -r (Join-Path $backend 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Backend dependency installation failed; the sidecar was not built.' }
& $venvPython -m pip install pyinstaller
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller installation failed; the sidecar was not built.' }

$targetTriple = (& rustc --print host-tuple).Trim()
if (-not $targetTriple) { throw 'Could not determine the Rust target triple.' }

$buildRoot = Join-Path $backend 'build\sidecar'
$distDir = Join-Path $buildRoot 'dist'
$workDir = Join-Path $buildRoot 'work'
$specDir = Join-Path $buildRoot 'spec'

& $venvPython -m PyInstaller --noconfirm --clean --onefile --name ecc-backend `
    --paths $backend --distpath $distDir --workpath $workDir --specpath $specDir `
    (Join-Path $backend 'ecc_backend.py')
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed; the sidecar was not built.' }

$binaries = Join-Path $frontend 'src-tauri\binaries'
New-Item -ItemType Directory -Force -Path $binaries | Out-Null
Copy-Item -Force (Join-Path $distDir 'ecc-backend.exe') `
    (Join-Path $binaries "ecc-backend-$targetTriple.exe")
