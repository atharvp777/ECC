@echo off
echo Starting Engineering Command Center Backend...
cd /d "%~dp0"

REM Create venv if it doesn't exist
if not exist "venv" (
    echo Creating virtual environment...
    python -m venv venv
)

REM Activate and install
call venv\Scripts\activate
pip install -r requirements.txt -q

REM Start server
echo Backend running at http://localhost:8000
echo Swagger docs at http://localhost:8000/docs
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
