@echo off
REM Keystone desktop launcher — starts the Flask app using the project venv.
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Could not find .venv. Create it first:
    echo     python -m venv .venv ^&^& .venv\Scripts\python.exe -m pip install -r requirements.txt
    pause
    exit /b 1
)

".venv\Scripts\python.exe" run_keystone.py
echo.
echo Keystone has stopped.
pause
