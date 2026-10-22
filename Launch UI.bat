@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
    echo Run Setup.bat first to install the environment.
    pause
    exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" "%~dp0app.py"
