<#
.SYNOPSIS
    Verification runner for the Orbit project.

.DESCRIPTION
    1. Checks that a Python virtual environment exists (./.venv).
    2. Ensures pytest is installed in that environment.
    3. Executes the deterministic pytest suite (backend/tests).
    4. Prints a clear PASS/FAIL summary.
    5. Optionally runs the live Groq smoke test (skipped if GROQ_API_KEY missing).
    6. Propagates any pytest errors – the script exits with a non‑zero code
       if any deterministic test fails.
    7. Never modifies production files, the .env file, or the live database.

.PARAMETER RunLiveTest
    Switch to also execute the optional live Groq smoke test.
#>

param(
    [switch]$RunLiveTest
)

# ----------------------------------------------------------------------
# 1. Verify virtual environment
# ----------------------------------------------------------------------
$venvPath = Join-Path -Path $PSScriptRoot -ChildPath ".venv"
if (-Not (Test-Path $venvPath)) {
    Write-Error "Virtual environment not found at $venvPath. Create it (e.g., python -m venv .venv) and install dependencies."
    exit 1
}
Write-Host "✅ Virtual environment found."

# ----------------------------------------------------------------------
# 2. Ensure pytest is available
# ----------------------------------------------------------------------
$env:PATH = [".venv\Scripts", $env:PATH]  # make pytest on PATH
if (-Not (Get-Command pytest -ErrorAction SilentlyContinue)) {
    Write-Error "pytest not found in the virtual environment. Run 'pip install pytest' inside .venv."
    exit 1
}
Write-Host "✅ pytest is available."

# ----------------------------------------------------------------------
# 3. Run deterministic test suite
# ----------------------------------------------------------------------
Write-Host "`nRunning deterministic tests..."
$testResult = pytest --quiet backend/tests
if ($LASTEXITCODE -ne 0) {
    Write-Error "❌ Deterministic tests FAILED."
    exit $LASTEXITCODE
}
Write-Host "✅ Deterministic tests PASSED."

# ----------------------------------------------------------------------
# 4. Optionally run the live Groq smoke test
# ----------------------------------------------------------------------
if ($RunLiveTest) {
    Write-Host "`nRunning live Groq smoke test (requires GROQ_API_KEY)..."
    $env:GROQ_API_KEY = $env:GROQ_API_KEY  # ensure it is visible to Python
    pytest --quiet backend/tests/test_planner.py::test_plan_tool_call_live_groq_smoke
    if ($LASTEXITCODE -ne 0) {
        Write-Error "❌ Live Groq smoke test FAILED."
        exit $LASTEXITCODE
    }
    Write-Host "✅ Live Groq smoke test PASSED."
}

Write-Host "`n=== VERIFICATION COMPLETE ==="
